"""
R87: Sector Correlation Monitor — Gemini CTO SPEC LOCKED

Systemic-Risk layer addressing the "Correlated Crash" blind spot.
Prevents false diversification when sectors move in lockstep.

Key design decisions (all Gemini-converged):
1. Cap-Weighted Returns for sector correlation [CONVERGED: GEMINI_R87_CAP_WEIGHTED]
2. Z-Score threshold (+1.5 SD) per pair [CONVERGED: GEMINI_R87_ZSCORE_THRESHOLD]
3. Dual-Window: 90d structural + 15d flash [CONVERGED: GEMINI_R87_DUAL_WINDOW]
4. 1.2x Sector Cap Hard Block via Union-Find Risk Buckets [CONVERGED: GEMINI_R87_RISK_BUCKET]
5. Systemic Flush detector (>50% pairs spiking) [CONVERGED: GEMINI_R87_DUAL_WINDOW]
6. CTO Mandate: Systemic Flush → auto-tighten trailing stops by 20%
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from data.sector_mapping import SECTOR_L1_GROUPS, SECTOR_MAPPING, SECTOR_L1_MAP

_logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────

# Window sizes [CONVERGED: GEMINI_R87_DUAL_WINDOW]
STRUCTURAL_WINDOW = 90     # 90-day for structural correlation
FLASH_WINDOW = 15          # 15-day for flash alerts
HISTORICAL_WINDOW = 756    # ~3 years for Z-score baseline (252 trading days × 3)

# Z-Score alert threshold [CONVERGED: GEMINI_R87_ZSCORE_THRESHOLD]
ZSCORE_ALERT = 1.5         # Alert when current corr > mean + 1.5 * std
ABSOLUTE_ALERT = 0.95      # Always alert regardless of Z-score (extreme tail)

# Flash alert threshold [CONVERGED: GEMINI_R87_DUAL_WINDOW]
FLASH_SPIKE_THRESHOLD = 0.20  # 15d_corr - 90d_corr > 0.20 → "Correlation Convergence"

# Systemic Flush detection
SYSTEMIC_FLUSH_THRESHOLD = 0.50  # >50% of pairs spiking = liquidity panic
SYSTEMIC_ELEVATED = 0.20         # 20-50% pairs = elevated
SYSTEMIC_FLASH_GAP = 0.15        # Per-pair gap threshold for systemic count

# Risk Bucket cap [CONVERGED: GEMINI_R87_RISK_BUCKET]
SECTOR_CAP_SINGLE = 0.20        # Default single-sector cap (from R82.2)
RISK_BUCKET_MULTIPLIER = 1.2    # Combined correlated cap = 1.2x single

# Color mapping for heatmap
CORR_COLORS = {
    "deep_red":    {"min": 0.7,  "max": 1.0,  "color": "#dc2626", "label": "Concentration Risk"},
    "orange":      {"min": 0.5,  "max": 0.7,  "color": "#f97316", "label": "Moderate Correlation"},
    "light_orange": {"min": 0.3, "max": 0.5,  "color": "#fdba74", "label": "Mild Positive"},
    "white":       {"min": -0.3, "max": 0.3,  "color": "#f5f5f5", "label": "Neutral"},
    "light_blue":  {"min": -0.5, "max": -0.3, "color": "#93c5fd", "label": "Mild Diversifier"},
    "deep_blue":   {"min": -1.0, "max": -0.5, "color": "#2563eb", "label": "Strong Diversifier"},
}

# Minimum stocks per sector to compute meaningful correlation
MIN_STOCKS_PER_SECTOR = 2


# ─── Union-Find for Risk Buckets ─────────────────────────────

class UnionFind:
    """Union-Find (Disjoint Set Union) for merging correlated sectors."""

    def __init__(self, items: list[str]):
        self.parent = {x: x for x in items}
        self.rank = {x: 0 for x in items}

    def find(self, x: str) -> str:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])  # path compression
        return self.parent[x]

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1

    def groups(self) -> dict[str, list[str]]:
        """Return {root: [members]} for all groups with >1 member."""
        from collections import defaultdict
        g: dict[str, list[str]] = defaultdict(list)
        for item in self.parent:
            g[self.find(item)].append(item)
        return {k: sorted(v) for k, v in g.items() if len(v) > 1}


# ─── Core Functions ──────────────────────────────────────────

def get_corr_color(corr: float) -> dict:
    """Map a correlation value to a color specification."""
    if corr >= 0.7:
        return CORR_COLORS["deep_red"]
    elif corr >= 0.5:
        return CORR_COLORS["orange"]
    elif corr >= 0.3:
        return CORR_COLORS["light_orange"]
    elif corr >= -0.3:
        return CORR_COLORS["white"]
    elif corr >= -0.5:
        return CORR_COLORS["light_blue"]
    else:
        return CORR_COLORS["deep_blue"]


def compute_cap_weighted_sector_returns(
    stock_returns: pd.DataFrame,
    market_caps: dict[str, float],
) -> pd.DataFrame:
    """Compute cap-weighted daily returns per L1 sector.

    Args:
        stock_returns: DataFrame with columns = stock codes, index = dates, values = daily returns
        market_caps: {code: market_cap_value} for weighting

    Returns:
        DataFrame with columns = L1 sector names, index = dates, values = cap-weighted returns
    """
    # Build sector → codes mapping (only codes present in returns)
    available_codes = set(stock_returns.columns)
    sector_codes: dict[str, list[str]] = {}
    for code, l2 in SECTOR_MAPPING.items():
        if code not in available_codes:
            continue
        l1 = SECTOR_L1_MAP.get(l2, "其他")
        if l1 not in sector_codes:
            sector_codes[l1] = []
        sector_codes[l1].append(code)

    sector_returns = {}
    for sector, codes in sector_codes.items():
        if len(codes) < MIN_STOCKS_PER_SECTOR:
            continue

        # Get weights — cap-weighted, fallback to equal
        weights = []
        for c in codes:
            cap = market_caps.get(c, 0)
            weights.append(max(cap, 0))

        total_cap = sum(weights)
        if total_cap <= 0:
            # Equal weight fallback for TPEX micro-caps
            weights = [1.0 / len(codes)] * len(codes)
        else:
            weights = [w / total_cap for w in weights]

        # Weighted return
        sector_ret = pd.Series(0.0, index=stock_returns.index, dtype=float)
        for code, w in zip(codes, weights):
            sector_ret += stock_returns[code].fillna(0) * w

        sector_returns[sector] = sector_ret

    return pd.DataFrame(sector_returns)


def compute_sector_correlation_matrix(
    sector_returns: pd.DataFrame,
    window: int = STRUCTURAL_WINDOW,
) -> pd.DataFrame:
    """Compute rolling correlation matrix between sectors.

    Args:
        sector_returns: Output of compute_cap_weighted_sector_returns()
        window: Rolling window size in trading days

    Returns:
        Correlation matrix (sectors × sectors) using last `window` days
    """
    if sector_returns.empty or len(sector_returns) < window:
        # Use whatever data we have
        return sector_returns.corr()

    recent = sector_returns.tail(window)
    return recent.corr()


def compute_zscore_alerts(
    sector_returns: pd.DataFrame,
    structural_window: int = STRUCTURAL_WINDOW,
    historical_window: int = HISTORICAL_WINDOW,
) -> list[dict]:
    """Compute Z-Score alerts for each sector pair.

    Compare current correlation to historical mean/std for each pair.
    Alert when Z > 1.5 or absolute corr > 0.95.

    Returns:
        List of alert dicts: {sector_a, sector_b, current_corr, historical_mean,
                              historical_std, z_score, alert_type}
    """
    sectors = list(sector_returns.columns)
    n = len(sectors)
    if n < 2:
        return []

    # Current correlation (structural window)
    curr_data = sector_returns.tail(structural_window) if len(sector_returns) >= structural_window else sector_returns
    curr_corr = curr_data.corr()

    # Historical baseline
    hist_data = sector_returns.tail(historical_window) if len(sector_returns) >= historical_window else sector_returns

    alerts = []
    for i in range(n):
        for j in range(i + 1, n):
            sa, sb = sectors[i], sectors[j]
            current = curr_corr.loc[sa, sb]

            if pd.isna(current):
                continue

            # Compute rolling correlation over historical window
            if len(hist_data) >= structural_window:
                rolling_corr = hist_data[sa].rolling(structural_window).corr(hist_data[sb])
                rolling_corr = rolling_corr.dropna()
            else:
                rolling_corr = pd.Series([current])

            if len(rolling_corr) < 2:
                h_mean = current
                h_std = 0.0
            else:
                h_mean = float(rolling_corr.mean())
                h_std = float(rolling_corr.std())

            # Z-Score
            z_score = (current - h_mean) / h_std if h_std > 0.01 else 0.0

            alert_type = None
            if current > ABSOLUTE_ALERT:
                alert_type = "absolute_extreme"
            elif z_score > ZSCORE_ALERT:
                alert_type = "zscore_spike"

            if alert_type:
                alerts.append({
                    "sector_a": sa,
                    "sector_b": sb,
                    "current_corr": round(float(current), 4),
                    "historical_mean": round(h_mean, 4),
                    "historical_std": round(h_std, 4),
                    "z_score": round(z_score, 2),
                    "alert_type": alert_type,
                })

    return alerts


def compute_flash_alerts(
    sector_returns: pd.DataFrame,
    structural_window: int = STRUCTURAL_WINDOW,
    flash_window: int = FLASH_WINDOW,
) -> list[dict]:
    """Compute 15-day flash alerts when short-term correlation spikes.

    Alert when 15d_corr > 90d_corr + FLASH_SPIKE_THRESHOLD.

    Returns:
        List of flash alert dicts: {sector_a, sector_b, corr_15d, corr_90d, spike}
    """
    sectors = list(sector_returns.columns)
    n = len(sectors)
    if n < 2 or len(sector_returns) < flash_window:
        return []

    # 15-day correlation
    flash_data = sector_returns.tail(flash_window)
    flash_corr = flash_data.corr()

    # 90-day correlation
    struct_data = sector_returns.tail(structural_window) if len(sector_returns) >= structural_window else sector_returns
    struct_corr = struct_data.corr()

    alerts = []
    for i in range(n):
        for j in range(i + 1, n):
            sa, sb = sectors[i], sectors[j]
            c15 = flash_corr.loc[sa, sb]
            c90 = struct_corr.loc[sa, sb]

            if pd.isna(c15) or pd.isna(c90):
                continue

            spike = float(c15 - c90)
            if spike > FLASH_SPIKE_THRESHOLD:
                alerts.append({
                    "sector_a": sa,
                    "sector_b": sb,
                    "corr_15d": round(float(c15), 4),
                    "corr_90d": round(float(c90), 4),
                    "spike": round(spike, 4),
                })

    return alerts


def compute_systemic_risk_score(
    sector_returns: pd.DataFrame,
    structural_window: int = STRUCTURAL_WINDOW,
    flash_window: int = FLASH_WINDOW,
) -> dict[str, Any]:
    """Compute systemic risk score = % of pairs with flash trigger active.

    Levels:
    - <20%: Normal rotation
    - 20-50%: Elevated
    - >50%: SYSTEMIC ALERT (circuit-breaker territory)
    """
    sectors = list(sector_returns.columns)
    n = len(sectors)
    total_pairs = n * (n - 1) // 2

    if total_pairs == 0 or len(sector_returns) < flash_window:
        return {
            "score": 0.0,
            "spiking_pairs": 0,
            "total_pairs": total_pairs,
            "level": "normal",
            "label": "Normal",
            "tighten_stops": False,
        }

    flash_data = sector_returns.tail(flash_window)
    flash_corr = flash_data.corr()

    struct_data = sector_returns.tail(structural_window) if len(sector_returns) >= structural_window else sector_returns
    struct_corr = struct_data.corr()

    spiking = 0
    for i in range(n):
        for j in range(i + 1, n):
            sa, sb = sectors[i], sectors[j]
            c15 = flash_corr.loc[sa, sb]
            c90 = struct_corr.loc[sa, sb]
            if pd.isna(c15) or pd.isna(c90):
                continue
            if (c15 - c90) > SYSTEMIC_FLASH_GAP:
                spiking += 1

    score = spiking / total_pairs if total_pairs > 0 else 0.0

    if score > SYSTEMIC_FLUSH_THRESHOLD:
        level = "systemic"
        label = "SYSTEMIC ALERT — Liquidity Flush"
        tighten = True
    elif score > SYSTEMIC_ELEVATED:
        level = "elevated"
        label = "Elevated — Monitor Closely"
        tighten = False
    else:
        level = "normal"
        label = "Normal Rotation"
        tighten = False

    return {
        "score": round(score, 3),
        "spiking_pairs": spiking,
        "total_pairs": total_pairs,
        "level": level,
        "label": label,
        # [CONVERGED: GEMINI_R87_CTO_MANDATE] Auto-tighten trailing stops by 20%
        "tighten_stops": tighten,
    }


def compute_risk_buckets(
    zscore_alerts: list[dict],
    flash_alerts: list[dict],
    all_sectors: list[str],
) -> dict[str, Any]:
    """Merge correlated sectors into Risk Buckets via Union-Find.

    Sectors that are in a Z-Score alert OR flash alert get merged.
    Combined cap per bucket = 1.2x single-sector cap.

    Returns:
        {
            buckets: [{root, members, combined_cap}],
            sector_to_bucket: {sector: root},
        }
    """
    uf = UnionFind(all_sectors)

    # Merge sectors that appear in alerts
    alerted_pairs = set()
    for a in zscore_alerts:
        pair = (a["sector_a"], a["sector_b"])
        alerted_pairs.add(pair)
    for a in flash_alerts:
        pair = (a["sector_a"], a["sector_b"])
        alerted_pairs.add(pair)

    for sa, sb in alerted_pairs:
        if sa in uf.parent and sb in uf.parent:
            uf.union(sa, sb)

    groups = uf.groups()

    buckets = []
    sector_to_bucket: dict[str, str] = {}
    for root, members in groups.items():
        combined_cap = SECTOR_CAP_SINGLE * RISK_BUCKET_MULTIPLIER
        buckets.append({
            "root": root,
            "members": members,
            "combined_cap": round(combined_cap, 3),
            "member_count": len(members),
        })
        for m in members:
            sector_to_bucket[m] = root

    return {
        "buckets": buckets,
        "sector_to_bucket": sector_to_bucket,
    }


def check_bucket_entry_allowed(
    risk_buckets: dict,
    portfolio_sector_weights: dict[str, float],
    new_sector: str,
    new_weight: float = 0.0,
) -> dict[str, Any]:
    """Check if a new entry is allowed given risk bucket caps.

    Args:
        risk_buckets: Output of compute_risk_buckets()
        portfolio_sector_weights: Current {sector: weight_pct} in portfolio
        new_sector: Sector of potential new entry
        new_weight: Weight the new entry would add

    Returns:
        {allowed, reason, bucket_info}
    """
    sector_to_bucket = risk_buckets.get("sector_to_bucket", {})
    bucket_root = sector_to_bucket.get(new_sector)

    if bucket_root is None:
        # Not in any correlated bucket — use single-sector cap
        current_weight = portfolio_sector_weights.get(new_sector, 0.0)
        if current_weight + new_weight > SECTOR_CAP_SINGLE:
            return {
                "allowed": False,
                "reason": f"Sector '{new_sector}' at {current_weight:.1%} + {new_weight:.1%} exceeds single-sector cap {SECTOR_CAP_SINGLE:.0%}",
                "bucket": None,
            }
        return {"allowed": True, "reason": "Within single-sector cap", "bucket": None}

    # Find the bucket
    for bucket in risk_buckets.get("buckets", []):
        if bucket["root"] == bucket_root:
            # Sum weights of all sectors in bucket
            total_bucket_weight = sum(
                portfolio_sector_weights.get(m, 0.0) for m in bucket["members"]
            )
            combined_cap = bucket["combined_cap"]

            if total_bucket_weight + new_weight > combined_cap:
                return {
                    "allowed": False,
                    "reason": (
                        f"Risk Bucket {bucket['members']} at {total_bucket_weight:.1%} + {new_weight:.1%} "
                        f"exceeds combined cap {combined_cap:.0%}"
                    ),
                    "bucket": bucket,
                }
            return {
                "allowed": True,
                "reason": f"Within risk bucket cap ({total_bucket_weight:.1%} / {combined_cap:.0%})",
                "bucket": bucket,
            }

    return {"allowed": True, "reason": "No matching bucket found", "bucket": None}


def build_heatmap_data(corr_matrix: pd.DataFrame) -> list[dict]:
    """Convert correlation matrix to heatmap-friendly data.

    Returns list of {sector_a, sector_b, correlation, color, label} for each cell.
    """
    sectors = list(corr_matrix.columns)
    data = []
    for i, sa in enumerate(sectors):
        for j, sb in enumerate(sectors):
            corr_val = corr_matrix.loc[sa, sb]
            if pd.isna(corr_val):
                corr_val = 0.0
            color_info = get_corr_color(float(corr_val))
            data.append({
                "sector_a": sa,
                "sector_b": sb,
                "correlation": round(float(corr_val), 4),
                "color": color_info["color"],
                "label": color_info["label"],
            })
    return data


def compute_full_sector_correlation(
    stock_returns: pd.DataFrame,
    market_caps: dict[str, float],
) -> dict[str, Any]:
    """Compute the full sector correlation report.

    Main entry point that combines all sub-computations.

    Args:
        stock_returns: DataFrame with columns = stock codes, index = dates
        market_caps: {code: market_cap} for cap-weighting

    Returns:
        Complete correlation report with heatmap, alerts, systemic risk, risk buckets.
    """
    # Step 1: Cap-weighted sector returns
    sector_returns = compute_cap_weighted_sector_returns(stock_returns, market_caps)
    if sector_returns.empty:
        return {
            "sectors": [],
            "correlation_matrix": {},
            "heatmap": [],
            "zscore_alerts": [],
            "flash_alerts": [],
            "systemic_risk": {"score": 0, "level": "normal", "label": "No data", "tighten_stops": False},
            "risk_buckets": {"buckets": [], "sector_to_bucket": {}},
        }

    sectors = list(sector_returns.columns)

    # Step 2: Correlation matrix (90d)
    corr_matrix = compute_sector_correlation_matrix(sector_returns, STRUCTURAL_WINDOW)

    # Step 3: Z-Score alerts
    zscore_alerts = compute_zscore_alerts(sector_returns, STRUCTURAL_WINDOW, HISTORICAL_WINDOW)

    # Step 4: Flash alerts (15d vs 90d)
    flash_alerts = compute_flash_alerts(sector_returns, STRUCTURAL_WINDOW, FLASH_WINDOW)

    # Step 5: Systemic risk score
    systemic_risk = compute_systemic_risk_score(sector_returns, STRUCTURAL_WINDOW, FLASH_WINDOW)

    # Step 6: Risk buckets (Union-Find)
    risk_buckets = compute_risk_buckets(zscore_alerts, flash_alerts, sectors)

    # Step 7: Heatmap data
    heatmap = build_heatmap_data(corr_matrix)

    # Serialize correlation matrix
    corr_dict = {}
    for sa in sectors:
        corr_dict[sa] = {}
        for sb in sectors:
            val = corr_matrix.loc[sa, sb]
            corr_dict[sa][sb] = round(float(val), 4) if not pd.isna(val) else 0.0

    return {
        "sectors": sectors,
        "correlation_matrix": corr_dict,
        "heatmap": heatmap,
        "zscore_alerts": zscore_alerts,
        "flash_alerts": flash_alerts,
        "systemic_risk": systemic_risk,
        "risk_buckets": risk_buckets,
    }

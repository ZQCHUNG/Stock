"""R64: Sector RS & Peer RS Check — Gemini Wall St. Trader Debate Converged

Three dimensions:
1. Sector RS: Median of L1 sector members' RS ratios [VERIFIED: INDUSTRY_STANDARD]
2. Peer Alpha: Stock RS / Sector RS — detect "Beta Trap" laggards
3. Cluster Risk: 3-tier warning (Normal / Caution / Danger)

Data coverage: 108 mapped stocks (L1 sectors) + "Unclassified" tier for unmapped.
"""

import logging
import time
from typing import Any

from analysis.rs_scanner import get_cached_rankings
from data.sector_mapping import (
    SECTOR_L1_GROUPS,
    get_stock_sector,
)

_logger = logging.getLogger(__name__)

# Module-level cache for sector RS table — avoids recomputing 927 times in batch scans
# Gemini CTO structural note: "Don't recalculate 927 times on Refresh All"
_sector_table_cache: dict | None = None
_sector_table_cache_ts: float = 0
_SECTOR_TABLE_TTL = 60  # seconds — covers a single scan session

# ---------- Peer Alpha thresholds ----------
# [PLACEHOLDER: PEER_ALPHA_THRESHOLD_001] needs backtest validation
PEER_ALPHA_LEADER = 1.2       # Genuine Leader: outperforming sector by 20%+
PEER_ALPHA_LAGGARD = 0.8      # Sector Laggard: underperforming despite sector strength

# ---------- Cluster Risk tiers ----------
# [PLACEHOLDER: CLUSTER_RISK_TIERS_001] validate against 2021 航運 / 2024 AI伺服器
CLUSTER_NORMAL_DIAMOND_PCT = 0.30   # < 30% Diamond = Normal
CLUSTER_NORMAL_HEAT = 0.60          # < 0.6 heat = Normal
CLUSTER_CAUTION_DIAMOND_PCT = 0.50  # 30%-50% Diamond = Caution
CLUSTER_CAUTION_HEAT = 0.75         # 0.6-0.75 heat = Caution
# Above both = Danger


def compute_sector_rs_table(rankings_data: dict | None = None) -> dict[str, dict]:
    """Compute median RS ratio per L1 sector from cached RS rankings.

    Returns:
        {sector_name: {median_rs, count, diamond_count, diamond_pct, members: [...]}}
    """
    global _sector_table_cache, _sector_table_cache_ts

    # Use module-level cache if no explicit data passed and cache is fresh
    if rankings_data is None:
        if _sector_table_cache is not None and (time.time() - _sector_table_cache_ts) < _SECTOR_TABLE_TTL:
            return _sector_table_cache
        rankings_data = get_cached_rankings()
    if not rankings_data:
        return {}

    # Build code → ranking lookup
    code_to_rs: dict[str, dict] = {}
    for r in rankings_data.get("rankings", []):
        code_to_rs[r["code"]] = r

    sector_table: dict[str, dict] = {}

    for sector_l1, codes in SECTOR_L1_GROUPS.items():
        members = []
        rs_ratios = []
        diamond_count = 0

        for code in codes:
            r = code_to_rs.get(code)
            if r is None:
                continue
            rs_ratio = r.get("rs_ratio", 0)
            rs_rating = r.get("rs_rating", 0)
            rs_ratios.append(rs_ratio)
            members.append({
                "code": code,
                "name": r.get("name", ""),
                "rs_ratio": rs_ratio,
                "rs_rating": rs_rating,
            })
            if rs_rating >= 80:
                diamond_count += 1

        if not rs_ratios:
            continue

        # [VERIFIED: INDUSTRY_STANDARD] Use median, not mean — Gemini mandate
        import numpy as np
        median_rs = float(np.median(rs_ratios))
        count = len(rs_ratios)

        sector_table[sector_l1] = {
            "median_rs": round(median_rs, 4),
            "count": count,
            "diamond_count": diamond_count,
            "diamond_pct": round(diamond_count / count, 3) if count > 0 else 0,
            "members": sorted(members, key=lambda m: m["rs_rating"], reverse=True),
        }

    # Cache result for batch operations
    _sector_table_cache = sector_table
    _sector_table_cache_ts = time.time()

    return sector_table


def compute_peer_alpha(stock_rs_ratio: float, sector_median_rs: float) -> dict:
    """Compute Peer Alpha = Stock RS / Sector RS.

    Returns:
        {peer_alpha, classification, downgrade}
        classification: "Leader" | "Rider" | "Laggard"
        downgrade: True if Diamond should be capped at Gold
    """
    if sector_median_rs <= 0:
        return {"peer_alpha": None, "classification": "N/A", "downgrade": False}

    alpha = stock_rs_ratio / sector_median_rs

    if alpha >= PEER_ALPHA_LEADER:
        classification = "Leader"
    elif alpha >= PEER_ALPHA_LAGGARD:
        classification = "Rider"
    else:
        classification = "Laggard"

    # [PLACEHOLDER: PEER_ALPHA_THRESHOLD_001] "Beta Trap" protection
    # Gemini: "We don't reward participation trophies in a momentum strategy"
    downgrade = alpha < PEER_ALPHA_LAGGARD

    return {
        "peer_alpha": round(alpha, 3),
        "classification": classification,
        "downgrade": downgrade,
    }


def assess_cluster_risk(
    diamond_pct: float,
    sector_heat: float | None = None,
) -> dict:
    """Assess sector cluster risk — 3-tier model from Gemini debate.

    Args:
        diamond_pct: Fraction of sector stocks with Diamond RS (0-1)
        sector_heat: Sector heat value from sector-heat endpoint (0-1), optional

    Returns:
        {level, label, advice}
        level: "normal" | "caution" | "danger"
    """
    heat = sector_heat or 0.0

    # [PLACEHOLDER: CLUSTER_RISK_TIERS_001]
    if diamond_pct >= CLUSTER_CAUTION_DIAMOND_PCT and heat >= CLUSTER_CAUTION_HEAT:
        return {
            "level": "danger",
            "label": "Parabolic Risk - Size Down",
            "advice": f"Sector overheated: {diamond_pct:.0%} Diamond, heat={heat:.2f}",
        }
    elif diamond_pct >= CLUSTER_NORMAL_DIAMOND_PCT and heat >= CLUSTER_NORMAL_HEAT:
        return {
            "level": "caution",
            "label": "Sector Crowded",
            "advice": f"Sector warming: {diamond_pct:.0%} Diamond, heat={heat:.2f}",
        }
    else:
        return {
            "level": "normal",
            "label": "Clear Skies",
            "advice": "",
        }


def get_sector_context(code: str, sector_heat_map: dict[str, float] | None = None) -> dict[str, Any]:
    """Get complete sector context for a stock.

    Args:
        code: Stock code
        sector_heat_map: Optional {sector_l1: weighted_heat} from sector-heat cache

    Returns:
        {
            sector_l1, sector_l2,
            sector_rs: {median_rs, count, diamond_count, diamond_pct},
            peer_alpha: {peer_alpha, classification, downgrade},
            cluster_risk: {level, label, advice},
            peer_rank: int (1-based rank within sector),
            blind_spot: bool,
        }
    """
    sector_l1 = get_stock_sector(code, level=1)
    sector_l2 = get_stock_sector(code, level=2)

    # Unmapped stock → "Sector Blind Spot"
    if sector_l1 == "未分類":
        # Get stock's own RS for reference
        rankings = get_cached_rankings()
        stock_rs = None
        if rankings:
            for r in rankings.get("rankings", []):
                if r["code"] == code:
                    stock_rs = r.get("rs_ratio")
                    break

        return {
            "sector_l1": "未分類",
            "sector_l2": "未分類",
            "sector_rs": None,
            "peer_alpha": {"peer_alpha": None, "classification": "N/A", "downgrade": False},
            "cluster_risk": {"level": "unknown", "label": "Sector Blind Spot", "advice": "No sector data — RS rating is market-wide only"},
            "peer_rank": None,
            "peer_total": None,
            "blind_spot": True,
        }

    # Compute sector RS table
    sector_table = compute_sector_rs_table()
    sector_info = sector_table.get(sector_l1)

    if sector_info is None:
        return {
            "sector_l1": sector_l1,
            "sector_l2": sector_l2,
            "sector_rs": None,
            "peer_alpha": {"peer_alpha": None, "classification": "N/A", "downgrade": False},
            "cluster_risk": {"level": "unknown", "label": "No sector RS data", "advice": ""},
            "peer_rank": None,
            "peer_total": None,
            "blind_spot": False,
        }

    # Find stock's RS ratio and peer rank
    stock_rs_ratio = None
    peer_rank = None
    for i, m in enumerate(sector_info["members"]):
        if m["code"] == code:
            stock_rs_ratio = m["rs_ratio"]
            peer_rank = i + 1  # 1-based (members sorted by rs_rating desc)
            break

    # Peer Alpha
    if stock_rs_ratio is not None:
        peer_alpha = compute_peer_alpha(stock_rs_ratio, sector_info["median_rs"])
    else:
        peer_alpha = {"peer_alpha": None, "classification": "N/A", "downgrade": False}

    # Cluster Risk
    sector_heat = 0.0
    if sector_heat_map:
        sector_heat = sector_heat_map.get(sector_l1, 0.0)
    cluster_risk = assess_cluster_risk(sector_info["diamond_pct"], sector_heat)

    return {
        "sector_l1": sector_l1,
        "sector_l2": sector_l2,
        "sector_rs": {
            "median_rs": sector_info["median_rs"],
            "count": sector_info["count"],
            "diamond_count": sector_info["diamond_count"],
            "diamond_pct": sector_info["diamond_pct"],
        },
        "peer_alpha": peer_alpha,
        "cluster_risk": cluster_risk,
        "peer_rank": peer_rank,
        "peer_total": sector_info["count"],
        "blind_spot": False,
    }

"""R85: VCP (Volatility Contraction Pattern) Detector — Gemini Wall St. Trader Debate Converged

Minervini-style VCP detection with Taiwan-market adaptations.

Converged spec (10 points):
1. Progressive Decay: T(n).depth < T(n-1).depth — no V-bottoms
2. Ghost Day: vol < 0.5 × vol_20d_MA in tightest contraction zone
3. Limit Up Reset: daily return > 9.5% resets contraction count
4. Context Qualifier: VCP_Score > 70 → upgrade Gold→Diamond; < 30 → "Thin Base" warning
5. Volume Floor: avg_vol_20d < 500 lots → score = 0
6. Pivot Point: High of last contraction (KISS principle)
7. Breakout: close > pivot AND volume > 2× vol_20d_MA
8. Min Contractions: 2 (T3 = Gold Standard bonus)
9. Max Base Depth: T1 > 35% → disqualified ("Loose and Sloppy")
10. PVT Coiled Spring: 2-3 days with range < 1% + vol < Ghost Day threshold
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

_logger = logging.getLogger(__name__)

# ---------- Parameters (all tagged per 假精確 Protocol) ----------

# [PLACEHOLDER: VCP_MIN_CONTRACTIONS_001] needs backtest validation
VCP_MIN_CONTRACTIONS = 2

# [PLACEHOLDER: VCP_MAX_BASE_DEPTH_001] "Loose and Sloppy" filter from Gemini
VCP_MAX_BASE_DEPTH = 0.35  # 35% — disqualify if T1 deeper than this

# [PLACEHOLDER: GHOST_DAY_VOL_RATIO_001]
GHOST_DAY_VOL_RATIO = 0.5  # Volume < 50% of 20d MA

# [PLACEHOLDER: LIMIT_UP_RESET_THRESHOLD_001]
LIMIT_UP_RESET = 0.095  # 9.5% daily return (allow for spread on 10% limit)

# [PLACEHOLDER: VCP_UPGRADE_THRESHOLD_001]
VCP_UPGRADE_THRESHOLD = 70  # Score >= 70 → upgrade Gold to Diamond

# [PLACEHOLDER: VCP_WARNING_THRESHOLD_001]
VCP_WARNING_THRESHOLD = 30  # Score < 30 on Entry D → "Thin Base" warning

# [VERIFIED: CONSISTENT_WITH_ENTRY_D] matches momentum_min_volume_lots
VCP_VOLUME_FLOOR_LOTS = 500  # Minimum 20d avg volume in lots (1 lot = 1000 shares)

# [PLACEHOLDER: VCP_BREAKOUT_VOL_MULT_001]
VCP_BREAKOUT_VOL_MULT = 2.0  # Breakout volume > 2× vol_20d_MA

# [PLACEHOLDER: VCP_LOOKBACK_WINDOW_001]
VCP_LOOKBACK_WINDOW = 120  # Days to search for VCP pattern

# [PLACEHOLDER: VCP_MIN_DURATION_001]
VCP_MIN_DURATION = 15  # Minimum days in VCP formation

# PVT (Price/Volume Tightening) "Coiled Spring"
PVT_RANGE_THRESHOLD = 0.01  # Daily range < 1%
PVT_MIN_CLUSTER = 2  # Minimum consecutive PVT days


@dataclass
class Contraction:
    """A single price contraction (base) in a VCP formation."""
    start_idx: int
    end_idx: int
    high: float
    low: float
    depth: float  # (high - low) / high
    duration: int  # trading days


@dataclass
class VCPResult:
    """Result of VCP detection for a single stock."""
    has_vcp: bool = False
    vcp_score: int = 0
    base_count: int = 0
    contractions: list[dict] = field(default_factory=list)
    ghost_day_count: int = 0
    pivot_price: float | None = None
    is_breakout: bool = False
    has_coiled_spring: bool = False
    coiled_spring_days: int = 0
    disqualify_reason: str = ""
    volume_floor_fail: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_vcp": self.has_vcp,
            "vcp_score": self.vcp_score,
            "base_count": self.base_count,
            "contractions": self.contractions,
            "ghost_day_count": self.ghost_day_count,
            "pivot_price": self.pivot_price,
            "is_breakout": self.is_breakout,
            "has_coiled_spring": self.has_coiled_spring,
            "coiled_spring_days": self.coiled_spring_days,
            "disqualify_reason": self.disqualify_reason,
            "volume_floor_fail": self.volume_floor_fail,
        }


def _find_contractions(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    daily_returns: np.ndarray,
    min_duration: int = 5,
) -> list[Contraction]:
    """Find distinct price contractions (bases) in a price series.

    A contraction is a period where price oscillates between a local high
    and progressively tighter lows. We use a swing-point approach:
    identify local highs/lows with at least `min_duration` bars between them.
    """
    n = len(highs)
    if n < min_duration * 2:
        return []

    # Step 1: Find swing highs and swing lows using rolling windows
    half_win = max(min_duration // 2, 3)
    swing_highs = []
    swing_lows = []

    for i in range(half_win, n - half_win):
        # Check for limit-up reset — skip this point as a swing
        if abs(daily_returns[i]) > LIMIT_UP_RESET:
            continue

        window_high = highs[max(0, i - half_win):i + half_win + 1]
        window_low = lows[max(0, i - half_win):i + half_win + 1]

        if highs[i] == np.max(window_high):
            swing_highs.append(i)
        if lows[i] == np.min(window_low):
            swing_lows.append(i)

    if len(swing_highs) < 1 or len(swing_lows) < 1:
        return []

    # Step 2: Pair swing highs with subsequent swing lows to form contractions
    contractions = []
    used_lows = set()

    for sh_idx in swing_highs:
        # Find the next swing low after this high
        best_low_idx = None
        for sl_idx in swing_lows:
            if sl_idx > sh_idx and sl_idx not in used_lows:
                best_low_idx = sl_idx
                break

        if best_low_idx is None:
            continue

        # Check for limit-up reset between high and low
        segment_returns = daily_returns[sh_idx:best_low_idx + 1]
        if np.any(np.abs(segment_returns) > LIMIT_UP_RESET):
            continue  # Limit up/down during formation — invalidate

        high_val = highs[sh_idx]
        low_val = lows[best_low_idx]
        depth = (high_val - low_val) / high_val if high_val > 0 else 0
        duration = best_low_idx - sh_idx

        if duration >= min_duration and depth > 0.01:  # Skip negligible wiggles
            contractions.append(Contraction(
                start_idx=sh_idx,
                end_idx=best_low_idx,
                high=high_val,
                low=low_val,
                depth=depth,
                duration=duration,
            ))
            used_lows.add(best_low_idx)

    return contractions


def _validate_progressive_decay(contractions: list[Contraction]) -> list[Contraction]:
    """Filter contractions to keep only progressively decaying sequences.

    Gemini mandate: T(n).depth < T(n-1).depth — each base must be shallower.
    If T2 is deeper than T1, the supply isn't being absorbed; it's being dumped.
    """
    if len(contractions) < 2:
        return contractions

    valid = [contractions[0]]
    for i in range(1, len(contractions)):
        if contractions[i].depth < valid[-1].depth:
            valid.append(contractions[i])
        # If depth increases, stop — pattern breaks

    return valid


def _count_ghost_days(
    volumes: np.ndarray,
    vol_ma20: np.ndarray,
    start_idx: int,
    end_idx: int,
) -> int:
    """Count Ghost Days in a range: vol < GHOST_DAY_VOL_RATIO × vol_20d_MA.

    Gemini: "A day where volume is < 50% of the 20-day MA while price is in
    the tightest part of the contraction. That is the signal that there is
    literally no one left to sell."
    """
    count = 0
    for i in range(start_idx, min(end_idx + 1, len(volumes))):
        if vol_ma20[i] > 0 and volumes[i] < GHOST_DAY_VOL_RATIO * vol_ma20[i]:
            count += 1
    return count


def _detect_coiled_spring(
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
    vol_ma20: np.ndarray,
    start_idx: int,
    end_idx: int,
) -> tuple[bool, int]:
    """Detect PVT (Price/Volume Tightening) "Coiled Spring" cluster.

    Gemini: "A cluster of 2-3 days where the daily range is < 1%
    and volume is non-existent."
    """
    consecutive = 0
    max_consecutive = 0

    for i in range(start_idx, min(end_idx + 1, len(highs))):
        daily_range = (highs[i] - lows[i]) / highs[i] if highs[i] > 0 else 0
        is_ghost = vol_ma20[i] > 0 and volumes[i] < GHOST_DAY_VOL_RATIO * vol_ma20[i]

        if daily_range < PVT_RANGE_THRESHOLD and is_ghost:
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 0

    has_spring = max_consecutive >= PVT_MIN_CLUSTER
    return has_spring, max_consecutive


def _compute_vcp_score(
    base_count: int,
    ghost_day_count: int,
    contractions: list[Contraction],
    has_coiled_spring: bool,
) -> int:
    """Compute VCP Score (0-100).

    Components:
    - Base count: 2 bases = 30pts, 3+ = 50pts (T3 "Gold Standard" bonus)
    - Progressive quality: tighter decay ratio = higher score (up to 20pts)
    - Ghost Days: >= 1 required for score > 50; each adds 5pts (max 15pts)
    - Coiled Spring: +15 bonus pts
    """
    score = 0

    # Base count (max 50)
    if base_count >= 3:
        score += 50  # T3 Gold Standard
    elif base_count >= 2:
        score += 30

    # Progressive quality — how tight is the last contraction? (max 20)
    if len(contractions) >= 2:
        first_depth = contractions[0].depth
        last_depth = contractions[-1].depth
        if first_depth > 0:
            ratio = last_depth / first_depth
            # ratio < 0.3 = very tight = 20pts, ratio 0.5 = decent = 10pts
            quality_score = max(0, min(20, int(20 * (1 - ratio))))
            score += quality_score

    # Ghost Days (max 15, but at least 1 required for score > 50)
    ghost_pts = min(15, ghost_day_count * 5)
    score += ghost_pts

    # Ghost Day gate: without at least 1, cap at 50
    if ghost_day_count == 0 and score > 50:
        score = 50

    # Coiled Spring bonus (+15)
    if has_coiled_spring:
        score += 15

    return min(100, score)


def detect_vcp(
    df: pd.DataFrame,
    lookback: int = VCP_LOOKBACK_WINDOW,
    min_duration: int = VCP_MIN_DURATION,
) -> VCPResult:
    """Detect VCP (Volatility Contraction Pattern) in price data.

    Args:
        df: DataFrame with columns: close, high, low, volume, volume_ma20
            (volume_ma20 optional — will compute if missing)
        lookback: Days to look back for VCP formation
        min_duration: Minimum days for each contraction

    Returns:
        VCPResult with detection details and score
    """
    result = VCPResult()

    # Validate input
    required_cols = {"close", "high", "low", "volume"}
    if not required_cols.issubset(set(df.columns)):
        missing = required_cols - set(df.columns)
        result.disqualify_reason = f"Missing columns: {missing}"
        return result

    if len(df) < lookback:
        result.disqualify_reason = f"Insufficient data: {len(df)} < {lookback}"
        return result

    # Use recent window
    window = df.iloc[-lookback:].copy()

    # Compute volume_ma20 if not present
    if "volume_ma20" not in window.columns:
        window["volume_ma20"] = window["volume"].rolling(20, min_periods=10).mean()

    # --- Volume Floor Check ---
    avg_vol_20d = window["volume_ma20"].iloc[-1]
    if pd.isna(avg_vol_20d):
        avg_vol_20d = window["volume"].tail(20).mean()

    avg_vol_lots = avg_vol_20d / 1000  # Convert shares to lots
    if avg_vol_lots < VCP_VOLUME_FLOOR_LOTS:
        result.volume_floor_fail = True
        result.disqualify_reason = (
            f"Volume floor: {avg_vol_lots:.0f} lots < {VCP_VOLUME_FLOOR_LOTS} lots"
        )
        return result

    # Extract arrays for computation
    highs = window["high"].values.astype(float)
    lows = window["low"].values.astype(float)
    closes = window["close"].values.astype(float)
    volumes = window["volume"].values.astype(float)
    vol_ma20 = window["volume_ma20"].values.astype(float)

    # Daily returns for limit-up detection
    daily_returns = np.zeros(len(closes))
    daily_returns[1:] = (closes[1:] - closes[:-1]) / closes[:-1]

    # --- Step 1: Find contractions ---
    raw_contractions = _find_contractions(
        highs, lows, closes, daily_returns,
        min_duration=max(5, min_duration // 3),  # Each base can be shorter than full VCP
    )

    if len(raw_contractions) < VCP_MIN_CONTRACTIONS:
        result.disqualify_reason = (
            f"Only {len(raw_contractions)} contractions found, need {VCP_MIN_CONTRACTIONS}"
        )
        return result

    # --- Step 2: Max Base Depth filter ("Loose and Sloppy") ---
    if raw_contractions[0].depth > VCP_MAX_BASE_DEPTH:
        result.disqualify_reason = (
            f"T1 depth {raw_contractions[0].depth:.1%} > {VCP_MAX_BASE_DEPTH:.0%} max "
            f"(Loose and Sloppy)"
        )
        return result

    # --- Step 3: Validate Progressive Decay ---
    valid_contractions = _validate_progressive_decay(raw_contractions)

    if len(valid_contractions) < VCP_MIN_CONTRACTIONS:
        result.disqualify_reason = (
            f"Progressive decay failed: only {len(valid_contractions)} valid bases "
            f"after decay filter"
        )
        return result

    # --- Step 4: Ghost Days in tightest (last) contraction ---
    last_c = valid_contractions[-1]
    ghost_days = _count_ghost_days(volumes, vol_ma20, last_c.start_idx, last_c.end_idx)

    # --- Step 5: Coiled Spring detection in last contraction ---
    has_spring, spring_days = _detect_coiled_spring(
        highs, lows, volumes, vol_ma20, last_c.start_idx, last_c.end_idx,
    )

    # --- Step 6: VCP Score ---
    vcp_score = _compute_vcp_score(
        base_count=len(valid_contractions),
        ghost_day_count=ghost_days,
        contractions=valid_contractions,
        has_coiled_spring=has_spring,
    )

    # --- Step 7: Pivot Point = High of last contraction ---
    pivot_price = last_c.high

    # --- Step 8: Breakout check (today) ---
    latest_close = closes[-1]
    latest_vol = volumes[-1]
    latest_vol_ma20 = vol_ma20[-1]
    is_breakout = (
        latest_close > pivot_price
        and latest_vol_ma20 > 0
        and latest_vol > VCP_BREAKOUT_VOL_MULT * latest_vol_ma20
    )

    # --- Step 9: VCP Duration check ---
    total_duration = valid_contractions[-1].end_idx - valid_contractions[0].start_idx
    if total_duration < min_duration:
        result.disqualify_reason = (
            f"VCP duration {total_duration} days < {min_duration} minimum"
        )
        return result

    # --- Build result ---
    result.has_vcp = True
    result.vcp_score = vcp_score
    result.base_count = len(valid_contractions)
    result.contractions = [
        {
            "base": i + 1,
            "depth": round(c.depth, 4),
            "duration": c.duration,
            "high": round(c.high, 2),
            "low": round(c.low, 2),
        }
        for i, c in enumerate(valid_contractions)
    ]
    result.ghost_day_count = ghost_days
    result.pivot_price = round(pivot_price, 2)
    result.is_breakout = is_breakout
    result.has_coiled_spring = has_spring
    result.coiled_spring_days = spring_days

    return result


def check_volume_dryup(
    df: pd.DataFrame,
    start_idx: int | None = None,
    end_idx: int | None = None,
) -> dict[str, Any]:
    """Check volume dry-up in a given range (or recent data).

    Useful for verifying Entry A squeeze has genuine volume contraction.

    Returns:
        {dryup_ratio, is_confirmed, ghost_day_count}
    """
    if "volume" not in df.columns:
        return {"dryup_ratio": None, "is_confirmed": False, "ghost_day_count": 0}

    if "volume_ma20" not in df.columns:
        vol_ma20 = df["volume"].rolling(20, min_periods=10).mean()
    else:
        vol_ma20 = df["volume_ma20"]

    if start_idx is None:
        start_idx = max(0, len(df) - 10)
    if end_idx is None:
        end_idx = len(df) - 1

    segment_vol = df["volume"].iloc[start_idx:end_idx + 1]
    segment_ma = vol_ma20.iloc[start_idx:end_idx + 1]

    if segment_ma.mean() == 0:
        return {"dryup_ratio": None, "is_confirmed": False, "ghost_day_count": 0}

    dryup_ratio = float(segment_vol.mean() / segment_ma.mean())
    ghost_count = int((segment_vol < GHOST_DAY_VOL_RATIO * segment_ma).sum())

    return {
        "dryup_ratio": round(dryup_ratio, 3),
        "is_confirmed": dryup_ratio < 0.7,  # Generous threshold for general check
        "ghost_day_count": ghost_count,
    }


def get_vcp_context(df: pd.DataFrame) -> dict[str, Any]:
    """Get VCP context for a stock — main entry point for API/frontend.

    Args:
        df: Full OHLCV DataFrame (should have indicators computed)

    Returns:
        Dict with VCP detection results, suitable for JSON serialization.
    """
    vcp = detect_vcp(df)
    result = vcp.to_dict()

    # Add signal interaction metadata
    if vcp.has_vcp:
        if vcp.vcp_score >= VCP_UPGRADE_THRESHOLD:
            result["signal_action"] = "upgrade"
            result["signal_action_label"] = "VCP Rocket Launch — Gold→Diamond"
        elif vcp.vcp_score < VCP_WARNING_THRESHOLD:
            result["signal_action"] = "warning"
            result["signal_action_label"] = "Thin Base — no VCP support"
        else:
            result["signal_action"] = "neutral"
            result["signal_action_label"] = "VCP forming"
    else:
        result["signal_action"] = "none"
        result["signal_action_label"] = vcp.disqualify_reason or "No VCP detected"

    return result

"""
R86: ATR-Based Stop-Loss Calculator — Gemini CTO Approved

Calculates per-position stop-loss levels using 3 methods:
1. Structural Stop — below recent swing low / VCP pivot
2. ATR Stop — entry - N×ATR(14) per entry type
3. Percentage Stop — hard floor (7%)

Takes the WIDEST (most protective) as initial stop.
Implements 4-phase trailing stop progression.
Includes gap-down risk estimation.

Converged Spec:
- ATR multipliers: squeeze 1.5, oversold 2.0, vol_ramp 2.0, momentum 2.0
- VCP pivot override mandatory when score ≥70
- Two-phase trailing: +1R→breakeven, +1.5R→ATR trail, +2R→tighten
- Gap risk: 95th percentile of 90-day gap-down history
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Any

from analysis.liquidity import get_tick_size

# ─── Constants (Protocol v3 placeholders) ─────────────────────

ATR_MULT_SQUEEZE = 1.5       # [PLACEHOLDER: ATR_MULT_SQUEEZE_001]
ATR_MULT_OVERSOLD = 2.0      # [PLACEHOLDER: ATR_MULT_OVERSOLD_001]
ATR_MULT_VOL_RAMP = 2.0      # [PLACEHOLDER: ATR_MULT_VOL_RAMP_001]
ATR_MULT_MOMENTUM = 2.0      # [CONVERGED: GEMINI_R86_TIGHTER] was 2.5
HARD_STOP_FLOOR = 0.07       # [VERIFIED: CONSISTENT_WITH_R80]
ATR_PERIOD = 14              # [PLACEHOLDER: ATR_PERIOD_001]

# Trailing stop phases
TRAIL_BREAKEVEN_R = 1.0      # [CONVERGED: GEMINI_R86_TWO_PHASE] move to entry
TRAIL_ACTIVATE_R = 1.5       # [CONVERGED: GEMINI_R86_TWO_PHASE] start ATR trail
TRAIL_ATR_MULT_PHASE2 = 2.0  # [PLACEHOLDER: TRAIL_ATR_MULT_1R_001]
TRAIL_TIGHTEN_R = 2.0        # [PLACEHOLDER: TRAIL_TIGHTEN_R_001]
TRAIL_ATR_MULT_PHASE3 = 1.5  # [PLACEHOLDER: TRAIL_ATR_MULT_2R_001]

# VCP integration
VCP_OVERRIDE_SCORE = 70      # [CONVERGED: GEMINI_R86_PIVOT_KING] mandatory override
VCP_CANDIDATE_SCORE = 50     # VCP pivot is candidate but ATR wins if tighter

# Gap risk analysis
GAP_HISTORY_DAYS = 90        # [PLACEHOLDER: GAP_HISTORY_DAYS_001]
GAP_PERCENTILE = 95          # [PLACEHOLDER: GAP_PERCENTILE_001]

# Structural stop: lookback for swing lows
SWING_LOW_LOOKBACK = 20      # [PLACEHOLDER: SWING_LOW_LOOKBACK_001]
SWING_LOW_WINDOW = 5         # [PLACEHOLDER: SWING_LOW_WINDOW_001]

# ATR multiplier mapping per entry type
ATR_MULTIPLIERS = {
    "squeeze_breakout": ATR_MULT_SQUEEZE,
    "oversold_bounce": ATR_MULT_OVERSOLD,
    "volume_ramp": ATR_MULT_VOL_RAMP,
    "momentum_breakout": ATR_MULT_MOMENTUM,
}

DEFAULT_ATR_MULT = 2.0  # fallback for unknown entry types


# ─── Data Classes ─────────────────────────────────────────────

@dataclass
class StopLevels:
    """Result of stop-loss calculation for a single position."""
    # Core stops
    initial_stop: float = 0.0
    stop_method: str = "percentage"  # which method was widest
    risk_pct: float = 0.0           # (entry - stop) / entry
    r_value: float = 0.0            # $ at risk per share

    # Individual method results
    structural_stop: float = 0.0
    atr_stop: float = 0.0
    percentage_stop: float = 0.0

    # VCP integration
    vcp_override: bool = False      # True if VCP pivot was used
    vcp_pivot_stop: float | None = None

    # Trailing stop phases
    trail_breakeven_price: float = 0.0   # Phase 1: move to entry at +1R
    trail_activate_price: float = 0.0    # Phase 2: start ATR trail at +1.5R
    trail_tighten_price: float = 0.0     # Phase 3: tighten at +2R
    current_atr: float = 0.0

    # Gap risk
    gap_risk_pct: float = 0.0       # 95th percentile gap-down size
    gap_warning: bool = False        # True if gap risk > stop distance

    # Metadata
    entry_price: float = 0.0
    entry_type: str = ""
    atr_multiplier: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_stop": round(self.initial_stop, 2),
            "stop_method": self.stop_method,
            "risk_pct": round(self.risk_pct, 4),
            "r_value": round(self.r_value, 2),
            "structural_stop": round(self.structural_stop, 2),
            "atr_stop": round(self.atr_stop, 2),
            "percentage_stop": round(self.percentage_stop, 2),
            "vcp_override": self.vcp_override,
            "vcp_pivot_stop": round(self.vcp_pivot_stop, 2) if self.vcp_pivot_stop else None,
            "trail_breakeven_price": round(self.trail_breakeven_price, 2),
            "trail_activate_price": round(self.trail_activate_price, 2),
            "trail_tighten_price": round(self.trail_tighten_price, 2),
            "current_atr": round(self.current_atr, 4),
            "gap_risk_pct": round(self.gap_risk_pct, 4),
            "gap_warning": self.gap_warning,
            "entry_price": round(self.entry_price, 2),
            "entry_type": self.entry_type,
            "atr_multiplier": self.atr_multiplier,
            # Trailing stop target prices (for chart display)
            "targets": {
                "breakeven": round(self.entry_price, 2),
                "target_1r": round(self.entry_price + self.r_value, 2) if self.r_value > 0 else 0,
                "target_2r": round(self.entry_price + 2 * self.r_value, 2) if self.r_value > 0 else 0,
                "target_3r": round(self.entry_price + 3 * self.r_value, 2) if self.r_value > 0 else 0,
            },
        }


# ─── Core Functions ───────────────────────────────────────────

def _find_recent_swing_low(df: pd.DataFrame, lookback: int = SWING_LOW_LOOKBACK,
                           window: int = SWING_LOW_WINDOW) -> float | None:
    """Find the most recent swing low in the price data.

    A swing low is a local minimum where price is lower than
    surrounding bars within the window.
    """
    if len(df) < lookback:
        return None

    recent = df.tail(lookback)
    lows = recent["low"].values

    for i in range(len(lows) - 1, window - 1, -1):
        # Check if lows[i-window:i] and lows[i+1:i+window+1] are all higher
        left = lows[max(0, i - window):i]
        right = lows[i + 1:min(len(lows), i + window + 1)]

        if len(left) == 0 or len(right) == 0:
            continue

        if all(lows[i] <= l for l in left) and all(lows[i] <= r for r in right):
            return float(lows[i])

    # Fallback: use the minimum of last `lookback` bars
    return float(np.min(lows))


def _calculate_structural_stop(df: pd.DataFrame, entry_price: float,
                               vcp_context: dict | None = None) -> float:
    """Calculate structural stop below recent swing low or VCP pivot.

    For VCP score ≥70: uses pivot_price - 1 tick (mandatory override).
    For VCP score 50-69: pivot is a candidate alongside swing low.
    """
    swing_low = _find_recent_swing_low(df) or 0.0

    # VCP pivot integration
    if vcp_context and vcp_context.get("has_vcp") and vcp_context.get("pivot_price"):
        vcp_score = vcp_context.get("vcp_score", 0)
        pivot = vcp_context["pivot_price"]
        tick = get_tick_size(pivot)
        pivot_stop = pivot - tick  # Pivot - 1 tick (TWSE tick size)

        if vcp_score >= VCP_OVERRIDE_SCORE:
            # Mandatory override — pivot is king
            return pivot_stop
        elif vcp_score >= VCP_CANDIDATE_SCORE:
            # Candidate — use whichever is tighter (higher)
            return max(swing_low, pivot_stop)

    return swing_low


def _calculate_atr_stop(entry_price: float, atr: float, entry_type: str,
                        atr_adjustment: float = 0.0) -> float:
    """Calculate ATR-based stop: entry - N×ATR.

    Args:
        atr_adjustment: V1.3 P2 Dynamic ATR offset from shake-out analysis.
            Positive = widen stop (more room), Negative = tighten.
            Clamped to [ATR_FLOOR, ATR_CEILING] from dynamic_atr module.
    """
    base_mult = ATR_MULTIPLIERS.get(entry_type, DEFAULT_ATR_MULT)
    mult = base_mult + atr_adjustment
    # Clamp to safe bounds (V1.3 P2)
    mult = max(1.5, min(3.5, mult))
    return entry_price - mult * atr


def _calculate_percentage_stop(entry_price: float) -> float:
    """Calculate hard percentage floor stop."""
    return entry_price * (1 - HARD_STOP_FLOOR)


def _estimate_gap_risk(df: pd.DataFrame, days: int = GAP_HISTORY_DAYS) -> float:
    """Estimate gap-down risk from recent history.

    Returns the 95th percentile gap-down size as a fraction.
    Gap-down = (open - prev_close) / prev_close when negative.
    """
    if len(df) < 10:
        return 0.0

    recent = df.tail(days)
    if len(recent) < 10:
        recent = df

    opens = recent["open"].values[1:]
    prev_closes = recent["close"].values[:-1]

    # Calculate gap returns
    gaps = (opens - prev_closes) / prev_closes

    # Only negative gaps (gap-downs)
    gap_downs = gaps[gaps < 0]

    if len(gap_downs) < 3:
        return 0.0

    # 95th percentile of gap-down magnitude (positive number)
    return float(abs(np.percentile(gap_downs, 100 - GAP_PERCENTILE)))


def calculate_stop_levels(
    df: pd.DataFrame,
    entry_price: float,
    entry_type: str = "squeeze_breakout",
    vcp_context: dict | None = None,
    atr_adjustment: float = 0.0,
) -> StopLevels:
    """Calculate stop-loss levels for a position.

    Takes the WIDEST (most protective / lowest price) of 3 methods
    as the initial stop, unless VCP pivot override applies.

    Args:
        df: OHLCV DataFrame with indicators (needs 'atr' column or will compute)
        entry_price: Entry price per share
        entry_type: One of squeeze_breakout, oversold_bounce, volume_ramp, momentum_breakout
        vcp_context: Optional VCP detection result dict
        atr_adjustment: V1.3 P2 Dynamic ATR offset from shake-out rate analysis

    Returns:
        StopLevels dataclass with all stop information
    """
    result = StopLevels(entry_price=entry_price, entry_type=entry_type)

    if len(df) < 5 or entry_price <= 0:
        return result

    # Get ATR
    if "atr" in df.columns:
        atr = float(df["atr"].dropna().iloc[-1])
    else:
        # Compute ATR from raw data (SMA to match legacy behavior)
        from analysis.indicators import calculate_atr
        atr_df = calculate_atr(df, period=ATR_PERIOD, method="sma")
        atr = float(atr_df["atr"].dropna().iloc[-1])

    result.current_atr = atr
    # V1.3 P2: Apply dynamic ATR adjustment to base multiplier
    base_mult = ATR_MULTIPLIERS.get(entry_type, DEFAULT_ATR_MULT)
    result.atr_multiplier = max(1.5, min(3.5, base_mult + atr_adjustment))

    # 1. Structural stop
    structural = _calculate_structural_stop(df, entry_price, vcp_context)
    result.structural_stop = structural

    # 2. ATR stop (with dynamic adjustment)
    atr_stop = _calculate_atr_stop(entry_price, atr, entry_type, atr_adjustment)
    result.atr_stop = atr_stop

    # 3. Percentage stop (hard floor)
    pct_stop = _calculate_percentage_stop(entry_price)
    result.percentage_stop = pct_stop

    # Check VCP override
    vcp_overridden = False
    if (vcp_context and vcp_context.get("has_vcp")
            and vcp_context.get("vcp_score", 0) >= VCP_OVERRIDE_SCORE
            and vcp_context.get("pivot_price")):
        pivot = vcp_context["pivot_price"]
        tick = get_tick_size(pivot)
        vcp_stop = pivot - tick
        result.vcp_pivot_stop = vcp_stop

        # VCP pivot override: if tighter (higher) than ATR, use it
        if vcp_stop > atr_stop:
            vcp_overridden = True
            result.vcp_override = True
            result.initial_stop = vcp_stop
            result.stop_method = "vcp_pivot"
    elif (vcp_context and vcp_context.get("has_vcp")
          and vcp_context.get("pivot_price")):
        pivot = vcp_context["pivot_price"]
        tick = get_tick_size(pivot)
        result.vcp_pivot_stop = pivot - tick

    if not vcp_overridden:
        # Take the WIDEST (lowest price) as initial stop
        candidates = {
            "structural": structural,
            "atr": atr_stop,
            "percentage": pct_stop,
        }
        # Filter out zeros
        valid = {k: v for k, v in candidates.items() if v > 0}
        if valid:
            # Widest = highest stop price (tightest risk)
            # But we want the most protective — actually we want the WIDEST stop
            # meaning the one that gives the most room (lowest price)
            # Per spec: "take the WIDEST" = most room = lowest stop price
            result.stop_method = min(valid, key=valid.get)
            result.initial_stop = valid[result.stop_method]
        else:
            result.initial_stop = pct_stop
            result.stop_method = "percentage"

    # Ensure stop is not above entry (nonsensical)
    if result.initial_stop >= entry_price:
        result.initial_stop = pct_stop
        result.stop_method = "percentage"

    # Calculate risk metrics
    result.risk_pct = (entry_price - result.initial_stop) / entry_price
    result.r_value = entry_price - result.initial_stop

    # Trailing stop target prices
    r = result.r_value
    if r > 0:
        result.trail_breakeven_price = entry_price + TRAIL_BREAKEVEN_R * r
        result.trail_activate_price = entry_price + TRAIL_ACTIVATE_R * r
        result.trail_tighten_price = entry_price + TRAIL_TIGHTEN_R * r

    # Gap risk estimation
    gap_risk = _estimate_gap_risk(df)
    result.gap_risk_pct = gap_risk
    if gap_risk > result.risk_pct and result.risk_pct > 0:
        result.gap_warning = True

    return result


def compute_trailing_stop(
    entry_price: float,
    current_price: float,
    highest_price: float,
    initial_stop: float,
    current_atr: float,
    r_value: float,
    atr_adjustment: float = 0.0,
) -> dict[str, Any]:
    """Compute the current trailing stop based on 4-phase progression.

    Phase 0 (Entry → +1R): Initial stop holds.
    Phase 1 (+1R): Move stop to entry price (breakeven).
    Phase 2 (+1.5R): Activate ATR trail at highest_close - N×ATR.
    Phase 3 (+2R): Tighten trail to highest_close - N×ATR.

    Args:
        entry_price: Original entry price
        current_price: Current market price
        highest_price: Highest close since entry
        initial_stop: Original calculated stop
        current_atr: Current ATR value
        r_value: Initial risk per share (entry - initial_stop)
        atr_adjustment: V1.3 P2 Dynamic ATR offset (applied to trail multipliers)

    Returns:
        Dict with phase, current_stop, reason
    """
    if r_value <= 0:
        return {
            "phase": 0,
            "current_stop": initial_stop,
            "reason": "Invalid R-value",
        }

    current_r = (current_price - entry_price) / r_value
    highest_r = (highest_price - entry_price) / r_value

    # V1.3 P2: Apply dynamic ATR adjustment to trailing multipliers
    trail_mult_p2 = max(1.5, min(3.5, TRAIL_ATR_MULT_PHASE2 + atr_adjustment))
    trail_mult_p3 = max(1.5, min(3.5, TRAIL_ATR_MULT_PHASE3 + atr_adjustment))

    if highest_r >= TRAIL_TIGHTEN_R:
        # Phase 3: Tighten trail
        trail_stop = highest_price - trail_mult_p3 * current_atr
        # Never lower than entry (breakeven floor)
        trail_stop = max(trail_stop, entry_price)
        return {
            "phase": 3,
            "current_stop": round(trail_stop, 2),
            "reason": f"+{highest_r:.1f}R reached — trail tightened to {trail_mult_p3:.1f}×ATR",
        }
    elif highest_r >= TRAIL_ACTIVATE_R:
        # Phase 2: ATR trail
        trail_stop = highest_price - trail_mult_p2 * current_atr
        trail_stop = max(trail_stop, entry_price)
        return {
            "phase": 2,
            "current_stop": round(trail_stop, 2),
            "reason": f"+{highest_r:.1f}R reached — ATR trail active ({trail_mult_p2:.1f}×ATR)",
        }
    elif highest_r >= TRAIL_BREAKEVEN_R:
        # Phase 1: Breakeven lock
        return {
            "phase": 1,
            "current_stop": round(entry_price, 2),
            "reason": f"+{highest_r:.1f}R reached — stop moved to breakeven",
        }
    else:
        # Phase 0: Initial stop
        return {
            "phase": 0,
            "current_stop": round(initial_stop, 2),
            "reason": "Initial stop — waiting for +1R",
        }


def get_stop_context(
    df: pd.DataFrame,
    entry_price: float,
    entry_type: str = "squeeze_breakout",
    vcp_context: dict | None = None,
    atr_adjustment: float = 0.0,
) -> dict[str, Any]:
    """Main entry point for API — calculate stops and return JSON-safe dict.

    Args:
        atr_adjustment: V1.3 P2 Dynamic ATR offset from shake-out analysis.
    """
    levels = calculate_stop_levels(df, entry_price, entry_type, vcp_context, atr_adjustment)
    return levels.to_dict()

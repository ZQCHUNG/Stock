"""[KILLED R14.17] WarriorExitEngine — Aggressive Mode (R88)

=== KILLED BY CTO R14.17 ACID TEST (2026-02-23) ===
Kill Switch TRIGGERED in ALL 3 periods (IS/OOS/Stress).
- Fewer trades (81 vs Bold 110) AND worse returns (+3.00% vs +3.13%)
- Home Runs: only 3 across 108 stocks × 3 periods
- Payload Ratio: 0.40 (below 0.50 threshold)
- 3×ATR trailing bleeds alpha — exits too late, trend already reversed

ROOT CAUSE (CTO diagnosis):
- TW stock market convexity = rotation speed, NOT holding time
- Wider stops → hold losers longer, NOT capture bigger upside
- Pyramiding (MA20 touchdown) rarely fires in 60-day window

REPLACEMENT: "Sniper Mode" (R14.17.2) — Bold exits + higher sizing (1.5% risk)
  Sniper B: OOS +34.89% Calmar 8.06 vs baseline +13.88% Calmar 5.61

This file is preserved as historical documentation. DO NOT USE.
CTO conversation: ce94f8a78bb93401
===

ORIGINAL ARCHITECTURE NOTE — PHYSICAL ISOLATION:
This file WAS the WarriorExitEngine. It was 100% SEPARATE from strategy_bold.py.
"""

import pandas as pd
import numpy as np
from analysis.indicators import calculate_all_indicators
from analysis.strategy_bold import generate_bold_signals


# === WarriorExitEngine Parameters ===
# ABSOLUTELY NO tight stops. Read the module docstring.
STRATEGY_AGGRESSIVE_PARAMS = {
    # --- Entry: Reuses Bold 4 entry types (A/B/C/D) ---
    # Entry filtering is MORE aggressive (lower thresholds to catch more signals)
    "min_volume_lots": 100,           # Lower volume floor (vs Bold's 200)
    "volume_breakout_ratio": 2.0,     # Slightly lower (vs Bold's 2.5)

    # --- WarriorExitEngine: Wide stops, ride the wave ---
    # DISASTER STOP: -20% hard limit (Secretary mandate, non-negotiable)
    "disaster_stop_pct": 0.20,

    # ATR TRAILING: 3×ATR from entry (CTO mandate)
    # Rationale: TW stocks gap up/down violently in main waves, 2×ATR gets stopped out
    "atr_trail_multiplier": 3.0,
    "atr_period": 20,

    # MA20 SLOPE COMBO STOP (CTO proposal — "Volatile Structural Stop")
    # Trigger: MA20 slope turns negative AND price < last week's low
    # This catches trend exhaustion without being too early
    "ma20_slope_combo_enabled": True,
    "ma20_slope_lookback": 5,         # Days to compute slope

    # MA50 DEATH CROSS: Final defense line
    # Only triggers after min_hold_days to avoid early false signals
    "ma50_death_cross_enabled": True,

    # HOLDING PERIOD
    "min_hold_days": 5,               # Minimum before any trailing exit
    "max_hold_days": 60,              # Max hold (aggressive = shorter cycles than Ultra-Wide)

    # --- Pyramiding (加碼) ---
    "pyramid_enabled": True,
    "pyramid_initial_pct": 0.20,      # First entry: 20% of allocated capital
    "pyramid_add_pct": 0.10,          # Each add: 10%
    "pyramid_max_total_pct": 0.40,    # Max total per stock: 40%
    "pyramid_max_adds": 2,            # Max 2 additions (20% + 10% + 10%)
    # Pyramid conditions (CTO: MA20 touchdown, not random %)
    "pyramid_min_gain_pct": 0.05,     # Must be profitable before adding
    "pyramid_volume_confirm": True,   # Volume must confirm the add

    # --- Position Management ---
    "max_positions": 2,               # Max 2 stocks simultaneously
    "require_sector_diversity": True, # Secretary mandate: no same sector

    # --- Liquidity Gate (Secretary mandate) ---
    # Entry size < 2% of 20-day avg volume
    "liquidity_pct_cap": 0.02,

    # --- Metrics ---
    # New North Star metrics (not Calmar)
    "payload_ratio_target": 0.50,     # Top 5% trades profit / total profit > 50%
    "home_run_threshold": 0.50,       # Trade with >50% gain = Home Run
}


def compute_warrior_exit(
    entry_price: float,
    current_price: float,
    peak_price: float,
    current_atr: float,
    hold_days: int,
    current_low: float,
    params: dict | None = None,
    # MA indicators for combo stop
    current_ma20: float | None = None,
    ma20_slope: float | None = None,
    weekly_low: float | None = None,
    # MA50 for death cross
    current_ma50: float | None = None,
    price_above_ma50: bool | None = None,
    prev_price_above_ma50: bool | None = None,
    # Gap-Down Guard (CTO R88 recommendation)
    current_open: float | None = None,
) -> dict:
    """WarriorExitEngine — Aggressive Mode exit logic.

    EXIT HIERARCHY (checked in order):
    0. Gap-Down Guard: open price already below disaster stop → exit at open
    1. Disaster stop: -20% from entry (HARD, no exceptions)
    2. ATR 3× trailing: from entry, widens as ATR grows
    3. MA20 slope combo: MA20 slope negative + price < weekly low
    4. MA50 death cross: price crosses below MA50 (final defense)
    5. Max hold days: force exit at 60 days

    WHAT IS NOT HERE (by design):
    - NO structural_stop (跌破前日低 → REMOVED)
    - NO time_stop_5d (5天沒漲就砍 → REMOVED)
    - NO tight trailing stops (nothing tighter than 3×ATR)
    """
    p = dict(STRATEGY_AGGRESSIVE_PARAMS)
    if params:
        p.update(params)

    gain_pct = (current_price / entry_price) - 1
    drawdown_from_peak = (current_price / peak_price) - 1 if peak_price > 0 else 0

    # === EXIT 0: GAP-DOWN GUARD (CTO R88 recommendation) ===
    # TW market limit-down gaps can bypass -20% stop if open < disaster level.
    # Exit immediately at open price to prevent further slippage.
    if current_open is not None:
        open_gain = (current_open / entry_price) - 1
        if open_gain <= -p["disaster_stop_pct"]:
            return {
                "should_exit": True,
                "exit_reason": "gap_down_guard",
                "gain_pct": gain_pct,
                "drawdown_from_peak": drawdown_from_peak,
                "trailing_stop_price": current_open,
            }

    # === EXIT 1: DISASTER STOP — -20% hard limit ===
    # Secretary mandate. Non-negotiable. Even during min_hold_days.
    if gain_pct <= -p["disaster_stop_pct"]:
        return {
            "should_exit": True,
            "exit_reason": f"disaster_stop_{p['disaster_stop_pct']*100:.0f}pct",
            "gain_pct": gain_pct,
            "drawdown_from_peak": drawdown_from_peak,
            "trailing_stop_price": entry_price * (1 - p["disaster_stop_pct"]),
        }

    # === MIN HOLD PROTECTION ===
    # Give the trade room to breathe. Only disaster stop applies before this.
    if hold_days < p["min_hold_days"]:
        atr_stop = entry_price - p["atr_trail_multiplier"] * current_atr
        return {
            "should_exit": False,
            "exit_reason": "",
            "gain_pct": gain_pct,
            "drawdown_from_peak": drawdown_from_peak,
            "trailing_stop_price": max(
                atr_stop,
                entry_price * (1 - p["disaster_stop_pct"])
            ),
        }

    # === EXIT 2: ATR 3× TRAILING ===
    # From entry, trail at peak - 3×ATR. Widens naturally as volatility grows.
    if current_atr > 0:
        atr_stop = peak_price - p["atr_trail_multiplier"] * current_atr
        # Floor: never let ATR stop be tighter than -20% from entry
        atr_floor = entry_price * (1 - p["disaster_stop_pct"])
        atr_stop = max(atr_stop, atr_floor)

        if current_price <= atr_stop:
            return {
                "should_exit": True,
                "exit_reason": "atr_trail_3x",
                "gain_pct": gain_pct,
                "drawdown_from_peak": drawdown_from_peak,
                "trailing_stop_price": atr_stop,
            }

    # === EXIT 3: MA20 SLOPE COMBO STOP ===
    # CTO's "Volatile Structural Stop": MA20 slope negative + price < weekly low
    # This catches trend exhaustion without premature exit
    if (p.get("ma20_slope_combo_enabled", True)
            and ma20_slope is not None
            and weekly_low is not None
            and current_ma20 is not None):
        if ma20_slope <= 0 and current_price < weekly_low:
            return {
                "should_exit": True,
                "exit_reason": "ma20_slope_combo",
                "gain_pct": gain_pct,
                "drawdown_from_peak": drawdown_from_peak,
                "trailing_stop_price": weekly_low,
            }

    # === EXIT 4: MA50 DEATH CROSS ===
    # Final defense: price crosses below MA50
    if (p.get("ma50_death_cross_enabled", True)
            and current_ma50 is not None
            and price_above_ma50 is not None
            and prev_price_above_ma50 is not None):
        # Death cross = was above MA50 yesterday, now below
        if prev_price_above_ma50 and not price_above_ma50:
            return {
                "should_exit": True,
                "exit_reason": "ma50_death_cross",
                "gain_pct": gain_pct,
                "drawdown_from_peak": drawdown_from_peak,
                "trailing_stop_price": current_ma50,
            }

    # === EXIT 5: MAX HOLD DAYS ===
    if hold_days >= p["max_hold_days"]:
        return {
            "should_exit": True,
            "exit_reason": f"max_hold_{p['max_hold_days']}d",
            "gain_pct": gain_pct,
            "drawdown_from_peak": drawdown_from_peak,
            "trailing_stop_price": current_price,
        }

    # === HOLD — No exit triggered ===
    # Compute current trailing stop for display
    if current_atr > 0:
        display_stop = max(
            peak_price - p["atr_trail_multiplier"] * current_atr,
            entry_price * (1 - p["disaster_stop_pct"])
        )
    else:
        display_stop = entry_price * (1 - p["disaster_stop_pct"])

    return {
        "should_exit": False,
        "exit_reason": "",
        "gain_pct": gain_pct,
        "drawdown_from_peak": drawdown_from_peak,
        "trailing_stop_price": display_stop,
    }


def check_pyramid_condition(
    entry_price: float,
    current_price: float,
    current_ma20: float | None,
    prev_close: float | None,
    current_volume: float | None,
    volume_ma20: float | None,
    add_count: int,
    params: dict | None = None,
) -> dict:
    """Check if pyramiding (加碼) conditions are met.

    CTO-approved pyramiding logic:
    - Add Point A (Base Breakout): After first pullback, second wave breakout
    - Add Point B (MA20 Touchdown): Price tests MA20, holds with shrinking volume, resumes up

    IRON RULE: Never add to a losing position (No Loser Averaging).
    """
    p = dict(STRATEGY_AGGRESSIVE_PARAMS)
    if params:
        p.update(params)

    if not p.get("pyramid_enabled", True):
        return {"should_add": False, "reason": "disabled"}

    if add_count >= p.get("pyramid_max_adds", 2):
        return {"should_add": False, "reason": "max_adds_reached"}

    gain_pct = (current_price / entry_price) - 1

    # IRON RULE: Must be profitable
    if gain_pct < p.get("pyramid_min_gain_pct", 0.05):
        return {"should_add": False, "reason": "not_profitable_enough"}

    # MA20 Touchdown condition:
    # Price near MA20 (within 3%) AND turning back up AND volume confirming
    if current_ma20 is not None and prev_close is not None:
        dist_to_ma20 = (current_price / current_ma20) - 1

        # Price bouncing off MA20 (within 3% band, now above)
        ma20_touchdown = (
            0 <= dist_to_ma20 <= 0.05  # Within 5% above MA20
            and current_price > prev_close  # Price turning up today
        )

        # Volume confirmation (optional but preferred)
        vol_ok = True
        if (p.get("pyramid_volume_confirm", True)
                and current_volume is not None
                and volume_ma20 is not None
                and volume_ma20 > 0):
            vol_ok = current_volume > volume_ma20 * 0.8  # Volume at least 80% of avg

        if ma20_touchdown and vol_ok:
            return {
                "should_add": True,
                "reason": "ma20_touchdown",
                "add_pct": p.get("pyramid_add_pct", 0.10),
            }

    return {"should_add": False, "reason": "no_condition_met"}


def compute_aggressive_metrics(trades: list[dict]) -> dict:
    """Compute Aggressive Mode specific metrics.

    North Star Metrics (replacing Calmar for this mode):
    1. Payload Ratio: Top 5% trades profit / total profit
    2. Home Run Frequency: Trades with >50% gain
    3. Ulcer Index: Pain measurement
    """
    if not trades:
        return {
            "payload_ratio": 0,
            "home_run_count": 0,
            "home_run_pct": 0,
            "ulcer_index": 0,
            "avg_winner": 0,
            "avg_loser": 0,
            "largest_winner": 0,
            "largest_loser": 0,
            "capture_rate_30": 0,
            "capture_rate_50": 0,
        }

    returns = [t.get("return_pct", 0) for t in trades]
    profits = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    n = len(trades)

    # 1. Payload Ratio: Top 5% most profitable trades' profit / total profit
    total_profit = sum(max(r, 0) for r in returns)
    if total_profit > 0 and len(profits) > 0:
        sorted_profits = sorted(profits, reverse=True)
        top_5pct_count = max(1, int(len(profits) * 0.05))
        top_5pct_profit = sum(sorted_profits[:top_5pct_count])
        payload_ratio = top_5pct_profit / total_profit
    else:
        payload_ratio = 0

    # 2. Home Run Frequency: Trades with >50% gain
    home_runs = [r for r in returns if r >= 0.50]
    home_run_count = len(home_runs)
    home_run_pct = home_run_count / n if n > 0 else 0

    # 3. Capture Rates
    capture_30 = len([r for r in returns if r >= 0.30]) / n if n > 0 else 0
    capture_50 = len([r for r in returns if r >= 0.50]) / n if n > 0 else 0

    # 4. Win/Loss stats
    avg_winner = np.mean(profits) if profits else 0
    avg_loser = np.mean(losses) if losses else 0
    largest_winner = max(returns) if returns else 0
    largest_loser = min(returns) if returns else 0

    return {
        "payload_ratio": round(float(payload_ratio), 4),
        "home_run_count": home_run_count,
        "home_run_pct": round(float(home_run_pct), 4),
        "ulcer_index": 0,  # Computed from equity curve, not trades
        "avg_winner": round(float(avg_winner), 4),
        "avg_loser": round(float(avg_loser), 4),
        "largest_winner": round(float(largest_winner), 4),
        "largest_loser": round(float(largest_loser), 4),
        "capture_rate_30": round(float(capture_30), 4),
        "capture_rate_50": round(float(capture_50), 4),
    }


def check_regime_gate(
    taiex_close: float | None = None,
    taiex_ma200: float | None = None,
    taiex_ma20_slope: float | None = None,
) -> dict:
    """Global Regime Gate — CTO R88 recommendation.

    Aggressive Mode should only "unlock" when TAIEX is healthy.
    If TAIEX is below MA200 or MA20 slope is negative → block new entries.

    Returns:
        {"allowed": bool, "reason": str, "downshift": str}
    """
    if taiex_close is None or taiex_ma200 is None:
        # No data → allow (graceful degradation)
        return {"allowed": True, "reason": "no_taiex_data", "downshift": "none"}

    below_ma200 = taiex_close < taiex_ma200
    slope_negative = taiex_ma20_slope is not None and taiex_ma20_slope < 0

    if below_ma200:
        return {
            "allowed": False,
            "reason": "taiex_below_ma200",
            "downshift": "bold",  # Fall back to TimidExitEngine
        }

    if slope_negative and below_ma200:
        return {
            "allowed": False,
            "reason": "taiex_bearish",
            "downshift": "skip",  # Skip entries entirely
        }

    if slope_negative:
        # MA20 slope negative but still above MA200 → cautious, allow with warning
        return {
            "allowed": True,
            "reason": "taiex_weakening",
            "downshift": "reduce_size",  # Reduce position size
        }

    return {"allowed": True, "reason": "taiex_healthy", "downshift": "none"}


def compute_ulcer_index(equity_curve: pd.Series) -> float:
    """Compute Ulcer Index from equity curve.

    Ulcer Index measures the depth and duration of drawdowns.
    UI = sqrt(mean(drawdown_pct^2))

    Lower = less pain. Higher = Joe needs to brace himself.
    """
    if equity_curve.empty or len(equity_curve) < 2:
        return 0.0

    cummax = equity_curve.cummax()
    drawdown_pct = ((equity_curve - cummax) / cummax) * 100  # In percentage
    ulcer_index = np.sqrt(np.mean(drawdown_pct ** 2))
    return round(float(ulcer_index), 4)

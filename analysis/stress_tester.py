"""Flash Crash Stress Test — Black Swan scenario simulator.

Phase 10 P0: CTO directive — "量化在最極端情況下的財務影響"
Architect approved: 3-day limit-down lock (台股 10%/day) + slippage

Scenario: All active positions simultaneously hit limit-down for N consecutive days.
Formula: E_stressed = E_current × (1 - LimitDown_10%)^3
Enhancement: slippage_multiplier = 0.95 (5% gap-down on exit)

[HYPOTHESIS: STRESS_TEST_PARAMS_V1]
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Stress Test parameters — Architect approved
LIMIT_DOWN_PCT = 0.10          # Taiwan stock daily limit: 10%
DEFAULT_STRESS_DAYS = 3        # Consecutive limit-down days
SLIPPAGE_MULTIPLIER = 0.95     # 5% gap-down slippage on forced exit
BUST_THRESHOLD = 0.50          # < 50% of initial equity = "bust"
INITIAL_EQUITY = 3_000_000     # [PLACEHOLDER] Joe's assumed capital (TWD)


def run_stress_test(
    stress_days: int = DEFAULT_STRESS_DAYS,
    slippage: float = SLIPPAGE_MULTIPLIER,
) -> dict:
    """Run Flash Crash stress test on current active positions.

    Architect directive: "最好的防禦，是在黑天鵝還沒起飛前，就已經在模擬器中殺死它一百次"

    Returns:
        {
            "scenario": str,
            "initial_equity": float,
            "current_equity": float,     # from War Room (virtual)
            "stressed_equity": float,    # after N-day limit-down
            "stressed_mdd_pct": float,   # max drawdown from peak
            "total_loss_pct": float,     # loss from current equity
            "is_bust": bool,             # < 50% initial equity
            "bust_threshold_pct": float, # 50%
            "positions_at_risk": int,    # number of active positions
            "per_position_details": [...],
            "stress_days": int,
            "slippage_multiplier": float,
            "recovery_needed_pct": float, # % gain needed to recover
        }
    """
    from analysis.signal_log import get_active_signals

    # Get current active positions
    active = get_active_signals(days_back=90)
    if not active:
        return _empty_result(stress_days, slippage)

    # Compute current virtual equity from active positions
    total_exposure = 0
    position_details = []

    for sig in active:
        entry_price = sig.get("entry_price", 0)
        if not entry_price or entry_price <= 0:
            continue

        # Estimate position value using risk-based sizing
        worst_case = sig.get("worst_case_pct")
        conf_score = sig.get("sim_score", 0)
        pos_pct = _estimate_position_pct(entry_price, worst_case, conf_score)

        position_value = INITIAL_EQUITY * pos_pct

        # Stress scenario: N days of limit-down
        # Day 1: price drops 10%, Day 2: another 10%, Day 3: another 10%
        # Compounding: final_price = entry × (1 - 0.10)^N
        crash_factor = (1 - LIMIT_DOWN_PCT) ** stress_days

        # Apply slippage on forced exit (gap-down, can't exit at stop)
        exit_factor = crash_factor * slippage

        stressed_value = position_value * exit_factor
        loss = position_value - stressed_value
        loss_pct = (1 - exit_factor) * 100

        position_details.append({
            "stock_code": sig.get("stock_code", ""),
            "stock_name": sig.get("stock_name", ""),
            "entry_price": entry_price,
            "position_pct": round(pos_pct, 4),
            "position_value": round(position_value, 0),
            "stressed_value": round(stressed_value, 0),
            "loss": round(loss, 0),
            "loss_pct": round(loss_pct, 2),
        })

        total_exposure += position_value

    # Compute portfolio-level impact
    total_loss = sum(p["loss"] for p in position_details)
    stressed_equity = INITIAL_EQUITY - total_loss
    total_loss_pct = (total_loss / INITIAL_EQUITY * 100) if INITIAL_EQUITY > 0 else 0
    is_bust = stressed_equity < (INITIAL_EQUITY * BUST_THRESHOLD)

    # Recovery needed: if you're at X, you need (1/X - 1) * 100% to recover
    recovery_pct = 0
    if stressed_equity > 0 and stressed_equity < INITIAL_EQUITY:
        recovery_pct = ((INITIAL_EQUITY / stressed_equity) - 1) * 100

    scenario_desc = (
        f"Flash Crash: All {len(position_details)} positions hit "
        f"{stress_days}-day consecutive limit-down ({LIMIT_DOWN_PCT:.0%}/day) "
        f"with {(1 - slippage):.0%} slippage"
    )

    return {
        "scenario": scenario_desc,
        "initial_equity": INITIAL_EQUITY,
        "current_equity": INITIAL_EQUITY,  # virtual baseline
        "stressed_equity": round(stressed_equity, 0),
        "stressed_mdd_pct": round(-total_loss_pct, 2),
        "total_loss_pct": round(total_loss_pct, 2),
        "total_loss": round(total_loss, 0),
        "is_bust": is_bust,
        "bust_threshold_pct": BUST_THRESHOLD * 100,
        "positions_at_risk": len(position_details),
        "total_exposure": round(total_exposure, 0),
        "exposure_pct": round(total_exposure / INITIAL_EQUITY * 100, 1) if INITIAL_EQUITY > 0 else 0,
        "per_position_details": position_details,
        "stress_days": stress_days,
        "slippage_multiplier": slippage,
        "crash_factor": round((1 - LIMIT_DOWN_PCT) ** stress_days, 4),
        "exit_factor": round((1 - LIMIT_DOWN_PCT) ** stress_days * slippage, 4),
        "recovery_needed_pct": round(recovery_pct, 1),
    }


def _estimate_position_pct(
    entry_price: float,
    worst_case_pct: Optional[float],
    confidence_score: int,
) -> float:
    """Estimate position percentage using the same logic as auto_sim."""
    equity = INITIAL_EQUITY
    risk_per_trade = 0.02  # 2% risk

    if worst_case_pct is not None and worst_case_pct < 0:
        risk_per_share = entry_price * abs(worst_case_pct) / 100.0
        if risk_per_share > 0:
            risk_amount = equity * risk_per_trade
            shares = int(risk_amount / risk_per_share)
            pos_value = shares * entry_price
            pos_pct = min(0.20, pos_value / equity if equity > 0 else 0)
        else:
            pos_pct = 0.10
    else:
        pos_pct = 0.10  # Default fallback

    # Confidence adjustment
    if confidence_score < 40:
        pos_pct *= 0.5
    elif confidence_score < 70:
        pos_pct *= 0.7

    return pos_pct


def _empty_result(stress_days: int, slippage: float) -> dict:
    """Return empty stress test result when no active positions."""
    return {
        "scenario": "No active positions",
        "initial_equity": INITIAL_EQUITY,
        "current_equity": INITIAL_EQUITY,
        "stressed_equity": INITIAL_EQUITY,
        "stressed_mdd_pct": 0,
        "total_loss_pct": 0,
        "total_loss": 0,
        "is_bust": False,
        "bust_threshold_pct": BUST_THRESHOLD * 100,
        "positions_at_risk": 0,
        "total_exposure": 0,
        "exposure_pct": 0,
        "per_position_details": [],
        "stress_days": stress_days,
        "slippage_multiplier": slippage,
        "crash_factor": round((1 - LIMIT_DOWN_PCT) ** stress_days, 4),
        "exit_factor": round((1 - LIMIT_DOWN_PCT) ** stress_days * slippage, 4),
        "recovery_needed_pct": 0,
    }

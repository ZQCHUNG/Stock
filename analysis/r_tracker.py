"""
R86: R-Multiple Tracker + System Expectancy — Gemini CTO Approved

Tracks position performance in units of initial risk (R-multiples).
Computes System Expectancy: (Win% × Avg_Win_R) - (Loss% × Avg_Loss_R).

Key features:
- Realized R vs Intended R (gap-down accounting)
- Status labels: Initial Risk, Breakeven, 1R Winner, Home Run
- Expectancy grades: Losing System, Break-even, Profitable, Market Wizard
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ─── Constants ────────────────────────────────────────────────

# R-Multiple status thresholds
R_BREAKEVEN_ZONE = 0.1       # |R| < 0.1 = breakeven zone
R_WINNER_THRESHOLD = 1.0     # R ≥ 1.0 = 1R winner
R_HOME_RUN_THRESHOLD = 3.0   # R ≥ 3.0 = home run

# Expectancy grades [CONVERGED: GEMINI_R86_EXPECTANCY]
EXPECTANCY_LOSING = 0.0      # < 0.0 = Losing System
EXPECTANCY_BREAKEVEN = 0.5   # 0.0-0.5 = Break-even Trader
EXPECTANCY_PROFITABLE = 1.0  # 0.5-1.0 = Profitable System
# > 1.0 = Market Wizard


# ─── Core Functions ───────────────────────────────────────────

def compute_r_multiple(
    entry_price: float,
    current_price: float,
    stop_price: float,
) -> float:
    """Compute R-multiple: current gain / initial risk.

    R = (current_price - entry_price) / (entry_price - stop_price)
    Positive R = profit in units of initial risk.
    Negative R = loss in units of initial risk.

    Returns:
        R-multiple value. 0.0 if entry == stop (zero risk).
    """
    risk = entry_price - stop_price
    if risk <= 0:
        return 0.0
    return (current_price - entry_price) / risk


def get_r_status(r_multiple: float) -> str:
    """Get human-readable status label for an R-multiple.

    Returns one of:
    - "Home Run" (R ≥ 3.0)
    - "1R Winner" (1.0 ≤ R < 3.0)
    - "Breakeven" (|R| < 0.1)
    - "Initial Risk" (R < 0)
    - "Partial Gain" (0.1 ≤ R < 1.0)
    """
    if r_multiple >= R_HOME_RUN_THRESHOLD:
        return "Home Run"
    elif r_multiple >= R_WINNER_THRESHOLD:
        return "1R Winner"
    elif abs(r_multiple) < R_BREAKEVEN_ZONE:
        return "Breakeven"
    elif r_multiple < 0:
        return "Initial Risk"
    else:
        return "Partial Gain"


def get_r_color(r_multiple: float) -> str:
    """Get display color for R-multiple value."""
    if r_multiple >= R_HOME_RUN_THRESHOLD:
        return "#a855f7"  # purple — home run
    elif r_multiple >= R_WINNER_THRESHOLD:
        return "#22c55e"  # green — winner
    elif abs(r_multiple) < R_BREAKEVEN_ZONE:
        return "#94a3b8"  # grey — breakeven
    elif r_multiple < -1.0:
        return "#ef4444"  # red — big loser
    elif r_multiple < 0:
        return "#f59e0b"  # amber — in the hole
    else:
        return "#3b82f6"  # blue — partial gain


def track_position_r(
    positions: list[dict],
) -> list[dict[str, Any]]:
    """Compute R-multiples for a list of open positions.

    Each position dict should have:
        code, entry_price, current_price, stop_price
    Optional:
        exit_price (for closed positions — realized R)
        name, lots

    Returns:
        List of position dicts enriched with R-multiple data.
    """
    results = []
    for pos in positions:
        entry = pos.get("entry_price", 0)
        current = pos.get("current_price", entry)
        stop = pos.get("stop_price", 0)
        exit_price = pos.get("exit_price")

        # Intended R (based on current price vs stop)
        intended_r = compute_r_multiple(entry, current, stop)

        # Realized R (based on actual exit price)
        realized_r = None
        gap_slippage = None
        if exit_price is not None:
            realized_r = compute_r_multiple(entry, exit_price, stop)
            gap_slippage = realized_r - compute_r_multiple(entry, stop, stop)
            # More useful: gap_slippage = realized_r vs what intended_r was at exit
            # If exit was at stop, intended_r = -1.0, realized_r could be worse
            gap_slippage = (realized_r - intended_r) if exit_price != current else None

        r_val = realized_r if realized_r is not None else intended_r
        status = get_r_status(r_val)
        color = get_r_color(r_val)

        risk_per_share = entry - stop if stop > 0 else 0
        display_text = ""
        if risk_per_share > 0 and r_val > 0:
            gain_per_share = current - entry if exit_price is None else exit_price - entry
            display_text = f"Risking ${risk_per_share:.1f} to make ${gain_per_share:.1f}"

        results.append({
            "code": pos.get("code", ""),
            "name": pos.get("name", ""),
            "lots": pos.get("lots", 0),
            "entry_price": entry,
            "current_price": current,
            "stop_price": stop,
            "exit_price": exit_price,
            "intended_r": round(intended_r, 2),
            "realized_r": round(realized_r, 2) if realized_r is not None else None,
            "gap_slippage": round(gap_slippage, 2) if gap_slippage is not None else None,
            "r_status": status,
            "r_color": color,
            "display_text": display_text,
            "risk_per_share": round(risk_per_share, 2),
            "is_closed": exit_price is not None,
        })

    return results


def compute_system_expectancy(
    trades: list[dict],
) -> dict[str, Any]:
    """Compute System Expectancy from closed trade R-multiples.

    Expectancy = (Win% × Avg_Win_R) - (Loss% × Avg_Loss_R)

    [CONVERGED: GEMINI_R86_EXPECTANCY]
    Uses REALIZED R, not intended R. No fantasy accounting.

    Args:
        trades: List of closed trade dicts, each with 'realized_r' or 'intended_r'.

    Returns:
        Dict with expectancy, win_rate, avg_win_r, avg_loss_r, grade, etc.
    """
    if not trades:
        return {
            "expectancy": 0.0,
            "grade": "Insufficient Data",
            "grade_color": "#6b7280",
            "win_rate": 0.0,
            "loss_rate": 0.0,
            "avg_win_r": 0.0,
            "avg_loss_r": 0.0,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "breakevens": 0,
            "best_r": 0.0,
            "worst_r": 0.0,
            "r_distribution": {},
        }

    # Extract R values (prefer realized, fall back to intended)
    r_values = []
    for t in trades:
        r = t.get("realized_r")
        if r is None:
            r = t.get("intended_r", 0.0)
        r_values.append(float(r))

    total = len(r_values)
    wins = [r for r in r_values if r > R_BREAKEVEN_ZONE]
    losses = [r for r in r_values if r < -R_BREAKEVEN_ZONE]
    breakevens = [r for r in r_values if abs(r) <= R_BREAKEVEN_ZONE]

    win_rate = len(wins) / total if total > 0 else 0
    loss_rate = len(losses) / total if total > 0 else 0
    avg_win_r = sum(wins) / len(wins) if wins else 0.0
    avg_loss_r = abs(sum(losses) / len(losses)) if losses else 0.0

    # Expectancy formula [CONVERGED: GEMINI_R86_EXPECTANCY]
    expectancy = (win_rate * avg_win_r) - (loss_rate * avg_loss_r)

    # Grade classification
    if total < 10:
        grade = "Insufficient Data"
        grade_color = "#6b7280"
    elif expectancy < EXPECTANCY_LOSING:
        grade = "Losing System"
        grade_color = "#ef4444"
    elif expectancy < EXPECTANCY_BREAKEVEN:
        grade = "Break-even Trader"
        grade_color = "#f59e0b"
    elif expectancy < EXPECTANCY_PROFITABLE:
        grade = "Profitable System"
        grade_color = "#22c55e"
    else:
        grade = "Market Wizard"
        grade_color = "#a855f7"

    # R-distribution buckets
    r_dist = {
        "big_loss_below_neg2": len([r for r in r_values if r < -2]),
        "loss_neg2_to_neg1": len([r for r in r_values if -2 <= r < -1]),
        "small_loss_neg1_to_0": len([r for r in r_values if -1 <= r < -R_BREAKEVEN_ZONE]),
        "breakeven": len(breakevens),
        "small_win_0_to_1": len([r for r in r_values if R_BREAKEVEN_ZONE <= r < 1]),
        "win_1_to_2": len([r for r in r_values if 1 <= r < 2]),
        "big_win_2_to_3": len([r for r in r_values if 2 <= r < 3]),
        "home_run_above_3": len([r for r in r_values if r >= 3]),
    }

    return {
        "expectancy": round(expectancy, 3),
        "grade": grade,
        "grade_color": grade_color,
        "win_rate": round(win_rate, 3),
        "loss_rate": round(loss_rate, 3),
        "avg_win_r": round(avg_win_r, 2),
        "avg_loss_r": round(avg_loss_r, 2),
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": len(breakevens),
        "best_r": round(max(r_values), 2) if r_values else 0.0,
        "worst_r": round(min(r_values), 2) if r_values else 0.0,
        "r_distribution": r_dist,
    }

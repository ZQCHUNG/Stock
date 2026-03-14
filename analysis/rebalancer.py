"""Portfolio Rebalancing Engine — V1.3 P0

CTO/Architect OFFICIALLY APPROVED (V1.3 Roadmap).
Position-Intelligence: dynamic rebalancing suggestions based on
Aggressive Index + Market Guard + Portfolio Heat.

Core Logic (CTO-approved matrix):
  Agg < 40 (Defensive) → suggest scale-down to 50%
  Agg 40-60 (Normal)   → hold current
  Agg > 60 (Aggressive) + Guard NORMAL → can scale up to 100%
  Guard CAUTION  → force scale-down regardless of Agg
  Guard LOCKDOWN → suggest full exit

CTO Addition: Hysteresis Buffer (anti-churning)
  Agg must hold threshold for 2 consecutive days before
  triggering a structural adjustment.

Two-Tier Adjustments (CTO directive):
  Light: ±10% (fine-tuning within current allocation)
  Structural: ±50% (regime-driven wholesale change)

[HYPOTHESIS: REBALANCE_AGG_THRESHOLDS_V1] — 40/60 split
[PLACEHOLDER: REBALANCE_SCALEDOWN_50] — 50% target in Defensive
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_FILE = DATA_DIR / "rebalancer_state.json"

# ─── Thresholds [HYPOTHESIS: REBALANCE_AGG_THRESHOLDS_V1] ───
AGG_DEFENSIVE = 40       # Below → scale down
AGG_AGGRESSIVE = 60      # Above → can scale up

# Target exposure per regime
EXPOSURE_DEFENSIVE = 0.50    # [PLACEHOLDER: REBALANCE_SCALEDOWN_50]
EXPOSURE_NORMAL = 1.00
EXPOSURE_AGGRESSIVE = 1.00

# Guard overrides
EXPOSURE_CAUTION = 0.50      # Guard CAUTION → force 50%
EXPOSURE_LOCKDOWN = 0.00     # Guard LOCKDOWN → exit all

# Hysteresis: consecutive days required to trigger structural change
HYSTERESIS_DAYS = 2          # CTO directive: anti-churning

# Two-tier adjustment thresholds (CTO directive)
LIGHT_ADJUSTMENT = 0.10      # ±10%
STRUCTURAL_ADJUSTMENT = 0.50  # ±50%


# ─── State Persistence ───────────────────────────────────────

def _load_state() -> dict:
    """Load persistent rebalancer state (hysteresis tracking)."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug(f"Optional data load failed: {e}")
    return {
        "prev_regime": "NORMAL",
        "regime_streak": 0,
        "last_date": None,
        "last_target_exposure": 1.0,
    }


def _save_state(state: dict) -> None:
    """Persist rebalancer state."""
    try:
        STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("Failed to save rebalancer state: %s", e)


# ─── Regime Classification ───────────────────────────────────

def classify_regime(agg_score: int | None, guard_level: int) -> str:
    """Classify current market regime from Agg Index + Guard Level.

    Returns: "LOCKDOWN", "CAUTION", "DEFENSIVE", "NORMAL", "AGGRESSIVE"
    """
    if guard_level >= 2:
        return "LOCKDOWN"
    if guard_level >= 1:
        return "CAUTION"
    if agg_score is None:
        return "NORMAL"
    if agg_score < AGG_DEFENSIVE:
        return "DEFENSIVE"
    if agg_score > AGG_AGGRESSIVE:
        return "AGGRESSIVE"
    return "NORMAL"


def get_target_exposure(regime: str) -> float:
    """Get raw target exposure for a regime (before hysteresis)."""
    return {
        "LOCKDOWN": EXPOSURE_LOCKDOWN,
        "CAUTION": EXPOSURE_CAUTION,
        "DEFENSIVE": EXPOSURE_DEFENSIVE,
        "NORMAL": EXPOSURE_NORMAL,
        "AGGRESSIVE": EXPOSURE_AGGRESSIVE,
    }.get(regime, EXPOSURE_NORMAL)


# ─── Hysteresis Logic (CTO: Anti-Churning) ───────────────────

def apply_hysteresis(
    current_regime: str,
    current_target: float,
    state: dict,
    today_str: str,
) -> tuple[float, str, dict]:
    """Apply hysteresis buffer to prevent regime-flip churning.

    CTO directive: Agg must hold threshold for 2 consecutive days
    before triggering a structural adjustment.

    Guard overrides (CAUTION/LOCKDOWN) bypass hysteresis —
    safety always takes priority.

    Returns: (effective_target, adjustment_type, updated_state)
    """
    prev_regime = state.get("prev_regime", "NORMAL")
    streak = state.get("regime_streak", 0)
    last_target = state.get("last_target_exposure", 1.0)
    last_date = state.get("last_date")

    # Guard overrides bypass hysteresis — safety first
    if current_regime in ("LOCKDOWN", "CAUTION"):
        new_state = {
            "prev_regime": current_regime,
            "regime_streak": 1,
            "last_date": today_str,
            "last_target_exposure": current_target,
        }
        adj_type = _classify_adjustment(last_target, current_target)
        return current_target, adj_type, new_state

    # Same regime as previous → increment streak
    if current_regime == prev_regime and last_date != today_str:
        streak += 1
    elif current_regime != prev_regime:
        streak = 1  # Reset on regime change

    # Check if streak meets hysteresis threshold
    if streak >= HYSTERESIS_DAYS:
        effective = current_target
    else:
        # Not enough consecutive days → hold previous target
        effective = last_target

    adj_type = _classify_adjustment(last_target, effective)

    new_state = {
        "prev_regime": current_regime,
        "regime_streak": streak,
        "last_date": today_str,
        "last_target_exposure": effective,
    }
    return effective, adj_type, new_state


def _classify_adjustment(old_target: float, new_target: float) -> str:
    """Classify adjustment magnitude (CTO: two-tier system)."""
    delta = abs(new_target - old_target)
    if delta < 0.01:
        return "HOLD"
    if delta <= LIGHT_ADJUSTMENT:
        return "LIGHT"
    return "STRUCTURAL"


# ─── Position-Level Actions ──────────────────────────────────

def compute_position_actions(
    positions: list[dict],
    target_exposure: float,
    regime: str,
) -> list[dict[str, Any]]:
    """Compute per-position rebalancing actions.

    Each position dict expects:
      code, name, is_live, entry_price, current_stop,
      trailing_phase, rs_rating, priority_score

    Returns list of action dicts:
      {code, name, current_weight, target_weight, action, reason, urgency}
    """
    if not positions:
        return []

    n = len(positions)
    actions = []

    for pos in positions:
        code = pos.get("code", "")
        name = pos.get("name", code)
        is_live = pos.get("is_live", False)
        trailing_phase = pos.get("trailing_phase", 0)

        # Current weight: equal weight as baseline (actual weights need portfolio value)
        current_weight = 1.0 / n if n > 0 else 0

        if regime == "LOCKDOWN":
            actions.append({
                "code": code,
                "name": name,
                "current_weight": round(current_weight * 100, 1),
                "target_weight": 0,
                "action": "EXIT",
                "reason": "Market Guard LOCKDOWN — 建議清倉",
                "urgency": "HIGH",
            })
            continue

        if regime == "CAUTION":
            new_weight = current_weight * EXPOSURE_CAUTION
            action_type = "REDUCE" if is_live else "SKIP"
            actions.append({
                "code": code,
                "name": name,
                "current_weight": round(current_weight * 100, 1),
                "target_weight": round(new_weight * 100, 1),
                "action": action_type,
                "reason": "Market Guard CAUTION — 減碼50%",
                "urgency": "MEDIUM",
            })
            continue

        if target_exposure < 1.0:
            # Defensive: reduce exposure but prioritize high-RS positions
            priority = pos.get("priority_score", 50)
            # Higher priority → keep more; lower priority → cut first
            priority_mult = 0.5 + 0.5 * (priority / 100)
            new_weight = current_weight * target_exposure * priority_mult
            if new_weight < current_weight * 0.9:
                action_type = "REDUCE"
                reason = f"Defensive regime — 依優先級減碼 (Score:{priority:.0f})"
                urgency = "MEDIUM"
            else:
                action_type = "HOLD"
                reason = f"高優先級保留 (Score:{priority:.0f})"
                urgency = "LOW"
        elif target_exposure >= 1.0 and regime == "AGGRESSIVE":
            if trailing_phase >= 2:
                action_type = "HOLD"
                reason = "ATR追蹤中 — 讓利潤奔跑"
                urgency = "LOW"
                new_weight = current_weight
            else:
                action_type = "HOLD"
                reason = "Aggressive regime — 可加碼"
                urgency = "LOW"
                new_weight = current_weight
        else:
            action_type = "HOLD"
            reason = "Normal regime — 維持現狀"
            urgency = "LOW"
            new_weight = current_weight

        actions.append({
            "code": code,
            "name": name,
            "current_weight": round(current_weight * 100, 1),
            "target_weight": round(new_weight * 100, 1),
            "action": action_type,
            "reason": reason,
            "urgency": urgency,
        })

    return actions


# ─── Main Entry Point ────────────────────────────────────────

def generate_rebalance_report(
    agg_score: int | None = None,
    guard_level: int = 0,
    guard_label: str = "NORMAL",
    positions: list[dict] | None = None,
) -> dict[str, Any]:
    """Generate portfolio rebalancing report.

    Can be called standalone or integrated into Morning Brief.

    Args:
        agg_score: Aggressive Index (0-100), None if unavailable
        guard_level: Market Guard level (0/1/2)
        guard_label: Market Guard label string
        positions: List of position dicts (from signal_log / morning brief)

    Returns dict with:
        regime, target_exposure, adjustment_type,
        hysteresis_active, position_actions, summary_message
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    state = _load_state()

    # 1. Classify regime
    regime = classify_regime(agg_score, guard_level)
    raw_target = get_target_exposure(regime)

    # 2. Apply hysteresis
    effective_target, adj_type, new_state = apply_hysteresis(
        regime, raw_target, state, today_str,
    )
    hysteresis_active = (effective_target != raw_target)

    # 3. Compute position-level actions
    if positions is None:
        positions = _fetch_live_positions()

    actions = compute_position_actions(positions, effective_target, regime)

    # 4. Generate summary message
    summary = _format_summary(
        regime, agg_score, guard_label,
        effective_target, adj_type, hysteresis_active, actions,
    )

    # 5. Save state
    _save_state(new_state)

    return {
        "timestamp": datetime.now().isoformat(),
        "regime": regime,
        "agg_score": agg_score,
        "guard_level": guard_level,
        "guard_label": guard_label,
        "target_exposure": effective_target,
        "raw_target_exposure": raw_target,
        "adjustment_type": adj_type,
        "hysteresis_active": hysteresis_active,
        "position_actions": actions,
        "summary_message": summary,
    }


# ─── Helper: Fetch Live Positions ────────────────────────────

def _fetch_live_positions() -> list[dict]:
    """Fetch current live positions from signal_log."""
    try:
        from analysis.signal_log import get_active_signals
        signals = get_active_signals(days_back=60)
        return [
            {
                "code": s.get("stock_code", ""),
                "name": s.get("stock_name", ""),
                "is_live": bool(s.get("is_live", 0)),
                "entry_price": s.get("entry_price"),
                "current_stop": s.get("current_stop_price"),
                "trailing_phase": s.get("trailing_phase", 0),
                "rs_rating": s.get("rs_rating"),
                "priority_score": 50,  # Default; caller should compute
            }
            for s in signals
            if s.get("is_live")
        ]
    except Exception as e:
        logger.warning("Failed to fetch live positions: %s", e)
        return []


# ─── Summary Formatter ────────────────────────────────────────

def _format_summary(
    regime: str,
    agg_score: int | None,
    guard_label: str,
    target_exposure: float,
    adj_type: str,
    hysteresis_active: bool,
    actions: list[dict],
) -> str:
    """Format rebalancing summary for Morning Brief Section 3."""
    lines = []

    # Regime header
    regime_icons = {
        "LOCKDOWN": "\U0001f6d1",
        "CAUTION": "\u26a0\ufe0f",
        "DEFENSIVE": "\U0001f9ca",
        "NORMAL": "\u2618\ufe0f",
        "AGGRESSIVE": "\U0001f525",
    }
    icon = regime_icons.get(regime, "")
    agg_str = f"{agg_score}" if agg_score is not None else "N/A"
    lines.append(f"{icon} Regime: {regime} (Agg:{agg_str} Guard:{guard_label})")
    lines.append(f"目標曝險: {target_exposure * 100:.0f}%")

    if hysteresis_active:
        lines.append("(緩衝中 — 待連續確認)")

    if adj_type == "STRUCTURAL":
        lines.append("*** 結構性調整 ***")
    elif adj_type == "LIGHT":
        lines.append("輕度微調")

    # Position actions
    exit_actions = [a for a in actions if a["action"] == "EXIT"]
    reduce_actions = [a for a in actions if a["action"] == "REDUCE"]
    hold_actions = [a for a in actions if a["action"] == "HOLD"]

    if exit_actions:
        lines.append("")
        lines.append("[建議出場]")
        for a in exit_actions:
            lines.append(f"  {a['code']} {a['name']} — {a['reason']}")

    if reduce_actions:
        lines.append("")
        lines.append("[建議減碼]")
        for a in reduce_actions:
            lines.append(
                f"  {a['code']} {a['name']}: "
                f"{a['current_weight']:.0f}% → {a['target_weight']:.0f}% "
                f"— {a['reason']}"
            )

    if hold_actions and not exit_actions and not reduce_actions:
        lines.append("")
        lines.append("[維持現狀] 無需調整")

    if not actions:
        lines.append("")
        lines.append("[無持倉] 無需調整")

    return "\n".join(lines)

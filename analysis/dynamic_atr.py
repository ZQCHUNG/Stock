"""
V1.3 P2: Dynamic ATR Multiplier — CTO Approved

Automatically adjusts ATR stop-loss multipliers based on Shake-out Rate.

Physical rationale (CTO):
  "既然我們現在有了「痛覺（Drift）」與「自我覺察（Shake-out Rate）」，
   現在我們要為系統裝上「肌肉的靈活性」"

Core Logic:
  - Shake-out Rate > 30% → ATR multiplier +0.2 (widen stop, reduce whipsaw)
  - Shake-out Rate < 15% → ATR multiplier -0.1 (tighten stop, lock profits)
  - Between 15%-30% → no adjustment (neutral zone)
  - Bounds: 1.5x ~ 3.5x (absolute limits)

Dependencies:
  - P0: Rebalancing Engine (regime classification)
  - P1: Drift Monitor (portfolio drift)
  - signal_log.detect_shake_outs() (shake-out rate data)
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────

# Shake-out rate thresholds — CTO approved
SHAKEOUT_HIGH = 0.30   # [VERIFIED: CTO_V1.3_P2] > 30% → widen
SHAKEOUT_LOW = 0.15    # [VERIFIED: CTO_V1.3_P2] < 15% → tighten

# ATR adjustment amounts — CTO approved
ATR_WIDEN_STEP = 0.2   # [VERIFIED: CTO_V1.3_P2] +0.2 when too many shakeouts
ATR_TIGHTEN_STEP = 0.1 # [VERIFIED: CTO_V1.3_P2] -0.1 when few shakeouts

# ATR multiplier absolute bounds — CTO approved
ATR_FLOOR = 1.5        # [VERIFIED: CTO_V1.3_P2] never tighter than 1.5x
ATR_CEILING = 3.5      # [VERIFIED: CTO_V1.3_P2] never wider than 3.5x

# Default base multipliers (from stop_loss.py)
DEFAULT_BASE_MULTIPLIERS = {
    "squeeze_breakout": 1.5,
    "oversold_bounce": 2.0,
    "volume_ramp": 2.0,
    "momentum_breakout": 2.0,
}
DEFAULT_FALLBACK_MULT = 2.0

# Rolling window for adjustment stability
MIN_STOPPED_SIGNALS = 5  # [HYPOTHESIS: MIN_SAMPLES_P2_001] need ≥5 stopped-out for adjustment

# State persistence
STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "dynamic_atr_state.json"
MAX_HISTORY = 60  # Keep 60 days of adjustment history


# ─── Core Computation ────────────────────────────────────────

def compute_atr_adjustment(shake_out_rate: float | None) -> dict[str, Any]:
    """Compute ATR multiplier adjustment based on shake-out rate.

    Args:
        shake_out_rate: Fraction (0.0 - 1.0) of stopped-out trades that were shakeouts.
                       None means insufficient data.

    Returns:
        {
            "adjustment": float,         # -0.1, 0.0, or +0.2
            "direction": str,            # "WIDEN" / "NEUTRAL" / "TIGHTEN"
            "shake_out_rate": float|None,
            "reason": str,
        }
    """
    if shake_out_rate is None:
        return {
            "adjustment": 0.0,
            "direction": "NEUTRAL",
            "shake_out_rate": None,
            "reason": "Shake-out data unavailable",
        }

    if shake_out_rate > SHAKEOUT_HIGH:
        return {
            "adjustment": ATR_WIDEN_STEP,
            "direction": "WIDEN",
            "shake_out_rate": round(shake_out_rate, 3),
            "reason": f"Shake-out Rate {shake_out_rate:.1%} > {SHAKEOUT_HIGH:.0%} — 停損過緊，放寬 ATR +{ATR_WIDEN_STEP}",
        }
    elif shake_out_rate < SHAKEOUT_LOW:
        return {
            "adjustment": -ATR_TIGHTEN_STEP,
            "direction": "TIGHTEN",
            "shake_out_rate": round(shake_out_rate, 3),
            "reason": f"Shake-out Rate {shake_out_rate:.1%} < {SHAKEOUT_LOW:.0%} — 停損空間充裕，收緊 ATR -{ATR_TIGHTEN_STEP}",
        }
    else:
        return {
            "adjustment": 0.0,
            "direction": "NEUTRAL",
            "shake_out_rate": round(shake_out_rate, 3),
            "reason": f"Shake-out Rate {shake_out_rate:.1%} 在中性區間 ({SHAKEOUT_LOW:.0%}-{SHAKEOUT_HIGH:.0%})",
        }


def get_adjusted_multiplier(
    entry_type: str,
    shake_out_rate: float | None,
    base_multipliers: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Get the adjusted ATR multiplier for a given entry type.

    Args:
        entry_type: One of squeeze_breakout, oversold_bounce, volume_ramp, momentum_breakout
        shake_out_rate: Current shake-out rate (0.0-1.0), None if unavailable
        base_multipliers: Override base multipliers (for testing)

    Returns:
        {
            "entry_type": str,
            "base_multiplier": float,
            "adjustment": float,
            "adjusted_multiplier": float,
            "clamped": bool,         # True if hit floor/ceiling
            "floor": float,
            "ceiling": float,
        }
    """
    bases = base_multipliers or DEFAULT_BASE_MULTIPLIERS
    base = bases.get(entry_type, DEFAULT_FALLBACK_MULT)

    adj = compute_atr_adjustment(shake_out_rate)
    raw = base + adj["adjustment"]

    # Clamp to bounds
    clamped = raw < ATR_FLOOR or raw > ATR_CEILING
    adjusted = max(ATR_FLOOR, min(ATR_CEILING, raw))

    return {
        "entry_type": entry_type,
        "base_multiplier": base,
        "adjustment": adj["adjustment"],
        "adjusted_multiplier": round(adjusted, 2),
        "clamped": clamped,
        "floor": ATR_FLOOR,
        "ceiling": ATR_CEILING,
    }


def get_all_adjusted_multipliers(
    shake_out_rate: float | None,
) -> dict[str, dict]:
    """Get adjusted multipliers for all entry types.

    Returns:
        {"squeeze_breakout": {...}, "oversold_bounce": {...}, ...}
    """
    result = {}
    for entry_type in DEFAULT_BASE_MULTIPLIERS:
        result[entry_type] = get_adjusted_multiplier(entry_type, shake_out_rate)
    return result


# ─── State Persistence ───────────────────────────────────────

def _load_state() -> list[dict]:
    """Load historical adjustment snapshots."""
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.warning("Failed to load dynamic ATR state: %s", e)
    return []


def _save_snapshot(snapshot: dict) -> None:
    """Append a snapshot to the state file (capped at MAX_HISTORY)."""
    history = _load_state()
    entry = {
        "date": snapshot.get("timestamp", datetime.now().isoformat()),
        "shake_out_rate": snapshot.get("shake_out_rate"),
        "adjustment": snapshot.get("adjustment", 0.0),
        "direction": snapshot.get("direction", "NEUTRAL"),
        "total_stopped": snapshot.get("total_stopped", 0),
        "shake_out_count": snapshot.get("shake_out_count", 0),
    }
    history.append(entry)

    # Cap at MAX_HISTORY
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]

    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error("Failed to save dynamic ATR state: %s", e)


# ─── Trend Analysis ──────────────────────────────────────────

def _compute_adjustment_trend(history: list[dict]) -> str:
    """Analyze trend of ATR adjustments over time.

    Returns: WIDENING / STABLE / TIGHTENING / INSUFFICIENT_DATA
    """
    if len(history) < 5:
        return "INSUFFICIENT_DATA"

    # Split into older and recent halves
    mid = len(history) // 2
    older = history[:mid]
    recent = history[mid:]

    older_avg = statistics.mean(h.get("adjustment", 0) for h in older)
    recent_avg = statistics.mean(h.get("adjustment", 0) for h in recent)

    diff = recent_avg - older_avg
    if diff > 0.05:
        return "WIDENING"
    elif diff < -0.05:
        return "TIGHTENING"
    return "STABLE"


# ─── Report Generation ───────────────────────────────────────

def generate_dynamic_atr_report(save_snapshot: bool = True) -> dict[str, Any]:
    """Generate a full Dynamic ATR report using live shake-out data.

    This is the main entry point called by scheduler / API.

    Returns:
        {
            "timestamp": str,
            "shake_out_rate": float | None,
            "total_stopped": int,
            "shake_out_count": int,
            "rate_warning": bool,
            "adjustment": float,
            "direction": str,
            "reason": str,
            "multipliers": {entry_type: adjusted_mult, ...},
            "trend": str,
            "summary_message": str,
        }
    """
    from analysis.signal_log import detect_shake_outs

    timestamp = datetime.now().isoformat()

    # Get shake-out data
    try:
        so_data = detect_shake_outs()
    except Exception as e:
        logger.error("Failed to detect shake-outs: %s", e)
        so_data = {
            "total_stopped_out": 0,
            "shake_out_count": 0,
            "shake_out_rate": None,
            "rate_warning": False,
            "details": [],
        }

    total_stopped = so_data.get("total_stopped_out", 0)
    shake_out_count = so_data.get("shake_out_count", 0)
    rate = so_data.get("shake_out_rate")

    # Check minimum samples
    if total_stopped < MIN_STOPPED_SIGNALS:
        rate = None  # Insufficient data for reliable adjustment

    # Compute adjustment
    adj = compute_atr_adjustment(rate)

    # Get all adjusted multipliers
    multipliers = {}
    for entry_type, info in get_all_adjusted_multipliers(rate).items():
        multipliers[entry_type] = info["adjusted_multiplier"]

    # Load history and compute trend
    history = _load_state()
    trend = _compute_adjustment_trend(history)

    # Save snapshot
    if save_snapshot:
        _save_snapshot({
            "timestamp": timestamp,
            "shake_out_rate": rate,
            "adjustment": adj["adjustment"],
            "direction": adj["direction"],
            "total_stopped": total_stopped,
            "shake_out_count": shake_out_count,
        })

    # Build summary message
    summary = _format_summary(adj, rate, total_stopped, shake_out_count, trend)

    return {
        "timestamp": timestamp,
        "shake_out_rate": rate,
        "total_stopped": total_stopped,
        "shake_out_count": shake_out_count,
        "rate_warning": so_data.get("rate_warning", False),
        "adjustment": adj["adjustment"],
        "direction": adj["direction"],
        "reason": adj["reason"],
        "multipliers": multipliers,
        "trend": trend,
        "summary_message": summary,
    }


def _format_summary(
    adj: dict, rate: float | None,
    total: int, shakeouts: int, trend: str,
) -> str:
    """Format human-readable summary for Morning Brief / LINE."""
    if rate is None:
        return f"📊 Dynamic ATR: 數據不足（已停損 {total} 筆，需 ≥{MIN_STOPPED_SIGNALS} 筆）— ATR 倍數維持不變"

    parts = []

    # Header
    direction_icon = {"WIDEN": "🔓", "TIGHTEN": "🔒", "NEUTRAL": "⚖️"}.get(adj["direction"], "📊")
    parts.append(f"{direction_icon} Dynamic ATR [{adj['direction']}]")

    # Shake-out stats
    parts.append(f"  洗盤率: {rate:.1%} ({shakeouts}/{total})")

    # Adjustment
    if adj["adjustment"] != 0:
        sign = "+" if adj["adjustment"] > 0 else ""
        parts.append(f"  ATR 調整: {sign}{adj['adjustment']:.1f}")
    else:
        parts.append("  ATR 調整: 無（中性區間）")

    # Trend
    trend_labels = {
        "WIDENING": "⬆️ 停損持續放寬中",
        "TIGHTENING": "⬇️ 停損持續收緊中",
        "STABLE": "➡️ 穩定",
        "INSUFFICIENT_DATA": "📊 歷史不足",
    }
    parts.append(f"  趨勢: {trend_labels.get(trend, trend)}")

    return "\n".join(parts)


# ─── Morning Brief Helper ────────────────────────────────────

def get_atr_alert_for_brief() -> str | None:
    """Return ATR adjustment message for Morning Brief (if non-neutral).

    Returns None when no adjustment needed (NEUTRAL), to keep brief clean.
    """
    try:
        report = generate_dynamic_atr_report(save_snapshot=False)
        if report["direction"] != "NEUTRAL" or report["rate_warning"]:
            return report["summary_message"]
        return None
    except Exception as e:
        logger.warning("Dynamic ATR brief failed: %s", e)
        return None

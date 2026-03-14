"""Drift Detector — Weekly performance audit for Auto-Sim signals.

P3: CTO Gemini directive — "讓 AI 對自己發出的信號負責"

Weekly audit (Saturday 09:00):
  1. Compute In-Bounds Rate: % of realized signals where actual_return_d21
     fell within [ci_lower, ci_upper]
  2. Z-Score failure: 3 consecutive signals where actual < worst_case
  3. Post-mortem: When In-Bounds Rate < 60%, analyze failure patterns
  4. Risk circuit breaker: global_risk_on flag

[HYPOTHESIS: IN_BOUNDS_THRESHOLD = 0.60, Z_SCORE_CONSECUTIVE = 3]
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Configurable thresholds
IN_BOUNDS_THRESHOLD = 0.60    # [HYPOTHESIS] Minimum acceptable In-Bounds Rate
Z_SCORE_CONSECUTIVE = 3       # [HYPOTHESIS] Consecutive worst-case breaches → alarm
RISK_FLAG_PATH = Path(__file__).resolve().parent.parent / "data" / "global_risk_flag.json"
DRIFT_REPORT_PATH = Path(__file__).resolve().parent.parent / "data" / "drift_report.json"


def compute_in_bounds_rate(days_back: int = 90) -> dict:
    """Compute In-Bounds Rate for realized signals.

    In-Bounds = actual_return_d21 fell within [ci_lower, ci_upper].

    Returns:
        {
            "total_realized": int,
            "in_bounds_count": int,
            "in_bounds_rate": float,
            "above_ci": int,   # actual > ci_upper (better than expected)
            "below_ci": int,   # actual < ci_lower (worse than expected)
            "healthy": bool,   # rate >= IN_BOUNDS_THRESHOLD
        }
    """
    from analysis.signal_log import get_realized_signals

    realized = get_realized_signals(days_back=days_back)
    if not realized:
        return {
            "total_realized": 0,
            "in_bounds_count": 0,
            "in_bounds_rate": None,
            "above_ci": 0,
            "below_ci": 0,
            "healthy": True,
        }

    in_bounds = 0
    above = 0
    below = 0

    for sig in realized:
        ib = sig.get("in_bounds_d21")
        if ib is not None:
            if ib == 1:
                in_bounds += 1
            else:
                # Determine direction of miss
                actual = sig.get("actual_return_d21")
                ci_upper = sig.get("ci_upper")
                ci_lower = sig.get("ci_lower")
                if actual is not None and ci_upper is not None and actual > ci_upper:
                    above += 1
                else:
                    below += 1

    total = len(realized)
    rate = in_bounds / total if total > 0 else None

    return {
        "total_realized": total,
        "in_bounds_count": in_bounds,
        "in_bounds_rate": round(rate, 4) if rate is not None else None,
        "above_ci": above,
        "below_ci": below,
        "healthy": rate is None or rate >= IN_BOUNDS_THRESHOLD,
    }


def detect_z_score_failure(days_back: int = 90) -> dict:
    """Detect consecutive worst-case breaches (Z-Score failure).

    If Z_SCORE_CONSECUTIVE consecutive signals have actual_return_d21 <
    worst_case_pct, trigger model failure warning.

    Returns:
        {
            "consecutive_breaches": int,
            "max_consecutive": int,
            "breach_signals": list,   # codes of breached signals
            "alarm": bool,
        }
    """
    from analysis.signal_log import get_realized_signals

    realized = get_realized_signals(days_back=days_back)
    if not realized:
        return {
            "consecutive_breaches": 0,
            "max_consecutive": 0,
            "breach_signals": [],
            "alarm": False,
        }

    # Sort by signal_date ascending for consecutive detection
    realized.sort(key=lambda x: x.get("signal_date", ""))

    consecutive = 0
    max_consecutive = 0
    current_breach_signals = []
    all_breach_signals = []

    for sig in realized:
        actual = sig.get("actual_return_d21")
        worst = sig.get("worst_case_pct")

        if actual is None or worst is None:
            # Reset streak on missing data
            consecutive = 0
            current_breach_signals = []
            continue

        # worst_case_pct is stored as percentage (e.g. -15.0 means -15%)
        # actual_return_d21 is stored as decimal (e.g. -0.15 means -15%)
        worst_decimal = worst / 100.0

        if actual < worst_decimal:
            consecutive += 1
            current_breach_signals.append({
                "stock_code": sig.get("stock_code"),
                "signal_date": sig.get("signal_date"),
                "actual": round(actual * 100, 2),
                "worst_case": round(worst, 2),
            })
            all_breach_signals.append(current_breach_signals[-1])
        else:
            consecutive = 0
            current_breach_signals = []

        max_consecutive = max(max_consecutive, consecutive)

    return {
        "consecutive_breaches": consecutive,
        "max_consecutive": max_consecutive,
        "breach_signals": all_breach_signals[-10:],  # Last 10
        "alarm": max_consecutive >= Z_SCORE_CONSECUTIVE,
    }


def run_post_mortem(days_back: int = 90) -> dict:
    """Post-mortem analysis when In-Bounds Rate < 60%.

    Analyzes failure patterns:
    - Which tiers (sniper/tactical) fail more?
    - Which industries have worst accuracy?
    - Direction bias (over-optimistic vs over-pessimistic?)

    Returns:
        {
            "needed": bool,
            "in_bounds_rate": float,
            "tier_accuracy": {tier: {total, in_bounds, rate}},
            "industry_accuracy": {industry: {total, in_bounds, rate}},
            "direction_bias": "over_optimistic" | "over_pessimistic" | "balanced",
            "recommendations": list[str],
        }
    """
    from analysis.signal_log import get_realized_signals

    bounds = compute_in_bounds_rate(days_back)
    if bounds["healthy"] or bounds["total_realized"] == 0:
        return {"needed": False, "in_bounds_rate": bounds["in_bounds_rate"]}

    realized = get_realized_signals(days_back=days_back)

    # Tier accuracy
    tier_stats: dict[str, dict] = {}
    for sig in realized:
        tier = sig.get("sniper_tier", "unknown") or "unknown"
        if tier not in tier_stats:
            tier_stats[tier] = {"total": 0, "in_bounds": 0}
        tier_stats[tier]["total"] += 1
        if sig.get("in_bounds_d21") == 1:
            tier_stats[tier]["in_bounds"] += 1

    for t in tier_stats.values():
        t["rate"] = round(t["in_bounds"] / t["total"], 4) if t["total"] > 0 else 0

    # Industry accuracy
    industry_stats: dict[str, dict] = {}
    for sig in realized:
        ind = sig.get("industry", "unknown") or "unknown"
        if ind not in industry_stats:
            industry_stats[ind] = {"total": 0, "in_bounds": 0}
        industry_stats[ind]["total"] += 1
        if sig.get("in_bounds_d21") == 1:
            industry_stats[ind]["in_bounds"] += 1

    for i in industry_stats.values():
        i["rate"] = round(i["in_bounds"] / i["total"], 4) if i["total"] > 0 else 0

    # Direction bias
    above = bounds["above_ci"]
    below = bounds["below_ci"]
    total_miss = above + below
    if total_miss > 0:
        if below / total_miss > 0.65:
            direction = "over_optimistic"
        elif above / total_miss > 0.65:
            direction = "over_pessimistic"
        else:
            direction = "balanced"
    else:
        direction = "balanced"

    # Recommendations
    recs = []
    if direction == "over_optimistic":
        recs.append("模型預期過度樂觀 — 考慮加大 worst_case 權重")
    if direction == "over_pessimistic":
        recs.append("模型預期過度悲觀 — CI 區間可能過寬")

    # Find worst-performing tier
    worst_tier = min(tier_stats.items(), key=lambda x: x[1]["rate"], default=None)
    if worst_tier and worst_tier[1]["rate"] < 0.50:
        recs.append(f"Tier '{worst_tier[0]}' 準確率僅 {worst_tier[1]['rate']:.0%} — 考慮降級該類信號")

    # Find worst-performing industry
    worst_ind = min(
        [(k, v) for k, v in industry_stats.items() if v["total"] >= 3],
        key=lambda x: x[1]["rate"],
        default=None,
    )
    if worst_ind and worst_ind[1]["rate"] < 0.40:
        recs.append(f"產業 '{worst_ind[0]}' 準確率僅 {worst_ind[1]['rate']:.0%} — 考慮暫時排除")

    return {
        "needed": True,
        "in_bounds_rate": bounds["in_bounds_rate"],
        "tier_accuracy": tier_stats,
        "industry_accuracy": industry_stats,
        "direction_bias": direction,
        "above_ci": above,
        "below_ci": below,
        "recommendations": recs,
    }


def get_risk_flag() -> dict:
    """Read global risk flag status.

    Returns:
        {"global_risk_on": bool, "reason": str, "updated_at": str}
    """
    if RISK_FLAG_PATH.exists():
        try:
            return json.loads(RISK_FLAG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to load risk flag: {e}")
    return {"global_risk_on": True, "reason": "default", "updated_at": ""}


def set_risk_flag(risk_on: bool, reason: str = "") -> dict:
    """Set global risk flag.

    When risk_on=False, Auto-Sim should replace recommendations with
    "⚠️ 系統維護中：模型信心不足，建議觀望"

    Args:
        risk_on: True = signals enabled, False = signals suppressed
        reason: Human-readable reason for the change
    """
    flag = {
        "global_risk_on": risk_on,
        "reason": reason,
        "updated_at": datetime.now().isoformat(),
    }
    RISK_FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RISK_FLAG_PATH.write_text(
        json.dumps(flag, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Risk flag set: risk_on=%s reason=%s", risk_on, reason)
    return flag


def run_weekly_audit() -> dict:
    """Run the full weekly audit.

    Called by scheduler every Saturday 09:00.

    Steps:
      1. Realize active signals (backfill actual returns)
      2. Compute In-Bounds Rate
      3. Detect Z-Score failures
      4. Run post-mortem if needed
      5. Update risk flag if consecutive weeks of high drift
      6. Generate LINE notification summary

    Returns:
        Full audit report dict.
    """
    logger.info("Weekly audit starting...")

    # Step 1: Realize active signals
    from analysis.signal_log import realize_signals
    realization = realize_signals()

    # Step 2: In-Bounds Rate
    bounds = compute_in_bounds_rate(days_back=90)

    # Step 3: Z-Score failure
    z_score = detect_z_score_failure(days_back=90)

    # Step 4: Post-mortem (if needed)
    post_mortem = run_post_mortem(days_back=90)

    # Step 5: Risk flag management
    risk_flag = get_risk_flag()
    flag_changed = False

    if z_score["alarm"]:
        # Z-Score failure → immediate risk-off
        if risk_flag["global_risk_on"]:
            set_risk_flag(False, f"Z-Score failure: {z_score['max_consecutive']} consecutive worst-case breaches")
            flag_changed = True
    elif not bounds["healthy"] and bounds["in_bounds_rate"] is not None:
        # Low In-Bounds Rate → check if this is second consecutive week
        prev_report = _load_previous_report()
        if prev_report and not prev_report.get("in_bounds", {}).get("healthy", True):
            # Two consecutive weeks of poor accuracy → risk-off
            if risk_flag["global_risk_on"]:
                set_risk_flag(False, f"Consecutive low In-Bounds Rate: {bounds['in_bounds_rate']:.0%}")
                flag_changed = True
    else:
        # All healthy → re-enable if was disabled
        if not risk_flag["global_risk_on"]:
            set_risk_flag(True, "Weekly audit: metrics returned to healthy levels")
            flag_changed = True

    # Build report
    report = {
        "audit_date": datetime.now().strftime("%Y-%m-%d"),
        "realization": realization,
        "in_bounds": bounds,
        "z_score": z_score,
        "post_mortem": post_mortem,
        "risk_flag": get_risk_flag(),
        "risk_flag_changed": flag_changed,
    }

    # Save report
    _save_report(report)

    # Step 6: Generate LINE message
    report["line_message"] = _format_audit_message(report)

    logger.info("Weekly audit complete: In-Bounds=%s, Z-Score alarm=%s, Risk=%s",
                bounds.get("in_bounds_rate"), z_score["alarm"],
                "ON" if get_risk_flag()["global_risk_on"] else "OFF")

    return report


def send_weekly_audit_notification(report: dict) -> bool:
    """Send weekly audit results via LINE Notify."""
    message = report.get("line_message", "")
    if not message:
        return False

    try:
        from backend.scheduler import _send_notification
        _send_notification(message)
        logger.info("Weekly audit notification sent")
        return True
    except Exception as e:
        logger.warning("Weekly audit notification failed: %s", e)
        return False


def _format_audit_message(report: dict) -> str:
    """Format weekly audit LINE Notify message."""
    now = datetime.now().strftime("%Y-%m-%d")
    bounds = report.get("in_bounds", {})
    z_score = report.get("z_score", {})
    realization = report.get("realization", {})
    risk = report.get("risk_flag", {})

    lines = [f"\n📋 Weekly Signal Audit ({now})"]

    # Realization summary
    lines.append(f"更新: {realization.get('updated', 0)} 筆, "
                 f"已實現: {realization.get('realized', 0)} 筆")

    # In-Bounds Rate
    rate = bounds.get("in_bounds_rate")
    if rate is not None:
        emoji = "✅" if bounds["healthy"] else "⚠️"
        lines.append(f"{emoji} In-Bounds Rate: {rate:.0%} "
                     f"({bounds['in_bounds_count']}/{bounds['total_realized']})")
        if bounds["above_ci"] or bounds["below_ci"]:
            lines.append(f"  偏高: {bounds['above_ci']} | 偏低: {bounds['below_ci']}")
    else:
        lines.append("📊 尚無已實現信號可供比對")

    # Z-Score
    if z_score["alarm"]:
        lines.append(f"🚨 Z-Score ALARM: {z_score['max_consecutive']} 連續突破最壞情境")
    elif z_score["max_consecutive"] > 0:
        lines.append(f"⚡ Z-Score: 最大連續突破 {z_score['max_consecutive']} 次")

    # Risk flag
    risk_on = risk.get("global_risk_on", True)
    if not risk_on:
        lines.append(f"🔴 風險熔斷: 信號推薦已暫停")
        lines.append(f"  原因: {risk.get('reason', 'N/A')}")
    else:
        lines.append("🟢 風險狀態: 正常")

    # Post-mortem highlights
    pm = report.get("post_mortem", {})
    if pm.get("needed"):
        lines.append("")
        lines.append("📝 死因分析:")
        lines.append(f"  方向偏差: {pm.get('direction_bias', 'N/A')}")
        for rec in pm.get("recommendations", [])[:3]:
            lines.append(f"  💡 {rec}")

    return "\n".join(lines)


def _save_report(report: dict) -> None:
    """Save drift report to disk (for next-week comparison)."""
    DRIFT_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DRIFT_REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _load_previous_report() -> Optional[dict]:
    """Load last week's drift report for consecutive-week detection."""
    if DRIFT_REPORT_PATH.exists():
        try:
            return json.loads(DRIFT_REPORT_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug(f"Failed to load previous drift report: {e}")
    return None

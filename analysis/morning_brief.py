"""Morning Briefing Generator — V1.2 P1

CTO/Architect OFFICIALLY APPROVED (3 rounds of review).
3-Section template, zero AI dependency, 100% deterministic.

Sections:
  1. Market Temperature — Aggressive Index + TAIEX + Market Guard
  2. Today's Focus — Top 5 by Priority Score (RS×0.3 + SQS×0.25 + AQS×0.2 + PA×0.15 + Liq×0.1)
  3. Risk Alerts — LOCKDOWN / stop-near / concentration warnings

[HYPOTHESIS: BRIEF_URGENCY_SORT] — Aggressive Index < 40 → Section 3 moves to top.
[HYPOTHESIS: PRIORITY_WEIGHTS_V1] — RS 30%, SQS 25%, AQS 20%, PA 15%, Liq 10%.
"""

import logging
from datetime import datetime
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CALENDAR_PATH = DATA_DIR / "market_calendar.yaml"

# Priority Score weights [HYPOTHESIS: PRIORITY_WEIGHTS_V1]
W_RS = 0.30
W_SQS = 0.25
W_AQS = 0.20
W_PA = 0.15
W_LIQ = 0.10

# AQS phase → normalized score (0-100)
AQS_PHASE_SCORE = {"BETA": 100, "ALPHA": 60, "GAMMA_READY": 80, "NONE": 0}

# Stop proximity threshold (price / stop < 1.05 → near stop)
STOP_PROXIMITY_THRESHOLD = 1.05

# Max focus stocks in Section 2
MAX_FOCUS = 5


def is_market_open(date: datetime | None = None) -> bool:
    """Check if the given date is a trading day.

    Rules:
    1. Skip weekends (Sat=5, Sun=6)
    2. Skip holidays from market_calendar.yaml
    """
    if date is None:
        date = datetime.now()

    # Weekend check
    if date.weekday() >= 5:
        return False

    # Holiday check
    date_str = date.strftime("%Y-%m-%d")
    try:
        if CALENDAR_PATH.exists():
            with open(CALENDAR_PATH, "r", encoding="utf-8") as f:
                cal = yaml.safe_load(f)
            holidays = cal.get(f"holidays_{date.year}", [])
            if date_str in holidays:
                return False
    except Exception as e:
        logger.warning("Failed to load market calendar: %s", e)

    return True


def _get_aggressive_index() -> tuple[int | None, str, str]:
    """Compute Aggressive Index inline (same logic as daily_review).

    Returns: (score, level_label, icon)
    """
    try:
        from analysis.market_regime import get_regime_context

        ctx = get_regime_context()
        market_score = min(30, max(0, int(ctx.get("score", 50) * 0.3)))

        from analysis.sector_rs import get_sector_rs_overview

        sector_data = get_sector_rs_overview()
        top3 = sector_data.get("top3_sectors", []) if sector_data else []
        sector_score = min(25, len(top3) * 8)

        from analysis.drift_detector import get_drift_report

        drift = get_drift_report()
        ib_rate = drift.get("in_bounds", {}).get("in_bounds_rate")
        ib_score = min(25, int((ib_rate or 0.5) * 25))

        from analysis.signal_log import get_all_signals

        recent = get_all_signals(limit=20)
        high_conf = sum(1 for s in recent if s.get("confidence_grade") == "HIGH")
        sig_score = min(20, high_conf * 5)

        score = market_score + sector_score + ib_score + sig_score
        if score >= 70:
            return score, "Aggressive", "\U0001f525"
        elif score < 40:
            return score, "Defensive", "\U0001f9ca"
        else:
            return score, "Normal", "\u2618\ufe0f"
    except Exception as e:
        logger.warning("Aggressive Index failed: %s", e)
        return None, "Unknown", "\u2753"


def _get_market_guard() -> dict:
    """Get Market Guard status."""
    try:
        from analysis.market_guard import get_market_exposure_limit
        import yfinance as yf
        import pandas as pd

        taiex = yf.download("^TWII", period="250d", progress=False, auto_adjust=True)
        if taiex is not None and len(taiex) > 0:
            status = get_market_exposure_limit(taiex)
            last_close = float(taiex["Close"].iloc[-1]) if "Close" in taiex.columns else float(taiex["close"].iloc[-1])
            prev_close = float(taiex["Close"].iloc[-2]) if len(taiex) > 1 and "Close" in taiex.columns else float(taiex["close"].iloc[-2]) if len(taiex) > 1 else last_close
            pct_change = (last_close / prev_close - 1) * 100 if prev_close else 0

            # MA20 direction
            close_col = taiex["Close"] if "Close" in taiex.columns else taiex["close"]
            ma20 = float(close_col.rolling(20).mean().iloc[-1])
            ma20_dir = "\u2191" if last_close > ma20 else "\u2193"

            return {
                "level": status.get("level", 0) if isinstance(status, dict) else getattr(status, "level", 0),
                "label": status.get("level_label", "NORMAL") if isinstance(status, dict) else getattr(status, "level_label", "NORMAL"),
                "taiex": last_close,
                "taiex_pct": round(pct_change, 1),
                "ma20_dir": ma20_dir,
            }
    except Exception as e:
        logger.warning("Market Guard failed: %s", e)
    return {"level": 0, "label": "NORMAL", "taiex": None, "taiex_pct": 0, "ma20_dir": "?"}


def _get_active_signals_enriched() -> list[dict]:
    """Get active signals with enriched metadata for priority scoring."""
    try:
        from analysis.signal_log import get_active_signals

        signals = get_active_signals(days_back=60)
        enriched = []
        for sig in signals:
            code = sig.get("stock_code", "")
            item = {
                "code": code,
                "name": sig.get("stock_name", code),
                "entry_price": sig.get("entry_price"),
                "current_stop": sig.get("current_stop_price"),
                "trailing_phase": sig.get("trailing_phase", 0),
                "is_live": bool(sig.get("is_live", 0)),
                "signal_date": sig.get("signal_date", ""),
                "rs_rating": sig.get("rs_rating"),
                "sim_score": sig.get("sim_score"),
                "confidence_grade": sig.get("confidence_grade"),
                "scale_out_triggered": bool(sig.get("scale_out_triggered", 0)),
            }
            enriched.append(item)
        return enriched
    except Exception as e:
        logger.warning("Active signals failed: %s", e)
        return []


def _compute_priority_score(sig: dict) -> float:
    """Compute Priority Score for a signal.

    All dimensions normalized to 0-100 before weighting.
    [HYPOTHESIS: PRIORITY_WEIGHTS_V1]
    """
    # RS: already 0-100 percentile
    rs = sig.get("rs_rating")
    rs = 50.0 if rs is None else min(100, max(0, rs))

    # SQS: sim_score is roughly 0-100
    sqs = sig.get("sim_score")
    sqs = 50 if sqs is None else min(100, max(0, sqs))

    # AQS: phase-based score
    aqs_phase = sig.get("aqs_phase", "NONE")
    aqs = AQS_PHASE_SCORE.get(aqs_phase, 0)

    # Peer Alpha: typically 0.5-3.0, normalize to 0-100
    pa_raw = sig.get("peer_alpha")
    pa_raw = 1.0 if pa_raw is None else pa_raw
    pa = min(100, max(0, (pa_raw - 0.5) * 40))  # 0.5→0, 1.0→20, 2.0→60, 3.0→100

    # Liquidity: typically 0-100
    liq = sig.get("liquidity_score")
    liq = 50 if liq is None else min(100, max(0, liq))

    return rs * W_RS + sqs * W_SQS + aqs * W_AQS + pa * W_PA + liq * W_LIQ


def _get_action_tag(sig: dict, today_str: str) -> str:
    """Generate action tag for a signal (CTO directive: action-oriented labels)."""
    if sig.get("is_live"):
        phase = sig.get("trailing_phase", 0)
        if phase >= 2:
            return "\U0001f4cd (ATR\u8ffd\u8e64\u4e2d)"
        return "\U0001f4cd (\u6301\u5009\u4e2d/\u8ffd\u8e64\u6b62\u640d)"

    if sig.get("signal_date") == today_str:
        return "\U0001f195 (\u65b0\u4fe1\u865f/\u89c0\u5bdf)"

    aqs_phase = sig.get("aqs_phase", "NONE")
    if aqs_phase in ("BETA", "GAMMA_READY"):
        return "\u26a1 (\u5efa\u8b70\u8a66\u55ae)"

    return "\U0001f50d (\u8ffd\u8e64\u4e2d)"


def _is_stop_near(sig: dict) -> bool:
    """Check if current price is approaching stop loss."""
    entry = sig.get("entry_price")
    stop = sig.get("current_stop")
    if not entry or not stop or stop <= 0:
        return False
    return entry / stop < STOP_PROXIMITY_THRESHOLD


def _get_risk_alerts(signals: list[dict], guard: dict, agg_score: int | None) -> list[str]:
    """Generate risk alert messages."""
    alerts = []

    # Market Guard LOCKDOWN
    if guard.get("level", 0) >= 2:
        alerts.append("\u26a0\ufe0f \u5168\u5c40\u98a8\u63a7: LOCKDOWN \u2014 \u7981\u6b62\u65b0\u9032\u5834")
    elif guard.get("level", 0) >= 1:
        alerts.append("\u26a0\ufe0f \u5168\u5c40\u98a8\u63a7: CAUTION \u2014 \u66dd\u96aa\u4e0a\u96501/2")

    # Stop proximity warnings
    for sig in signals:
        if sig.get("is_live") and _is_stop_near(sig):
            alerts.append(
                f"\u26a0\ufe0f {sig['code']} {sig['name']} "
                f"\u6b62\u640d\u903c\u8fd1 (${sig.get('current_stop', '?')})"
            )

    # Sector concentration (check from portfolio heat if available)
    try:
        from analysis.portfolio_heat import compute_portfolio_heat

        live_signals = [s for s in signals if s.get("is_live")]
        if len(live_signals) >= 2:
            codes = [s["code"] for s in live_signals]
            heat = compute_portfolio_heat(codes)
            if isinstance(heat, dict):
                concentration = heat.get("max_sector_pct", 0)
                if concentration > 50:
                    sector_name = heat.get("max_sector_name", "?")
                    alerts.append(
                        f"\u26a0\ufe0f {sector_name}\u96c6\u4e2d\u5ea6 {concentration:.0f}% "
                        f"(\u5efa\u8b70 <50%)"
                    )
    except Exception:
        pass

    # Backtest drift alert (V1.3 P1)
    try:
        from analysis.drift_monitor import get_drift_alert_for_brief

        drift_alert = get_drift_alert_for_brief()
        if drift_alert:
            alerts.append(drift_alert)
    except Exception:
        pass

    # Dynamic ATR alert (V1.3 P2)
    try:
        from analysis.dynamic_atr import get_atr_alert_for_brief

        atr_alert = get_atr_alert_for_brief()
        if atr_alert:
            alerts.append(atr_alert)
    except Exception:
        pass

    return alerts


def _get_rebalance_summary(
    agg_score: int | None, guard: dict, focus_sigs: list[dict]
) -> dict | None:
    """Get rebalancing suggestions (V1.3 P0 integration)."""
    try:
        from analysis.rebalancer import generate_rebalance_report

        live_positions = [s for s in focus_sigs if s.get("is_live")]
        return generate_rebalance_report(
            agg_score=agg_score,
            guard_level=guard.get("level", 0),
            guard_label=guard.get("label", "NORMAL"),
            positions=live_positions,
        )
    except Exception as e:
        logger.warning("Rebalancer failed: %s", e)
        return None


def generate_morning_brief(send_notification: bool = True) -> dict:
    """Generate the morning briefing.

    Returns dict with raw data + formatted LINE message.
    Optionally sends via LINE Notify / Telegram.
    """
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    weekday_names = ["\u4e00", "\u4e8c", "\u4e09", "\u56db", "\u4e94", "\u516d", "\u65e5"]
    weekday = weekday_names[now.weekday()]

    # --- Gather data ---
    agg_score, agg_level, agg_icon = _get_aggressive_index()
    guard = _get_market_guard()
    signals = _get_active_signals_enriched()

    # Enrich signals with sector/AQS data (best-effort)
    for sig in signals:
        try:
            from analysis.sector_rs import get_sector_context

            ctx = get_sector_context(sig["code"])
            if ctx:
                pa_data = ctx.get("peer_alpha", {})
                sig["peer_alpha"] = pa_data.get("peer_alpha", 1.0)
                sig["sector"] = ctx.get("sector_l1", "")
        except Exception:
            sig["peer_alpha"] = 1.0

    # Compute Priority Scores and sort
    for sig in signals:
        sig["priority_score"] = _compute_priority_score(sig)

    signals.sort(key=lambda s: s.get("priority_score", 0), reverse=True)

    # Separate: live positions (always shown) + top N by priority
    live_sigs = [s for s in signals if s.get("is_live")]
    non_live = [s for s in signals if not s.get("is_live")]
    focus_sigs = live_sigs.copy()
    for s in non_live:
        if len(focus_sigs) >= MAX_FOCUS:
            break
        if s["code"] not in {f["code"] for f in focus_sigs}:
            focus_sigs.append(s)

    # Risk alerts
    alerts = _get_risk_alerts(signals, guard, agg_score)

    # --- Format LINE message ---
    lines = []

    # [HYPOTHESIS: BRIEF_URGENCY_SORT] — Risk first when defensive
    urgency_mode = agg_score is not None and agg_score < 40

    if urgency_mode and alerts:
        lines.append("=== \U0001f6a8 \u7dca\u6025\u8b66\u5831 ===")
        for a in alerts:
            lines.append(a)
        lines.append("")

    # Section 1: Market Temperature
    lines.append(f"=== Joe's Morning Brief ===")
    lines.append(f"\U0001f4c5 {today_str} ({weekday}) 08:30")
    lines.append("")
    lines.append("[\u5e02\u5834\u9ad4\u6eab]")

    if agg_score is not None:
        lines.append(f"- Aggressive Index: {agg_score} {agg_icon} {agg_level}")
    else:
        lines.append("- Aggressive Index: N/A")

    if guard.get("taiex"):
        sign = "+" if guard["taiex_pct"] >= 0 else ""
        lines.append(
            f"- TAIEX: {guard['taiex']:,.0f} ({sign}{guard['taiex_pct']}%) "
            f"MA20{guard['ma20_dir']}"
        )

    guard_label = guard.get("label", "NORMAL")
    guard_icon = "\u2705" if guard.get("level", 0) == 0 else "\u26a0\ufe0f" if guard.get("level", 0) == 1 else "\U0001f6d1"
    lines.append(f"- \u5168\u5c40\u98a8\u63a7: {guard_label} {guard_icon}")
    lines.append("")

    # Section 2: Today's Focus
    lines.append(f"[\u4eca\u65e5\u7126\u9ede] ({len(focus_sigs)}\u6a94)")
    if focus_sigs:
        for i, sig in enumerate(focus_sigs, 1):
            tag = _get_action_tag(sig, today_str)
            rs_str = f"RS:{sig.get('rs_rating', 0):.0f}" if sig.get("rs_rating") else ""
            code_name = f"{sig['code']} {sig['name']}"
            parts = [code_name, rs_str]
            if sig.get("current_stop"):
                parts.append(f"\u6b62\u640d${sig['current_stop']:.1f}")
            parts.append(tag)
            lines.append(f"{i}. {' '.join(p for p in parts if p)}")
    else:
        lines.append("(\u7121\u6d3b\u8e8d\u4fe1\u865f)")
    lines.append("")

    # Section 3: Risk Alerts (if not already shown in urgency mode)
    if not urgency_mode and alerts:
        lines.append("[\u98a8\u96aa\u8b66\u5831]")
        for a in alerts:
            lines.append(a)
    elif not alerts:
        lines.append("[\u98a8\u96aa\u8b66\u5831] \u7121 \u2705")

    # Section 4: Rebalancing Suggestions (V1.3 P0)
    rebalance = _get_rebalance_summary(agg_score, guard, focus_sigs)
    if rebalance:
        lines.append("")
        lines.append(rebalance["summary_message"])

    message = "\n".join(lines)

    # --- Send notification ---
    if send_notification:
        try:
            from backend.scheduler import _send_notification

            _send_notification(message)
            logger.info("Morning brief sent via notification channels")
        except Exception as e:
            logger.warning("Morning brief notification failed: %s", e)

    return {
        "timestamp": now.isoformat(),
        "is_market_open": is_market_open(now),
        "aggressive_index": {"score": agg_score, "level": agg_level, "icon": agg_icon},
        "market_guard": guard,
        "focus_stocks": focus_sigs,
        "risk_alerts": alerts,
        "urgency_mode": urgency_mode,
        "rebalance": rebalance,
        "message": message,
    }

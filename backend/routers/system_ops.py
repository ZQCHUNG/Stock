"""Operational monitoring routes — OMS, signal log, drift, war room, stress test, etc.

Split from system.py — oms-*, signal-log, auto-sim, risk-flag, weekly-audit,
failure-analysis, war-room, stress-test, aggressive-index, pipeline-monitor,
daily-summary, morning-brief, rebalance, drift-monitor, dynamic-atr,
and various Phase endpoint groups.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# OMS (Order Management System)
# ---------------------------------------------------------------------------


@router.get("/oms-events")
def oms_events(limit: int = 50):
    """R50-2: OMS order event log

    Get recent OMS auto-exit and trailing stop update events.
    """
    from backend.order_manager import get_order_events
    return {"events": get_order_events(limit=limit)}


@router.get("/oms-stats")
def oms_stats():
    """R50-2: OMS execution statistics

    Stats on auto-exit count, reason distribution, cumulative P&L.
    """
    from backend.order_manager import get_oms_stats
    return get_oms_stats()


@router.post("/oms-run")
def oms_run_now():
    """R50-2: Manually trigger OMS check

    Immediately check all positions for stop-loss/take-profit/trailing stop conditions.
    """
    from backend.order_manager import check_positions_and_execute
    return check_positions_and_execute()


@router.get("/oms-efficiency")
def oms_efficiency():
    """R51-2: OMS efficiency analysis

    Analyze stop-loss/take-profit/trailing stop effectiveness: win rate, avg P&L, coverage.
    """
    from backend.order_manager import get_oms_efficiency
    return get_oms_efficiency()


@router.get("/performance-attribution")
def performance_attribution():
    """R51-2: Trade performance attribution

    Analyze closed trades by exit type, holding period, market regime.
    """
    from backend import db
    from backend.dependencies import make_serializable

    closed = db.get_closed_positions(limit=500)
    if not closed:
        return make_serializable({"has_data": False})

    # Group by exit reason
    by_reason: dict[str, list] = {}
    for c in closed:
        reason = c.get("exit_reason") or "manual"
        by_reason.setdefault(reason, []).append(c)

    reason_stats = {}
    for reason, trades in by_reason.items():
        pnls = [(t.get("net_pnl") or 0) for t in trades]
        wins = sum(1 for p in pnls if p > 0)
        reason_stats[reason] = {
            "count": len(trades),
            "win_rate": round(wins / len(trades), 3),
            "total_pnl": round(sum(pnls), 0),
            "avg_pnl": round(sum(pnls) / len(pnls), 0),
        }

    # Group by holding period buckets
    period_buckets = {"1-5d": [], "6-10d": [], "11-20d": [], "21d+": []}
    for c in closed:
        days = c.get("days_held") or 0
        if days <= 5:
            period_buckets["1-5d"].append(c)
        elif days <= 10:
            period_buckets["6-10d"].append(c)
        elif days <= 20:
            period_buckets["11-20d"].append(c)
        else:
            period_buckets["21d+"].append(c)

    period_stats = {}
    for bucket, trades in period_buckets.items():
        if not trades:
            continue
        pnls = [(t.get("net_pnl") or 0) for t in trades]
        wins = sum(1 for p in pnls if p > 0)
        period_stats[bucket] = {
            "count": len(trades),
            "win_rate": round(wins / len(trades), 3),
            "avg_pnl": round(sum(pnls) / len(pnls), 0),
        }

    # Monthly P&L
    monthly: dict[str, float] = {}
    for c in closed:
        exit_date = c.get("exit_date", "")
        if len(exit_date) >= 7:
            month = exit_date[:7]
            monthly[month] = monthly.get(month, 0) + (c.get("net_pnl") or 0)

    monthly_sorted = [
        {"month": m, "pnl": round(v, 0)}
        for m, v in sorted(monthly.items())
    ]

    return make_serializable({
        "has_data": True,
        "total_closed": len(closed),
        "by_exit_reason": reason_stats,
        "by_holding_period": period_stats,
        "monthly_pnl": monthly_sorted[-12:],  # Last 12 months
    })


# ---------------------------------------------------------------------------
# P2-B: Auto-Sim Pipeline
# ---------------------------------------------------------------------------


@router.post("/auto-sim")
def trigger_auto_sim(send_notify: bool = True):
    """P2-B: Run Auto-Sim Pipeline — screener -> find_similar_dual -> LINE Notify.

    Finds RS >= 80 stocks, runs similarity analysis, sends top 5 diversified
    signals to LINE Notify.
    """
    from analysis.auto_sim import run_auto_sim, send_auto_sim_notification

    try:
        result = run_auto_sim()
        if send_notify and result.get("top_signals"):
            result["notification_sent"] = send_auto_sim_notification(result)
        else:
            result["notification_sent"] = False
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# P3: Signal Log + Drift Detection
# ---------------------------------------------------------------------------


@router.get("/signal-log")
def get_signal_log(status: str = "all", limit: int = 100):
    """P3: Get trade signal log entries.

    status: 'all', 'active', or 'realized'
    """
    from analysis.signal_log import get_all_signals, get_active_signals, get_realized_signals
    from backend.dependencies import make_serializable

    if status == "active":
        signals = get_active_signals(days_back=90)
    elif status == "realized":
        signals = get_realized_signals(days_back=90)
    else:
        signals = get_all_signals(limit=limit)

    return make_serializable(signals)


@router.post("/signal-log/realize")
def realize_signals_now():
    """P3: Manually trigger signal realization (backfill actual returns)."""
    from analysis.signal_log import realize_signals

    try:
        result = realize_signals()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/drift-report")
def drift_report():
    """P3: Get drift detection report (In-Bounds Rate + Z-Score).

    Returns current drift metrics without running full audit.
    """
    from backend.dependencies import make_serializable
    from analysis.drift_detector import (
        compute_in_bounds_rate,
        detect_z_score_failure,
        get_risk_flag,
    )

    bounds = compute_in_bounds_rate(days_back=90)
    z_score = detect_z_score_failure(days_back=90)
    risk_flag = get_risk_flag()

    return make_serializable({
        "in_bounds": bounds,
        "z_score": z_score,
        "risk_flag": risk_flag,
    })


@router.post("/weekly-audit")
def trigger_weekly_audit():
    """P3: Manually trigger weekly drift audit + LINE notification."""
    from analysis.drift_detector import run_weekly_audit, send_weekly_audit_notification

    try:
        report = run_weekly_audit()
        sent = send_weekly_audit_notification(report)
        report["notification_sent"] = sent
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/risk-flag")
def get_risk_flag_status():
    """P3: Get global risk flag status."""
    from analysis.drift_detector import get_risk_flag
    return get_risk_flag()


@router.post("/risk-flag")
def set_risk_flag_manual(risk_on: bool = True, reason: str = "manual"):
    """P3: Manually set global risk flag."""
    from analysis.drift_detector import set_risk_flag
    return set_risk_flag(risk_on, reason)


# ---------------------------------------------------------------------------
# Phase 6: Trailing Stops + Failure Analysis
# ---------------------------------------------------------------------------


@router.get("/failure-analysis")
def failure_analysis(days_back: int = 90):
    """Phase 6 P2: Rule-based failure attribution for signals exceeding worst case.

    Architect mandate: "Rule-based first, AI second"
    Physical data (Entry/Exit/ATR) always included.
    """
    from backend.dependencies import make_serializable
    from analysis.failure_analyst import analyze_all_failures

    try:
        results = analyze_all_failures(days_back=days_back)
        return make_serializable({"failures": results, "count": len(results)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trailing-stops/update")
def update_trailing_stops():
    """Phase 6 P0: Update trailing stop prices for all active signals.

    Wires R86 ATR-based trailing stop to the Signal Log.
    Architect directive: "Wire R86 ATR-based stop values to Dashboard"
    """
    from analysis.signal_log import update_trailing_stops as _update
    try:
        return _update()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Phase 7-8: Sector Heatmap, Self-healed Events, Missed Opportunities
# ---------------------------------------------------------------------------


@router.get("/sector-heatmap")
def sector_heatmap():
    """Phase 8 P1: Sector RS Ranking Heatmap data.

    Reuses R84 sector_rs.py — Architect mandate: "No new modules allowed"
    Returns sector-level RS rankings for treemap visualization.
    """
    from backend.dependencies import make_serializable

    try:
        from analysis.sector_rs import compute_sector_rs_table
        table = compute_sector_rs_table()

        sectors = []
        for name, info in table.items():
            sectors.append({
                "name": name,
                "median_rs": info.get("median_rs", 0),
                "count": info.get("count", 0),
                "diamond_count": info.get("diamond_count", 0),
                "diamond_pct": info.get("diamond_pct", 0),
            })

        # Sort by median_rs descending
        sectors.sort(key=lambda x: x["median_rs"], reverse=True)
        top3 = [s["name"] for s in sectors[:3]]

        return make_serializable({
            "sectors": sectors,
            "top3": top3,
            "total_sectors": len(sectors),
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/self-healed-events")
def self_healed_events():
    """Phase 8 P0: Self-healed data anomaly events.

    Returns counter + recent events from the pipeline sanitizer.
    """
    events_file = Path(__file__).resolve().parent.parent.parent / "data" / "self_healed_events.json"
    if events_file.exists():
        try:
            return json.loads(events_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to load self-healed events: {e}")
    return {"total_healed": 0, "total_flagged": 0, "events": []}


@router.get("/missed-opportunities")
def missed_opportunities(days_back: int = 30, limit: int = 50):
    """Phase 7 P2: Signals penalized by Energy Score.

    Secretary directive: "Are filtered signals 'bullets' or 'bombs'?"
    """
    from analysis.signal_log import get_filtered_signals

    try:
        results = get_filtered_signals(days_back=days_back, limit=limit)
        return {"filtered": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Phase 9-10: War Room, Stress Test, Aggressive Index, Industry Success
# ---------------------------------------------------------------------------


@router.get("/aggressive-index")
def aggressive_index():
    """Phase 10 P1: Aggressive Index — System Temperature Gauge.

    Architect approved: [HYPOTHESIS: AGGRESSIVE_INDEX_WEIGHTS_V1]
    Combines Market Context (30) + Sector RS (25) + In-Bounds Rate (25) + Signal Quality (20).
    0-40: Defensive (blue), 40-70: Normal (green), 70-100: Aggressive (red).
    """
    score = 0
    breakdown = {}

    # 1. Market Context (max 30)
    try:
        from data.fetcher import get_taiex_data
        taiex = get_taiex_data(period_days=60)
        if taiex is not None and len(taiex) >= 25:
            close = taiex["close"]
            ma20 = close.rolling(20).mean()
            latest = float(close.iloc[-1])
            ma20_val = float(ma20.iloc[-1])
            if latest > ma20_val:
                market_score = 30
                market_label = "Bull (TAIEX > MA20)"
            else:
                market_score = 10
                market_label = "Bear (TAIEX < MA20)"
        else:
            market_score = 15
            market_label = "No data"
    except Exception as e:
        logger.debug(f"Health score: market context failed: {e}")
        market_score = 15
        market_label = "Error"

    score += market_score
    breakdown["market_context"] = {"score": market_score, "max": 30, "label": market_label}

    # 2. Sector RS Distribution (max 25)
    try:
        from analysis.sector_rs import compute_sector_rs_table
        sector_table = compute_sector_rs_table()
        if sector_table:
            sorted_sectors = sorted(sector_table.items(), key=lambda x: x[1].get("median_rs", 0), reverse=True)
            top3_median = [v.get("median_rs", 0) for _, v in sorted_sectors[:3]]
            avg_top3 = sum(top3_median) / len(top3_median) if top3_median else 0

            if avg_top3 > 70:
                sector_score = 25
                sector_label = f"Strong (Top3 avg={avg_top3:.0f})"
            elif avg_top3 > 50:
                sector_score = 15
                sector_label = f"Moderate (Top3 avg={avg_top3:.0f})"
            else:
                sector_score = 5
                sector_label = f"Weak (Top3 avg={avg_top3:.0f})"
        else:
            sector_score = 10
            sector_label = "No data"
    except Exception as e:
        logger.debug(f"Health score: sector RS failed: {e}")
        sector_score = 10
        sector_label = "Error"

    score += sector_score
    breakdown["sector_rs"] = {"score": sector_score, "max": 25, "label": sector_label}

    # 3. In-Bounds Rate (max 25)
    try:
        from analysis.drift_detector import compute_in_bounds_rate
        ib = compute_in_bounds_rate(days_back=90)
        rate = ib.get("in_bounds_rate")

        if rate is None:
            ib_score = 15  # No data = neutral
            ib_label = "No realized signals"
        elif rate > 0.70:
            ib_score = 25
            ib_label = f"Excellent ({rate:.0%})"
        elif rate > 0.60:
            ib_score = 20
            ib_label = f"Good ({rate:.0%})"
        elif rate > 0.50:
            ib_score = 15
            ib_label = f"Fair ({rate:.0%})"
        else:
            ib_score = 5
            ib_label = f"Poor ({rate:.0%})"
    except Exception as e:
        logger.debug(f"Health score: in-bounds rate failed: {e}")
        ib_score = 10
        ib_label = "Error"

    score += ib_score
    breakdown["in_bounds_rate"] = {"score": ib_score, "max": 25, "label": ib_label}

    # 4. Signal Quality — recent 5 signals avg confidence (max 20)
    try:
        from analysis.signal_log import get_all_signals
        recent = get_all_signals(limit=5)
        if recent:
            avg_conf = sum(s.get("sim_score", 0) for s in recent) / len(recent)
            if avg_conf >= 60:
                sq_score = 20
                sq_label = f"High (avg={avg_conf:.0f})"
            elif avg_conf >= 40:
                sq_score = 12
                sq_label = f"Medium (avg={avg_conf:.0f})"
            else:
                sq_score = 5
                sq_label = f"Low (avg={avg_conf:.0f})"
        else:
            sq_score = 10
            sq_label = "No signals"
    except Exception as e:
        logger.debug(f"Health score: signal quality failed: {e}")
        sq_score = 10
        sq_label = "Error"

    score += sq_score
    breakdown["signal_quality"] = {"score": sq_score, "max": 20, "label": sq_label}

    # Determine regime
    if score >= 70:
        regime = "aggressive"
        advice = "資金效率最大化"
        color = "#ef4444"  # red/hot
    elif score >= 40:
        regime = "normal"
        advice = "正常操作"
        color = "#22c55e"  # green/warm
    else:
        regime = "defensive"
        advice = "建議防禦，縮減倉位"
        color = "#3b82f6"  # blue/cold

    return {
        "score": score,
        "regime": regime,
        "advice": advice,
        "color": color,
        "breakdown": breakdown,
        "label": "[HYPOTHESIS: AGGRESSIVE_INDEX_WEIGHTS_V1]",
    }


@router.get("/stress-test")
def stress_test(stress_days: int = 3, slippage: float = 0.95):
    """Phase 10 P0: Flash Crash Stress Test.

    Architect approved: 3-day limit-down lock + 5% slippage.
    """
    from analysis.stress_tester import run_stress_test

    try:
        return run_stress_test(stress_days=stress_days, slippage=slippage)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/war-room")
def war_room():
    """Phase 9 P1: Virtual Portfolio Equity Curve (War Room View).

    Architect approved: "Joe's virtual clone — 24/7 executing all directives"
    [VIRTUAL: ALL_SIGNALS_TRACKED] — assumes every recommendation was followed.

    Uses signal_log position_pct for vol-adjusted sizing.
    Architect directive: "Fixed 10% would erase risk management soul"
    """
    from analysis.signal_log import get_realized_signals, get_all_signals

    try:
        # Get all signals (both active and realized)
        all_signals = get_all_signals(limit=9999)
        realized = [s for s in all_signals if s.get("status") == "realized"]

        # Sort by signal_date ascending for equity curve computation
        realized.sort(key=lambda s: s.get("signal_date", ""))

        # Compute equity curve
        INITIAL_EQUITY = 3_000_000  # [PLACEHOLDER] Joe's assumed capital
        equity = INITIAL_EQUITY
        equity_curve = [{"date": "", "equity": equity, "drawdown_pct": 0}]
        peak = equity
        max_dd = 0
        total_trades = 0
        wins = 0
        total_pnl = 0

        for sig in realized:
            ret_d21 = sig.get("actual_return_d21")
            if ret_d21 is None:
                continue

            # Use position_pct from signal_log; fallback to 10%
            pos_pct = 0.10  # Default fallback
            entry_price = sig.get("entry_price", 0)
            worst_case = sig.get("worst_case_pct")
            conf_score = sig.get("sim_score", 0)

            if entry_price and worst_case and worst_case < 0:
                risk_per_share = entry_price * abs(worst_case) / 100.0
                if risk_per_share > 0:
                    risk_amount = equity * 0.02  # 2% risk per trade
                    shares = int(risk_amount / risk_per_share)
                    pos_value = shares * entry_price
                    pos_pct = min(0.20, pos_value / equity if equity > 0 else 0)

                    # Confidence adjustment
                    if conf_score < 40:
                        pos_pct *= 0.5
                    elif conf_score < 70:
                        pos_pct *= 0.7

            # PnL for this trade
            trade_pnl = equity * pos_pct * ret_d21
            equity += trade_pnl
            total_trades += 1
            total_pnl += trade_pnl

            if ret_d21 > 0:
                wins += 1

            # Track drawdown
            if equity > peak:
                peak = equity
            dd_pct = (equity - peak) / peak if peak > 0 else 0
            if dd_pct < max_dd:
                max_dd = dd_pct

            equity_curve.append({
                "date": sig.get("signal_date", ""),
                "equity": round(equity, 0),
                "drawdown_pct": round(dd_pct * 100, 2),
                "stock_code": sig.get("stock_code", ""),
                "return_pct": round(ret_d21 * 100, 2),
            })

        # Summary stats
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        total_return_pct = ((equity - INITIAL_EQUITY) / INITIAL_EQUITY * 100) if INITIAL_EQUITY > 0 else 0
        expectancy = (total_pnl / total_trades) if total_trades > 0 else 0

        # MDD warning (Architect: >15% -> volatility warning)
        mdd_warning = abs(max_dd) > 0.15

        return {
            "label": "[VIRTUAL: ALL_SIGNALS_TRACKED]",
            "initial_equity": INITIAL_EQUITY,
            "final_equity": round(equity, 0),
            "total_return_pct": round(total_return_pct, 2),
            "total_trades": total_trades,
            "win_rate": round(win_rate, 1),
            "expectancy": round(expectancy, 0),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "mdd_warning": mdd_warning,
            "equity_curve": equity_curve,
            "active_count": sum(1 for s in all_signals if s.get("status") == "active"),
            "realized_count": len(realized),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/industry-success-rates")
def industry_success_rates(days_back: int = 90):
    """Phase 9 P0: Industry-level In-Bounds Rate for success rate back-weighting.

    Architect approved: [HYPOTHESIS: INDUSTRY_EXPERIENCE_WEIGHTS_V1]
    """
    from analysis.auto_sim import _compute_industry_success_rates

    try:
        rates = _compute_industry_success_rates(days_back=days_back)
        return {"rates": rates, "days_back": days_back}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Phase 11-14: Signal confirmation, reviews, audits, AI comments, etc.
# ---------------------------------------------------------------------------


@router.post("/signal/{signal_id}/confirm-live")
def confirm_live_trade(signal_id: int, actual_price: float):
    """Phase 11 P1: Mark a signal as 'live' — Joe confirmed execution.

    Architect: "is_live = True means the position officially enters asset protection mode"
    """
    from analysis.signal_log import confirm_live_trade as _confirm

    try:
        result = _confirm(signal_id=signal_id, actual_price=actual_price)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/daily-review-preview")
def daily_review_preview():
    """Phase 12 P1: Preview the daily review message (without sending LINE).

    Architect: Option A (template-based, no external API).
    """
    from data.daily_update import generate_daily_review
    msg = generate_daily_review()
    return {"message": msg or "(empty)", "generated_at": datetime.now().isoformat()}


@router.get("/shake-out-audit")
def shake_out_audit():
    """Phase 13 Task 2: Shake-out Detector — Stop-loss quality diagnosis.

    Architect OFFICIALLY APPROVED. CTO: "Joe's worst frustration is getting stopped out then watching it rally"
    """
    from analysis.signal_log import detect_shake_outs
    return detect_shake_outs()


@router.get("/slippage-audit")
def slippage_audit():
    """Phase 12 P0: Slippage Auditor — Real-trade friction analysis.

    Architect OFFICIALLY APPROVED.
    [HYPOTHESIS: SLIPPAGE_SENSITIVITY_V1]
    """
    from analysis.slippage_auditor import run_slippage_audit
    return run_slippage_audit()


@router.get("/param-recommendations")
def param_recommendations(days_back: int = 90):
    """Phase 14 Task 3: Parameter Recommendation Engine — Read-only suggestions.

    Architect APPROVED: No auto-modify, display only.
    """
    from analysis.param_recommender import generate_recommendations
    return generate_recommendations(days_back=days_back)


@router.get("/energy-trend/{stock_code}")
def energy_trend(stock_code: str, days_back: int = 3):
    """V1.1 P1: Energy Score Sparkline data from daily report snapshots.

    Architect APPROVED: File-based read, no DB queries.
    Returns list of {date, energy_tr_ratio, energy_vol_ratio, confidence_score}.
    """
    from analysis.auto_sim import get_energy_trend
    return get_energy_trend(stock_code, days_back=days_back)


@router.post("/ai-comment/{stock_code}")
def ai_comment(stock_code: str):
    """Phase 14 Task 1: AI Signal Commentator — on-demand for single stock.

    Architect APPROVED: "Cold, sharp-tongued but risk-reward obsessed veteran TW trader"
    """
    from analysis.ai_commentator import get_single_comment
    from analysis.signal_log import _get_conn

    # Fetch signal context from DB
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT * FROM trade_signals_log
               WHERE stock_code = ?
               ORDER BY signal_date DESC LIMIT 1""",
            (stock_code,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return {"stock_code": stock_code, "comment": "無歷史信號資料"}

    context = dict(row)
    comment = get_single_comment(stock_code, context)

    # Update DB
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE trade_signals_log SET ai_comment = ? WHERE id = ?",
            (comment, row["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    return {"stock_code": stock_code, "comment": comment, "signal_id": row["id"]}


# ---------------------------------------------------------------------------
# Phase 5: Pipeline Monitor
# ---------------------------------------------------------------------------


@router.get("/pipeline-monitor")
def pipeline_monitor():
    """Phase 5: Pipeline health monitor — data freshness + scheduler status.

    Returns file freshness, scheduler heartbeat, and cron job status.
    CTO directive: "Joe should see last successful execution time for all cron jobs"
    """
    import os
    from backend.dependencies import make_serializable

    data_dir = Path(__file__).resolve().parent.parent.parent / "data"

    # 1. Data file freshness
    now = datetime.now()
    files = {
        "close_matrix": {
            "path": data_dir / "pit_close_matrix.parquet",
            "description": "PIT Close Matrix",
            "max_age_hours": 28,
        },
        "rs_matrix": {
            "path": data_dir / "pit_rs_matrix.parquet",
            "description": "PIT RS Percentile",
            "max_age_hours": 28,
        },
        "screener_db": {
            "path": data_dir / "screener.db",
            "description": "Screener Snapshot",
            "max_age_hours": 28,
        },
        "features_parquet": {
            "path": data_dir / "pattern_data" / "features" / "features_all.parquet",
            "description": "65-Feature Parquet",
            "max_age_hours": 28,
        },
        "price_cache": {
            "path": data_dir / "pattern_data" / "features" / "price_cache.parquet",
            "description": "Price Cache",
            "max_age_hours": 28,
        },
        "forward_returns": {
            "path": data_dir / "pattern_data" / "features" / "forward_returns.parquet",
            "description": "Forward Returns",
            "max_age_hours": 28,
        },
        "signal_log_db": {
            "path": data_dir / "signal_log.db",
            "description": "Signal Log DB (P3)",
            "max_age_hours": 168,
        },
        "drift_report": {
            "path": data_dir / "drift_report.json",
            "description": "Drift Report (P3)",
            "max_age_hours": 168,
        },
        "param_scan": {
            "path": data_dir / "parameter_scan_history.json",
            "description": "Parameter Scan (P4)",
            "max_age_hours": 168,
        },
    }

    file_status = []
    for key, info in files.items():
        path = info["path"]
        if path.exists():
            mtime = os.path.getmtime(path)
            mtime_dt = datetime.fromtimestamp(mtime)
            age_hours = (now - mtime_dt).total_seconds() / 3600
            size_mb = os.path.getsize(path) / (1024 * 1024)
            stale = age_hours > info["max_age_hours"]
            file_status.append({
                "key": key,
                "description": info["description"],
                "exists": True,
                "last_modified": mtime_dt.isoformat(),
                "age_hours": round(age_hours, 1),
                "size_mb": round(size_mb, 2),
                "stale": stale,
                "status": "stale" if stale else "fresh",
            })
        else:
            file_status.append({
                "key": key,
                "description": info["description"],
                "exists": False,
                "status": "missing",
                "stale": True,
            })

    # 2. Scheduler heartbeat
    heartbeat = {}
    hb_path = data_dir / "scheduler_heartbeat.json"
    if hb_path.exists():
        try:
            heartbeat = json.loads(hb_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug(f"Failed to load scheduler heartbeat: {e}")

    # 3. Summary
    fresh_count = sum(1 for f in file_status if f.get("status") == "fresh")
    total_count = len(file_status)
    overall = "healthy" if fresh_count == total_count else "degraded" if fresh_count > total_count // 2 else "critical"

    return make_serializable({
        "overall": overall,
        "fresh_count": fresh_count,
        "total_count": total_count,
        "files": file_status,
        "scheduler": heartbeat,
        "checked_at": now.isoformat(),
    })


# ---------------------------------------------------------------------------
# Phase 6 P1: Daily Summary — "Ask My System" API
# ---------------------------------------------------------------------------


@router.get("/daily-summary")
def daily_summary():
    """Phase 6 P1: Structured daily summary for Gemini Live / external consumers.

    Returns system health, top active signals with stops, pipeline status,
    and risk flag in a single JSON payload designed for natural language conversion.
    """
    from backend.dependencies import make_serializable

    result = {}

    # 1. System health summary
    try:
        result["health"] = _get_health_summary()
    except Exception as e:
        logger.debug(f"Glance: health summary failed: {e}")
        result["health"] = {"status": "unknown"}

    # 2. Active signals with trailing stops
    try:
        from analysis.signal_log import get_active_signals
        active = get_active_signals(days_back=30)
        result["active_signals"] = {
            "count": len(active),
            "signals": [
                {
                    "code": s.get("stock_code"),
                    "name": s.get("stock_name"),
                    "entry_price": s.get("entry_price"),
                    "current_stop": s.get("current_stop_price"),
                    "trailing_phase": s.get("trailing_phase", 0),
                    "score": s.get("sim_score"),
                    "grade": s.get("confidence_grade"),
                    "tier": s.get("sniper_tier"),
                    "signal_date": s.get("signal_date"),
                }
                for s in active[:10]  # top 10
            ],
        }
    except Exception as e:
        logger.debug(f"Glance: active signals failed: {e}")
        result["active_signals"] = {"count": 0, "signals": []}

    # 3. Risk flag
    try:
        from analysis.drift_detector import get_risk_flag
        result["risk_flag"] = get_risk_flag()
    except Exception as e:
        logger.debug(f"Glance: risk flag failed: {e}")
        result["risk_flag"] = {"global_risk_on": True, "reason": "default"}

    # 4. Pipeline freshness (lightweight)
    try:
        import os
        data_dir = Path(__file__).resolve().parent.parent.parent / "data"
        now = datetime.now()
        key_files = {
            "close_matrix": data_dir / "pit_close_matrix.parquet",
            "screener": data_dir / "screener.db",
        }
        pipeline_ok = True
        for key, path in key_files.items():
            if path.exists():
                age_h = (now - datetime.fromtimestamp(os.path.getmtime(path))).total_seconds() / 3600
                if age_h > 28:
                    pipeline_ok = False
            else:
                pipeline_ok = False
        result["pipeline_healthy"] = pipeline_ok
    except Exception as e:
        logger.debug(f"Glance: pipeline freshness check failed: {e}")
        result["pipeline_healthy"] = None

    # 5. Recent auto-sim results (latest signals sent)
    try:
        from analysis.signal_log import get_all_signals
        recent = get_all_signals(limit=5)
        result["latest_signals"] = [
            {
                "code": s.get("stock_code"),
                "name": s.get("stock_name"),
                "score": s.get("sim_score"),
                "grade": s.get("confidence_grade"),
                "date": s.get("signal_date"),
            }
            for s in recent
        ]
    except Exception as e:
        logger.debug(f"Glance: latest signals failed: {e}")
        result["latest_signals"] = []

    result["generated_at"] = datetime.now().isoformat()
    return make_serializable(result)


def _get_health_summary() -> dict:
    """Build lightweight health summary from pipeline-monitor data."""
    import os
    data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    now = datetime.now()

    key_checks = [
        ("close_matrix", data_dir / "pit_close_matrix.parquet", 28),
        ("rs_matrix", data_dir / "pit_rs_matrix.parquet", 28),
        ("screener", data_dir / "screener.db", 28),
    ]

    issues = []
    for name, path, max_age in key_checks:
        if not path.exists():
            issues.append(f"{name}: missing")
        else:
            age_h = (now - datetime.fromtimestamp(os.path.getmtime(path))).total_seconds() / 3600
            if age_h > max_age:
                issues.append(f"{name}: stale ({age_h:.0f}h)")

    status = "healthy" if not issues else "degraded"
    return {"status": status, "issues": issues}


# ---------------------------------------------------------------------------
# V1.2-V1.3: Morning Brief, Rebalance, Drift Monitor, Dynamic ATR
# ---------------------------------------------------------------------------


@router.get("/morning-brief")
def morning_brief(send: bool = False):
    """V1.2 P1: Morning Briefing Generator — preview or send.

    CTO/Architect OFFICIALLY APPROVED.
    - send=false (default): preview only, no notification
    - send=true: generate + push via LINE/Telegram
    """
    from analysis.morning_brief import generate_morning_brief, is_market_open

    result = generate_morning_brief(send_notification=send)
    result["is_market_open"] = is_market_open()
    return result


@router.get("/rebalance")
def rebalance_report():
    """V1.3 P0: Portfolio Rebalancing Engine — standalone report.

    CTO/Architect OFFICIALLY APPROVED.
    Returns regime classification, target exposure, hysteresis state,
    and per-position rebalancing actions.
    """
    from analysis.rebalancer import generate_rebalance_report
    from analysis.morning_brief import _get_aggressive_index, _get_market_guard

    agg_score, agg_level, agg_icon = _get_aggressive_index()
    guard = _get_market_guard()

    return generate_rebalance_report(
        agg_score=agg_score,
        guard_level=guard.get("level", 0),
        guard_label=guard.get("label", "NORMAL"),
    )


@router.get("/drift-monitor")
def drift_monitor():
    """V1.3 P1: Backtest Drift Monitor — live vs backtest equity curve.

    CTO/Architect OFFICIALLY APPROVED.
    Returns portfolio-level drift, Z-score, alert level,
    expanding negative detection, and historical trend.
    """
    from analysis.drift_monitor import generate_drift_report

    return generate_drift_report(save_snapshot=False)


@router.get("/dynamic-atr")
def dynamic_atr():
    """V1.3 P2: Dynamic ATR Multiplier — auto-adjust stop-loss based on shake-out rate.

    CTO APPROVED: "Adding muscular flexibility to the system"
    Returns current shake-out rate, ATR adjustment, adjusted multipliers per entry type,
    and historical trend.
    """
    from analysis.dynamic_atr import generate_dynamic_atr_report

    return generate_dynamic_atr_report(save_snapshot=False)

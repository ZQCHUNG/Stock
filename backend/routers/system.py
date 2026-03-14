"""系統路由 — 快取狀態、最近股票、健康檢查、備份"""

import json
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter()

RECENT_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "recent_stocks.json"


@router.get("/health")
def system_health(include_slow: bool = False):
    """R47-2: 統一系統健康檢查

    Fast checks: Redis, SQLite, Scheduler, data files.
    Set include_slow=true to also check yfinance and FinMind (adds 2-10s).
    """
    from backend.health import get_system_health
    return get_system_health(include_slow=include_slow)


@router.get("/cache-stats")
def cache_stats():
    """取得快取統計"""
    from data.cache import get_cache_stats
    return get_cache_stats()


@router.post("/flush-cache")
def flush_cache():
    """清空所有快取"""
    from data.cache import flush_cache as _flush
    _flush()
    return {"ok": True}


@router.get("/recent-stocks")
def get_recent_stocks():
    """取得最近查看的股票"""
    try:
        if RECENT_FILE.exists():
            codes = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
            from data.stock_list import get_stock_name
            return [{"code": c, "name": get_stock_name(c)} for c in codes]
    except Exception:
        pass
    return []


@router.post("/recent-stocks/{code}")
def add_recent_stock(code: str):
    """記錄最近查看的股票 + Sprint 15 P1-B: 加入 on-demand cache queue"""
    codes = []
    try:
        if RECENT_FILE.exists():
            codes = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
    except Exception:
        codes = []

    if code in codes:
        codes.remove(code)
    codes.insert(0, code)
    codes = codes[:20]  # 最多保留 20 筆

    RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECENT_FILE.write_text(json.dumps(codes, ensure_ascii=False), encoding="utf-8")

    # Sprint 15 P1-B: Add to on-demand cache queue for nightly pre-computation
    _add_to_cache_queue(code)

    return {"ok": True}


# Sprint 15 P1-B: On-demand cache queue
_CACHE_QUEUE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "cache_queue.json"


def _add_to_cache_queue(code: str):
    """Add stock to nightly pre-computation queue. Deduplicates automatically."""
    try:
        queue = []
        if _CACHE_QUEUE_FILE.exists():
            queue = json.loads(_CACHE_QUEUE_FILE.read_text(encoding="utf-8"))
        if code not in queue:
            queue.append(code)
            queue = queue[-50:]  # keep last 50
            _CACHE_QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass  # non-critical


@router.get("/worker-heartbeat")
def worker_heartbeat():
    """取得 Worker 心跳"""
    from data.cache import get_worker_heartbeat
    hb = get_worker_heartbeat()
    return hb or {"status": "offline"}


@router.get("/v4-params")
def get_v4_params():
    """取得 v4 策略預設參數"""
    from config import STRATEGY_V4_PARAMS
    return STRATEGY_V4_PARAMS


@router.get("/transition-alerts")
def get_transition_alerts(limit: int = 20):
    """取得 Maturity Transition 事件（Gemini R24 P2）

    Returns list of transition events, most recent first.
    High-value events: Leader stock upgrading maturity while sector is hot.
    """
    from data.cache import get_transition_events
    events = get_transition_events(limit=limit)
    # Return most recent first
    return list(reversed(events))


# ---------------------------------------------------------------------------
# R47-3: Backup & Export
# ---------------------------------------------------------------------------

@router.post("/backup")
def run_backup():
    """R47-3: 執行資料備份（SQLite + JSON 設定檔）"""
    from backend.backup import run_backup as _run
    return _run()


@router.get("/backups")
def list_backups():
    """R47-3: 列出所有備份檔案"""
    from backend.backup import list_backups as _list
    return _list()


@router.get("/export/positions/csv")
def export_positions_csv():
    """R47-3: 匯出倉位資料為 CSV"""
    from backend.backup import export_positions_csv as _export
    content = _export()
    if not content:
        return Response(content="No data", media_type="text/plain")
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=positions.csv"},
    )


@router.get("/export/positions/json")
def export_positions_json():
    """R47-3: 匯出倉位資料為 JSON"""
    from backend.backup import export_positions_json as _export
    from backend.dependencies import make_serializable
    return make_serializable(_export())


@router.get("/export/signals/csv")
def export_signals_csv(source: str | None = None):
    """R47-3: 匯出 SQS 信號記錄為 CSV"""
    from backend.backup import export_signals_csv as _export
    content = _export(source=source)
    if not content:
        return Response(content="No data", media_type="text/plain")
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=signals.csv"},
    )


# ---------------------------------------------------------------------------
# R55-2: CSV Export for backtest results, portfolio, screener, report
# ---------------------------------------------------------------------------

@router.post("/export/backtest/csv")
def export_backtest_csv(result: dict):
    """R55-2: 匯出回測結果為 CSV"""
    from backend.export_utils import backtest_to_csv
    content = backtest_to_csv(result)
    code = result.get("code", "unknown")
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=backtest_{code}.csv"},
    )


@router.get("/export/portfolio/csv")
def export_full_portfolio_csv():
    """R55-2: 匯出完整投資組合報告為 CSV"""
    from backend import db
    from backend.export_utils import portfolio_to_csv
    positions = db.get_open_positions()
    closed = db.get_closed_positions(limit=200)
    summary = {}
    if positions:
        total_value = sum(p.get("entry_price", 0) * p.get("lots", 0) * 1000 for p in positions)
        summary = {
            "total_positions": len(positions),
            "total_market_value": total_value,
        }
    content = portfolio_to_csv(positions, closed, summary)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=portfolio.csv"},
    )


@router.post("/export/screener/csv")
def export_screener_csv(payload: dict):
    """R55-2: 匯出選股結果為 CSV"""
    from backend.export_utils import screener_to_csv
    results = payload.get("results", [])
    filters = payload.get("filters")
    content = screener_to_csv(results, filters)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=screener_results.csv"},
    )


@router.post("/export/report/csv")
def export_report_csv(report: dict):
    """R55-2: 匯出分析報告為 CSV"""
    from backend.export_utils import report_to_csv
    code = report.get("code", "unknown")
    content = report_to_csv(report)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=report_{code}.csv"},
    )


# ---------------------------------------------------------------------------
# R57: PDF Export via Playwright
# ---------------------------------------------------------------------------

@router.get("/export/report/pdf/{code}")
async def export_report_pdf(code: str):
    """R57: 匯出分析報告為 PDF（Playwright 渲染 Vue 頁面）"""
    try:
        from backend.pdf_export import export_report_pdf as _export
        pdf_bytes = await _export(code)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=report_{code}.pdf"},
        )
    except ImportError:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Playwright not installed. Run: pip install playwright && python -m playwright install chromium")
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")


@router.get("/export/portfolio/pdf")
async def export_portfolio_pdf():
    """R57: 匯出投資組合為 PDF"""
    try:
        from backend.pdf_export import export_portfolio_pdf as _export
        pdf_bytes = await _export()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=portfolio.pdf"},
        )
    except ImportError:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Playwright not installed")
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")


@router.get("/export/backtest/pdf/{code}")
async def export_backtest_pdf(code: str, period: int = 1095):
    """R57: 匯出回測報告為 PDF"""
    try:
        from backend.pdf_export import export_backtest_pdf as _export
        pdf_bytes = await _export(code, period)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=backtest_{code}.pdf"},
        )
    except ImportError:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Playwright not installed")
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")


@router.get("/data-quality")
def data_quality():
    """R48-2: 數據品質檢查

    檢查自選股和持倉股票的數據完整性、異常值、時效性。
    """
    from concurrent.futures import ThreadPoolExecutor
    from backend import db
    from backend.data_quality import check_batch_data_quality
    from data.fetcher import get_stock_data

    # Collect codes from watchlist + open positions
    codes = set()

    try:
        from backend import db
        wl = db.get_watchlist()
        codes.update(wl)
    except Exception:
        pass

    try:
        positions = db.get_open_positions()
        codes.update(p["code"] for p in positions)
    except Exception:
        pass

    if not codes:
        return {
            "checked_at": None,
            "total_stocks": 0,
            "ok_count": 0, "warning_count": 0, "error_count": 0,
            "overall_score": 1.0,
            "stocks": [],
            "critical_issues": [],
            "message": "無自選股或持倉資料",
        }

    # Parallel fetch
    stock_data = {}
    def _fetch(code):
        try:
            return code, get_stock_data(code, period_days=60)
        except Exception:
            return code, None

    with ThreadPoolExecutor(max_workers=6) as ex:
        for code, df in ex.map(_fetch, list(codes)[:30]):  # Max 30 stocks
            stock_data[code] = df if df is not None else __import__('pandas').DataFrame()

    return check_batch_data_quality(stock_data)


@router.get("/api-performance")
def api_performance():
    """R49-3: API 性能統計

    顯示最近 500 個 API 請求的響應時間統計，按端點分組。
    """
    from backend.app import get_api_performance_stats
    return get_api_performance_stats()


@router.get("/oms-events")
def oms_events(limit: int = 50):
    """R50-2: OMS 訂單事件記錄

    取得最近的 OMS 自動出場與移動停利更新事件。
    """
    from backend.order_manager import get_order_events
    return {"events": get_order_events(limit=limit)}


@router.get("/oms-stats")
def oms_stats():
    """R50-2: OMS 執行統計

    統計自動出場次數、原因分佈、累計損益。
    """
    from backend.order_manager import get_oms_stats
    return get_oms_stats()


@router.post("/oms-run")
def oms_run_now():
    """R50-2: 手動觸發 OMS 檢查

    立即檢查所有持倉的停損/停利/移動停利條件。
    """
    from backend.order_manager import check_positions_and_execute
    return check_positions_and_execute()


@router.get("/oms-efficiency")
def oms_efficiency():
    """R51-2: OMS 效率分析

    分析停損/停利/移動停利的有效性：勝率、平均損益、覆蓋率。
    """
    from backend.order_manager import get_oms_efficiency
    return get_oms_efficiency()


@router.get("/performance-attribution")
def performance_attribution():
    """R51-2: 交易績效歸因

    按出場類型、持倉時間、市場情境分析已平倉交易的績效。
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


@router.get("/dashboard")
def dashboard_summary():
    """R52 P1: Dashboard summary — aggregates key data for the homepage.

    Returns positions summary, P&L, market regime, OMS efficiency, alerts.
    """
    from backend.dependencies import make_serializable

    result = {
        "positions": _dashboard_positions(),
        "pnl": _dashboard_pnl(),
        "regime": _dashboard_regime(),
        "oms": _dashboard_oms(),
        "alerts": _dashboard_alerts(),
        "risk": _dashboard_risk(),
        "today_signals": _dashboard_today_signals(),
        "equity_curve": _dashboard_equity_curve(),
    }
    return make_serializable(result)


def _dashboard_positions():
    """Open positions summary for dashboard."""
    try:
        from backend import db
        positions = db.get_open_positions()
        if not positions:
            return {"count": 0, "total_value": 0, "total_pnl": 0, "total_pnl_pct": 0}

        total_value = sum(p.get("market_value", 0) for p in positions)
        total_cost = sum(p.get("entry_price", 0) * p.get("lots", 0) * 1000 for p in positions)
        total_pnl = sum(p.get("pnl", 0) for p in positions)
        pnl_pct = total_pnl / total_cost if total_cost > 0 else 0

        return {
            "count": len(positions),
            "total_value": round(total_value, 0),
            "total_pnl": round(total_pnl, 0),
            "total_pnl_pct": round(pnl_pct, 4),
            "top_positions": [
                {"code": p.get("code"), "name": p.get("name", ""),
                 "pnl": p.get("pnl", 0), "pnl_pct": p.get("pnl_pct", 0)}
                for p in sorted(positions, key=lambda x: abs(x.get("pnl", 0)), reverse=True)[:5]
            ],
        }
    except Exception:
        return {"count": 0, "total_value": 0, "total_pnl": 0, "total_pnl_pct": 0}


def _dashboard_pnl():
    """Monthly P&L summary from closed trades."""
    try:
        from backend import db
        closed = db.get_closed_positions(limit=500)
        if not closed:
            return {"total_closed": 0, "cumulative_pnl": 0, "monthly": []}

        cumulative = sum(c.get("net_pnl", 0) for c in closed)
        monthly: dict[str, float] = {}
        for c in closed:
            exit_date = c.get("exit_date", "")
            if len(exit_date) >= 7:
                month = exit_date[:7]
                monthly[month] = monthly.get(month, 0) + (c.get("net_pnl") or 0)

        monthly_list = [{"month": m, "pnl": round(v, 0)} for m, v in sorted(monthly.items())]

        return {
            "total_closed": len(closed),
            "cumulative_pnl": round(cumulative, 0),
            "monthly": monthly_list[-6:],  # Last 6 months for compact view
        }
    except Exception:
        return {"total_closed": 0, "cumulative_pnl": 0, "monthly": []}


def _dashboard_regime():
    """Current ML market regime (fast — uses cached data if available)."""
    try:
        from backend.regime_classifier import classify_market_regime
        from data.fetcher import get_stock_data

        df = get_stock_data("0050", period_days=250)
        if df is None or len(df) < 60:
            return {"regime": "unknown", "label": "N/A", "confidence": 0}

        rd = classify_market_regime(
            close=df["close"].values,
            high=df["high"].values,
            low=df["low"].values,
            volume=df["volume"].values.astype(float),
        )
        return {
            "regime": rd.get("regime", "unknown"),
            "label": rd.get("regime_label", "N/A"),
            "confidence": rd.get("confidence", 0),
            "kelly": rd.get("kelly_multiplier", 0.5),
            "v4_suitability": rd.get("v4_suitability", "unknown"),
            "advice": rd.get("strategy_advice", ""),
        }
    except Exception:
        return {"regime": "unknown", "label": "N/A", "confidence": 0}


def _dashboard_oms():
    """OMS efficiency summary."""
    try:
        from backend.order_manager import get_oms_efficiency
        eff = get_oms_efficiency()
        return {
            "auto_coverage": eff.get("auto_coverage", 0),
            "max_consecutive_losses": eff.get("max_consecutive_losses", 0),
            "total_auto_exits": eff.get("total_auto_exits", 0),
        }
    except Exception:
        return {"auto_coverage": 0, "max_consecutive_losses": 0, "total_auto_exits": 0}


def _dashboard_alerts():
    """Recent system alerts from alert history."""
    try:
        alert_history = Path(__file__).resolve().parent.parent.parent / "data" / "alert_history.json"
        if not alert_history.exists():
            return []
        data = json.loads(alert_history.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data[-5:]  # Last 5 alerts
        return []
    except Exception:
        return []


def _dashboard_risk():
    """R53: Quick risk snapshot — VaR + Kelly."""
    try:
        from backend import db
        from analysis.risk import calculate_portfolio_var
        from data.fetcher import get_stock_data
        from concurrent.futures import ThreadPoolExecutor

        positions = db.get_open_positions()
        if not positions:
            return {"has_data": False}

        codes = list({p["code"] for p in positions})
        total_value = sum(p.get("entry_price", 0) * p.get("lots", 0) * 1000 for p in positions)

        stock_data = {}
        def _fetch(code):
            try:
                return code, get_stock_data(code, period_days=120)
            except Exception:
                return code, None

        with ThreadPoolExecutor(max_workers=4) as ex:
            for code, df in ex.map(_fetch, codes):
                if df is not None and len(df) >= 30:
                    stock_data[code] = df

        if not stock_data:
            return {"has_data": False}

        var_result = calculate_portfolio_var(stock_data, confidence=0.95, days=250, portfolio_value=total_value)
        var_1d_pct = var_result.get("var_pct", 0) or 0
        var_5d_pct = var_1d_pct * (5 ** 0.5)

        return {
            "has_data": True,
            "var_1d_pct": round(var_1d_pct, 4),
            "var_5d_pct": round(var_5d_pct, 4),
            "var_1d_amt": round(var_1d_pct * total_value, 0),
            "total_value": round(total_value, 0),
            "position_count": len(positions),
        }
    except Exception:
        return {"has_data": False}


def _dashboard_today_signals():
    """R53: Today's BUY/SELL signals from cached scan results."""
    try:
        from data.cache import get_cached_scan_results
        cached = get_cached_scan_results()
        if not cached:
            return []
        signals = []
        for item in cached:
            if item.get("signal") in ("BUY", "SELL"):
                signals.append({
                    "code": item.get("code"),
                    "name": item.get("name", ""),
                    "signal": item.get("signal"),
                    "price": item.get("price", 0),
                    "entry_type": item.get("entry_type", ""),
                })
        return signals[:10]  # Top 10
    except Exception:
        return []


def _dashboard_equity_curve():
    """R53: Portfolio equity curve from equity snapshots."""
    try:
        from backend import db
        snapshots = db.get_equity_snapshots()
        if not snapshots:
            return {"dates": [], "values": []}
        # Last 90 entries
        recent = snapshots[-90:]
        dates = [s.get("date", "") for s in recent]
        values = [s.get("total_equity", 0) for s in recent]
        return {"dates": dates, "values": values}
    except Exception:
        return {"dates": [], "values": []}


# ---------------------------------------------------------------------------
# R62: Business Metrics endpoints
# ---------------------------------------------------------------------------

@router.get("/metrics")
def get_metrics():
    """R62: Get business metrics summary."""
    from backend.metrics import metrics
    return metrics.get_summary().to_dict()


@router.get("/metrics/events")
def get_metric_events(limit: int = 50):
    """R62: Get recent metric events."""
    from backend.metrics import metrics
    return metrics.get_recent_events(limit=limit)


@router.get("/metrics/anomalies")
def get_anomalies():
    """R62: Get current anomaly alerts."""
    from backend.metrics import metrics
    return {"anomalies": metrics.detect_anomalies()}


# ---------------------------------------------------------------------------
# R63: TWSE Data Provider — Official Data Source Integration
# ---------------------------------------------------------------------------

@router.get("/twse/db-stats")
def twse_db_stats():
    """R63: Get TWSE SQLite database statistics."""
    from data.twse_provider import get_db_stats
    return get_db_stats()


@router.post("/twse/sync/{code}")
def twse_sync_stock(code: str, months: int = 12, force: bool = False):
    """R63: Sync a stock's data from TWSE/TPEX to SQLite.

    This fetches raw OHLCV, dividends, and computes adjustment factors.
    """
    from data.twse_provider import sync_and_adjust
    count = sync_and_adjust(code, months_back=months, force=force)
    return {"code": code, "rows_synced": count, "months": months}


@router.get("/twse/compare/{code}")
def twse_compare(code: str, days: int = 30):
    """R63: Shadow Mode — Compare TWSE data with yfinance.

    Returns consistency report showing any price discrepancies.
    """
    from data.twse_provider import compare_with_yfinance
    return compare_with_yfinance(code, days)


@router.post("/twse/backfill")
def twse_backfill(codes: list[str], months: int = 12, with_dividends: bool = True):
    """R63: Bulk backfill multiple stocks from TWSE.

    Warning: This is a slow operation due to TWSE rate limiting.
    """
    from data.twse_provider import HistoryBackfiller
    bf = HistoryBackfiller()
    bf.add_stocks(codes)
    results = bf.run(months_back=months, with_dividends=with_dividends)
    return {"results": results, "total_stocks": len(codes)}


# ---------------------------------------------------------------------------
# R89: Market Regime Global Switch — 全局市場環境斷路器
# [CONVERGED — Wall Street Trader + Architect Critic APPROVED]
# ---------------------------------------------------------------------------

@router.get("/market-guard")
def market_guard_status():
    """R89: Get current market guard level (NORMAL / CAUTION / LOCKDOWN).

    Uses TAIEX MA20/MA200, ADL, market breadth, and gap detection
    to determine maximum allowed portfolio exposure.

    Returns:
        MarketGuardStatus with level (0/1/2) and exposure_limit (0.0-1.0)
    """
    from backend.dependencies import make_serializable
    from analysis.market_guard import get_market_exposure_limit
    from data.fetcher import get_taiex_data, get_stock_data
    from concurrent.futures import ThreadPoolExecutor
    from config import SCAN_STOCKS

    # Fetch TAIEX data (need 200+ days for MA200)
    taiex_df = None
    try:
        taiex_df = get_taiex_data(period_days=300)
    except Exception as e:
        logger.warning("Market guard: failed to fetch TAIEX: %s", e)

    if taiex_df is None or len(taiex_df) < 200:
        return make_serializable({
            "level": 0,
            "level_label": "UNKNOWN",
            "exposure_limit": 1.0,
            "detail": "TAIEX data insufficient. Defaulting to NORMAL.",
            "triggers": [],
        })

    # Fetch close prices for ADL and breadth (sample of SCAN_STOCKS)
    # Use a sample to keep response time reasonable
    sample_codes = list(SCAN_STOCKS.keys())[:50]
    stock_closes = {}

    def _fetch_close(code):
        try:
            df = get_stock_data(code, period_days=60)
            if df is not None and len(df) >= 25:
                return code, df["close"]
        except Exception:
            pass
        return code, None

    try:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for code, close_series in ex.map(_fetch_close, sample_codes):
                if close_series is not None:
                    stock_closes[code] = close_series
    except Exception as e:
        logger.warning("Market guard: failed to fetch stock closes: %s", e)

    status = get_market_exposure_limit(taiex_df, stock_closes)
    return make_serializable(status.to_dict())


# ---------------------------------------------------------------------------
# R89: Exception Dashboard — 異常監控面板
# [CONVERGED — Wall Street Trader + Architect Critic APPROVED]
# ---------------------------------------------------------------------------

@router.get("/exception-dashboard")
def exception_dashboard():
    """R89: Exception-only dashboard for risk monitoring.

    Returns 4 exception cards:
    1. Portfolio Heat & Concentration (sector >40%, total ATR >6%)
    2. Signal Drift (Entry SQS vs Current SQS degradation)
    3. Liquidity Trap (Days to liquidate >3 days)
    4. Price Gap Alert (Architect Critic addition)

    Plus: market guard status summary.
    """
    from backend.dependencies import make_serializable

    result = {
        "market_guard": _exception_market_guard(),
        "heat_concentration": _exception_heat(),
        "signal_drift": _exception_signal_drift(),
        "liquidity_trap": _exception_liquidity(),
        "price_gap": _exception_price_gap(),
        "data_health": _exception_data_health(),
    }
    return make_serializable(result)


def _exception_market_guard():
    """Market guard status for exception dashboard."""
    try:
        from analysis.market_guard import get_market_exposure_limit
        from data.fetcher import get_taiex_data
        taiex_df = get_taiex_data(period_days=300)
        status = get_market_exposure_limit(taiex_df)
        return {
            "level": status.level,
            "level_label": status.level_label,
            "exposure_limit": status.exposure_limit,
            "taiex_close": status.taiex_close,
            "taiex_ma20": status.taiex_ma20,
            "taiex_ma200": status.taiex_ma200,
            "triggers": status.triggers,
            "detail": status.detail,
            "is_alert": status.level > 0,
        }
    except Exception as e:
        return {"level": 0, "level_label": "ERROR", "detail": str(e), "is_alert": False}


def _exception_heat():
    """Card 1: Portfolio Heat & Concentration.

    Alert when:
    - Single sector > 40% [PLACEHOLDER: CONCENTRATION_LIMIT]
    - Total ATR stop risk > 6% of account [VERIFIED: JOE_RISK_THRESHOLD]
    """
    try:
        from backend import db
        positions = db.get_open_positions()
        if not positions:
            return {"is_alert": False, "detail": "No positions", "sectors": [], "total_risk_pct": 0}

        total_value = sum(
            p.get("entry_price", 0) * p.get("lots", 0) * 1000
            for p in positions
        ) or 1

        # Sector concentration
        sector_values: dict[str, float] = {}
        for p in positions:
            sector = p.get("sector", "未分類") or "未分類"
            val = p.get("entry_price", 0) * p.get("lots", 0) * 1000
            sector_values[sector] = sector_values.get(sector, 0) + val

        sector_pcts = {s: round(v / total_value, 4) for s, v in sector_values.items()}
        max_sector = max(sector_pcts.values()) if sector_pcts else 0
        max_sector_name = max(sector_pcts, key=sector_pcts.get) if sector_pcts else ""

        # Total ATR stop risk (approximate: SL 7% × position %)
        total_risk = 0
        for p in positions:
            entry = p.get("entry_price", 0)
            stop = p.get("stop_price", entry * 0.93)
            lots = p.get("lots", 0)
            risk_amount = (entry - stop) * lots * 1000 if entry > stop else 0
            total_risk += risk_amount
        total_risk_pct = total_risk / total_value if total_value > 0 else 0

        # [PLACEHOLDER: CONCENTRATION_LIMIT] = 0.40
        # [VERIFIED: JOE_RISK_THRESHOLD] = 0.06
        sector_alert = max_sector > 0.40
        risk_alert = total_risk_pct > 0.06

        alerts = []
        if sector_alert:
            alerts.append(f"{max_sector_name} 佔比 {max_sector:.0%} > 40% 上限")
        if risk_alert:
            alerts.append(f"總 ATR 停損風險 {total_risk_pct:.1%} > 6% 上限")

        return {
            "is_alert": sector_alert or risk_alert,
            "sector_alert": sector_alert,
            "risk_alert": risk_alert,
            "max_sector_name": max_sector_name,
            "max_sector_pct": round(max_sector, 4),
            "total_risk_pct": round(total_risk_pct, 4),
            "sectors": sector_pcts,
            "alerts": alerts,
            "detail": "; ".join(alerts) if alerts else "正常",
        }
    except Exception as e:
        return {"is_alert": False, "detail": str(e)}


def _exception_signal_drift():
    """Card 2: Signal Drift — SQS degradation for held stocks.

    Alert when Entry_SQS - Current_SQS > 25 points.
    This means fundamentals/chips have deteriorated while price hasn't
    triggered technical stop-loss yet.
    """
    try:
        from backend import db
        positions = db.get_open_positions()
        if not positions:
            return {"is_alert": False, "drifted": [], "detail": "No positions"}

        drifted = []
        for p in positions:
            entry_sqs = p.get("entry_sqs", 0)
            current_sqs = p.get("current_sqs", entry_sqs)
            if entry_sqs and current_sqs and (entry_sqs - current_sqs) > 25:
                drifted.append({
                    "code": p.get("code", ""),
                    "name": p.get("name", ""),
                    "entry_sqs": entry_sqs,
                    "current_sqs": current_sqs,
                    "drift": round(entry_sqs - current_sqs, 1),
                })

        return {
            "is_alert": len(drifted) > 0,
            "drifted": drifted,
            "count": len(drifted),
            "detail": f"{len(drifted)} 檔持股 SQS 下滑超過 25 分" if drifted else "所有持股 SQS 穩定",
        }
    except Exception as e:
        return {"is_alert": False, "drifted": [], "detail": str(e)}


def _exception_liquidity():
    """Card 3: Liquidity Trap — days to liquidate check.

    If liquidating all positions at 15% of daily volume takes >3 days,
    this is a warning signal.
    """
    try:
        from backend import db
        from data.fetcher import get_stock_data
        from concurrent.futures import ThreadPoolExecutor

        positions = db.get_open_positions()
        if not positions:
            return {"is_alert": False, "trapped": [], "detail": "No positions"}

        codes = list({p["code"] for p in positions})

        # Fetch recent volume data
        volumes = {}
        def _fetch_vol(code):
            try:
                df = get_stock_data(code, period_days=30)
                if df is not None and len(df) >= 5:
                    return code, float(df["volume"].tail(20).mean())
            except Exception:
                pass
            return code, 0

        with ThreadPoolExecutor(max_workers=6) as ex:
            for code, avg_vol in ex.map(_fetch_vol, codes):
                volumes[code] = avg_vol

        trapped = []
        for p in positions:
            code = p.get("code", "")
            lots = p.get("lots", 0)
            shares = lots * 1000
            avg_vol = volumes.get(code, 0)

            if avg_vol > 0:
                # Assume we can trade 15% of daily volume
                daily_capacity = avg_vol * 0.15
                days_to_exit = shares / daily_capacity if daily_capacity > 0 else 99
            else:
                days_to_exit = 99

            if days_to_exit > 3:
                trapped.append({
                    "code": code,
                    "name": p.get("name", ""),
                    "lots": lots,
                    "avg_volume": round(avg_vol, 0),
                    "days_to_exit": round(days_to_exit, 1),
                })

        return {
            "is_alert": len(trapped) > 0,
            "trapped": trapped,
            "count": len(trapped),
            "detail": f"{len(trapped)} 檔持股退場需 >3 天" if trapped else "所有持股流動性正常",
        }
    except Exception as e:
        return {"is_alert": False, "trapped": [], "detail": str(e)}


def _exception_price_gap():
    """Card 4: Price Gap Alert (Architect Critic addition).

    Gap-down > -3% with abnormal volume → structural damage warning.
    """
    try:
        from analysis.market_guard import detect_price_gap
        from data.fetcher import get_taiex_data

        taiex_df = get_taiex_data(period_days=30)
        if taiex_df is None or len(taiex_df) < 21:
            return {"is_alert": False, "detail": "Insufficient data"}

        alert, gap_pct = detect_price_gap(taiex_df)

        return {
            "is_alert": alert,
            "gap_pct": gap_pct,
            "detail": (
                f"TAIEX 開盤跳空 {gap_pct:.1%} + 異常量能，結構性損毀風險"
                if alert else "今日無異常跳空"
            ),
        }
    except Exception as e:
        return {"is_alert": False, "detail": str(e)}


def _exception_data_health():
    """Card 5: Data Health — Fetcher freshness check.

    Enhanced health check: verify all 10 fetchers have fresh data.
    [CONVERGED — Architect Critic: resource integrity is highest defense]
    """
    try:
        from data.health_check import run_health_check
        result = run_health_check()

        any_fail = result["overall"] == "FAIL"
        checks_summary = []
        for c in result.get("checks", []):
            checks_summary.append({
                "name": c.get("check", ""),
                "status": c.get("status", "UNKNOWN"),
                "detail": c.get("detail", ""),
            })

        return {
            "is_alert": any_fail,
            "overall": result["overall"],
            "checks": checks_summary,
            "detail": "資料品質異常，SQS 評分可能不可靠" if any_fail else "所有資料來源正常",
        }
    except Exception as e:
        return {"is_alert": False, "overall": "ERROR", "detail": str(e)}


# ---------------------------------------------------------------------------
# Phase 3: Daily Pattern Update — manual trigger + status
# ---------------------------------------------------------------------------

@router.post("/pattern-daily-update")
def trigger_daily_pattern_update():
    """Phase 3: Manually trigger the daily pattern update pipeline.

    Runs: close matrix extend → RS recompute → screener refresh.
    This normally runs at 20:15 via cron, but can be triggered manually.
    """
    from fastapi import HTTPException
    from data.daily_update import run_daily_update

    try:
        result = run_daily_update()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pattern-daily-status")
def pattern_daily_status():
    """Phase 3: Check freshness of close matrix, RS matrices, and screener DB."""
    import os

    data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    files = {
        "pit_close_matrix": data_dir / "pit_close_matrix.parquet",
        "pit_rs_matrix": data_dir / "pit_rs_matrix.parquet",
        "pit_rs_percentile": data_dir / "pit_rs_percentile.parquet",
        "screener_db": data_dir / "screener.db",
        "features_all": data_dir / "pattern_data" / "features" / "features_all.parquet",
    }

    status = {}
    for name, path in files.items():
        if path.exists():
            mtime = os.path.getmtime(path)
            size_mb = os.path.getsize(path) / (1024 * 1024)
            status[name] = {
                "exists": True,
                "last_modified": datetime.fromtimestamp(mtime).isoformat(),
                "size_mb": round(size_mb, 1),
            }
        else:
            status[name] = {"exists": False}

    return status


@router.post("/emergency-stop")
def emergency_stop():
    """R91: Manual Kill-Switch — one-click stop all automated trading.

    [CONVERGED — Wall Street Trader CTO mandate 2026-02-22]
    Atomic actions:
    1. Stop scheduler (all cron jobs)
    2. Snapshot current state to disk
    3. Return confirmation

    Joe can trigger this from Dashboard to immediately halt everything.
    """
    import json as _json
    from datetime import datetime

    now = datetime.now()
    actions = []

    # 1. Stop scheduler
    try:
        from backend.scheduler import stop_scheduler, get_health
        health_before = get_health()
        stop_scheduler()
        actions.append({"action": "stop_scheduler", "status": "ok", "detail": "Scheduler stopped"})
    except Exception as e:
        actions.append({"action": "stop_scheduler", "status": "error", "detail": str(e)})

    # 2. Snapshot current state to disk
    try:
        from backend import db
        positions = db.get_open_positions()
        snapshot = {
            "timestamp": now.isoformat(),
            "trigger": "manual_emergency_stop",
            "positions": positions,
            "position_count": len(positions),
        }
        snapshot_path = Path(__file__).resolve().parent.parent.parent / "data" / "emergency_snapshot.json"
        snapshot_path.write_text(
            _json.dumps(snapshot, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        actions.append({
            "action": "snapshot_state",
            "status": "ok",
            "detail": f"Saved {len(positions)} positions to {snapshot_path.name}",
        })
    except Exception as e:
        actions.append({"action": "snapshot_state", "status": "error", "detail": str(e)})

    # 2.5. Phase 11 P0: Set global_risk_on = False (persistent lockdown)
    # Architect: "必須具備狀態持久化，即便伺服器重啟也應保持 LOCKDOWN"
    try:
        from analysis.drift_detector import set_risk_flag
        set_risk_flag(risk_on=False, reason="EMERGENCY_STOP — manual kill switch")
        actions.append({"action": "set_risk_off", "status": "ok", "detail": "global_risk_on = False (persisted)"})
    except Exception as e:
        actions.append({"action": "set_risk_off", "status": "error", "detail": str(e)})

    # 3. Send notification
    try:
        from backend.scheduler import _send_notification
        _send_notification(
            f"\n🚨 EMERGENCY STOP 觸發\n"
            f"⏰ {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Scheduler 已停止\n"
            f"Risk Flag: OFF (LOCKDOWN)\n"
            f"所有自動交易已暫停\n"
            f"需手動解除 Risk Flag 才能恢復"
        )
        actions.append({"action": "notify", "status": "ok", "detail": "Emergency notification sent"})
    except Exception as e:
        actions.append({"action": "notify", "status": "error", "detail": str(e)})

    return {
        "status": "emergency_stop_executed",
        "timestamp": now.isoformat(),
        "actions": actions,
        "system_locked": True,
    }


# ---------------------------------------------------------------------------
# P2-B: Auto-Sim Pipeline — manual trigger
# ---------------------------------------------------------------------------

@router.post("/auto-sim")
def trigger_auto_sim(send_notify: bool = True):
    """P2-B: Run Auto-Sim Pipeline — screener → find_similar_dual → LINE Notify.

    Finds RS >= 80 stocks, runs similarity analysis, sends top 5 diversified
    signals to LINE Notify.
    """
    from fastapi import HTTPException
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
    from fastapi import HTTPException
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
    from fastapi import HTTPException
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
# Phase 6 P0: Trailing Stops — Active Signal Protection
# ---------------------------------------------------------------------------

@router.get("/failure-analysis")
def failure_analysis(days_back: int = 90):
    """Phase 6 P2: Rule-based failure attribution for signals exceeding worst case.

    Architect mandate: "Rule-based 第一, AI 第二"
    Physical data (Entry/Exit/ATR) always included.
    """
    from backend.dependencies import make_serializable
    from analysis.failure_analyst import analyze_all_failures

    try:
        results = analyze_all_failures(days_back=days_back)
        return make_serializable({"failures": results, "count": len(results)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sector-heatmap")
def sector_heatmap():
    """Phase 8 P1: Sector RS Ranking Heatmap data.

    Reuses R84 sector_rs.py — Architect mandate: "嚴禁新建模組"
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
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/self-healed-events")
def self_healed_events():
    """Phase 8 P0: Self-healed data anomaly events.

    Returns counter + recent events from the pipeline sanitizer.
    """
    import json
    events_file = Path(__file__).resolve().parent.parent.parent / "data" / "self_healed_events.json"
    if events_file.exists():
        try:
            return json.loads(events_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"total_healed": 0, "total_flagged": 0, "events": []}


@router.get("/missed-opportunities")
def missed_opportunities(days_back: int = 30, limit: int = 50):
    """Phase 7 P2: Signals penalized by Energy Score.

    Secretary directive: "究竟被過濾掉的是「子彈」還是「炸彈」？"
    """
    from analysis.signal_log import get_filtered_signals

    try:
        results = get_filtered_signals(days_back=days_back, limit=limit)
        return {"filtered": results, "count": len(results)}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/signal/{signal_id}/confirm-live")
def confirm_live_trade(signal_id: int, actual_price: float):
    """Phase 11 P1: Mark a signal as 'live' — Joe confirmed execution.

    Architect: "is_live = True 意味著該標的正式進入資產保衛模式"
    """
    from analysis.signal_log import confirm_live_trade as _confirm

    try:
        result = _confirm(signal_id=signal_id, actual_price=actual_price)
        if "error" in result:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/daily-review-preview")
def daily_review_preview():
    """Phase 12 P1: Preview the daily review message (without sending LINE).

    Architect: Option A (template-based, no external API).
    """
    from data.daily_update import generate_daily_review
    msg = generate_daily_review()
    return {"message": msg or "(empty)", "generated_at": __import__("datetime").datetime.now().isoformat()}


@router.get("/shake-out-audit")
def shake_out_audit():
    """Phase 13 Task 2: Shake-out Detector — Stop-loss quality diagnosis.

    Architect OFFICIALLY APPROVED. CTO: "Joe 最挫折的往往是被洗掉後拉上去"
    """
    from analysis.signal_log import detect_shake_outs
    return detect_shake_outs()


@router.get("/slippage-audit")
def slippage_audit():
    """Phase 12 P0: Slippage Auditor — Real-trade friction analysis.

    Architect OFFICIALLY APPROVED. CTO: "如果實戰滑價吃掉了預期利潤，所有回測都是幻影"
    [HYPOTHESIS: SLIPPAGE_SENSITIVITY_V1]
    """
    from analysis.slippage_auditor import run_slippage_audit
    return run_slippage_audit()


@router.get("/param-recommendations")
def param_recommendations(days_back: int = 90):
    """Phase 14 Task 3: Parameter Recommendation Engine — Read-only suggestions.

    Architect APPROVED: No auto-modify, display only.
    CTO: "系統應該能告訴 Joe 哪些參數可能需要調整，但不自動修改"
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

    Architect APPROVED: "冷靜、毒舌但極度看重風險回報比的台股資深交易員"
    CTO: "讓 AI 用一句話戳穿信號的本質"
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


@router.get("/aggressive-index")
def aggressive_index():
    """Phase 10 P1: Aggressive Index — System Temperature Gauge.

    Architect approved: [HYPOTHESIS: AGGRESSIVE_INDEX_WEIGHTS_V1]
    Combines Market Context (30) + Sector RS (25) + In-Bounds Rate (25) + Signal Quality (20).
    0-40: Defensive (blue), 40-70: Normal (green), 70-100: Aggressive (red).
    """
    import logging
    logger = logging.getLogger(__name__)

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
    except Exception:
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
    except Exception:
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
    except Exception:
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
    except Exception:
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
    Secretary: "最好的防禦，是在黑天鵝還沒起飛前，就已經在模擬器中殺死它一百次"
    """
    from analysis.stress_tester import run_stress_test

    try:
        return run_stress_test(stress_days=stress_days, slippage=slippage)
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/war-room")
def war_room():
    """Phase 9 P1: Virtual Portfolio Equity Curve (War Room View).

    Architect approved: "Joe 的虛擬分身 — 24 小時不休息地執行所有指令"
    [VIRTUAL: ALL_SIGNALS_TRACKED] — assumes every recommendation was followed.

    Uses signal_log position_pct for vol-adjusted sizing.
    Architect directive: "固定 10% 會抹殺掉系統對風險管理的靈魂"
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
            # Architect: "position_pct 包含系統在進場當下的波動率補償"
            pos_pct = 0.10  # Default fallback
            # position_pct is not stored in signal_log currently;
            # compute from entry_price + confidence_score
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

        # MDD warning (Architect: >15% → volatility warning)
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
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/industry-success-rates")
def industry_success_rates(days_back: int = 90):
    """Phase 9 P0: Industry-level In-Bounds Rate for success rate back-weighting.

    Architect approved: [HYPOTHESIS: INDUSTRY_EXPERIENCE_WEIGHTS_V1]
    "成功往往吸引更多資金 (Positive Feedback)"
    """
    from analysis.auto_sim import _compute_industry_success_rates

    try:
        rates = _compute_industry_success_rates(days_back=days_back)
        return {"rates": rates, "days_back": days_back}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trailing-stops/update")
def update_trailing_stops():
    """Phase 6 P0: Update trailing stop prices for all active signals.

    Wires R86 ATR-based trailing stop to the Signal Log.
    Architect directive: "將 R86 的 ATR-based stop 數值推送到 Dashboard"
    """
    from analysis.signal_log import update_trailing_stops as _update
    try:
        return _update()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Phase 5: Pipeline Monitor — execution health dashboard
# ---------------------------------------------------------------------------

@router.get("/pipeline-monitor")
def pipeline_monitor():
    """Phase 5: Pipeline health monitor — data freshness + scheduler status.

    Returns file freshness, scheduler heartbeat, and cron job status.
    CTO directive: "Joe 進入控制塔能看到所有定時任務的最後成功執行時間"
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
            "max_age_hours": 28,  # ~1 trading day + buffer
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
            "max_age_hours": 168,  # weekly
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
        except Exception:
            pass

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

    CTO directive: Joe 問 "Gemini，今天系統健康嗎？有哪些高分標的？" → 回答
    Architect: "[INFRA] 安全的唯讀 endpoint"
    """
    from backend.dependencies import make_serializable

    result = {}

    # 1. System health summary
    try:
        result["health"] = _get_health_summary()
    except Exception:
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
    except Exception:
        result["active_signals"] = {"count": 0, "signals": []}

    # 3. Risk flag
    try:
        from analysis.drift_detector import get_risk_flag
        result["risk_flag"] = get_risk_flag()
    except Exception:
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
    except Exception:
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
    except Exception:
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

    CTO APPROVED: "為系統裝上肌肉的靈活性"
    Returns current shake-out rate, ATR adjustment, adjusted multipliers per entry type,
    and historical trend.
    """
    from analysis.dynamic_atr import generate_dynamic_atr_report

    return generate_dynamic_atr_report(save_snapshot=False)

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
    """記錄最近查看的股票"""
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
    return {"ok": True}


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
        from backend.routers.watchlist import _load_watchlist
        wl = _load_watchlist()
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
        from backend.ml_regime import classify_market_regime
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

    # 3. Send notification
    try:
        from backend.scheduler import _send_notification
        _send_notification(
            f"\n🚨 EMERGENCY STOP 觸發\n"
            f"⏰ {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Scheduler 已停止\n"
            f"所有自動交易已暫停"
        )
        actions.append({"action": "notify", "status": "ok", "detail": "Emergency notification sent"})
    except Exception as e:
        actions.append({"action": "notify", "status": "error", "detail": str(e)})

    return {
        "status": "emergency_stop_executed",
        "timestamp": now.isoformat(),
        "actions": actions,
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

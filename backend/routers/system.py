"""系統路由 — 快取狀態、最近股票、健康檢查、備份"""

import json
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

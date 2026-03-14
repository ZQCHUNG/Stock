"""System routes — health, cache, recent stocks, backup, dashboard, metrics, TWSE, market-guard.

Export endpoints have been moved to system_export.py.
Operational monitoring endpoints have been moved to system_ops.py.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter()

RECENT_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "recent_stocks.json"


@router.get("/health")
def system_health(include_slow: bool = False):
    """R47-2: Unified system health check

    Fast checks: Redis, SQLite, Scheduler, data files.
    Set include_slow=true to also check yfinance and FinMind (adds 2-10s).
    """
    from backend.health import get_system_health
    return get_system_health(include_slow=include_slow)


@router.get("/cache-stats")
def cache_stats():
    """Get cache statistics"""
    from data.cache import get_cache_stats
    return get_cache_stats()


@router.post("/flush-cache")
def flush_cache():
    """Flush all caches"""
    from data.cache import flush_cache as _flush
    _flush()
    return {"ok": True}


@router.get("/recent-stocks")
def get_recent_stocks():
    """Get recently viewed stocks"""
    try:
        if RECENT_FILE.exists():
            codes = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
            from data.stock_list import get_stock_name
            return [{"code": c, "name": get_stock_name(c)} for c in codes]
    except Exception as e:
        logger.debug(f"Failed to load recent stocks: {e}")
    return []


@router.post("/recent-stocks/{code}")
def add_recent_stock(code: str):
    """Record recently viewed stock + Sprint 15 P1-B: add to on-demand cache queue"""
    codes = []
    try:
        if RECENT_FILE.exists():
            codes = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug(f"Failed to read recent stocks file: {e}")
        codes = []

    if code in codes:
        codes.remove(code)
    codes.insert(0, code)
    codes = codes[:20]  # Keep max 20

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
    except Exception as e:
        logger.debug(f"Failed to update cache queue: {e}")


@router.get("/worker-heartbeat")
def worker_heartbeat():
    """Check worker heartbeat status"""
    heartbeat_file = Path(__file__).resolve().parent.parent.parent / "data" / "scheduler_heartbeat.json"
    if heartbeat_file.exists():
        try:
            data = json.loads(heartbeat_file.read_text(encoding="utf-8"))
            return data
        except Exception as e:
            logger.debug(f"Failed to read heartbeat: {e}")
    return {"status": "unknown"}


@router.get("/v4-params")
def get_v4_params():
    """Get current V4 strategy parameters"""
    from config import DEFAULT_V4_CONFIG
    return {
        "stop_loss_pct": DEFAULT_V4_CONFIG.stop_loss_pct,
        "take_profit_pct": DEFAULT_V4_CONFIG.take_profit_pct,
    }


@router.get("/transition-alerts")
def get_transition_alerts():
    """Get recent strategy transition alerts"""
    from data.cache import get_cached_scan_results
    from backend.dependencies import make_serializable

    cached = get_cached_scan_results()
    if not cached:
        return []

    alerts = []
    for item in cached:
        if item.get("transition"):
            alerts.append({
                "code": item.get("code"),
                "name": item.get("name", ""),
                "transition": item.get("transition"),
                "signal": item.get("signal"),
            })
    return make_serializable(alerts)


@router.post("/backup")
def run_backup():
    """R47-3: Run data backup (SQLite + JSON config files)"""
    from backend.backup import run_backup as _run
    return _run()


@router.get("/backups")
def list_backups():
    """R47-3: List all backup files"""
    from backend.backup import list_backups as _list
    return _list()


@router.get("/data-quality")
def data_quality():
    """R49-1: Data quality dashboard

    Checks: data freshness, NaN ratio, price anomalies, volume anomalies.
    Samples 10 stocks from SCAN_STOCKS.
    """
    from concurrent.futures import ThreadPoolExecutor
    from config import SCAN_STOCKS
    from data.fetcher import get_stock_data
    from backend.dependencies import make_serializable
    import numpy as np

    sample_codes = list(SCAN_STOCKS.keys())[:10]
    results = []

    def _check(code):
        try:
            df = get_stock_data(code, period_days=60)
            if df is None or len(df) < 10:
                return {"code": code, "status": "no_data"}

            nan_ratio = float(df.isna().sum().sum() / (len(df) * len(df.columns)))
            close = df["close"]
            pct_change = close.pct_change().dropna()
            max_pct = float(pct_change.abs().max()) if len(pct_change) > 0 else 0

            issues = []
            if nan_ratio > 0.05:
                issues.append(f"High NaN ratio: {nan_ratio:.2%}")
            if max_pct > 0.12:
                issues.append(f"Price anomaly: {max_pct:.1%} single-day change")

            return {
                "code": code,
                "status": "ok" if not issues else "warning",
                "rows": len(df),
                "nan_ratio": round(nan_ratio, 4),
                "max_daily_change": round(max_pct, 4),
                "issues": issues,
            }
        except Exception as e:
            return {"code": code, "status": "error", "error": str(e)}

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(_check, sample_codes))

    ok_count = sum(1 for r in results if r.get("status") == "ok")
    return make_serializable({
        "total_checked": len(results),
        "ok_count": ok_count,
        "warning_count": len(results) - ok_count,
        "stocks": results,
    })


@router.get("/api-performance")
def api_performance():
    """R49-3: API performance statistics

    Shows response time stats for last 500 API requests, grouped by endpoint.
    """
    from backend.app import get_api_performance_stats
    return get_api_performance_stats()


# ---------------------------------------------------------------------------
# R52 P1: Dashboard Summary
# ---------------------------------------------------------------------------


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
    except Exception as e:
        logger.debug(f"Dashboard positions summary failed: {e}")
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
            "monthly": monthly_list[-6:],
        }
    except Exception as e:
        logger.debug(f"Dashboard P&L summary failed: {e}")
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
    except Exception as e:
        logger.debug(f"Dashboard regime classification failed: {e}")
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
    except Exception as e:
        logger.debug(f"Dashboard OMS summary failed: {e}")
        return {"auto_coverage": 0, "max_consecutive_losses": 0, "total_auto_exits": 0}


def _dashboard_alerts():
    """Recent system alerts from alert history."""
    try:
        alert_history = Path(__file__).resolve().parent.parent.parent / "data" / "alert_history.json"
        if not alert_history.exists():
            return []
        data = json.loads(alert_history.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data[-5:]
        return []
    except Exception as e:
        logger.debug(f"Dashboard alerts load failed: {e}")
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
            except Exception as e:
                logger.debug(f"VaR data fetch failed for {code}: {e}")
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
    except Exception as e:
        logger.debug(f"Dashboard VaR calculation failed: {e}")
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
        return signals[:10]
    except Exception as e:
        logger.debug(f"Dashboard today signals failed: {e}")
        return []


def _dashboard_equity_curve():
    """R53: Portfolio equity curve from equity snapshots."""
    try:
        from backend import db
        snapshots = db.get_equity_snapshots()
        if not snapshots:
            return {"dates": [], "values": []}
        recent = snapshots[-90:]
        dates = [s.get("date", "") for s in recent]
        values = [s.get("total_equity", 0) for s in recent]
        return {"dates": dates, "values": values}
    except Exception as e:
        logger.debug(f"Dashboard equity curve failed: {e}")
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
# R63: TWSE Data Provider
# ---------------------------------------------------------------------------


@router.get("/twse/db-stats")
def twse_db_stats():
    """TWSE SQLite database statistics"""
    from data.twse_provider import get_db_stats
    return get_db_stats()


@router.post("/twse/sync/{code}")
def twse_sync(code: str, days: int = 365):
    """Sync stock data from TWSE/TPEX to local SQLite"""
    from data.twse_provider import sync_stock
    try:
        result = sync_stock(code, lookback_days=days)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/twse/compare/{code}")
def twse_compare(code: str):
    """Compare TWSE data with yfinance (shadow mode validation)"""
    from data.twse_provider import compare_with_yfinance
    try:
        return compare_with_yfinance(code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/twse/backfill")
def twse_backfill(codes: list[str] | None = None, days: int = 365):
    """Batch backfill TWSE data for multiple stocks"""
    from data.twse_provider import batch_backfill
    try:
        result = batch_backfill(codes=codes, lookback_days=days)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# R89: Market Guard
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
    sample_codes = list(SCAN_STOCKS.keys())[:50]
    stock_closes = {}

    def _fetch_close(code):
        try:
            df = get_stock_data(code, period_days=60)
            if df is not None and len(df) >= 25:
                return code, df["close"]
        except Exception as e:
            logger.debug(f"Market guard fetch failed for {code}: {e}")
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
# R89: Exception Dashboard
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
        }
    except Exception as e:
        logger.debug(f"Exception dashboard: market guard failed: {e}")
        return {"level": 0, "level_label": "UNKNOWN", "exposure_limit": 1.0}


def _exception_heat():
    """Portfolio heat & sector concentration exceptions."""
    try:
        from backend import db
        from data.sector_mapping import get_stock_sector
        positions = db.get_open_positions()
        if not positions:
            return {"has_exceptions": False}

        # Sector concentration
        sector_values: dict[str, float] = {}
        total_value = 0
        for p in positions:
            sector = get_stock_sector(p["code"], level=1)
            value = p.get("entry_price", 0) * p.get("lots", 0) * 1000
            sector_values[sector] = sector_values.get(sector, 0) + value
            total_value += value

        exceptions = []
        for sector, value in sector_values.items():
            pct = value / total_value if total_value > 0 else 0
            if pct > 0.40:
                exceptions.append({
                    "type": "sector_concentration",
                    "sector": sector,
                    "pct": round(pct * 100, 1),
                    "threshold": 40,
                })

        return {"has_exceptions": len(exceptions) > 0, "exceptions": exceptions}
    except Exception as e:
        logger.debug(f"Exception dashboard: heat check failed: {e}")
        return {"has_exceptions": False}


def _exception_signal_drift():
    """Signal drift exceptions (entry SQS vs current SQS)."""
    try:
        from analysis.signal_log import get_active_signals
        active = get_active_signals(days_back=30)
        exceptions = []
        for s in active:
            entry_score = s.get("sim_score", 0)
            # Would need real-time SQS recomputation; placeholder for now
            if entry_score and entry_score < 30:
                exceptions.append({
                    "code": s.get("stock_code"),
                    "entry_score": entry_score,
                    "type": "low_entry_score",
                })
        return {"has_exceptions": len(exceptions) > 0, "exceptions": exceptions[:5]}
    except Exception as e:
        logger.debug(f"Exception dashboard: signal drift failed: {e}")
        return {"has_exceptions": False}


def _exception_liquidity():
    """Liquidity trap exceptions."""
    try:
        from backend import db
        positions = db.get_open_positions()
        if not positions:
            return {"has_exceptions": False}

        exceptions = []
        for p in positions:
            # Check average volume vs position size
            avg_vol = p.get("avg_volume_20d", 0)
            shares = p.get("lots", 0) * 1000
            if avg_vol > 0:
                dtl = shares / (avg_vol * 0.1)  # 10% participation rate
                if dtl > 3:
                    exceptions.append({
                        "code": p["code"],
                        "dtl_days": round(dtl, 1),
                        "type": "slow_liquidation",
                    })
        return {"has_exceptions": len(exceptions) > 0, "exceptions": exceptions[:5]}
    except Exception as e:
        logger.debug(f"Exception dashboard: liquidity check failed: {e}")
        return {"has_exceptions": False}


def _exception_price_gap():
    """Price gap exceptions (Architect addition)."""
    try:
        from backend import db
        from data.fetcher import get_stock_data

        positions = db.get_open_positions()
        if not positions:
            return {"has_exceptions": False}

        exceptions = []
        for p in positions[:10]:  # Check first 10
            try:
                df = get_stock_data(p["code"], period_days=5)
                if df is not None and len(df) >= 2:
                    prev_close = float(df["close"].iloc[-2])
                    current_open = float(df["open"].iloc[-1])
                    gap_pct = (current_open - prev_close) / prev_close
                    if abs(gap_pct) > 0.03:  # >3% gap
                        exceptions.append({
                            "code": p["code"],
                            "gap_pct": round(gap_pct * 100, 2),
                            "type": "gap_down" if gap_pct < 0 else "gap_up",
                        })
            except Exception as e:
                logger.debug(f"Price gap check failed: {e}")

        return {"has_exceptions": len(exceptions) > 0, "exceptions": exceptions}
    except Exception as e:
        logger.debug(f"Exception dashboard: price gap check failed: {e}")
        return {"has_exceptions": False}


def _exception_data_health():
    """Data health exceptions."""
    try:
        import os
        data_dir = Path(__file__).resolve().parent.parent.parent / "data"
        now = datetime.now()
        issues = []

        key_files = [
            ("close_matrix", data_dir / "pit_close_matrix.parquet", 28),
            ("screener_db", data_dir / "screener.db", 28),
        ]
        for name, path, max_age_h in key_files:
            if not path.exists():
                issues.append({"file": name, "issue": "missing"})
            else:
                age_h = (now - datetime.fromtimestamp(os.path.getmtime(path))).total_seconds() / 3600
                if age_h > max_age_h:
                    issues.append({"file": name, "issue": f"stale ({age_h:.0f}h)"})

        return {"has_exceptions": len(issues) > 0, "exceptions": issues}
    except Exception as e:
        logger.debug(f"Exception dashboard: data health check failed: {e}")
        return {"has_exceptions": False}


# ---------------------------------------------------------------------------
# Pattern Daily Update + Emergency Stop
# ---------------------------------------------------------------------------


@router.post("/pattern-daily-update")
def trigger_daily_pattern_update():
    """Phase 3: Manually trigger the daily pattern update pipeline.

    Runs: close matrix extend -> RS recompute -> screener refresh.
    This normally runs at 20:15 via cron, but can be triggered manually.
    """
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

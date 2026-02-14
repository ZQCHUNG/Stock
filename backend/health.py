"""Unified system health check module (Gemini R47-2)

Checks all critical subsystems and returns a combined health status:
- Scheduler (APScheduler)
- Data sources (yfinance, FinMind)
- Cache (Redis)
- Database (SQLite portfolio)
"""

import logging
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def check_redis_health() -> dict:
    """Check Redis connectivity and basic stats."""
    try:
        from data.cache import get_redis
        client = get_redis()
        if client is None:
            return {
                "status": "stopped",
                "message": "Redis not available (using in-memory fallback)",
            }
        info = client.info("memory")
        dbsize = client.dbsize()
        return {
            "status": "healthy",
            "keys": dbsize,
            "used_memory_human": info.get("used_memory_human", "?"),
        }
    except Exception as e:
        return {"status": "stopped", "message": str(e)}


def check_database_health() -> dict:
    """Check SQLite portfolio database connectivity."""
    try:
        from backend import db
        # Try a simple query
        positions = db.get_open_positions()
        return {
            "status": "healthy",
            "open_positions": len(positions) if positions else 0,
        }
    except Exception as e:
        return {"status": "degraded", "message": str(e)}


def check_yfinance_health() -> dict:
    """Check yfinance data source by fetching a known stock (^TWII)."""
    try:
        import yfinance as yf
        start = time.time()
        ticker = yf.Ticker("^TWII")
        hist = ticker.history(period="2d", auto_adjust=True)
        elapsed = round(time.time() - start, 2)

        if hist.empty:
            return {"status": "degraded", "message": "Empty response", "latency_s": elapsed}

        last_date = str(hist.index[-1].date()) if len(hist) > 0 else "unknown"
        return {
            "status": "healthy",
            "latency_s": elapsed,
            "last_data_date": last_date,
        }
    except Exception as e:
        return {"status": "stopped", "message": str(e)}


def check_finmind_health() -> dict:
    """Check FinMind API availability."""
    try:
        import requests
        start = time.time()
        resp = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params={"dataset": "TaiwanStockInfo", "stock_id": "2330"},
            timeout=10,
        )
        elapsed = round(time.time() - start, 2)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == 200:
                return {"status": "healthy", "latency_s": elapsed}
            return {"status": "degraded", "message": f"API status: {data.get('status')}", "latency_s": elapsed}
        return {"status": "degraded", "message": f"HTTP {resp.status_code}", "latency_s": elapsed}
    except Exception as e:
        return {"status": "stopped", "message": str(e)}


def check_scheduler_health() -> dict:
    """Check APScheduler status."""
    try:
        from backend.scheduler import get_health
        return get_health()
    except Exception as e:
        return {"status": "stopped", "message": str(e)}


def check_data_files_health() -> dict:
    """Check critical data files exist and are readable."""
    files_to_check = {
        "alert_config": DATA_DIR / "alert_config.json",
        "watchlist": DATA_DIR / "watchlist.json",
        "sqs_signals": DATA_DIR / "sqs_signal_tracker.json",
    }
    results = {}
    for name, path in files_to_check.items():
        if path.exists():
            try:
                size = path.stat().st_size
                results[name] = {"exists": True, "size_bytes": size}
            except Exception:
                results[name] = {"exists": True, "readable": False}
        else:
            results[name] = {"exists": False}
    return results


def get_system_health(include_slow: bool = False) -> dict:
    """Get comprehensive system health status.

    Args:
        include_slow: If True, also check external data sources (yfinance, FinMind).
                      These checks can take 2-10 seconds each.
    """
    now = datetime.now()
    components = {}

    # Fast checks (always run)
    components["redis"] = check_redis_health()
    components["database"] = check_database_health()
    components["scheduler"] = check_scheduler_health()
    components["data_files"] = check_data_files_health()

    # Slow checks (optional, for external data sources)
    if include_slow:
        components["yfinance"] = check_yfinance_health()
        components["finmind"] = check_finmind_health()

    # Compute overall status
    statuses = [
        v.get("status", "unknown")
        for k, v in components.items()
        if k != "data_files"  # data_files doesn't have a single status
    ]
    if "stopped" in statuses:
        overall = "degraded"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "timestamp": now.isoformat(),
        "components": components,
    }

"""FastAPI 應用入口

CORS 設定、路由掛載、靜態檔案伺服（production 模式）。
"""

import sys
from pathlib import Path

# 確保專案根目錄在 sys.path，讓 from analysis.xxx import 正常運作
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import logging
import time
from collections import deque
from threading import Lock

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.routers import stocks, analysis, backtest, report, recommend, screener, watchlist, system, configs, bt_results, portfolio, alerts, sqs_performance, risk, strategies, ws, cluster

logger = logging.getLogger(__name__)

# R50-1: Initialize structured logging
from backend.logging_config import setup_logging
import os
setup_logging(json_format=os.environ.get("LOG_FORMAT") == "json")

app = FastAPI(title="台股技術分析系統 API", version="2.0")


@app.on_event("startup")
async def startup_scheduler():
    """R45: Start APScheduler for background alert checks.
    R55: Start WebSocket market data feed.
    """
    try:
        from backend.scheduler import start_scheduler
        start_scheduler(interval_minutes=5)
    except Exception as e:
        logger.warning(f"Failed to start scheduler: {e}")

    # R55-1: Start WebSocket market feed
    try:
        from backend.ws_manager import market_feed
        await market_feed.start()
    except Exception as e:
        logger.warning(f"Failed to start market feed: {e}")


@app.on_event("shutdown")
async def shutdown_cleanup():
    """R55: Stop market feed on shutdown."""
    try:
        from backend.ws_manager import market_feed
        await market_feed.stop()
    except Exception:
        pass


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Standardized error response for all unhandled exceptions (Gemini R44)."""
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "error_code": "INTERNAL_ERROR",
            "message": str(exc),
            "path": str(request.url.path),
        },
    )

# R50-1: API Key Authentication Middleware
from backend.config import API_KEY, API_KEY_HEADER

if API_KEY:
    @app.middleware("http")
    async def api_key_middleware(request: Request, call_next):
        """Simple API key authentication for production."""
        path = request.url.path
        # Skip auth for health check and static files
        if path.startswith("/api/system/health") or not path.startswith("/api/"):
            return await call_next(request)
        key = request.headers.get(API_KEY_HEADER, "")
        if key != API_KEY:
            return JSONResponse(status_code=401, content={"error": "Invalid API key"})
        return await call_next(request)


# Sprint 15 P0-B: API Timeout Guard — prevent infinite waits for non-cached stocks
_HEAVY_PATTERNS = ('/recommend/', '/auto-sim', '/batch-sqs', '/strategy-fitness',
                   '/weekly-audit', '/shake-out', '/failure-analysis',
                   '/export/', '/rs-scan')
_TIMEOUT_DEFAULT = 15.0   # 15s for normal endpoints
_TIMEOUT_HEAVY = 120.0    # 120s for batch/scan endpoints


@app.middleware("http")
async def timeout_guard(request: Request, call_next):
    """Sprint 15 P0-B: Return 504 instead of letting clients hang forever.
    CTO directive: 120s wait = system dead. Return error fast."""
    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)

    is_heavy = any(p in path for p in _HEAVY_PATTERNS)
    timeout = _TIMEOUT_HEAVY if is_heavy else _TIMEOUT_DEFAULT

    try:
        return await asyncio.wait_for(call_next(request), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"API timeout ({timeout}s): {request.method} {path}")
        return JSONResponse(
            status_code=504,
            content={
                "error": True,
                "error_code": "TIMEOUT",
                "message": f"伺服器回應超時 ({timeout:.0f}s)。此股票可能尚未被快取，將於今晚 20:00 排程計算。",
                "path": path,
                "timeout_s": timeout,
            },
        )


# R49-3: API Performance Monitoring Middleware
_perf_lock = Lock()
_perf_log: deque = deque(maxlen=500)  # Last 500 requests
_slow_threshold_ms = 2000  # Log warning for requests > 2s


@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    """Record request timing for all API endpoints."""
    start = time.time()
    response = await call_next(request)
    elapsed_ms = (time.time() - start) * 1000

    path = request.url.path
    if path.startswith("/api/"):
        entry = {
            "path": path,
            "method": request.method,
            "status": response.status_code,
            "elapsed_ms": round(elapsed_ms, 1),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with _perf_lock:
            _perf_log.append(entry)

        if elapsed_ms > _slow_threshold_ms:
            logger.warning(f"Slow API: {request.method} {path} took {elapsed_ms:.0f}ms")

        # Add timing header
        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"

    return response


def get_api_performance_stats() -> dict:
    """Get API performance statistics for the monitoring endpoint."""
    with _perf_lock:
        entries = list(_perf_log)

    if not entries:
        return {"total_requests": 0, "endpoints": []}

    # Group by path
    from collections import defaultdict
    by_path: dict = defaultdict(list)
    for e in entries:
        by_path[e["path"]].append(e["elapsed_ms"])

    endpoints = []
    for path, times in sorted(by_path.items()):
        import numpy as np
        arr = np.array(times)
        endpoints.append({
            "path": path,
            "count": len(times),
            "avg_ms": round(float(arr.mean()), 1),
            "p50_ms": round(float(np.median(arr)), 1),
            "p95_ms": round(float(np.percentile(arr, 95)), 1),
            "max_ms": round(float(arr.max()), 1),
            "slow_count": int((arr > _slow_threshold_ms).sum()),
        })

    endpoints.sort(key=lambda x: x["avg_ms"], reverse=True)

    return {
        "total_requests": len(entries),
        "window_start": entries[0]["timestamp"] if entries else None,
        "window_end": entries[-1]["timestamp"] if entries else None,
        "slow_threshold_ms": _slow_threshold_ms,
        "endpoints": endpoints,
    }


# CORS — 從環境變數讀取，開發模式預設允許 Vite dev server
from backend.config import CORS_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 掛載路由
app.include_router(stocks.router, prefix="/api/stocks", tags=["stocks"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["backtest"])
app.include_router(report.router, prefix="/api/report", tags=["report"])
app.include_router(recommend.router, prefix="/api/recommend", tags=["recommend"])
app.include_router(screener.router, prefix="/api/screener", tags=["screener"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])
app.include_router(system.router, prefix="/api/system", tags=["system"])
app.include_router(configs.router, prefix="/api/configs", tags=["configs"])
app.include_router(bt_results.router, prefix="/api/backtest-results", tags=["backtest-results"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["alerts"])
app.include_router(sqs_performance.router, prefix="/api/sqs-performance", tags=["sqs-performance"])
app.include_router(risk.router, prefix="/api/risk", tags=["risk"])
app.include_router(strategies.router, prefix="/api/strategies", tags=["strategies"])
app.include_router(cluster.router, prefix="/api/cluster", tags=["cluster"])

# R55-1: WebSocket + market data REST endpoints (no prefix — ws routes are top-level)
app.include_router(ws.router, tags=["websocket"])

# Production: 伺服 Vue build 靜態檔
DIST_DIR = PROJECT_ROOT / "frontend" / "dist"
if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="static")

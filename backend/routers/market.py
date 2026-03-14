"""Market regime & sector heat routes.

Split from analysis.py — market-regime, market-regime-ml, sector-heat endpoints.
"""

import threading
import time
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
import logging

from data.cache import get_cached_sector_heat, set_cached_sector_heat

logger = logging.getLogger(__name__)

router = APIRouter()

# Background scan guard — prevents duplicate concurrent scans
_bg_scan_running = False
_bg_scan_start: float = 0.0
_bg_scan_lock = threading.Lock()
_BG_SCAN_TIMEOUT = 600  # 10 minutes — auto-reset if scan hangs


def _do_background_scan():
    """Run the full sector heat scan in a background thread.

    Delegates to worker.scan_sector_heat() which already has the complete
    scanning logic (momentum, maturity transitions, leader detection, etc.).
    Falls back to a minimal inline scan if the worker module is unavailable.
    """
    global _bg_scan_running
    try:
        from backend.worker import scan_sector_heat
        result = scan_sector_heat()
        set_cached_sector_heat(result)
        logger.info(
            f"Background sector heat scan complete: "
            f"{result['scanned']} stocks, {result['total_buy']} buys"
        )
    except Exception as e:
        logger.error(f"Background sector heat scan failed: {e}")
    finally:
        with _bg_scan_lock:
            _bg_scan_running = False


def _trigger_background_scan():
    """Start a background scan if one is not already running."""
    global _bg_scan_running, _bg_scan_start
    with _bg_scan_lock:
        if _bg_scan_running:
            # Auto-reset if scan has been running longer than timeout
            if (time.time() - _bg_scan_start) > _BG_SCAN_TIMEOUT:
                logger.warning(
                    "Background scan exceeded %ds timeout, auto-resetting",
                    _BG_SCAN_TIMEOUT,
                )
                _bg_scan_running = False
            else:
                logger.info("Background sector heat scan already in progress, skipping")
                return
        _bg_scan_running = True
        _bg_scan_start = time.time()

    thread = threading.Thread(target=_do_background_scan, daemon=True)
    thread.start()


@router.get("/market-regime")
def get_market_regime():
    """Detect current market environment"""
    from data.fetcher import get_taiex_data
    from analysis.indicators import calculate_all_indicators
    import numpy as np
    try:
        df = get_taiex_data(period_days=365)
        if df.empty:
            return {"regime": "unknown", "detail": ""}
        indicators = calculate_all_indicators(df)
        latest = indicators.iloc[-1]
        ma20 = latest.get("ma20", np.nan)
        ma60 = latest.get("ma60", np.nan)
        rsi = latest.get("rsi", 50)

        if ma20 > ma60 and rsi > 50:
            regime = "bull"
        elif ma20 < ma60 and rsi < 50:
            regime = "bear"
        else:
            regime = "sideways"

        return {
            "regime": regime,
            "taiex_close": float(latest["close"]),
            "ma20": float(ma20) if not np.isnan(ma20) else None,
            "ma60": float(ma60) if not np.isnan(ma60) else None,
            "rsi": float(rsi) if not np.isnan(rsi) else None,
        }
    except Exception as e:
        logger.debug(f"Operation failed, returning default: {e}")
        return {"regime": "unknown"}


@router.get("/market-regime-ml")
def get_market_regime_ml():
    """R50-3: ML-enhanced market regime classification

    Uses multi-indicator features (ADX, ATR%, RSI, MACD, MA crossover, volume trend)
    for 6-regime classification with confidence scores and strategy recommendations.
    """
    from data.fetcher import get_stock_data
    from backend.regime_classifier import classify_market_regime
    from backend.dependencies import make_serializable
    import numpy as np

    try:
        # Use 0050.TW as proxy for Taiwan market
        df = get_stock_data("0050", period_days=250)
        if df is None or len(df) < 60:
            return make_serializable({"regime": "unknown", "error": "數據不足"})

        result = classify_market_regime(
            close=df["close"].values,
            high=df["high"].values,
            low=df["low"].values,
            volume=df["volume"].values,
        )
        return make_serializable(result)
    except Exception as e:
        return {"regime": "unknown", "error": str(e)}


@router.get("/sector-heat")
def get_sector_heat(force_refresh: bool = False):
    """Sector heat analysis (Gemini R21 P1: Sector Rotation Monitor)

    Reads worker-cached data. On cache miss, triggers a background scan
    and returns 503. On force_refresh, triggers background scan and returns 202.
    """
    # 1. force_refresh: trigger background scan, return 202 immediately
    if force_refresh:
        _trigger_background_scan()
        return JSONResponse(
            status_code=202,
            content={
                "message": "Sector heat refresh triggered. Data will be available shortly.",
            },
        )

    # 2. Try cache (worker-populated or previous background scan)
    cached = get_cached_sector_heat()
    if cached:
        return cached

    # 3. Cache miss (cold start): trigger background scan, return 503
    _trigger_background_scan()
    raise HTTPException(
        status_code=503,
        detail=(
            "Sector heat data is being calculated. "
            "Please retry in 1-2 minutes."
        ),
    )

"""Market regime & sector heat routes.

Split from analysis.py — market-regime, market-regime-ml, sector-heat endpoints.
"""

from fastapi import APIRouter, HTTPException
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


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

    Reads worker-cached data first, falls back to live computation.
    ?force_refresh=true to force live recomputation.
    """
    from data.cache import get_cached_sector_heat, set_cached_sector_heat
    from backend.dependencies import make_serializable

    # 1. Try Redis cache first (worker-populated)
    if not force_refresh:
        cached = get_cached_sector_heat()
        if cached:
            return cached

    # 2. Fallback: live computation (same logic as worker)
    from concurrent.futures import ThreadPoolExecutor
    from config import SCAN_STOCKS
    from data.fetcher import get_stock_data
    from analysis.strategy_v4 import get_v4_analysis
    from data.sector_mapping import get_stock_sector

    MATURITY_WEIGHTS = {
        "Speculative Spike": 1.0,
        "Trend Formation": 1.5,
        "Structural Shift": 2.0,
    }

    def _scan_stock(code):
        try:
            df = get_stock_data(code, period_days=120)
            v4 = get_v4_analysis(df)
            sector = get_stock_sector(code, level=1)
            return {
                "code": code,
                "name": SCAN_STOCKS.get(code, code),
                "sector": sector,
                "signal": v4["signal"],
                "signal_maturity": v4.get("signal_maturity", "N/A"),
                "uptrend_days": v4.get("uptrend_days", 0),
            }
        except Exception as e:
            logger.debug(f"Data fetch failed, returning default: {e}")
            return None

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(_scan_stock, list(SCAN_STOCKS.keys())))

    valid = [r for r in results if r is not None]

    sectors: dict[str, list] = {}
    for s in valid:
        sec = s["sector"]
        sectors.setdefault(sec, []).append(s)

    heat_data = []
    for sector, stocks in sectors.items():
        total = len(stocks)
        buy_stocks = [s for s in stocks if s["signal"] == "BUY"]
        buy_count = len(buy_stocks)
        heat = buy_count / total if total > 0 else 0

        weighted_sum = sum(MATURITY_WEIGHTS.get(s["signal_maturity"], 1.0) for s in buy_stocks)
        weighted_heat = weighted_sum / total if total > 0 else 0

        heat_data.append({
            "sector": sector,
            "total": total,
            "buy_count": buy_count,
            "heat": round(heat, 3),
            "weighted_heat": round(weighted_heat, 3),
            "buy_stocks": [{"code": s["code"], "name": s["name"], "maturity": s["signal_maturity"]} for s in buy_stocks],
            "all_stocks": [s["code"] for s in stocks],
        })

    heat_data.sort(key=lambda x: x["weighted_heat"], reverse=True)

    result = {
        "sectors": heat_data,
        "scanned": len(valid),
        "total_buy": sum(h["buy_count"] for h in heat_data),
    }

    # Cache the live result for subsequent requests
    set_cached_sector_heat(result)

    return make_serializable(result)

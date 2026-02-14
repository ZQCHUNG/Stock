"""技術分析路由"""

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/{code}/indicators")
def get_indicators(code: str, period_days: int = 365, tail: int = Query(120, ge=10, le=1000)):
    """計算所有技術指標"""
    from data.fetcher import get_stock_data
    from analysis.indicators import calculate_all_indicators
    from backend.dependencies import df_to_response
    try:
        df = get_stock_data(code, period_days=period_days)
        result = calculate_all_indicators(df)
        return df_to_response(result, tail=tail)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{code}/v4-signal")
def get_v4_signal(code: str, period_days: int = 365):
    """取得最新 v4 分析結果"""
    from data.fetcher import get_stock_data
    from analysis.strategy_v4 import get_v4_analysis
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=period_days)
        result = get_v4_analysis(df)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{code}/v4-enhanced")
def get_v4_enhanced(code: str, period_days: int = 365):
    """取得 v4 增強分析（含法人 Gatekeeper + 信心分數）"""
    from data.fetcher import get_stock_data, get_institutional_data
    from analysis.strategy_v4 import get_v4_enhanced_analysis
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=period_days)
        try:
            inst_df = get_institutional_data(code, days=10)
        except Exception:
            inst_df = None
        result = get_v4_enhanced_analysis(df, inst_df=inst_df)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{code}/v4-signals-full")
def get_v4_signals_full(code: str, period_days: int = 365, tail: int = Query(120, ge=10, le=500)):
    """取得完整 v4 訊號序列（含所有指標）"""
    from data.fetcher import get_stock_data
    from analysis.strategy_v4 import generate_v4_signals
    from backend.dependencies import df_to_response
    try:
        df = get_stock_data(code, period_days=period_days)
        signals_df = generate_v4_signals(df)
        return df_to_response(signals_df, tail=tail)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{code}/support-resistance")
def get_support_resistance(code: str, period_days: int = 365):
    """計算支撐壓力位"""
    from data.fetcher import get_stock_data
    from analysis.indicators import calculate_all_indicators
    from analysis.report.technical import _detect_swing_points, _calculate_support_resistance
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=period_days)
        indicators = calculate_all_indicators(df)
        indicators["ma120"] = indicators["close"].rolling(120).mean()
        indicators["ma240"] = indicators["close"].rolling(240).mean()
        current_price = float(indicators["close"].iloc[-1])
        swings = _detect_swing_points(indicators)
        supports, resistances = _calculate_support_resistance(indicators, swings, current_price)
        return make_serializable({
            "current_price": current_price,
            "supports": [{"price": s.price, "source": s.source, "strength": s.strength} for s in supports],
            "resistances": [{"price": r.price, "source": r.source, "strength": r.strength} for r in resistances],
        })
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{code}/volume-patterns")
def get_volume_patterns(code: str, period_days: int = 365):
    """量能型態偵測"""
    from data.fetcher import get_stock_data
    from analysis.volume_pattern import get_volume_pattern_summary
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=period_days)
        result = get_volume_pattern_summary(df)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/market-regime")
def get_market_regime():
    """偵測當前大盤環境"""
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
    except Exception:
        return {"regime": "unknown"}

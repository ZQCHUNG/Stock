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


@router.get("/sector-heat")
def get_sector_heat():
    """產業熱度分析（Gemini R21 P1: Sector Rotation Monitor）

    掃描 SCAN_STOCKS 池，計算每個產業的 V4 訊號密度。
    """
    from concurrent.futures import ThreadPoolExecutor
    from config import SCAN_STOCKS
    from data.fetcher import get_stock_data, get_stock_info
    from analysis.strategy_v4 import get_v4_analysis
    from backend.dependencies import make_serializable

    MATURITY_SCORES = {
        "Speculative Spike": 1,
        "Trend Formation": 2,
        "Structural Shift": 3,
    }

    def _scan_stock(code):
        try:
            df = get_stock_data(code, period_days=120)
            v4 = get_v4_analysis(df)
            try:
                info = get_stock_info(code)
                sector = info.get("sector", "")
            except Exception:
                sector = ""
            return {
                "code": code,
                "name": SCAN_STOCKS.get(code, code),
                "sector": sector or "未分類",
                "signal": v4["signal"],
                "signal_maturity": v4.get("signal_maturity", "N/A"),
                "uptrend_days": v4.get("uptrend_days", 0),
            }
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(_scan_stock, list(SCAN_STOCKS.keys())))

    valid = [r for r in results if r is not None]

    # Group by sector
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

        # Average maturity score for BUY stocks
        maturity_scores = [MATURITY_SCORES.get(s["signal_maturity"], 0) for s in buy_stocks]
        avg_maturity = sum(maturity_scores) / len(maturity_scores) if maturity_scores else 0

        heat_data.append({
            "sector": sector,
            "total": total,
            "buy_count": buy_count,
            "heat": round(heat, 3),
            "avg_maturity_score": round(avg_maturity, 2),
            "buy_stocks": [{"code": s["code"], "name": s["name"], "maturity": s["signal_maturity"]} for s in buy_stocks],
            "all_stocks": [s["code"] for s in stocks],
        })

    heat_data.sort(key=lambda x: x["heat"], reverse=True)

    return make_serializable({
        "sectors": heat_data,
        "scanned": len(valid),
        "total_buy": sum(h["buy_count"] for h in heat_data),
    })


@router.get("/{code}/risk-factors")
def get_risk_factors(code: str, period_days: int = 365):
    """取得部位風險因子（Position Calculator 用）

    返回 is_biotech, cash_runway, institutional_visibility, avg_volume 等
    用於計算 Liquidity_Factor。
    """
    from concurrent.futures import ThreadPoolExecutor
    from data.fetcher import (
        get_stock_data, get_stock_info_and_fundamentals,
        get_institutional_data, get_financial_statements,
    )
    from analysis.report.recommendation import (
        _is_biotech_industry, _calculate_institutional_score,
    )
    from backend.dependencies import make_serializable
    import numpy as np

    try:
        # 並行取得所有需要的資料
        with ThreadPoolExecutor(max_workers=4) as executor:
            fut_data = executor.submit(get_stock_data, code, period_days=period_days)
            fut_info = executor.submit(get_stock_info_and_fundamentals, code)
            fut_inst = executor.submit(get_institutional_data, code, days=20)
            fut_fin = executor.submit(get_financial_statements, code)

            df = fut_data.result()
            try:
                company_info, _ = fut_info.result()
            except Exception:
                company_info = {"industry": "", "sector": ""}
            try:
                inst_df = fut_inst.result()
            except Exception:
                inst_df = None
            try:
                fin_data = fut_fin.result()
            except Exception:
                fin_data = None

        # 計算風險因子
        is_biotech = _is_biotech_industry(
            company_info.get("industry", ""),
            company_info.get("sector", ""),
        )
        inst_result = _calculate_institutional_score(inst_df)
        cash_runway = fin_data.get("cash_runway") if fin_data else None

        # 20 日平均成交量（股）
        avg_volume_20d = float(df["volume"].tail(20).mean()) if len(df) >= 20 else 0

        # 計算 Liquidity Factor
        liquidity_factor = 1.0
        warnings = []

        if is_biotech:
            liquidity_factor *= 0.5
            warnings.append("生技股：部位 ×0.5")

        if cash_runway is not None:
            op_runway = cash_runway.get("runway_quarters", 99)
            total_runway = cash_runway.get("total_runway_quarters", 99)
            # 生技股：最嚴格，取 min(op, total)
            # 非生技：只看營業現金流（投資支出不算核心損耗）
            eff_runway = min(op_runway, total_runway) if is_biotech else op_runway

            if eff_runway < 4:
                liquidity_factor *= 0.25
                warnings.append(f"現金跑道 {eff_runway:.1f} 季（<4）：部位 ×0.25")
            elif eff_runway < 8:
                liquidity_factor *= 0.5
                warnings.append(f"現金跑道 {eff_runway:.1f} 季（<8）：部位 ×0.5")

            # 非生技的 Total Runway 警告（Capital Strain，不觸發 hard gatekeeper）
            if not is_biotech and total_runway < 8:
                warnings.append(f"資本支出壓力：總跑道 {total_runway:.1f} 季（僅提示）")

        if inst_result.get("visibility") == "ghost_town":
            liquidity_factor = 0
            warnings.append("零法人交易（Ghost Town）：建議不持有")
        elif avg_volume_20d < 500_000:
            # 500K 股 = 500 張，低於此線性遞減
            vol_factor = max(0.1, avg_volume_20d / 500_000)
            liquidity_factor *= vol_factor
            warnings.append(f"成交量偏低（{avg_volume_20d/1000:.0f}張/日）：部位 ×{vol_factor:.2f}")

        current_price = float(df["close"].iloc[-1])

        return make_serializable({
            "is_biotech": is_biotech,
            "cash_runway": cash_runway,
            "institutional": inst_result,
            "avg_volume_20d": avg_volume_20d,
            "liquidity_factor": round(liquidity_factor, 4),
            "warnings": warnings,
            "current_price": current_price,
            "industry": company_info.get("industry", ""),
            "sector": company_info.get("sector", ""),
        })
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

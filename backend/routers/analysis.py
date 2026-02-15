"""技術分析路由"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


# Pydantic models for request validation (Gemini R44)
class SqsStockItem(BaseModel):
    code: str = Field(..., min_length=4, max_length=6)
    strategy: str = Field(default="V4", pattern="^(V4|V5|Adaptive)$")
    maturity: str = "N/A"


class BatchSqsRequest(BaseModel):
    stocks: list[SqsStockItem] = Field(..., min_length=1, max_length=200)


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


@router.get("/{code}/v5-signal")
def get_v5_signal(code: str, period_days: int = 365):
    """取得最新 V5 均值回歸分析結果（Gemini R36）"""
    from data.fetcher import get_stock_data
    from analysis.strategy_v5 import get_v5_analysis
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=period_days)
        result = get_v5_analysis(df)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{code}/bold-signal")
def get_bold_signal(code: str, period_days: int = 1095):
    """取得最新 Bold 大膽策略分析結果

    Bold 策略偵測：能量擠壓突破 + 量能爬坡（小型股發現）
    """
    from data.fetcher import get_stock_data
    from analysis.strategy_bold import get_bold_analysis
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=period_days)
        result = get_bold_analysis(df)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{code}/adaptive-signal")
def get_adaptive_signal(code: str, period_days: int = 365):
    """V4+V5 自適應混合訊號（Gemini R36）

    根據市場狀態動態分配 V4/V5 權重，回傳混合評分。
    """
    from data.fetcher import get_stock_data
    from analysis.strategy_v4 import get_v4_analysis
    from analysis.strategy_v5 import get_v5_analysis, adaptive_strategy_score
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=period_days)
        v4 = get_v4_analysis(df)
        v5 = get_v5_analysis(df)

        # Get market regime from portfolio router (0050 ADX-based)
        try:
            from backend.routers.portfolio import get_market_regime
            regime_data = get_market_regime()
            regime_en = regime_data.get("regime_en", "range_quiet") if regime_data.get("has_data") else "range_quiet"
        except Exception:
            regime_en = "range_quiet"

        adaptive = adaptive_strategy_score(
            v4_signal=v4["signal"],
            v5_signal=v5["signal"],
            regime=regime_en,
            v4_confidence=1.0,
            v5_bias_confirmed=v5.get("bias_confirmed", False),
        )

        return make_serializable({
            "v4": v4,
            "v5": v5,
            "adaptive": adaptive,
        })
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{code}/risk-budget")
def get_risk_budget(code: str, period_days: int = 365):
    """V4/V5 多策略風險預算（Gemini R37: MultiStrategyBouncer）

    偵測 V4/V5 訊號衝突 + 曝險上限建議。
    """
    from data.fetcher import get_stock_data
    from analysis.strategy_v4 import get_v4_analysis
    from analysis.strategy_v5 import get_v5_analysis
    from analysis.risk_budget import multi_strategy_bouncer
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=period_days)
        v4 = get_v4_analysis(df)
        v5 = get_v5_analysis(df)

        # Get market regime
        try:
            from backend.routers.portfolio import get_market_regime
            regime_data = get_market_regime()
            regime_en = regime_data.get("regime_en", "range_quiet") if regime_data.get("has_data") else "range_quiet"
        except Exception:
            regime_en = "range_quiet"

        # Get Kelly from portfolio optimal exposure (if available)
        kelly_half = 0.5
        try:
            from backend.routers.portfolio import get_optimal_exposure
            exposure_data = get_optimal_exposure()
            if exposure_data.get("has_data"):
                kelly_half = exposure_data.get("kelly_half", 0.5)
        except Exception:
            pass

        result = multi_strategy_bouncer(
            code=code,
            v4_signal=v4["signal"],
            v5_signal=v5["signal"],
            v4_confidence=v4.get("confidence_score", 1.0),
            kelly_half=kelly_half,
            current_exposure=0,  # No portfolio context for single-stock query
            regime=regime_en,
            v5_bias_confirmed=v5.get("bias_confirmed", False),
        )

        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/signal-tracker/record")
def record_signals(max_workers: int = 4):
    """記錄當日所有 BUY 信號（Gemini R39: Forward Testing）"""
    from analysis.signal_tracker import record_daily_signals
    from backend.dependencies import make_serializable
    try:
        result = record_daily_signals(max_workers=max_workers)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/signal-tracker/fill")
def fill_returns(lookback_days: int = 10):
    """回填信號的前瞻報酬率（1/3/5 日）"""
    from analysis.signal_tracker import fill_forward_returns
    from backend.dependencies import make_serializable
    try:
        result = fill_forward_returns(lookback_days=lookback_days)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signal-tracker/performance")
def signal_performance(days: int = 30, strategy: str = "", code: str = ""):
    """查詢信號前瞻績效"""
    from analysis.signal_tracker import get_signal_performance
    from backend.dependencies import make_serializable
    try:
        result = get_signal_performance(
            days=days,
            strategy=strategy or None,
            code=code or None,
        )
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signal-tracker/accuracy")
def signal_accuracy(days: int = 60):
    """取得各策略信號準確率摘要"""
    from analysis.signal_tracker import get_strategy_accuracy
    from backend.dependencies import make_serializable
    try:
        result = get_strategy_accuracy(days=days)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signal-tracker/decay")
def signal_decay(days: int = 90):
    """取得信號衰減曲線（Gemini R40→R41: 1/3/5/10/20 天）

    顯示信號發出後 1/3/5/10/20 日的平均報酬 + EV，揭示信號有效期。
    """
    from analysis.signal_tracker import get_signal_decay
    from backend.dependencies import make_serializable
    try:
        result = get_signal_decay(days=days)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signal-tracker/{code}/summary")
def signal_stock_summary(code: str, days: int = 180):
    """個股信號前瞻績效摘要（Gemini R41: TechnicalView overlay）

    回傳該股各策略的勝率、EV、平均報酬、近期信號。
    """
    from analysis.signal_tracker import get_stock_signal_summary
    from backend.dependencies import make_serializable
    try:
        result = get_stock_signal_summary(code, days=days)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/sqs")
def get_sqs(code: str):
    """取得個股 Signal Quality Score（Gemini R42）

    整合適配度、Regime、EV、板塊熱度、成熟度為 0-100 分。
    """
    from analysis.scoring import compute_sqs_for_signal
    from analysis.strategy_v4 import get_v4_analysis
    from data.fetcher import get_stock_data
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=365)
        v4 = get_v4_analysis(df)
        signal_strategy = "V4" if v4.get("signal") == "BUY" else "V4"
        maturity = v4.get("signal_maturity", "N/A")

        result = compute_sqs_for_signal(
            code=code,
            signal_strategy=signal_strategy,
            signal_maturity=maturity,
        )
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch-sqs")
def batch_sqs(payload: BatchSqsRequest):
    """批次計算 SQS（Gemini R42: Alpha Hunter SQS-Ledger）

    接收 [{"code": "2330", "strategy": "V4", "maturity": "Structural Shift"}, ...]
    回傳各股 SQS 分數。
    """
    from analysis.scoring import compute_sqs_for_signal
    from backend.dependencies import make_serializable
    try:
        stocks = payload.stocks
        results = {}
        for s in stocks:
            try:
                sqs = compute_sqs_for_signal(s.code, s.strategy, s.maturity)
                results[s.code] = sqs
            except Exception:
                results[s.code] = {"sqs": 50.0, "grade": "silver", "grade_label": "普通信號"}
        return make_serializable(results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sqs-distribution")
def get_sqs_distribution():
    """取得當前所有 BUY 信號的 SQS 分佈 + 自適應百分位等級（Gemini R43）"""
    from analysis.scoring import compute_sqs_for_signal, compute_sqs_distribution
    from backend.dependencies import make_serializable
    try:
        # Get current alpha hunter data for all BUY stocks
        from data.cache import get_cached_alpha_hunter
        alpha = get_cached_alpha_hunter()
        if not alpha or not alpha.get("sectors"):
            return {"count": 0, "error": "No alpha hunter data available"}

        all_stocks = []
        for sector in alpha["sectors"]:
            for stock in sector.get("stocks", []):
                all_stocks.append(stock)

        if not all_stocks:
            return {"count": 0, "error": "No BUY signals found"}

        # Compute SQS for each stock
        sqs_scores = []
        for s in all_stocks:
            try:
                sqs = compute_sqs_for_signal(
                    s["code"],
                    signal_strategy="V4",
                    signal_maturity=s.get("maturity", "N/A"),
                )
                sqs_scores.append(sqs)
            except Exception:
                pass

        result = compute_sqs_distribution(sqs_scores)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategy-fitness")
def get_strategy_fitness(codes: str = ""):
    """取得策略適配度標籤（Gemini R38: Strategy Fitness Engine）

    快速查詢 SQLite 中已預計算的 V4/V5/Adaptive 績效 + Fitness Tag。
    ?codes=2330,2317 → 過濾指定股票。空 = 全部。
    """
    from analysis.strategy_fitness import get_fitness_tags, get_fitness_summary
    from backend.dependencies import make_serializable
    try:
        code_list = [c.strip() for c in codes.split(",") if c.strip()] if codes else None
        tags = get_fitness_tags(code_list)
        summary = get_fitness_summary()
        return make_serializable({"stocks": tags, "summary": summary})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/strategy-fitness/scan")
def run_strategy_fitness_scan(period_days: int = 730, max_workers: int = 4):
    """啟動策略適配度掃描（Gemini R38）

    批次計算所有 SCAN_STOCKS 的 V4/V5/Adaptive 績效。
    注意：此操作耗時較長（~10-30 分鐘），建議背景執行。
    """
    from analysis.strategy_fitness import run_fitness_scan
    from backend.dependencies import make_serializable
    try:
        result = run_fitness_scan(period_days=period_days, max_workers=max_workers)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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


@router.get("/market-regime-ml")
def get_market_regime_ml():
    """R50-3: ML 增強市場情境分類

    使用多指標特徵（ADX, ATR%, RSI, MACD, MA 交叉, 成交量趨勢）
    進行 6 種市場情境分類，帶信心分數與策略建議。
    """
    from data.fetcher import get_stock_data
    from backend.ml_regime import classify_market_regime
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
    """產業熱度分析（Gemini R21 P1: Sector Rotation Monitor）

    優先讀取 Worker 快取的數據，無快取時 fallback 到即時計算。
    ?force_refresh=true 強制即時重算。
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
        except Exception:
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


def _calculate_confidence_multiplier(
    signal_maturity: str,
    sector_momentum: str,
    is_leader: bool,
    liquidity_factor: float,
    has_capital_strain: bool,
    sector_weighted_heat: float | None = None,
) -> tuple[float, list[str]]:
    """Calculate position confidence multiplier (Gemini R23, R24 adjusted).

    Returns (multiplier, breakdown_list).

    Base matrix: Maturity × Sector Momentum
    Modifiers: +0.2 Leader, ×LF, -0.1 Capital Strain, sector overheat decay
    Clamp to [0.1, 1.5], special case LF=0 → C=0

    R24 adjustments per Gemini CTO review:
    - SS+Surge: 0.8→0.6 (FOMO risk, first-week premium too high)
    - SS+Cooling: 0.3→0.1 (distribution trap / 無基之彈)
    - Structural+Heating: 1.1→1.2 (most stable alpha, deserve more aggression)
    - Clamp lower: 0.3→0.1 (allow near-zero for extreme risk)
    """
    # Base matrix: maturity → {momentum → base_score}
    MATRIX = {
        "Structural Shift": {"surge": 1.3, "heating": 1.2, "stable": 0.9, "cooling": 0.6},
        "Trend Formation": {"surge": 1.1, "heating": 0.9, "stable": 0.7, "cooling": 0.4},
        "Speculative Spike": {"surge": 0.6, "heating": 0.6, "stable": 0.4, "cooling": 0.1},
    }

    # Ghost Town override
    if liquidity_factor == 0:
        return 0.0, ["LF=0 (Ghost Town)：建議不持有"]

    breakdown = []

    # Base score from matrix
    maturity_row = MATRIX.get(signal_maturity, MATRIX["Speculative Spike"])
    base = maturity_row.get(sector_momentum, maturity_row.get("stable", 0.5))
    breakdown.append(f"基礎: {signal_maturity} × {sector_momentum} = {base:.1f}")

    score = base

    # Leader bonus
    if is_leader:
        score += 0.2
        breakdown.append("Leader +0.2")

    # Capital strain penalty
    if has_capital_strain:
        score -= 0.1
        breakdown.append("資本壓力 -0.1")

    # Apply liquidity factor
    if liquidity_factor < 1.0:
        score *= liquidity_factor
        breakdown.append(f"LF ×{liquidity_factor:.2f}")

    # Sector overheat decay (Gemini R24: crowded trade warning)
    if sector_weighted_heat is not None and sector_weighted_heat > 0.8:
        decay = max(0.7, 1.0 - (sector_weighted_heat - 0.8) * 1.5)
        score *= decay
        breakdown.append(f"板塊過熱衰減 ×{decay:.2f} (Hw={sector_weighted_heat:.2f})")

    # Clamp (R24: lower bound 0.1 to allow near-zero for extreme risk)
    score = max(0.1, min(1.5, score))
    breakdown.append(f"最終: {score:.2f}")

    return round(score, 2), breakdown


def _get_stock_sector_context(code: str) -> dict:
    """Get sector momentum and leader status from cached sector heat data."""
    from data.cache import get_cached_sector_heat
    from data.sector_mapping import get_stock_sector

    result = {
        "sector_momentum": "stable",
        "is_leader": False,
        "sector_l1": "未分類",
        "sector_weighted_heat": None,
    }

    sector_l1 = get_stock_sector(code, level=1)
    result["sector_l1"] = sector_l1

    cached = get_cached_sector_heat()
    if not cached:
        return result

    sectors = cached.get("sectors", [])
    for sec in sectors:
        if sec.get("sector") != sector_l1:
            continue
        result["sector_momentum"] = sec.get("momentum", "stable")
        result["sector_weighted_heat"] = sec.get("weighted_heat")
        leader = sec.get("leader")
        if leader and leader.get("code") == code:
            result["is_leader"] = True
        break

    return result


@router.get("/{code}/risk-factors")
def get_risk_factors(code: str, period_days: int = 365):
    """取得部位風險因子（Position Calculator 用）

    返回 is_biotech, cash_runway, institutional_visibility, avg_volume,
    liquidity_factor, confidence_multiplier 等。
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

        # Dynamic exit: ATR-based trailing stop (Gemini R24)
        atr_14 = None
        trailing_stop_price = None
        highest_close_20d = None
        if len(df) >= 15:
            high = df["high"]
            low = df["low"]
            close = df["close"]
            tr = (high - low).combine(abs(high - close.shift(1)), max).combine(abs(low - close.shift(1)), max)
            atr_14 = float(tr.tail(14).mean())
            highest_close_20d = float(close.tail(20).max())
            # Trailing: max(static SL, highest_close - 2×ATR)
            trailing_candidate = highest_close_20d - 2 * atr_14
            # Will finalize after stop_loss_price is set

        # V4 signal for maturity info
        from analysis.strategy_v4 import get_v4_analysis
        try:
            v4 = get_v4_analysis(df)
            signal_maturity = v4.get("signal_maturity", "N/A")
            v4_signal = v4.get("signal", "HOLD")
            stop_loss_price = v4.get("stop_loss_price")
        except Exception:
            signal_maturity = "N/A"
            v4_signal = "HOLD"
            stop_loss_price = None

        # Default stop loss from V4 or calculate from config
        if stop_loss_price is None:
            from config import DEFAULT_V4_CONFIG
            stop_loss_price = round(current_price * (1 - DEFAULT_V4_CONFIG.stop_loss_pct), 2)

        # Finalize trailing stop
        if atr_14 is not None and highest_close_20d is not None:
            trailing_candidate = highest_close_20d - 2 * atr_14
            trailing_stop_price = round(max(stop_loss_price, trailing_candidate), 2)

        # Sector context (momentum, leader status)
        sector_ctx = _get_stock_sector_context(code)

        # Capital strain flag
        has_capital_strain = False
        if not is_biotech and cash_runway is not None:
            total_runway = cash_runway.get("total_runway_quarters", 99)
            if total_runway < 8:
                has_capital_strain = True

        # Confidence multiplier
        conf_mult, conf_breakdown = _calculate_confidence_multiplier(
            signal_maturity=signal_maturity,
            sector_momentum=sector_ctx["sector_momentum"],
            is_leader=sector_ctx["is_leader"],
            liquidity_factor=round(liquidity_factor, 4),
            has_capital_strain=has_capital_strain,
            sector_weighted_heat=sector_ctx.get("sector_weighted_heat"),
        )

        return make_serializable({
            "is_biotech": is_biotech,
            "cash_runway": cash_runway,
            "institutional": inst_result,
            "avg_volume_20d": avg_volume_20d,
            "liquidity_factor": round(liquidity_factor, 4),
            "warnings": warnings,
            "current_price": current_price,
            "stop_loss_price": stop_loss_price,
            "v4_signal": v4_signal,
            "signal_maturity": signal_maturity,
            "sector_l1": sector_ctx["sector_l1"],
            "sector_momentum": sector_ctx["sector_momentum"],
            "is_leader": sector_ctx["is_leader"],
            "confidence_multiplier": conf_mult,
            "confidence_breakdown": conf_breakdown,
            "industry": company_info.get("industry", ""),
            "sector": company_info.get("sector", ""),
            # Dynamic exit (Gemini R24)
            "atr_14": round(atr_14, 2) if atr_14 is not None else None,
            "highest_close_20d": highest_close_20d,
            "trailing_stop_price": trailing_stop_price,
        })
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{code}/corporate-actions")
def get_corporate_actions(code: str, period_days: int = 365):
    """R58: 偵測企業行為事件（除權息、分割、漲跌停、暫停交易）"""
    from data.fetcher import get_stock_data, get_dividend_data, get_splits_data
    from data.corporate_actions import detect_corporate_actions

    try:
        df = get_stock_data(code, period_days=period_days)
        dividends = get_dividend_data(code)
        splits = get_splits_data(code)
        report = detect_corporate_actions(
            stock_code=code,
            df=df,
            dividends=dividends,
            splits=splits,
        )
        return report.summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/valuation")
def get_valuation(code: str):
    """R62: 取得個股估值資料 (PE/PB/殖利率) — TWSE BWIBBU_d

    Returns:
        pe, pb, dividend_yield, valuation_score (0-100)
    """
    from data.twse_scraper import get_stock_valuation, compute_valuation_score
    try:
        val = get_stock_valuation(code)
        if not val:
            return {"code": code, "available": False, "reason": "No valuation data"}

        score = compute_valuation_score(
            val.get("pe"), val.get("pb"), val.get("dividend_yield")
        )
        return {
            "code": code,
            "available": True,
            "pe": val.get("pe"),
            "pb": val.get("pb"),
            "dividend_yield": val.get("dividend_yield"),
            "close": val.get("close"),
            "valuation_score": round(score, 1),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/revenue")
def get_revenue(code: str, months: int = Query(default=12, ge=1, le=36)):
    """R62: 取得個股月營收資料 — 公開資訊觀測站 MOPS

    Returns:
        Monthly revenue data with YoY growth rate
    """
    from data.twse_scraper import get_stock_revenue, compute_growth_score
    from backend.dependencies import make_serializable
    try:
        df = get_stock_revenue(code, months=months)
        if df is None or df.empty:
            return {"code": code, "available": False, "data": []}

        latest_yoy = df.iloc[-1].get("revenue_yoy") if not df.empty else None
        growth_score = compute_growth_score(latest_yoy)

        return make_serializable({
            "code": code,
            "available": True,
            "growth_score": round(growth_score, 1),
            "latest_revenue_yoy": latest_yoy,
            "data": df.to_dict(orient="records"),
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# R64: 相似線型匹配 (Pattern Matching via DTW)
# ============================================================

@router.get("/{code}/similar-stocks")
def find_similar_stocks(
    code: str,
    window: int = Query(20, ge=5, le=120, description="比對天數 (20=月線, 60=季線)"),
    top_n: int = Query(10, ge=1, le=50),
    candidate_codes: str | None = Query(None, description="指定比對股票 (逗號分隔)"),
):
    """找出與目標股票近期走勢相似的股票 (DTW 演算法)"""
    from analysis.pattern_matcher import find_similar_stocks as _find
    try:
        codes = candidate_codes.split(",") if candidate_codes else None
        results = _find(code, window=window, top_n=top_n, candidate_codes=codes)
        return {"code": code, "window": window, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/similar-history")
def find_similar_in_history(
    code: str,
    window: int = Query(20, ge=5, le=120),
    search_code: str | None = Query(None, description="搜尋目標股票 (預設=自身歷史)"),
    lookback_days: int = Query(365, ge=60, le=1825),
):
    """在歷史中找出類似的線型區段 + 之後走勢"""
    from analysis.pattern_matcher import find_similar_pattern_in_history as _find
    try:
        results = _find(code, window=window, search_code=search_code,
                        lookback_days=lookback_days)
        return {"code": code, "window": window, "search_code": search_code or code,
                "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

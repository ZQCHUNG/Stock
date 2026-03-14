"""Technical analysis routes — core signal generation, indicators, fundamentals.

Endpoints for V4/V5/Bold/Adaptive signals, indicators, support-resistance,
valuation, revenue, liquidity, corporate actions, VCP, accumulation,
RS rankings, bold-status, sector-context, volume-patterns.

Signal tracking, pattern matching, risk calculation, and market regime
endpoints have been split into separate routers:
- signals.py: signal-tracker/*, sqs, batch-sqs, sqs-distribution, strategy-fitness
- patterns.py: similar-stocks, similar-history, winner-dna-match, pattern-library, super-stock-flag
- risk_calc.py: risk-factors, risk-budget, stop-levels, sizing-advisor, trail-classifier
- market.py: market-regime, market-regime-ml, sector-heat
"""

from fastapi import APIRouter, HTTPException, Query
from backend.dependencies import raise_stock_data_error as _raise_stock_data_error
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{code}/indicators")
def get_indicators(code: str, period_days: int = 365, tail: int = Query(120, ge=10, le=1000)):
    """Calculate all technical indicators"""
    from data.fetcher import get_stock_data
    from analysis.indicators import calculate_all_indicators
    from backend.dependencies import df_to_response
    try:
        df = get_stock_data(code, period_days=period_days)
        result = calculate_all_indicators(df)
        return df_to_response(result, tail=tail)
    except Exception as e:
        _raise_stock_data_error(code, e)


@router.get("/{code}/v4-signal")
def get_v4_signal(code: str, period_days: int = 365):
    """Get latest v4 analysis result"""
    from data.fetcher import get_stock_data
    from analysis.strategy_v4 import get_v4_analysis
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=period_days)
        result = get_v4_analysis(df)
        return make_serializable(result)
    except Exception as e:
        _raise_stock_data_error(code, e)


@router.get("/{code}/v4-enhanced")
def get_v4_enhanced(code: str, period_days: int = 365):
    """Get v4 enhanced analysis (with institutional gatekeeper + confidence score)"""
    from data.fetcher import get_stock_data, get_institutional_data
    from analysis.strategy_v4 import get_v4_enhanced_analysis
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=period_days)
        try:
            inst_df = get_institutional_data(code, days=10)
        except Exception as e:
            logger.debug(f"Optional operation failed: {e}")
            inst_df = None
        result = get_v4_enhanced_analysis(df, inst_df=inst_df)
        return make_serializable(result)
    except Exception as e:
        _raise_stock_data_error(code, e)


@router.get("/{code}/v4-signals-full")
def get_v4_signals_full(code: str, period_days: int = 365, tail: int = Query(120, ge=10, le=500)):
    """Get full v4 signal sequence (with all indicators)"""
    from data.fetcher import get_stock_data
    from analysis.strategy_v4 import generate_v4_signals
    from backend.dependencies import df_to_response
    try:
        df = get_stock_data(code, period_days=period_days)
        signals_df = generate_v4_signals(df)
        return df_to_response(signals_df, tail=tail)
    except Exception as e:
        _raise_stock_data_error(code, e)


@router.get("/{code}/support-resistance")
def get_support_resistance(code: str, period_days: int = 365):
    """Calculate support and resistance levels"""
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
        _raise_stock_data_error(code, e)


@router.get("/{code}/v5-signal")
def get_v5_signal(code: str, period_days: int = 365):
    """Get latest V5 mean reversion analysis result (Gemini R36)"""
    from data.fetcher import get_stock_data
    from analysis.strategy_v5 import get_v5_analysis
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=period_days)
        result = get_v5_analysis(df)
        return make_serializable(result)
    except Exception as e:
        _raise_stock_data_error(code, e)


@router.get("/{code}/bold-signal")
def get_bold_signal(code: str, period_days: int = 1095):
    """Get latest Bold strategy analysis result

    Bold strategy detects: squeeze breakout + volume ramp (small-cap discovery)
    """
    from data.fetcher import get_stock_data
    from analysis.strategy_bold import get_bold_analysis
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=period_days)
        result = get_bold_analysis(df)
        return make_serializable(result)
    except Exception as e:
        _raise_stock_data_error(code, e)


@router.get("/{code}/rs-rating")
def get_rs_rating(code: str, period_days: int = 400):
    """Get individual stock Weighted RS Rating (R63)

    Calculates 120-day weighted relative strength, needs full market scan for percentile.
    Single query only returns raw RS ratio + market ranking (if cached).
    """
    from data.fetcher import get_stock_data
    from analysis.strategy_bold import compute_rs_ratio, STRATEGY_BOLD_PARAMS
    import json
    import os

    try:
        df = get_stock_data(code, period_days=period_days)
        p = STRATEGY_BOLD_PARAMS
        rs_ratio = compute_rs_ratio(
            df,
            lookback=p.get("rs_lookback", 120),
            exclude_recent=p.get("rs_exclude_recent", 5),
            base_weight=p.get("rs_base_weight", 0.6),
            recent_weight=p.get("rs_recent_weight", 0.4),
            recent_days=p.get("rs_recent_days", 20),
        )

        # Try to find percentile from cached full market rankings
        rs_rating = None
        grade = "unknown"
        rs_path = os.path.join("data", "rs_ranking.json")
        if os.path.exists(rs_path):
            with open(rs_path, encoding="utf-8") as f:
                rankings = json.load(f)
            for r in rankings.get("rankings", []):
                if r["code"] == code:
                    rs_rating = r["rs_rating"]
                    break

        if rs_rating is not None:
            if rs_rating >= 80:
                grade = "Diamond"
            elif rs_rating >= 60:
                grade = "Gold"
            elif rs_rating >= 40:
                grade = "Silver"
            else:
                grade = "Noise"

        return {
            "code": code,
            "rs_ratio": round(rs_ratio, 4) if rs_ratio else None,
            "rs_rating": rs_rating,
            "grade": grade,
            "params": {
                "lookback": p.get("rs_lookback", 120),
                "exclude_recent": p.get("rs_exclude_recent", 5),
                "base_weight": p.get("rs_base_weight", 0.6),
                "recent_weight": p.get("rs_recent_weight", 0.4),
            },
        }
    except Exception as e:
        _raise_stock_data_error(code, e)


@router.get("/{code}/liquidity")
def get_liquidity(code: str, period_days: int = 365,
                  position_ntd: float = 1_000_000):
    """Calculate liquidity risk score (R69)

    3-dimension scoring: DTL days-to-liquidate + Spread + ADV Ratio.
    """
    from data.fetcher import get_stock_data
    from analysis.liquidity import calculate_liquidity_score
    try:
        df = get_stock_data(code, period_days=period_days)
        result = calculate_liquidity_score(df, position_size_ntd=position_ntd)
        return result
    except Exception as e:
        _raise_stock_data_error(code, e)


@router.get("/{code}/adaptive-signal")
def get_adaptive_signal(code: str, period_days: int = 365):
    """V4+V5 Adaptive mixed signal (Gemini R36)

    Dynamically allocates V4/V5 weights based on market state, returns blended score.
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
        except Exception as e:
            logger.debug(f"Optional operation failed: {e}")
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
        _raise_stock_data_error(code, e)


@router.get("/{code}/volume-patterns")
def get_volume_patterns(code: str, period_days: int = 365):
    """Volume pattern detection"""
    from data.fetcher import get_stock_data
    from analysis.volume_pattern import get_volume_pattern_summary
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=period_days)
        result = get_volume_pattern_summary(df)
        return make_serializable(result)
    except Exception as e:
        _raise_stock_data_error(code, e)


@router.get("/{code}/corporate-actions")
def get_corporate_actions(code: str, period_days: int = 365):
    """R58: Detect corporate action events (ex-dividend, splits, limit up/down, halt)"""
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
        _raise_stock_data_error(code, e)


@router.get("/{code}/valuation")
def get_valuation(code: str):
    """R62: Get stock valuation data (PE/PB/Dividend Yield) — TWSE BWIBBU_d

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
        raise HTTPException(status_code=502, detail=f"TWSE valuation data error for {code}: {e}")


@router.get("/{code}/revenue")
def get_revenue(code: str, months: int = Query(default=12, ge=1, le=36)):
    """R62: Get stock monthly revenue — MOPS

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
        raise HTTPException(status_code=502, detail=f"MOPS revenue data error for {code}: {e}")


# === R63: RS Scanner & Bold Status ===


@router.get("/rs-rankings")
def get_rs_rankings():
    """Get cached full-market RS rankings (R63)

    Returns the most recent scan's RS ranking results. Returns empty if no cache.
    """
    from analysis.rs_scanner import get_cached_rankings
    rankings = get_cached_rankings()
    if not rankings:
        return {"total_stocks": 0, "rankings": [], "scan_date": None}
    return rankings


@router.post("/rs-scan")
def trigger_rs_scan(max_workers: int = Query(8, ge=1, le=20)):
    """Trigger full-market RS scan (R63)

    Long-running (minutes), frontend should show loading spinner.
    """
    from analysis.rs_scanner import scan_market_rs
    try:
        result = scan_market_rs(max_workers=max_workers)
        return {
            "status": "ok",
            "total_stocks": result.get("total_stocks", 0),
            "elapsed_sec": result.get("elapsed_sec", 0),
            "scan_date": result.get("scan_date"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/bold-status")
def get_bold_status(code: str, period_days: int = 1095):
    """Get Bold strategy full status panel (R63)

    Combines Bold signal + RS Rating + strategy params (MLS, ECF).
    Frontend BoldStatusPanel uses this single endpoint for all data.
    """
    from data.fetcher import get_stock_data
    from analysis.strategy_bold import (
        get_bold_analysis, STRATEGY_BOLD_PARAMS, compute_rs_ratio,
    )
    from analysis.rs_scanner import get_stock_rs_rating
    from backend.dependencies import make_serializable

    try:
        df = get_stock_data(code, period_days=period_days)
        bold = get_bold_analysis(df)

        # RS rating from cached rankings
        rs_info = get_stock_rs_rating(code)

        # If no cached rating, compute raw RS ratio
        if not rs_info:
            p = STRATEGY_BOLD_PARAMS
            rs_ratio = compute_rs_ratio(
                df,
                lookback=p.get("rs_lookback", 120),
                exclude_recent=p.get("rs_exclude_recent", 5),
                base_weight=p.get("rs_base_weight", 0.6),
                recent_weight=p.get("rs_recent_weight", 0.4),
                recent_days=p.get("rs_recent_days", 20),
            )
            rs_info = {
                "rs_ratio": round(rs_ratio, 4) if rs_ratio else None,
                "rs_rating": None,
                "grade": "unknown",
                "scan_date": None,
            }

        # Strategy params summary
        p = STRATEGY_BOLD_PARAMS
        params_summary = {
            "mls_enabled": p.get("momentum_lag_stop_enabled", True),
            "mls_extended_days": p.get("time_stop_extended_days", 8),
            "mls_gain_threshold": p.get("momentum_lag_gain_threshold", 0.01),
            "ecf_enabled": p.get("equity_curve_filter_enabled", True),
            "ecf_loss_cap": p.get("consecutive_loss_cap", 3),
            "ecf_reduction": p.get("position_reduction_factor", 0.5),
            "rs_filter_enabled": p.get("rs_filter_enabled", True),
            "rs_min_rating": p.get("rs_min_rating", 80),
        }

        return make_serializable({
            "code": code,
            "bold": bold,
            "rs": rs_info,
            "params": params_summary,
        })
    except Exception as e:
        _raise_stock_data_error(code, e)


@router.get("/{code}/sector-context")
def get_sector_context_endpoint(code: str):
    """R64: Sector RS + Peer Alpha + Cluster Risk context for a stock.

    Uses cached RS rankings + sector mapping + sector heat to provide
    a complete sector context view.
    """
    from analysis.sector_rs import get_sector_context
    from data.cache import get_cached_sector_heat
    from backend.dependencies import make_serializable

    try:
        # Build sector heat map from cached data
        sector_heat_map: dict[str, float] = {}
        cached_heat = get_cached_sector_heat()
        if cached_heat and "sectors" in cached_heat:
            for s in cached_heat["sectors"]:
                sector_heat_map[s.get("sector", "")] = s.get("weighted_heat", 0)

        result = get_sector_context(code, sector_heat_map=sector_heat_map)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/vcp")
def get_vcp_endpoint(code: str, period_days: int = 365):
    """R85: VCP (Volatility Contraction Pattern) detection.

    Minervini-style VCP with Taiwan-market adaptations.
    Returns VCP score, base count, ghost days, coiled spring, pivot price.
    """
    from data.fetcher import get_stock_data
    from analysis.indicators import calculate_all_indicators
    from analysis.vcp_detector import get_vcp_context
    from backend.dependencies import make_serializable

    try:
        df = get_stock_data(code, period_days=period_days)
        df = calculate_all_indicators(df)
        result = get_vcp_context(df)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/accumulation-scan")
def get_accumulation_scan(code: str, period_days: int = 365):
    """Wyckoff Accumulation Scanner.

    Detects accumulation (Wyckoff Phase B/C) patterns via 6 quantitative conditions:
    1. Higher Lows
    2. Volume Test
    3. Post-test Consolidation
    4. Low ADX
    5. RS Strength
    6. AQS Smart Money (R95.1)

    Returns phase (NONE/ALPHA/BETA/INVALIDATED), score 0-100, and condition details.
    """
    from data.fetcher import get_stock_data
    from analysis.accumulation_scanner import detect_accumulation
    from backend.dependencies import make_serializable

    try:
        df = get_stock_data(code, period_days=period_days)

        # Try to get RS rating for condition 5
        rs_rating = None
        try:
            from analysis.rs_scanner import get_stock_rs
            rs_rating = get_stock_rs(code)
        except Exception as e:
            logger.debug(f"Optional data fetch failed: {e}")
            pass  # RS is optional; skip if unavailable

        result = detect_accumulation(df, rs_rating=rs_rating, stock_code=code)
        output = result.to_dict()
        output["code"] = code
        output["latest_close"] = round(float(df["close"].iloc[-1]), 2)
        output["high_52w"] = round(float(df["high"].max()), 2)
        output["low_52w"] = round(float(df["low"].min()), 2)
        output["data_points"] = len(df)

        return make_serializable(output)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

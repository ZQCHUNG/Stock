"""Risk calculation routes — position sizing, stop levels, trail classification.

Split from analysis.py — risk-factors, risk-budget, stop-levels,
sizing-advisor, trail-classifier endpoints.
"""

from fastapi import APIRouter, HTTPException, Query
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper functions (moved from analysis.py)
# ---------------------------------------------------------------------------


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

    Base matrix: Maturity x Sector Momentum
    Modifiers: +0.2 Leader, xLF, -0.1 Capital Strain, sector overheat decay
    Clamp to [0.1, 1.5], special case LF=0 -> C=0

    R24 adjustments per Gemini CTO review:
    - SS+Surge: 0.8->0.6 (FOMO risk, first-week premium too high)
    - SS+Cooling: 0.3->0.1 (distribution trap)
    - Structural+Heating: 1.1->1.2 (most stable alpha, deserve more aggression)
    - Clamp lower: 0.3->0.1 (allow near-zero for extreme risk)
    """
    # Base matrix: maturity -> {momentum -> base_score}
    MATRIX = {
        "Structural Shift": {"surge": 1.3, "heating": 1.2, "stable": 0.9, "cooling": 0.6},
        "Trend Formation": {"surge": 1.1, "heating": 0.9, "stable": 0.7, "cooling": 0.4},
        "Speculative Spike": {"surge": 0.6, "heating": 0.6, "stable": 0.4, "cooling": 0.1},
    }

    # Ghost Town override
    if liquidity_factor == 0:
        return 0.0, ["LF=0 (Ghost Town): no position recommended"]

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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{code}/risk-factors")
def get_risk_factors(code: str, period_days: int = 365):
    """Get position risk factors (for Position Calculator)

    Returns is_biotech, cash_runway, institutional_visibility, avg_volume,
    liquidity_factor, confidence_multiplier, etc.
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
        # Parallel fetch all required data
        with ThreadPoolExecutor(max_workers=4) as executor:
            fut_data = executor.submit(get_stock_data, code, period_days=period_days)
            fut_info = executor.submit(get_stock_info_and_fundamentals, code)
            fut_inst = executor.submit(get_institutional_data, code, days=20)
            fut_fin = executor.submit(get_financial_statements, code)

            df = fut_data.result()
            try:
                company_info, _ = fut_info.result()
            except Exception as e:
                logger.debug(f"Optional operation failed: {e}")
                company_info = {"industry": "", "sector": ""}
            try:
                inst_df = fut_inst.result()
            except Exception as e:
                logger.debug(f"Optional operation failed: {e}")
                inst_df = None
            try:
                fin_data = fut_fin.result()
            except Exception as e:
                logger.debug(f"Optional operation failed: {e}")
                fin_data = None

        # Calculate risk factors
        is_biotech = _is_biotech_industry(
            company_info.get("industry", ""),
            company_info.get("sector", ""),
        )
        inst_result = _calculate_institutional_score(inst_df)
        cash_runway = fin_data.get("cash_runway") if fin_data else None

        # 20-day average volume (shares)
        avg_volume_20d = float(df["volume"].tail(20).mean()) if len(df) >= 20 else 0

        # Calculate Liquidity Factor
        liquidity_factor = 1.0
        warnings = []

        if is_biotech:
            liquidity_factor *= 0.5
            warnings.append("生技股：部位 ×0.5")

        if cash_runway is not None:
            op_runway = cash_runway.get("runway_quarters", 99)
            total_runway = cash_runway.get("total_runway_quarters", 99)
            eff_runway = min(op_runway, total_runway) if is_biotech else op_runway

            if eff_runway < 4:
                liquidity_factor *= 0.25
                warnings.append(f"現金跑道 {eff_runway:.1f} 季（<4）：部位 ×0.25")
            elif eff_runway < 8:
                liquidity_factor *= 0.5
                warnings.append(f"現金跑道 {eff_runway:.1f} 季（<8）：部位 ×0.5")

            if not is_biotech and total_runway < 8:
                warnings.append(f"資本支出壓力：總跑道 {total_runway:.1f} 季（僅提示）")

        if inst_result.get("visibility") == "ghost_town":
            liquidity_factor = 0
            warnings.append("零法人交易（Ghost Town）：建議不持有")
        elif avg_volume_20d < 500_000:
            vol_factor = max(0.1, avg_volume_20d / 500_000)
            liquidity_factor *= vol_factor
            warnings.append(f"成交量偏低（{avg_volume_20d/1000:.0f}張/日）：部位 ×{vol_factor:.2f}")

        current_price = float(df["close"].iloc[-1])

        # Dynamic exit: ATR-based trailing stop (Gemini R24)
        from analysis.indicators import compute_true_range
        atr_14 = None
        trailing_stop_price = None
        highest_close_20d = None
        if len(df) >= 15:
            close = df["close"]
            tr = compute_true_range(df)
            atr_14 = float(tr.tail(14).mean())
            highest_close_20d = float(close.tail(20).max())
            trailing_candidate = highest_close_20d - 2 * atr_14

        # V4 signal for maturity info
        from analysis.strategy_v4 import get_v4_analysis
        try:
            v4 = get_v4_analysis(df)
            signal_maturity = v4.get("signal_maturity", "N/A")
            v4_signal = v4.get("signal", "HOLD")
            stop_loss_price = v4.get("stop_loss_price")
        except Exception as e:
            logger.debug(f"Optional operation failed: {e}")
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


@router.get("/{code}/risk-budget")
def get_risk_budget(code: str, period_days: int = 365):
    """V4/V5 Multi-strategy risk budget (Gemini R37: MultiStrategyBouncer)

    Detects V4/V5 signal conflicts + exposure cap recommendations.
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
        except Exception as e:
            logger.debug(f"Optional operation failed: {e}")
            regime_en = "range_quiet"

        # Get Kelly from portfolio optimal exposure (if available)
        kelly_half = 0.5
        try:
            from backend.routers.portfolio import get_optimal_exposure
            exposure_data = get_optimal_exposure()
            if exposure_data.get("has_data"):
                kelly_half = exposure_data.get("kelly_half", 0.5)
        except Exception as e:
            logger.debug(f"Optional operation failed: {e}")

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


@router.get("/{code}/trail-classifier")
def get_trail_classifier(code: str):
    """R76: Stock personality classifier — Momentum Scalper vs Precision Trender

    Based on R75 WFO-validated auto trail classifier:
    - ATR% >= 1.8% -> Momentum Scalper (flat 2% trail, high-freq small wins)
    - ATR% < 1.8%  -> Precision Trender (ATR k=1.0 trail, volatility-calibrated)
    """
    import numpy as np
    from data.fetcher import get_stock_data
    from analysis.indicators import calculate_atr

    try:
        df = get_stock_data(code, period_days=365)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch data: {e}")

    if df is None or len(df) < 30:
        raise HTTPException(status_code=400, detail="Insufficient data")

    # Compute ATR_14 (SMA to preserve original behavior)
    atr_df = calculate_atr(df, period=14, method="sma", min_periods=7)
    atr_14 = atr_df["atr"]
    atr_pct = atr_df["atr_pct"]
    c = df["close"]

    # 60-day rolling median (same as backtest engine)
    atr_pct_median = atr_pct.rolling(60, min_periods=20).median()

    # Current values
    current_atr_pct = float(atr_pct_median.iloc[-1]) if not np.isnan(atr_pct_median.iloc[-1]) else float(atr_pct.iloc[-1])
    threshold = 0.018  # 1.8%

    if current_atr_pct >= threshold:
        mode = "momentum_scalper"
        trail_desc = "Flat 2% trail"
    else:
        mode = "precision_trender"
        trail_desc = f"ATR k=1.0 trail (~{current_atr_pct*100:.1f}%)"

    # Recent ATR% history (last 60 days for sparkline)
    recent_atr_pct = atr_pct_median.tail(60).dropna()

    return {
        "code": code,
        "mode": mode,
        "atr_pct": round(current_atr_pct * 100, 2),  # as percentage
        "threshold_pct": threshold * 100,
        "trail_description": trail_desc,
        "atr_14": round(float(atr_14.iloc[-1]), 2) if not np.isnan(atr_14.iloc[-1]) else None,
        "close": round(float(c.iloc[-1]), 2),
        "history": [round(float(v) * 100, 2) for v in recent_atr_pct.values],
    }


@router.get("/{code}/sizing-advisor")
def get_sizing_advisor(
    code: str,
    capital: float = Query(1_000_000, ge=100_000, le=100_000_000),
    risk_pct: float = Query(3.0, ge=0.5, le=10.0, description="Max risk per trade (%)"),
    odd_lot: bool = Query(False, description="零股模式 (1-share increments)"),
):
    """R81/R82: Sizing Advisor — Equal Risk position sizing with sector penalty.

    Traffic light system:
    - GREEN: Standard sizing, within risk budget
    - YELLOW: Concentrated (1-lot floor, over-risk) or sector penalty applied
    - RED: Insufficient capital (can't afford 1 lot / 1 share)
    """
    import numpy as np
    import pandas as pd
    from data.fetcher import get_stock_data
    from data.sector_mapping import get_stock_sector
    from backtest.risk_manager import (
        get_suggested_position, get_sector_penalty_multiplier, SIZING_DEFAULTS,
    )

    try:
        df = get_stock_data(code, period_days=365)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch data: {e}")

    if df is None or len(df) < 30:
        raise HTTPException(status_code=400, detail="Insufficient data")

    # Compute ATR% (same logic as trail-classifier)
    from analysis.indicators import calculate_atr
    atr_df = calculate_atr(df, period=14, method="sma", min_periods=7)
    atr_pct = atr_df["atr_pct"]
    c = df["close"]
    atr_pct_median = atr_pct.rolling(60, min_periods=20).median()

    current_atr_pct = float(atr_pct_median.iloc[-1]) if not np.isnan(atr_pct_median.iloc[-1]) else float(atr_pct.iloc[-1])
    entry_price = float(c.iloc[-1])
    threshold = 0.018

    mode = "Trender" if current_atr_pct < threshold else "Scalper"
    stock_sector = get_stock_sector(code, level=1)

    # R82.2: Concentration-Cap sector multiplier (disabled by default)
    # [VERIFIED] No sector penalty outperforms disabled in 108-stock TWSE universe
    sector_mult = 1.0
    sector_reason = ""
    try:
        from backend.db import get_open_positions
        positions = get_open_positions()
        if positions:
            sector_mult, sector_reason = get_sector_penalty_multiplier(
                stock_sector, positions, penalty_factor=1.0,  # disabled by default
            )
    except Exception as e:
        logger.debug(f"Optional operation failed: {e}")
        pass  # DB not available or empty — no penalty

    # Sizing params
    sizing_params = {"max_risk_per_trade": risk_pct / 100}
    if odd_lot:
        sizing_params["trade_unit"] = 1
        sizing_params["min_lot_floor"] = False

    # Call sizing module (base, without sector penalty)
    sizing_base = get_suggested_position(
        mode=mode, atr_pct=current_atr_pct,
        equity=capital, entry_price=entry_price,
        params=sizing_params,
    )

    # Apply sector penalty to get adjusted sizing
    if sector_mult < 1.0 and sizing_base.shares > 0:
        adjusted_params = dict(sizing_params)
        adjusted_params["max_risk_per_trade"] = (risk_pct / 100) * sector_mult
        sizing = get_suggested_position(
            mode=mode, atr_pct=current_atr_pct,
            equity=capital, entry_price=entry_price,
            params=adjusted_params,
        )
    else:
        sizing = sizing_base

    # Traffic light
    if sizing.shares == 0:
        light = "red"
        light_label = "資金不足"
    elif sizing.over_risk:
        light = "yellow"
        light_label = "高資本集中度"
    elif sector_mult < 1.0:
        light = "yellow"
        light_label = "板塊集中"
    else:
        light = "green"
        light_label = "標準倉位"

    trade_unit = 1 if odd_lot else 1000
    lots = sizing.shares // trade_unit
    cost = sizing.shares * entry_price
    cost_pct = cost / capital * 100 if capital > 0 else 0
    one_lot_cost = trade_unit * entry_price

    # Base (naive) sizing for comparison
    base_lots = sizing_base.shares // trade_unit
    base_cost = sizing_base.shares * entry_price

    return {
        "code": code,
        "mode": mode,
        "atr_pct": round(current_atr_pct * 100, 2),
        "entry_price": round(entry_price, 2),
        "capital": capital,
        "sector": stock_sector,
        "odd_lot": odd_lot,
        # Adjusted sizing result
        "suggested_lots": lots,
        "suggested_shares": sizing.shares,
        "position_pct": round(sizing.position_pct * 100, 1),
        "cost": round(cost, 0),
        "cost_pct": round(cost_pct, 1),
        "regime_multiplier": round(sizing.regime_multiplier, 2),
        "risk_per_trade_pct": round(sizing.risk_per_trade_pct * 100, 2),
        "max_risk_pct": risk_pct,
        # Base (naive) sizing for comparison
        "base_lots": base_lots,
        "base_cost": round(base_cost, 0),
        # Sector penalty
        "sector_multiplier": round(sector_mult, 2),
        "sector_penalty_applied": sector_mult < 1.0,
        "sector_reason": sector_reason,
        # Traffic light
        "light": light,
        "light_label": light_label,
        "over_risk": sizing.over_risk,
        # Context
        "one_lot_cost": round(one_lot_cost, 0),
        "capital_barrier": one_lot_cost > capital,
        "reasoning": sizing.reasoning,
    }


@router.get("/{code}/stop-levels")
def get_stop_levels_endpoint(
    code: str,
    entry_price: float,
    entry_type: str = "squeeze_breakout",
    period_days: int = 365,
):
    """R86: ATR-Based Stop-Loss Calculator.

    Calculates stop levels using 3 methods (structural, ATR, percentage),
    with VCP pivot override and gap risk estimation.
    Returns initial stop, trailing stop targets, and R-value.
    """
    from data.fetcher import get_stock_data
    from analysis.indicators import calculate_all_indicators
    from analysis.stop_loss import get_stop_context
    from analysis.vcp_detector import get_vcp_context
    from backend.dependencies import make_serializable

    try:
        df = get_stock_data(code, period_days=period_days)
        df = calculate_all_indicators(df)

        # Get VCP context for potential pivot override
        vcp_context = get_vcp_context(df)

        result = get_stop_context(df, entry_price, entry_type, vcp_context)
        return make_serializable(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

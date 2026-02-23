"""回測路由"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class BacktestRequest(BaseModel):
    period_days: int = 1095
    initial_capital: float = 1_000_000
    params: dict | None = None
    commission_rate: float | None = None  # 手續費率 (default 0.001425)
    tax_rate: float | None = None         # 交易稅率 (default 0.003)
    slippage: float | None = None         # 滑價率 (default 0.001)


class PortfolioRequest(BaseModel):
    stock_codes: list[str]
    period_days: int = 1095
    initial_capital: float = 1_000_000
    params: dict | None = None


class SimulationRequest(BaseModel):
    period_days: int = 365
    days: int = 30
    initial_capital: float = 1_000_000
    params: dict | None = None


class RollingRequest(BaseModel):
    period_days: int = 1095
    initial_capital: float = 1_000_000
    window_months: int = 6
    params: dict | None = None


class SensitivityRequest(BaseModel):
    period_days: int = 1095
    initial_capital: float = 1_000_000
    params: dict | None = None


class AlphaBetaRequest(BaseModel):
    period_days: int = 1095
    initial_capital: float = 1_000_000
    params: dict | None = None


class StrategyComparisonRequest(BaseModel):
    period_days: int = 730
    initial_capital: float = 1_000_000
    v4_params: dict | None = None
    v5_params: dict | None = None


class MetaStrategyRequest(BaseModel):
    stock_codes: list[str]
    period_days: int = 730
    initial_capital: float = 1_000_000


class BoldBacktestRequest(BaseModel):
    period_days: int = 1825  # 5 年（小型股需要長期數據）
    initial_capital: float = 1_000_000
    params: dict | None = None
    ultra_wide: bool = False  # 是否使用 Ultra-Wide Conviction 模式
    commission_rate: float | None = None
    tax_rate: float | None = None
    slippage: float | None = None
    broker_discount: float = 1.0  # Phase 9A: 1.0=full, 0.28=2.8折
    use_dynamic_slippage: bool = False  # Phase 9A: Kyle Lambda volume-dependent


class AggressiveBacktestRequest(BaseModel):
    period_days: int = 2920  # 8 年（大波段需要長期數據）
    initial_capital: float = 1_000_000
    params: dict | None = None
    commission_rate: float | None = None
    tax_rate: float | None = None
    slippage: float | None = None


class PortfolioBoldRequest(BaseModel):
    """Portfolio-level Bold backtest (R14.18 Production Baseline)"""
    period_days: int = 1095  # 3 years default
    initial_capital: float = 10_000_000
    params: dict | None = None  # Override PortfolioBacktester params
    broker_discount: float = 1.0  # Phase 9A
    use_dynamic_slippage: bool = False  # Phase 9A


class SqsBacktestRequest(BaseModel):
    stock_codes: list[str] | None = None
    period_days: int = 730
    max_workers: int = 4
    thresholds: list[float] = [40, 60, 80]


def _serialize_backtest_result(result) -> dict:
    """BacktestResult → JSON-safe dict"""
    from backend.dependencies import series_to_response, make_serializable
    trades = []
    for t in result.trades:
        trades.append({
            "date_open": t.date_open.isoformat() if t.date_open else None,
            "date_close": t.date_close.isoformat() if t.date_close else None,
            "shares": t.shares,
            "price_open": round(t.price_open, 2),
            "price_close": round(t.price_close, 2),
            "pnl": round(t.pnl, 0),
            "return_pct": round(t.return_pct, 4),
            "exit_reason": t.exit_reason,
            "liquidity_warning": t.liquidity_warning,
            "slippage_cost": round(t.slippage_cost, 0),
            "gross_pnl": round(t.gross_pnl, 0),
        })

    total_commission = sum(t.commission for t in result.trades)
    total_tax = sum(t.tax for t in result.trades)
    total_slippage = sum(t.slippage_cost for t in result.trades)
    total_costs = total_commission + total_tax + total_slippage
    total_gross_pnl = sum(t.gross_pnl for t in result.trades)

    # Phase 9A: Gross return (from gross equity curve if available)
    gross_equity = getattr(result, "gross_equity_curve", None)
    gross_total_return = None
    if gross_equity is not None and not gross_equity.empty:
        initial = gross_equity.iloc[0] if len(gross_equity) > 0 else 1
        if initial > 0:
            gross_total_return = (gross_equity.iloc[-1] - initial) / initial

    # Phase 9A: Cost-to-Alpha Ratio (CAR) — CTO mandate
    car = None
    if gross_total_return and gross_total_return > 0:
        car = round(total_costs / (gross_total_return * result.equity_curve.iloc[0]) * 100, 2) if result.equity_curve.iloc[0] > 0 else None

    resp = {
        "total_return": result.total_return,
        "annual_return": result.annual_return,
        "max_drawdown": result.max_drawdown,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "sharpe_ratio": result.sharpe_ratio,
        "sortino_ratio": result.sortino_ratio,
        "calmar_ratio": result.calmar_ratio,
        "total_trades": result.total_trades,
        "avg_holding_days": result.avg_holding_days,
        "avg_win": result.avg_win,
        "avg_loss": result.avg_loss,
        "max_consecutive_wins": result.max_consecutive_wins,
        "max_consecutive_losses": result.max_consecutive_losses,
        "dividend_income": result.dividend_income,
        "params_description": result.params_description,
        "total_commission": round(total_commission, 0),
        "total_tax": round(total_tax, 0),
        "total_slippage": round(total_slippage, 0),
        "total_costs": round(total_costs, 0),
        "cost_to_alpha_ratio": car,
        "gross_total_return": round(gross_total_return, 4) if gross_total_return is not None else None,
        "equity_curve": series_to_response(result.equity_curve),
        "daily_returns": series_to_response(result.daily_returns),
        "trades": trades,
        "corporate_action_warnings": getattr(result, "corporate_action_warnings", []),
        "trail_mode_info": getattr(result, "trail_mode_info", {}),
    }

    # Phase 9A: include gross equity curve if available
    if gross_equity is not None and not gross_equity.empty:
        resp["gross_equity_curve"] = series_to_response(gross_equity)

    return resp


@router.post("/{code}/v4")
def run_v4_backtest(code: str, req: BacktestRequest):
    """執行 v4 回測"""
    from data.fetcher import get_stock_data, get_dividend_data, get_splits_data
    from backtest.engine import run_backtest_v4
    try:
        df = get_stock_data(code, period_days=req.period_days)
        result = run_backtest_v4(
            df, initial_capital=req.initial_capital, params=req.params,
            commission_rate=req.commission_rate, tax_rate=req.tax_rate,
            slippage=req.slippage,
        )

        # R58: Corporate action detection
        try:
            from data.corporate_actions import detect_corporate_actions, annotate_trades_with_actions
            dividends = get_dividend_data(code)
            splits = get_splits_data(code)
            ca_report = detect_corporate_actions(code, df, dividends, splits)
            result.corporate_action_warnings = annotate_trades_with_actions(
                result.trades, ca_report)
        except Exception:
            pass  # Non-critical: don't fail backtest if CA detection fails

        return _serialize_backtest_result(result)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/portfolio")
def run_portfolio_backtest(req: PortfolioRequest):
    """執行組合回測"""
    from data.fetcher import get_stock_data
    from data.stock_list import get_stock_name
    from backtest.engine import run_portfolio_backtest_v4
    from backend.dependencies import series_to_response, make_serializable
    try:
        stock_data = {}
        stock_names = {}
        for code in req.stock_codes:
            try:
                stock_data[code] = get_stock_data(code, period_days=req.period_days)
                stock_names[code] = get_stock_name(code)
            except Exception:
                continue

        if not stock_data:
            raise HTTPException(status_code=400, detail="無法取得任何股票資料")

        result = run_portfolio_backtest_v4(
            stock_data, stock_names=stock_names,
            initial_capital=req.initial_capital, params=req.params,
        )

        # 序列化個股結果
        stock_results = {}
        for code, sr in result.stock_results.items():
            stock_results[code] = _serialize_backtest_result(sr)

        return make_serializable({
            "total_return": result.total_return,
            "annual_return": result.annual_return,
            "max_drawdown": result.max_drawdown,
            "sharpe_ratio": result.sharpe_ratio,
            "sortino_ratio": result.sortino_ratio,
            "calmar_ratio": result.calmar_ratio,
            "total_trades": result.total_trades,
            "winning_stocks": result.winning_stocks,
            "losing_stocks": result.losing_stocks,
            "initial_capital": result.initial_capital,
            "per_stock_capital": result.per_stock_capital,
            "stock_codes": result.stock_codes,
            "stock_names": result.stock_names,
            "equity_curve": series_to_response(result.equity_curve),
            "daily_returns": series_to_response(result.daily_returns),
            "stock_results": stock_results,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{code}/simulation")
def run_simulation(code: str, req: SimulationRequest):
    """執行模擬交易"""
    from data.fetcher import get_stock_data
    from simulation.simulator import run_simulation_v4
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=req.period_days)
        result = run_simulation_v4(df, initial_capital=req.initial_capital,
                                   days=req.days, params=req.params)

        daily_records = []
        for r in result.daily_records:
            daily_records.append({
                "date": r.date.isoformat(),
                "close": r.close,
                "signal": r.signal,
                "action": r.action,
                "shares": r.shares,
                "cash": r.cash,
                "position_value": r.position_value,
                "total_equity": r.total_equity,
                "daily_pnl": r.daily_pnl,
                "daily_return": r.daily_return,
            })

        return make_serializable({
            "initial_capital": result.initial_capital,
            "final_equity": result.final_equity,
            "total_return": result.total_return,
            "max_drawdown": result.max_drawdown,
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "total_commission": result.total_commission,
            "total_tax": result.total_tax,
            "daily_records": daily_records,
            "trade_log": result.trade_log,
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{code}/rolling")
def run_rolling(code: str, req: RollingRequest):
    """執行 Rolling Backtest"""
    from data.fetcher import get_stock_data
    from backtest.rolling import run_rolling_backtest
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=req.period_days)
        result = run_rolling_backtest(
            df, initial_capital=req.initial_capital,
            window_months=req.window_months, params=req.params,
        )

        windows = []
        for w in result.windows:
            windows.append({
                "window_name": w.window_name,
                "start_date": w.start_date,
                "end_date": w.end_date,
                "trading_days": w.trading_days,
                "total_return": w.total_return,
                "annual_return": w.annual_return,
                "max_drawdown": w.max_drawdown,
                "win_rate": w.win_rate,
                "total_trades": w.total_trades,
                "profit_factor": w.profit_factor,
                "sharpe_ratio": w.sharpe_ratio,
            })

        return make_serializable({
            "windows": windows,
            "avg_return": result.avg_return,
            "return_std": result.return_std,
            "min_return": result.min_return,
            "max_return": result.max_return,
            "positive_windows": result.positive_windows,
            "total_windows": result.total_windows,
            "avg_win_rate": result.avg_win_rate,
            "avg_max_drawdown": result.avg_max_drawdown,
            "consistency_score": result.consistency_score,
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{code}/sensitivity")
def run_sensitivity(code: str, req: SensitivityRequest):
    """參數敏感度分析"""
    from data.fetcher import get_stock_data
    from backtest.rolling import run_parameter_sensitivity
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=req.period_days)
        results = run_parameter_sensitivity(
            df, base_params=req.params, initial_capital=req.initial_capital,
        )
        return make_serializable(results)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{code}/alpha-beta")
def run_alpha_beta(code: str, req: AlphaBetaRequest):
    """Alpha/Beta 風險分析"""
    from data.fetcher import get_stock_data, get_taiex_data
    from backtest.engine import run_backtest_v4
    from backtest.alpha_beta import calculate_alpha_beta
    from backend.dependencies import make_serializable, series_to_response
    try:
        df = get_stock_data(code, period_days=req.period_days)
        taiex = get_taiex_data(period_days=req.period_days)

        bt = run_backtest_v4(df, initial_capital=req.initial_capital, params=req.params)
        result = calculate_alpha_beta(bt.equity_curve, taiex["close"])

        # Series 特殊處理
        rolling_alpha = result.pop("rolling_alpha", None)
        rolling_alpha_ema = result.pop("rolling_alpha_ema", None)

        serialized = make_serializable(result)
        serialized["rolling_alpha"] = series_to_response(rolling_alpha) if rolling_alpha is not None else {"dates": [], "values": []}
        serialized["rolling_alpha_ema"] = series_to_response(rolling_alpha_ema) if rolling_alpha_ema is not None else {"dates": [], "values": []}

        return serialized
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{code}/adaptive")
def run_adaptive_backtest(code: str, req: BacktestRequest):
    """執行 Adaptive 自適應混合回測（V4+V5 根據市場 regime 自動切換）"""
    from data.fetcher import get_stock_data
    from backtest.engine import run_backtest_adaptive
    try:
        df = get_stock_data(code, period_days=req.period_days)
        # Detect market regime
        try:
            from backend.routers.portfolio import get_market_regime
            regime_data = get_market_regime()
            regime_en = regime_data.get("regime_en", "range_quiet") if regime_data.get("has_data") else "range_quiet"
        except Exception:
            regime_en = "range_quiet"
        result = run_backtest_adaptive(
            df, regime=regime_en, initial_capital=req.initial_capital,
            commission_rate=req.commission_rate, tax_rate=req.tax_rate,
            slippage=req.slippage,
        )
        return _serialize_backtest_result(result)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{code}/v5")
def run_v5_backtest(code: str, req: BacktestRequest):
    """執行 V5 均值回歸回測（Gemini R37）"""
    from data.fetcher import get_stock_data
    from backtest.engine import run_backtest_v5
    try:
        df = get_stock_data(code, period_days=req.period_days)
        result = run_backtest_v5(
            df, initial_capital=req.initial_capital, params=req.params,
            commission_rate=req.commission_rate, tax_rate=req.tax_rate,
            slippage=req.slippage,
        )
        return _serialize_backtest_result(result)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{code}/bold")
def run_bold_backtest(code: str, req: BoldBacktestRequest):
    """執行 Bold 大膽策略回測（Energy Squeeze + Step-up Buffer）

    支援兩種模式：
    - Standard: 擠壓突破 + 量能爬坡，120 天 max hold
    - Ultra-Wide: MA200 斜率保護 + 365 天 conviction hold
    """
    from data.fetcher import get_stock_data
    from backtest.engine import run_backtest_bold, TransactionCostCalculator
    try:
        df = get_stock_data(code, period_days=req.period_days)
        # Phase 9A: build cost calculator with broker discount + dynamic slippage
        cost_calc = TransactionCostCalculator(
            commission_rate=req.commission_rate or 0.001425,
            tax_rate=req.tax_rate or 0.003,
            base_slippage=req.slippage or 0.001,
            broker_discount=req.broker_discount,
            use_dynamic_slippage=req.use_dynamic_slippage,
        )
        result = run_backtest_bold(
            df,
            initial_capital=req.initial_capital,
            params=req.params,
            ultra_wide=req.ultra_wide,
            cost_calculator=cost_calc,
        )
        return _serialize_backtest_result(result)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{code}/aggressive")
def run_aggressive_backtest(code: str, req: AggressiveBacktestRequest):
    """執行 Aggressive Mode 回測（真・大膽模式 — WarriorExitEngine）

    目標：捕捉 +50% ~ +200% 大波段（亞翔、陽明、光聖、亞果型）。
    接受 15-20% MDD 作為代價。

    與 Bold 完全分離的出場引擎：
    - 無 structural_stop、無 time_stop_5d
    - ATR 3× trailing + MA50 death cross + -20% 災難止損
    - 含加碼機制（Pyramiding）
    """
    from data.fetcher import get_stock_data
    from backtest.engine import run_backtest_aggressive
    from backend.dependencies import make_serializable
    try:
        df = get_stock_data(code, period_days=req.period_days)
        result = run_backtest_aggressive(
            df,
            initial_capital=req.initial_capital,
            params=req.params,
            commission_rate=req.commission_rate,
            tax_rate=req.tax_rate,
            slippage=req.slippage,
        )
        serialized = _serialize_backtest_result(result)
        # Attach aggressive-specific metrics
        if result.trail_mode_info and "aggressive_metrics" in result.trail_mode_info:
            serialized["aggressive_metrics"] = make_serializable(
                result.trail_mode_info["aggressive_metrics"]
            )
        return serialized
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{code}/strategy-comparison")
def run_strategy_comparison(code: str, req: StrategyComparisonRequest):
    """V4 vs V5 vs Adaptive vs Bold 策略比較

    同時執行四種回測，回傳並排比較指標 + 差異分析。
    """
    from data.fetcher import get_stock_data
    from backtest.engine import run_backtest_v4, run_backtest_v5, run_backtest_adaptive, run_backtest_bold
    from backend.dependencies import make_serializable

    try:
        df = get_stock_data(code, period_days=req.period_days)

        # Detect market regime for adaptive mode
        try:
            from backend.routers.portfolio import get_market_regime
            regime_data = get_market_regime()
            regime_en = regime_data.get("regime_en", "range_quiet") if regime_data.get("has_data") else "range_quiet"
        except Exception:
            regime_en = "range_quiet"

        v4_result = run_backtest_v4(df, initial_capital=req.initial_capital, params=req.v4_params)
        v5_result = run_backtest_v5(df, initial_capital=req.initial_capital, params=req.v5_params)
        adaptive_result = run_backtest_adaptive(
            df, regime=regime_en, initial_capital=req.initial_capital,
            v4_params=req.v4_params, v5_params=req.v5_params,
        )
        bold_result = run_backtest_bold(df, initial_capital=req.initial_capital, ultra_wide=True)

        def _summary(r):
            return {
                "total_return": r.total_return,
                "annual_return": r.annual_return,
                "max_drawdown": r.max_drawdown,
                "sharpe_ratio": r.sharpe_ratio,
                "sortino_ratio": r.sortino_ratio,
                "calmar_ratio": r.calmar_ratio,
                "win_rate": r.win_rate,
                "profit_factor": r.profit_factor,
                "total_trades": r.total_trades,
                "avg_holding_days": r.avg_holding_days,
                "params_description": r.params_description,
            }

        # Recovery Factor = total_return / abs(max_drawdown)
        def _recovery_factor(r):
            return r.total_return / abs(r.max_drawdown) if r.max_drawdown < 0 else 0

        comparison = {
            "sharpe_delta": adaptive_result.sharpe_ratio - v4_result.sharpe_ratio,
            "return_delta": adaptive_result.total_return - v4_result.total_return,
            "drawdown_delta": adaptive_result.max_drawdown - v4_result.max_drawdown,
            "recovery_v4": round(_recovery_factor(v4_result), 3),
            "recovery_v5": round(_recovery_factor(v5_result), 3),
            "recovery_adaptive": round(_recovery_factor(adaptive_result), 3),
            "recovery_bold": round(_recovery_factor(bold_result), 3),
        }

        return make_serializable({
            "v4": _serialize_backtest_result(v4_result),
            "v5": _serialize_backtest_result(v5_result),
            "adaptive": _serialize_backtest_result(adaptive_result),
            "bold": _serialize_backtest_result(bold_result),
            "v4_summary": _summary(v4_result),
            "v5_summary": _summary(v5_result),
            "adaptive_summary": _summary(adaptive_result),
            "bold_summary": _summary(bold_result),
            "comparison": comparison,
            "regime": regime_en,
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/meta-strategy")
def run_meta_strategy_backtest(req: MetaStrategyRequest):
    """Meta-Strategy 回測：按 Fitness Tag 自動選擇 V4/V5（Gemini R41）

    根據每檔股票的 Strategy Fitness Tag 決定使用 V4 或 V5：
    - Trend Preferred / Trend Only → V4
    - Volatility Preferred / Reversion Only → V5
    - Balanced / others → Adaptive

    回傳等權重組合績效 + 個股選用策略明細。
    """
    from data.fetcher import get_stock_data
    from data.stock_list import get_stock_name
    from analysis.strategy_fitness import get_fitness_tags
    from backtest.engine import BacktestEngine
    from backend.dependencies import series_to_response, make_serializable
    import pandas as pd
    import numpy as np

    try:
        # Look up fitness tags
        tags = get_fitness_tags(req.stock_codes)
        tag_map = {t["code"]: t.get("fitness_tag", "") for t in tags}

        n_stocks = len(req.stock_codes)
        if n_stocks == 0:
            raise HTTPException(status_code=400, detail="未提供股票代碼")

        per_stock = req.initial_capital / n_stocks

        stock_results = {}
        stock_strategies = {}
        stock_equity_curves = {}
        total_trades = 0
        winning_stocks = losing_stocks = 0

        for code in req.stock_codes:
            try:
                df = get_stock_data(code, period_days=req.period_days)
                if df is None or len(df) < 60:
                    continue

                tag = tag_map.get(code, "")
                engine = BacktestEngine(initial_capital=per_stock)

                # Select strategy by fitness tag
                if tag in ("Trend Preferred (V4)", "Trend Only (V4)"):
                    bt = engine.run_v4(df)
                    chosen = "V4"
                elif tag in ("Volatility Preferred (V5)", "Reversion Only (V5)"):
                    bt = engine.run_v5(df)
                    chosen = "V5"
                else:
                    # Balanced, Insufficient Data, No Signal → Adaptive
                    try:
                        from backend.routers.portfolio import get_market_regime
                        regime_data = get_market_regime()
                        regime_en = regime_data.get("regime_en", "range_quiet") if regime_data.get("has_data") else "range_quiet"
                    except Exception:
                        regime_en = "range_quiet"
                    bt = engine.run_adaptive(df, regime=regime_en)
                    chosen = "Adaptive"

                stock_strategies[code] = {
                    "fitness_tag": tag or "N/A",
                    "chosen_strategy": chosen,
                    "total_return": bt.total_return,
                    "sharpe_ratio": bt.sharpe_ratio,
                    "total_trades": bt.total_trades,
                    "win_rate": bt.win_rate,
                    "name": get_stock_name(code),
                }
                stock_results[code] = _serialize_backtest_result(bt)
                if not bt.equity_curve.empty:
                    stock_equity_curves[code] = bt.equity_curve
                total_trades += bt.total_trades
                if bt.total_return > 0:
                    winning_stocks += 1
                elif bt.total_return < 0:
                    losing_stocks += 1
            except Exception:
                continue

        if not stock_equity_curves:
            raise HTTPException(status_code=400, detail="無法取得任何回測結果")

        # Merge equity curves
        eq_df = pd.DataFrame(stock_equity_curves)
        eq_df = eq_df.ffill().bfill()
        portfolio_equity = eq_df.sum(axis=1)
        portfolio_returns = portfolio_equity.pct_change().dropna()

        total_return = (portfolio_equity.iloc[-1] - req.initial_capital) / req.initial_capital
        trading_days = len(portfolio_equity)
        annual_return = (1 + total_return) ** (252 / trading_days) - 1 if trading_days > 1 else 0

        peak = portfolio_equity.expanding().max()
        max_drawdown = float(((portfolio_equity - peak) / peak).min())

        sharpe = 0.0
        if len(portfolio_returns) > 1 and portfolio_returns.std() > 0:
            rf_daily = 0.015 / 252
            excess = portfolio_returns - rf_daily
            sharpe = float(excess.mean() / excess.std() * np.sqrt(252))

        # Compare with pure-V4 portfolio
        v4_total_return = None
        try:
            from backtest.engine import run_portfolio_backtest_v4
            v4_stock_data = {}
            for code in req.stock_codes:
                try:
                    v4_stock_data[code] = get_stock_data(code, period_days=req.period_days)
                except Exception:
                    pass
            if v4_stock_data:
                v4_result = run_portfolio_backtest_v4(
                    v4_stock_data, initial_capital=req.initial_capital)
                v4_total_return = v4_result.total_return
        except Exception:
            pass

        return make_serializable({
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe,
            "total_trades": total_trades,
            "winning_stocks": winning_stocks,
            "losing_stocks": losing_stocks,
            "stock_strategies": stock_strategies,
            "stock_results": stock_results,
            "equity_curve": series_to_response(portfolio_equity),
            "v4_baseline_return": v4_total_return,
            "alpha_vs_v4": total_return - v4_total_return if v4_total_return is not None else None,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sqs-backtest")
def run_sqs_backtest_endpoint(req: SqsBacktestRequest):
    """SQS effectiveness backtest: compare filtered vs all signals."""
    try:
        from backtest.sqs_backtest import run_sqs_backtest
        result = run_sqs_backtest(
            stock_codes=req.stock_codes,
            period_days=req.period_days,
            max_workers=req.max_workers,
            thresholds=req.thresholds,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{code}/attribution")
def run_attribution(code: str, req: BacktestRequest):
    """R58: Performance attribution (Brinson model + factor analysis)."""
    from data.fetcher import get_stock_data, get_taiex_data
    from backtest.engine import run_backtest_v4
    from backtest.attribution import compute_trade_attribution, compute_factor_exposure

    try:
        df = get_stock_data(code, period_days=req.period_days)
        taiex = get_taiex_data(period_days=req.period_days)

        result = run_backtest_v4(
            df, initial_capital=req.initial_capital, params=req.params,
            commission_rate=req.commission_rate, tax_rate=req.tax_rate,
            slippage=req.slippage,
        )

        # Brinson attribution (strategy vs buy-and-hold)
        stock_returns = df["close"].pct_change().dropna()
        brinson = compute_trade_attribution(result.trades, stock_returns)

        # Factor analysis
        market_returns = taiex["close"].pct_change().dropna() if not taiex.empty else pd.Series(dtype=float)
        factors = compute_factor_exposure(result.daily_returns, market_returns)

        return {
            "brinson": brinson.to_dict(),
            "factors": factors.to_dict(),
            "trades_count": len(result.trades),
            "holding_periods": len([t for t in result.trades if t.date_close]),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# R59: Forward Testing endpoints
# ---------------------------------------------------------------------------

@router.get("/forward-test/summary")
def get_forward_test_summary():
    """R59: Get forward test summary statistics."""
    from backtest.forward_test import get_summary
    s = get_summary()
    return {
        "total_signals": s.total_signals,
        "signals_opened": s.signals_opened,
        "signals_skipped": s.signals_skipped,
        "signals_pending": s.signals_pending,
        "total_positions": s.total_positions,
        "open_positions": s.open_positions,
        "closed_positions": s.closed_positions,
        "win_rate": s.win_rate,
        "avg_return": s.avg_return,
        "total_pnl": s.total_pnl,
        "avg_hold_days": s.avg_hold_days,
        "best_trade": s.best_trade,
        "worst_trade": s.worst_trade,
    }


@router.get("/forward-test/signals")
def get_forward_signals(limit: int = 50, status: str | None = None):
    """R59: Get recent forward test signals."""
    from backtest.forward_test import get_signals
    return get_signals(limit=limit, status=status)


@router.get("/forward-test/positions")
def get_forward_positions(limit: int = 50, status: str | None = None):
    """R59: Get recent forward test positions."""
    from backtest.forward_test import get_positions
    return get_positions(limit=limit, status=status)


@router.post("/forward-test/scan")
def run_forward_scan(stock_codes: list[str] | None = None):
    """R59: Run forward test signal scan (post-market)."""
    from backtest.forward_test import scan_and_record_signals
    signals = scan_and_record_signals(stock_codes=stock_codes)
    return {
        "signals_found": len(signals),
        "signals": [
            {
                "id": s.id,
                "code": s.stock_code,
                "price": s.signal_price,
                "confidence": s.confidence,
            }
            for s in signals
        ],
    }


@router.post("/forward-test/open/{signal_id}")
def open_forward_position(signal_id: int, capital: float = 500_000):
    """R59: Open a virtual position from a signal."""
    from backtest.forward_test import open_virtual_position
    pos = open_virtual_position(signal_id, capital=capital)
    if not pos:
        raise HTTPException(status_code=400, detail="Failed to open position")
    return {
        "position_id": pos.id,
        "code": pos.stock_code,
        "open_price": pos.open_price,
        "shares": pos.shares,
        "tp_price": pos.tp_price,
        "sl_price": pos.sl_price,
    }


@router.post("/forward-test/update")
def update_forward_positions():
    """R59: Update all open forward test positions (daily check)."""
    from backtest.forward_test import update_positions_daily
    actions = update_positions_daily()
    return {"actions": actions, "total": len(actions)}


@router.get("/forward-test/compare")
def compare_forward_backtest(stock_code: str | None = None):
    """R59: Compare forward test vs backtest results."""
    from backtest.forward_test import compare_with_backtest
    return compare_with_backtest(stock_code=stock_code)


# ---------------------------------------------------------------------------
# R60: Risk Management endpoints
# ---------------------------------------------------------------------------

class RiskAssessmentRequest(BaseModel):
    stock_codes: list[str] = []
    portfolio_value: float = 1_000_000
    holdings: dict[str, float] | None = None  # {code: market_value}
    confidence: float = 0.95
    single_stock_limit: float = 0.20
    sector_limit: float = 0.40
    max_dd_threshold: float = -0.15
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0
    consecutive_losses: int = 0


@router.post("/risk/assess")
def assess_risk(req: RiskAssessmentRequest):
    """R60: Full portfolio risk assessment (VaR + concentration + drawdown + stress)."""
    from data.fetcher import get_stock_data
    from backtest.risk_manager import assess_portfolio_risk

    try:
        stock_data = {}
        codes = req.stock_codes or (list(req.holdings.keys()) if req.holdings else [])
        for code in codes:
            df = get_stock_data(code, period_days=365)
            if df is not None and len(df) > 0:
                stock_data[code] = df

        report = assess_portfolio_risk(
            stock_data=stock_data,
            holdings=req.holdings,
            portfolio_value=req.portfolio_value,
            confidence=req.confidence,
            single_stock_limit=req.single_stock_limit,
            sector_limit=req.sector_limit,
            max_dd_threshold=req.max_dd_threshold,
            daily_pnl=req.daily_pnl,
            weekly_pnl=req.weekly_pnl,
            monthly_pnl=req.monthly_pnl,
            consecutive_losses=req.consecutive_losses,
        )
        return report.to_dict()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/risk/var")
def compute_var_endpoint(req: RiskAssessmentRequest):
    """R60: Compute portfolio VaR (Historical + Parametric + CVaR)."""
    from data.fetcher import get_stock_data
    from backtest.risk_manager import compute_portfolio_returns, compute_var

    try:
        stock_data = {}
        codes = req.stock_codes or (list(req.holdings.keys()) if req.holdings else [])
        for code in codes:
            df = get_stock_data(code, period_days=365)
            if df is not None and len(df) > 0:
                stock_data[code] = df

        weights = None
        if req.holdings:
            total = sum(req.holdings.values())
            if total > 0:
                weights = {c: v / total for c, v in req.holdings.items()}

        port_ret = compute_portfolio_returns(stock_data, weights)
        result = compute_var(port_ret, req.confidence, req.portfolio_value)
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# === Phase 8A: Portfolio Bold Backtest with Equity Curve (CTO R14.18) ===


@router.post("/portfolio-bold")
def run_portfolio_bold_backtest(req: PortfolioBoldRequest):
    """Phase 8A: Run portfolio-level Bold backtest (R14.18 Production Baseline).

    Returns equity curve, TAIEX benchmark, drawdown, holdings count,
    and monthly returns for visualization.
    """
    from backtest.portfolio_runner import PortfolioBacktester
    from data.fetcher import get_stock_data, get_taiex_data
    from data.sector_mapping import get_stock_sector
    from config import SCAN_STOCKS
    from backend.dependencies import make_serializable
    import pandas as pd
    import numpy as np

    try:
        params = req.params or {}
        params.setdefault("initial_capital", req.initial_capital)
        params.setdefault("period_days", req.period_days)

        # Load stock data for all SCAN_STOCKS
        # Need extra history for signal computation (60 days min)
        fetch_days = req.period_days + 300
        stock_data = {}
        stock_sectors = {}
        for code in SCAN_STOCKS:
            try:
                df = get_stock_data(code, period_days=fetch_days)
                if df is not None and not df.empty and len(df) > 60:
                    stock_data[code] = df
                    stock_sectors[code] = get_stock_sector(code, level=1) or ""
            except Exception:
                continue

        if not stock_data:
            raise HTTPException(status_code=400, detail="No stock data loaded")

        # Load TAIEX for guard
        taiex_data = None
        try:
            taiex_data = get_taiex_data(period_days=fetch_days)
        except Exception:
            pass

        # Phase 9A: build cost calculator for portfolio backtest
        from backtest.engine import TransactionCostCalculator
        cost_calc = TransactionCostCalculator(
            broker_discount=req.broker_discount,
            use_dynamic_slippage=req.use_dynamic_slippage,
        )
        bt = PortfolioBacktester(params=params, cost_calculator=cost_calc)
        result = bt.run(
            stock_data=stock_data,
            stock_sectors=stock_sectors,
            taiex_data=taiex_data,
        )

        eq_df = result.equity_curve
        if eq_df.empty:
            raise HTTPException(status_code=400, detail="Backtest produced no data")

        dates = eq_df.index.strftime("%Y-%m-%d").tolist()
        equity = eq_df["equity"].tolist()

        # Drawdown series
        running_max = eq_df["equity"].cummax()
        drawdown = ((eq_df["equity"] - running_max) / running_max).tolist()

        # TAIEX benchmark (normalized to same starting capital)
        benchmark = []
        try:
            taiex = get_taiex_data(period_days=req.period_days + 60)
            if not taiex.empty:
                taiex_close = taiex["close"] if "close" in taiex.columns else taiex.iloc[:, 0]
                # Align to backtest date range
                taiex_close.index = pd.to_datetime(taiex_close.index)
                bt_start = pd.Timestamp(dates[0])
                bt_end = pd.Timestamp(dates[-1])
                taiex_aligned = taiex_close.loc[
                    (taiex_close.index >= bt_start) & (taiex_close.index <= bt_end)
                ]
                if len(taiex_aligned) > 0:
                    # Normalize: start at same capital as portfolio
                    scale = req.initial_capital / taiex_aligned.iloc[0]
                    taiex_norm = (taiex_aligned * scale).tolist()
                    taiex_dates = taiex_aligned.index.strftime("%Y-%m-%d").tolist()
                    benchmark = [
                        {"date": d, "value": round(v, 0)}
                        for d, v in zip(taiex_dates, taiex_norm)
                    ]
        except Exception:
            pass  # Benchmark is optional

        # Holdings count per day (from trades)
        holdings_count = _compute_holdings_count(dates, result.trades)

        # Monthly returns
        monthly_returns = _compute_monthly_returns(eq_df)

        # MDD duration (days from peak to recovery)
        mdd_info = _compute_mdd_info(eq_df)

        # Trade summary for chart markers
        trade_markers = []
        for t in result.trades:
            trade_markers.append({
                "code": t.code,
                "date_open": t.date_open,
                "date_close": t.date_close,
                "return_pct": round(t.return_pct, 4),
                "exit_reason": t.exit_reason,
                "entry_type": t.entry_type,
            })

        return make_serializable({
            "dates": dates,
            "equity": equity,
            "benchmark": benchmark,
            "drawdown": drawdown,
            "holdings_count": holdings_count,
            "monthly_returns": monthly_returns,
            "mdd_info": mdd_info,
            "trade_markers": trade_markers,
            # Summary stats
            "total_return": result.total_return,
            "annual_return": result.annual_return,
            "max_drawdown": result.max_drawdown,
            "sharpe_ratio": result.sharpe_ratio,
            "calmar_ratio": result.calmar_ratio,
            "profit_factor": result.profit_factor,
            "win_rate": result.win_rate,
            "total_trades": result.total_trades,
            "avg_return": result.avg_return,
            "avg_holding_days": result.avg_holding_days,
            "max_positions_used": result.max_positions_used,
            "avg_positions": result.avg_positions,
            "taiex_guard_activations": result.taiex_guard_activations,
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _compute_holdings_count(dates: list[str], trades) -> list[int]:
    """Compute number of open positions for each date."""
    import pandas as pd
    counts = []
    for d in dates:
        n = 0
        for t in trades:
            if t.date_open and t.date_close:
                if t.date_open <= d <= t.date_close:
                    n += 1
            elif t.date_open and not t.date_close:
                if t.date_open <= d:
                    n += 1
        counts.append(n)
    return counts


def _compute_monthly_returns(eq_df) -> list[dict]:
    """Compute monthly returns from equity DataFrame."""
    import pandas as pd
    equity = eq_df["equity"]
    # Resample to month-end
    monthly = equity.resample("ME").last()
    monthly_ret = monthly.pct_change().dropna()
    result = []
    for dt, ret in monthly_ret.items():
        result.append({
            "year": dt.year,
            "month": dt.month,
            "return_pct": round(float(ret) * 100, 2),
        })
    return result


def _compute_mdd_info(eq_df) -> dict:
    """Compute max drawdown duration and peak-to-trough info."""
    import pandas as pd
    equity = eq_df["equity"]
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max

    # Find MDD trough
    mdd_idx = drawdown.idxmin()
    mdd_val = float(drawdown.min())

    # Find peak before MDD trough
    peak_idx = running_max.loc[:mdd_idx].idxmax()

    # Find recovery after MDD trough (equity >= peak value)
    peak_val = equity.loc[peak_idx]
    recovery_mask = equity.loc[mdd_idx:] >= peak_val
    recovery_idx = None
    if recovery_mask.any():
        recovery_idx = recovery_mask.idxmax()

    duration_days = (mdd_idx - peak_idx).days if hasattr(mdd_idx - peak_idx, 'days') else 0
    recovery_days = None
    if recovery_idx is not None:
        recovery_days = (recovery_idx - mdd_idx).days if hasattr(recovery_idx - mdd_idx, 'days') else None

    return {
        "peak_date": peak_idx.strftime("%Y-%m-%d") if hasattr(peak_idx, 'strftime') else str(peak_idx),
        "trough_date": mdd_idx.strftime("%Y-%m-%d") if hasattr(mdd_idx, 'strftime') else str(mdd_idx),
        "recovery_date": recovery_idx.strftime("%Y-%m-%d") if recovery_idx is not None and hasattr(recovery_idx, 'strftime') else None,
        "mdd_pct": round(mdd_val * 100, 2),
        "drawdown_days": duration_days,
        "recovery_days": recovery_days,
        "total_underwater_days": duration_days + (recovery_days or 0),
    }


@router.post("/risk/stress-test")
def run_stress_test_endpoint(req: RiskAssessmentRequest):
    """R60: Run stress tests on portfolio."""
    from data.fetcher import get_stock_data, get_taiex_data
    from analysis.risk import calculate_portfolio_beta
    from backtest.risk_manager import run_stress_test

    try:
        holdings = req.holdings or {}
        if not holdings and req.stock_codes:
            # Equal weight if no explicit holdings
            val = req.portfolio_value / len(req.stock_codes)
            holdings = {c: val for c in req.stock_codes}

        # Get betas
        stock_data = {}
        for code in holdings:
            df = get_stock_data(code, period_days=365)
            if df is not None and len(df) > 0:
                stock_data[code] = df

        market_df = get_taiex_data(period_days=365)
        betas = calculate_portfolio_beta(stock_data, market_df) if market_df is not None else {}

        results = run_stress_test(holdings, betas, portfolio_value=req.portfolio_value)
        return [
            {
                "scenario": r.scenario,
                "portfolio_pnl": r.portfolio_pnl,
                "portfolio_pnl_amt": r.portfolio_pnl_amt,
                "worst_stock": r.worst_stock,
                "worst_stock_pnl": r.worst_stock_pnl,
                "details": r.details,
            }
            for r in results
        ]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/risk/circuit-breaker")
def check_circuit_breaker(
    daily_pnl: float = 0.0,
    weekly_pnl: float = 0.0,
    monthly_pnl: float = 0.0,
    consecutive_losses: int = 0,
):
    """R60: Evaluate circuit breaker conditions."""
    from backtest.risk_manager import evaluate_circuit_breaker
    result = evaluate_circuit_breaker(
        daily_pnl=daily_pnl,
        weekly_pnl=weekly_pnl,
        monthly_pnl=monthly_pnl,
        consecutive_losses=consecutive_losses,
    )
    return result.to_dict()
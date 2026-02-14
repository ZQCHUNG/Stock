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
        })

    return {
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
        "equity_curve": series_to_response(result.equity_curve),
        "daily_returns": series_to_response(result.daily_returns),
        "trades": trades,
    }


@router.post("/{code}/v4")
def run_v4_backtest(code: str, req: BacktestRequest):
    """執行 v4 回測"""
    from data.fetcher import get_stock_data
    from backtest.engine import run_backtest_v4
    try:
        df = get_stock_data(code, period_days=req.period_days)
        result = run_backtest_v4(
            df, initial_capital=req.initial_capital, params=req.params,
            commission_rate=req.commission_rate, tax_rate=req.tax_rate,
            slippage=req.slippage,
        )
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

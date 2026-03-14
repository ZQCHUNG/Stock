"""Rolling Backtest — 前推一致性測試（Walk-Forward Consistency Test）

驗證 v4 策略是否在不同市場環境下表現穩定：
- 分割為多個半年視窗
- 用相同固定參數跑每個視窗
- 比較勝率、報酬率、最大回撤
- 重點：2022 年空頭（萬八→萬二）是否能保本

設計理念（與 Gemini 技術總監討論 R10）：
- 我們的 v4 是固定參數策略，不是 per-period 優化
- 所以這是 Consistency Test，不是 Walk-Forward Optimization
- 目的：驗證策略不是只在特定行情賺錢（排除過擬合）
"""

from dataclasses import dataclass, field
import pandas as pd
import numpy as np
from backtest.engine import BacktestEngine, BacktestResult
import logging
logger = logging.getLogger(__name__)



@dataclass
class WindowResult:
    """單一視窗回測結果"""
    window_name: str = ""
    start_date: str = ""
    end_date: str = ""
    trading_days: int = 0
    total_return: float = 0.0
    annual_return: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0


@dataclass
class RollingBacktestResult:
    """Rolling Backtest 結果"""
    windows: list[WindowResult] = field(default_factory=list)
    stock_code: str = ""

    # 一致性指標
    avg_return: float = 0.0
    return_std: float = 0.0
    min_return: float = 0.0
    max_return: float = 0.0
    positive_windows: int = 0
    total_windows: int = 0
    avg_win_rate: float = 0.0
    avg_max_drawdown: float = 0.0
    consistency_score: float = 0.0  # 0-100


def run_rolling_backtest(
    df: pd.DataFrame,
    initial_capital: float = 1_000_000,
    window_months: int = 6,
    params: dict | None = None,
) -> RollingBacktestResult:
    """執行 Rolling Backtest（前推一致性測試）

    Args:
        df: 完整股價 DataFrame（建議 3-5 年）
        initial_capital: 每個視窗的初始資金
        window_months: 視窗大小（月），預設 6 個月
        params: v4 策略參數覆蓋

    Returns:
        RollingBacktestResult
    """
    if df is None or len(df) < 60:
        return RollingBacktestResult()

    engine = BacktestEngine(initial_capital=initial_capital)
    windows: list[WindowResult] = []

    # 按半年分割
    start = df.index[0]
    end = df.index[-1]

    current = start
    while current < end:
        window_end = current + pd.DateOffset(months=window_months)
        if window_end > end:
            window_end = end

        # 取出視窗資料（加入前 60 天暖機期以確保指標穩定）
        warmup_start = current - pd.DateOffset(days=90)
        window_data = df.loc[warmup_start:window_end]

        if len(window_data) < 60:
            current = window_end
            continue

        # 執行回測
        try:
            result = engine.run_v4(window_data, params=params)
        except Exception as e:
            logger.debug(f"Optional operation failed: {e}")
            current = window_end
            continue

        # 計算此視窗的實際交易天數（排除暖機期）
        actual_window = df.loc[current:window_end]
        trading_days = len(actual_window)

        # 標記視窗名稱
        year = current.year
        half = "H1" if current.month <= 6 else "H2"
        window_name = f"{year}{half}"

        wr = WindowResult(
            window_name=window_name,
            start_date=current.strftime("%Y-%m-%d"),
            end_date=min(window_end, end).strftime("%Y-%m-%d"),
            trading_days=trading_days,
            total_return=result.total_return,
            annual_return=result.annual_return,
            max_drawdown=result.max_drawdown,
            win_rate=result.win_rate,
            total_trades=result.total_trades,
            profit_factor=result.profit_factor,
            sharpe_ratio=result.sharpe_ratio,
            avg_win=result.avg_win,
            avg_loss=result.avg_loss,
        )
        windows.append(wr)

        current = window_end

    if not windows:
        return RollingBacktestResult()

    # 計算一致性指標
    returns = [w.total_return for w in windows]
    win_rates = [w.win_rate for w in windows]
    drawdowns = [w.max_drawdown for w in windows]

    avg_return = float(np.mean(returns))
    return_std = float(np.std(returns))
    positive = sum(1 for r in returns if r > 0)

    # 一致性分數 (0-100)
    # 權重：回撤控制 50%（存活優先）+ 正報酬視窗 30% + 報酬穩定度 20%
    # 回撤懲罰：任何視窗 MaxDD > -15% 時扣分（動量策略回撤容忍度低）
    win_pct = positive / len(windows)
    stability = max(0, 1 - return_std / max(abs(avg_return), 0.01))
    dd_control = max(0, 1 + np.mean(drawdowns) / 0.3)  # 回撤 < 30% 得分

    # 回撤懲罰機制：超過 -15% 的視窗數量越多，扣分越重
    severe_dd_count = sum(1 for d in drawdowns if d < -0.15)
    dd_penalty = severe_dd_count / len(windows)  # 0~1

    consistency = (win_pct * 30 + stability * 20 + dd_control * 50)
    consistency *= (1 - dd_penalty * 0.5)  # 每個嚴重回撤視窗扣 50%/N
    consistency = max(0, min(100, consistency))

    return RollingBacktestResult(
        windows=windows,
        avg_return=avg_return,
        return_std=return_std,
        min_return=float(np.min(returns)),
        max_return=float(np.max(returns)),
        positive_windows=positive,
        total_windows=len(windows),
        avg_win_rate=float(np.mean(win_rates)),
        avg_max_drawdown=float(np.mean(drawdowns)),
        consistency_score=consistency,
    )


def run_parameter_sensitivity(
    df: pd.DataFrame,
    base_params: dict | None = None,
    initial_capital: float = 1_000_000,
) -> list[dict]:
    """Parameter Sensitivity Analysis（參數敏感度分析）

    測試不同參數組合對策略表現的影響。
    如果微小參數變化導致結果劇烈變化，則策略可能過擬合。

    Args:
        df: 股價 DataFrame
        base_params: 基礎參數
        initial_capital: 初始資金

    Returns:
        list of dict, 每個 dict 含參數組合和對應結果
    """
    from config import STRATEGY_V4_PARAMS


    base = dict(STRATEGY_V4_PARAMS)
    if base_params:
        base.update(base_params)

    engine = BacktestEngine(initial_capital=initial_capital)
    results = []

    # 測試 ADX 門檻變化
    for adx in [14, 16, 18, 20, 22, 25]:
        p = dict(base)
        p["adx_min"] = adx
        try:
            r = engine.run_v4(df, params=p)
            results.append({
                "param": "ADX",
                "value": adx,
                "return": r.total_return,
                "win_rate": r.win_rate,
                "trades": r.total_trades,
                "max_dd": r.max_drawdown,
                "sharpe": r.sharpe_ratio,
            })
        except Exception as e:
            logger.debug(f"Skipping due to operation error: {e}")
            continue

    # 測試停利門檻變化
    for tp in [0.06, 0.08, 0.10, 0.12, 0.15, 0.20]:
        p = dict(base)
        p["take_profit_pct"] = tp
        try:
            r = engine.run_v4(df, params=p)
            results.append({
                "param": "TP%",
                "value": f"{tp:.0%}",
                "return": r.total_return,
                "win_rate": r.win_rate,
                "trades": r.total_trades,
                "max_dd": r.max_drawdown,
                "sharpe": r.sharpe_ratio,
            })
        except Exception as e:
            logger.debug(f"Skipping due to operation error: {e}")
            continue

    # 測試停損門檻變化
    for sl in [0.04, 0.05, 0.07, 0.10, 0.12]:
        p = dict(base)
        p["stop_loss_pct"] = sl
        try:
            r = engine.run_v4(df, params=p)
            results.append({
                "param": "SL%",
                "value": f"{sl:.0%}",
                "return": r.total_return,
                "win_rate": r.win_rate,
                "trades": r.total_trades,
                "max_dd": r.max_drawdown,
                "sharpe": r.sharpe_ratio,
            })
        except Exception as e:
            logger.debug(f"Skipping due to operation error: {e}")
            continue

    # 測試移動停利變化
    for trail in [0.01, 0.02, 0.03, 0.05]:
        p = dict(base)
        p["trailing_stop_pct"] = trail
        try:
            r = engine.run_v4(df, params=p)
            results.append({
                "param": "Trail%",
                "value": f"{trail:.0%}",
                "return": r.total_return,
                "win_rate": r.win_rate,
                "trades": r.total_trades,
                "max_dd": r.max_drawdown,
                "sharpe": r.sharpe_ratio,
            })
        except Exception as e:
            logger.debug(f"Skipping due to operation error: {e}")
            continue

    return results

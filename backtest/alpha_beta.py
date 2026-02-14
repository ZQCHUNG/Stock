"""Alpha/Beta 風險分析模組

基於 CAPM 模型計算策略的風險調整後績效指標：
- Jensen's Alpha: α = Rp - [Rf + β(Rm - Rf)]
- Up/Down Beta: 大盤上漲/下跌時的 Beta
- Capture Ratio: 上行/下行捕捉率
- Rolling Alpha: 滾動窗口的 Jensen's Alpha

注意：基準 (^TWII) 為價格指數，未含配息。
Alpha 在除權息旺季（7-8 月）可能因此產生季節性偏差。
"""

import pandas as pd
import numpy as np
from scipy import stats


def calculate_alpha_beta(
    equity_curve: pd.Series,
    benchmark_curve: pd.Series,
    rf_annual: float = 0.015,
    rolling_window: int = 60,
) -> dict:
    """計算 Alpha/Beta 風險分析指標

    Args:
        equity_curve: 策略權益曲線 (index=date, values=equity)
        benchmark_curve: 基準指數收盤價 (index=date, values=close)
        rf_annual: 年化無風險利率 (預設 1.5%)
        rolling_window: Rolling Alpha 窗口天數 (預設 60)

    Returns:
        dict 包含:
        - alpha_jensen: Jensen's Alpha (年化)
        - excess_return: 超額報酬 = 策略年化報酬 - Rf
        - alpha_market: 策略年化報酬 - 基準年化報酬
        - beta: 整體 Beta
        - up_beta: 上行 Beta (Rm > 0)
        - down_beta: 下行 Beta (Rm < 0)
        - upside_capture: 上行捕捉率
        - downside_capture: 下行捕捉率
        - r_squared: 回歸 R²
        - rolling_alpha: Series of rolling Jensen's Alpha
        - rolling_alpha_ema: EMA(20) 平滑線
        - benchmark_disclaimer: 基準指數說明
    """
    result = _empty_result()

    if equity_curve.empty or benchmark_curve.empty:
        return result

    # 對齊日期（取交集）
    strat_returns = equity_curve.pct_change().dropna()
    bench_returns = benchmark_curve.pct_change().dropna()

    common_dates = strat_returns.index.intersection(bench_returns.index)
    if len(common_dates) < 30:
        return result

    strat_ret = strat_returns.loc[common_dates]
    bench_ret = bench_returns.loc[common_dates]

    # 日化無風險利率
    rf_daily = (1 + rf_annual) ** (1 / 252) - 1
    trading_days = len(common_dates)

    # ===== 整體 Beta & Jensen's Alpha =====
    slope, intercept, r_value, _, _ = stats.linregress(bench_ret, strat_ret)
    beta = slope
    r_squared = r_value ** 2

    # Jensen's Alpha (年化)
    # α_daily = intercept (from regression: Rp = α + β*Rm)
    # 更精確的公式: α = Rp - [Rf + β(Rm - Rf)]
    strat_annual = (1 + strat_ret.mean()) ** 252 - 1
    bench_annual = (1 + bench_ret.mean()) ** 252 - 1
    alpha_jensen = strat_annual - (rf_annual + beta * (bench_annual - rf_annual))

    # 超額報酬 (Net of Rf) — 不是 Alpha，純粹「贏過定存多少」
    excess_return = strat_annual - rf_annual

    # Alpha vs Market — 策略報酬 vs 大盤報酬
    alpha_market = strat_annual - bench_annual

    # ===== Up/Down Beta =====
    up_mask = bench_ret > 0
    down_mask = bench_ret < 0

    up_beta = _calc_beta(strat_ret[up_mask], bench_ret[up_mask])
    down_beta = _calc_beta(strat_ret[down_mask], bench_ret[down_mask])

    # ===== Capture Ratio =====
    upside_capture = _calc_capture(strat_ret[up_mask], bench_ret[up_mask])
    downside_capture = _calc_capture(strat_ret[down_mask], bench_ret[down_mask])

    # ===== Rolling Alpha =====
    rolling_alpha = _calc_rolling_alpha(
        strat_ret, bench_ret, rf_daily, rolling_window,
    )
    rolling_alpha_ema = rolling_alpha.ewm(span=20, min_periods=10).mean()

    result.update({
        "alpha_jensen": alpha_jensen,
        "excess_return": excess_return,
        "alpha_market": alpha_market,
        "beta": beta,
        "up_beta": up_beta,
        "down_beta": down_beta,
        "upside_capture": upside_capture,
        "downside_capture": downside_capture,
        "r_squared": r_squared,
        "rolling_alpha": rolling_alpha,
        "rolling_alpha_ema": rolling_alpha_ema,
        "trading_days": trading_days,
        "benchmark_disclaimer": (
            "基準指數 (^TWII) 為價格指數，未含配息。"
            "Alpha 在除權息旺季可能產生季節性偏差。"
        ),
    })
    return result


def _empty_result() -> dict:
    return {
        "alpha_jensen": 0.0,
        "excess_return": 0.0,
        "alpha_market": 0.0,
        "beta": 0.0,
        "up_beta": 0.0,
        "down_beta": 0.0,
        "upside_capture": 0.0,
        "downside_capture": 0.0,
        "r_squared": 0.0,
        "rolling_alpha": pd.Series(dtype=float),
        "rolling_alpha_ema": pd.Series(dtype=float),
        "trading_days": 0,
        "benchmark_disclaimer": "",
    }


def _calc_beta(strat_ret: pd.Series, bench_ret: pd.Series) -> float:
    """計算 Beta (OLS slope)"""
    if len(strat_ret) < 10 or len(bench_ret) < 10:
        return 0.0
    slope, _, _, _, _ = stats.linregress(bench_ret, strat_ret)
    return slope


def _calc_capture(strat_ret: pd.Series, bench_ret: pd.Series) -> float:
    """計算 Capture Ratio = avg(strategy) / avg(benchmark)"""
    if len(strat_ret) < 5 or len(bench_ret) < 5:
        return 0.0
    avg_bench = bench_ret.mean()
    if abs(avg_bench) < 1e-10:
        return 0.0
    return strat_ret.mean() / avg_bench


def _calc_rolling_alpha(
    strat_ret: pd.Series,
    bench_ret: pd.Series,
    rf_daily: float,
    window: int,
) -> pd.Series:
    """計算 Rolling Jensen's Alpha (年化)

    每個窗口做一次 OLS 回歸：Rp = α + β*Rm
    年化: α_annual = (1 + α_daily)^252 - 1
    """
    alphas = pd.Series(index=strat_ret.index, dtype=float)

    for i in range(window, len(strat_ret)):
        s = strat_ret.iloc[i - window:i]
        b = bench_ret.iloc[i - window:i]

        if len(s) < window * 0.8:
            continue

        slope, intercept, _, _, _ = stats.linregress(b, s)

        # Jensen's Alpha: α = Rp_mean - [Rf + β(Rm_mean - Rf)]
        rp_mean = s.mean()
        rm_mean = b.mean()
        alpha_daily = rp_mean - (rf_daily + slope * (rm_mean - rf_daily))
        alpha_annual = (1 + alpha_daily) ** 252 - 1

        alphas.iloc[i] = alpha_annual

    return alphas.dropna()

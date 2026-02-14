"""Alpha/Beta 風險分析模組測試"""

import pandas as pd
import numpy as np
import pytest
from backtest.alpha_beta import calculate_alpha_beta, _calc_beta, _calc_capture


def _make_equity_curve(n=200, seed=42, trend=0.0005):
    """產生模擬權益曲線"""
    np.random.seed(seed)
    dates = pd.bdate_range("2024-01-01", periods=n)
    returns = np.random.normal(trend, 0.01, n)
    equity = 1_000_000 * np.cumprod(1 + returns)
    return pd.Series(equity, index=dates)


def _make_benchmark(n=200, seed=99, trend=0.0003):
    """產生模擬基準指數"""
    np.random.seed(seed)
    dates = pd.bdate_range("2024-01-01", periods=n)
    returns = np.random.normal(trend, 0.008, n)
    close = 18000 * np.cumprod(1 + returns)
    return pd.Series(close, index=dates)


class TestCalculateAlphaBeta:
    def test_basic_output_keys(self):
        equity = _make_equity_curve()
        bench = _make_benchmark()
        result = calculate_alpha_beta(equity, bench)

        expected_keys = [
            "alpha_jensen", "excess_return", "alpha_market",
            "beta", "up_beta", "down_beta",
            "upside_capture", "downside_capture",
            "r_squared", "rolling_alpha", "rolling_alpha_ema",
            "trading_days", "benchmark_disclaimer",
        ]
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_trading_days(self):
        equity = _make_equity_curve(n=200)
        bench = _make_benchmark(n=200)
        result = calculate_alpha_beta(equity, bench)
        assert result["trading_days"] > 100

    def test_beta_reasonable_range(self):
        equity = _make_equity_curve()
        bench = _make_benchmark()
        result = calculate_alpha_beta(equity, bench)
        # Beta should be in a reasonable range for correlated returns
        assert -5 < result["beta"] < 5

    def test_r_squared_range(self):
        equity = _make_equity_curve()
        bench = _make_benchmark()
        result = calculate_alpha_beta(equity, bench)
        assert 0 <= result["r_squared"] <= 1

    def test_up_down_beta_exist(self):
        equity = _make_equity_curve()
        bench = _make_benchmark()
        result = calculate_alpha_beta(equity, bench)
        # Up and down beta should be numbers
        assert isinstance(result["up_beta"], float)
        assert isinstance(result["down_beta"], float)

    def test_capture_ratios(self):
        equity = _make_equity_curve()
        bench = _make_benchmark()
        result = calculate_alpha_beta(equity, bench)
        # Capture ratios should be finite
        assert np.isfinite(result["upside_capture"])
        assert np.isfinite(result["downside_capture"])

    def test_rolling_alpha_is_series(self):
        equity = _make_equity_curve(n=200)
        bench = _make_benchmark(n=200)
        result = calculate_alpha_beta(equity, bench, rolling_window=60)
        assert isinstance(result["rolling_alpha"], pd.Series)
        # Should have entries for window onwards
        assert len(result["rolling_alpha"]) > 50

    def test_rolling_alpha_ema_smoothed(self):
        equity = _make_equity_curve(n=200)
        bench = _make_benchmark(n=200)
        result = calculate_alpha_beta(equity, bench)
        # EMA should be smoother (lower std) than raw
        if len(result["rolling_alpha"]) > 20 and len(result["rolling_alpha_ema"]) > 20:
            raw_std = result["rolling_alpha"].std()
            ema_std = result["rolling_alpha_ema"].std()
            assert ema_std <= raw_std * 1.1  # EMA should not be noisier

    def test_empty_equity(self):
        result = calculate_alpha_beta(pd.Series(dtype=float), _make_benchmark())
        assert result["trading_days"] == 0
        assert result["alpha_jensen"] == 0.0

    def test_empty_benchmark(self):
        result = calculate_alpha_beta(_make_equity_curve(), pd.Series(dtype=float))
        assert result["trading_days"] == 0

    def test_short_overlap(self):
        # Only 20 days overlap — below minimum of 30
        equity = _make_equity_curve(n=20)
        bench = _make_benchmark(n=20)
        result = calculate_alpha_beta(equity, bench)
        assert result["trading_days"] == 0

    def test_different_dates_aligned(self):
        """策略和基準有不同的交易日，應取交集"""
        np.random.seed(42)
        dates_a = pd.bdate_range("2024-01-01", periods=100)
        dates_b = pd.bdate_range("2024-01-05", periods=100)  # offset by few days
        equity = pd.Series(1e6 * np.cumprod(1 + np.random.normal(0.001, 0.01, 100)), index=dates_a)
        bench = pd.Series(18000 * np.cumprod(1 + np.random.normal(0.0003, 0.008, 100)), index=dates_b)
        result = calculate_alpha_beta(equity, bench)
        # Should work with partial overlap
        assert result["trading_days"] > 0

    def test_jensen_alpha_vs_excess_return(self):
        """Jensen's Alpha 和 Excess Return 不應相同（除非 Beta=1 且 Rm=Rf）"""
        equity = _make_equity_curve(trend=0.002)  # Strong uptrend
        bench = _make_benchmark(trend=0.001)
        result = calculate_alpha_beta(equity, bench)
        # They should be different values in general
        assert result["alpha_jensen"] != result["excess_return"] or result["beta"] == pytest.approx(1.0, abs=0.1)

    def test_benchmark_disclaimer_present(self):
        equity = _make_equity_curve()
        bench = _make_benchmark()
        result = calculate_alpha_beta(equity, bench)
        assert "價格指數" in result["benchmark_disclaimer"]

    def test_custom_rf_and_window(self):
        equity = _make_equity_curve(n=300)
        bench = _make_benchmark(n=300)
        result = calculate_alpha_beta(equity, bench, rf_annual=0.03, rolling_window=120)
        assert result["trading_days"] > 0
        # Rolling alpha should have fewer entries with larger window
        assert len(result["rolling_alpha"]) > 0


class TestHelpers:
    def test_calc_beta_insufficient_data(self):
        s = pd.Series([0.01] * 5)
        b = pd.Series([0.01] * 5)
        assert _calc_beta(s, b) == 0.0

    def test_calc_beta_with_data(self):
        np.random.seed(42)
        b = pd.Series(np.random.normal(0, 0.01, 100))
        s = 1.5 * b + np.random.normal(0, 0.005, 100)  # Beta ~1.5
        beta = _calc_beta(pd.Series(s), pd.Series(b))
        assert beta == pytest.approx(1.5, abs=0.3)

    def test_calc_capture_zero_benchmark(self):
        s = pd.Series([0.01] * 10)
        b = pd.Series([0.0] * 10)
        assert _calc_capture(s, b) == 0.0

    def test_calc_capture_normal(self):
        s = pd.Series([0.02, 0.01, 0.03, 0.015, 0.025])
        b = pd.Series([0.01, 0.005, 0.02, 0.01, 0.015])
        cap = _calc_capture(s, b)
        # Strategy avg = 0.02, Bench avg = 0.012 → capture = 1.667
        assert cap == pytest.approx(0.02 / 0.012, abs=0.01)

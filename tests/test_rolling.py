"""Rolling Backtest 測試"""

import pandas as pd
import numpy as np
import pytest

from backtest.rolling import (
    run_rolling_backtest,
    run_parameter_sensitivity,
    WindowResult,
    RollingBacktestResult,
)


@pytest.fixture
def long_uptrend_df():
    """3 年上升趨勢資料（適合 rolling backtest）"""
    np.random.seed(42)
    n = 750  # ~3 years of trading days
    dates = pd.bdate_range("2022-01-01", periods=n)
    base = 100.0 + np.arange(n) * 0.15 + np.random.normal(0, 1.5, n)
    close = np.maximum(base, 50)

    df = pd.DataFrame({
        "open": close - np.random.uniform(0, 1, n),
        "high": close + np.random.uniform(0, 2, n),
        "low": close - np.random.uniform(0, 2, n),
        "close": close,
        "volume": np.random.randint(5000, 50000, n).astype(float),
    }, index=dates)
    df.index.name = "date"
    return df


class TestRollingBacktest:
    """run_rolling_backtest 測試"""

    def test_returns_result_dataclass(self, long_uptrend_df):
        result = run_rolling_backtest(long_uptrend_df)
        assert isinstance(result, RollingBacktestResult)

    def test_has_multiple_windows(self, long_uptrend_df):
        result = run_rolling_backtest(long_uptrend_df, window_months=6)
        assert result.total_windows >= 3  # 3 years / 6 months = ~6 windows

    def test_window_result_fields(self, long_uptrend_df):
        result = run_rolling_backtest(long_uptrend_df)
        if result.windows:
            w = result.windows[0]
            assert isinstance(w, WindowResult)
            assert w.window_name != ""
            assert w.start_date != ""
            assert w.end_date != ""
            assert w.trading_days > 0

    def test_consistency_score_range(self, long_uptrend_df):
        result = run_rolling_backtest(long_uptrend_df)
        assert 0 <= result.consistency_score <= 100

    def test_aggregate_stats(self, long_uptrend_df):
        result = run_rolling_backtest(long_uptrend_df)
        if result.total_windows > 0:
            assert result.min_return <= result.max_return
            assert result.positive_windows <= result.total_windows
            assert 0 <= result.avg_win_rate <= 1

    def test_short_data_returns_empty(self):
        """資料太短應回傳空結果"""
        dates = pd.bdate_range("2024-01-01", periods=30)
        df = pd.DataFrame({
            "open": [100.0] * 30,
            "high": [101.0] * 30,
            "low": [99.0] * 30,
            "close": [100.0] * 30,
            "volume": [10000.0] * 30,
        }, index=dates)
        df.index.name = "date"
        result = run_rolling_backtest(df)
        assert result.total_windows == 0

    def test_none_data_returns_empty(self):
        result = run_rolling_backtest(None)
        assert result.total_windows == 0

    def test_custom_window_months(self, long_uptrend_df):
        result_3m = run_rolling_backtest(long_uptrend_df, window_months=3)
        result_12m = run_rolling_backtest(long_uptrend_df, window_months=12)
        # 3-month windows should produce more windows than 12-month
        assert result_3m.total_windows >= result_12m.total_windows

    def test_custom_params(self, long_uptrend_df):
        params = {"adx_min": 15, "rsi_low": 25}
        result = run_rolling_backtest(long_uptrend_df, params=params)
        assert isinstance(result, RollingBacktestResult)

    def test_window_names_format(self, long_uptrend_df):
        result = run_rolling_backtest(long_uptrend_df)
        for w in result.windows:
            # Format: "2022H1", "2022H2", etc.
            assert len(w.window_name) == 6
            assert w.window_name[:4].isdigit()
            assert w.window_name[4:] in ("H1", "H2")


class TestParameterSensitivity:
    """run_parameter_sensitivity 測試"""

    def test_returns_list(self, long_uptrend_df):
        results = run_parameter_sensitivity(long_uptrend_df)
        assert isinstance(results, list)

    def test_has_multiple_results(self, long_uptrend_df):
        results = run_parameter_sensitivity(long_uptrend_df)
        assert len(results) >= 10  # ADX(6) + TP(6) + SL(5) + Trail(4) = 21

    def test_result_fields(self, long_uptrend_df):
        results = run_parameter_sensitivity(long_uptrend_df)
        if results:
            r = results[0]
            assert "param" in r
            assert "value" in r
            assert "return" in r
            assert "win_rate" in r
            assert "trades" in r
            assert "max_dd" in r

    def test_covers_all_param_types(self, long_uptrend_df):
        results = run_parameter_sensitivity(long_uptrend_df)
        params_tested = {r["param"] for r in results}
        assert "ADX" in params_tested
        assert "TP%" in params_tested
        assert "SL%" in params_tested
        assert "Trail%" in params_tested

    def test_custom_base_params(self, long_uptrend_df):
        base = {"adx_min": 20, "take_profit_pct": 0.12}
        results = run_parameter_sensitivity(long_uptrend_df, base_params=base)
        assert isinstance(results, list)

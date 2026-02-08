"""模擬交易測試"""

import pandas as pd
import numpy as np
import pytest
from simulation.simulator import (
    MonthlySimulator,
    SimulationResult,
    run_simulation,
    run_simulation_v4,
    simulation_to_dataframe,
    format_simulation_summary,
)


class TestMonthlySimulator:
    def test_basic_run(self, sample_ohlcv):
        sim = MonthlySimulator(initial_capital=1_000_000)
        result = sim.run(sample_ohlcv, days=20)
        assert isinstance(result, SimulationResult)
        assert len(result.daily_records) <= 20

    def test_initial_capital(self, sample_ohlcv):
        sim = MonthlySimulator(initial_capital=1_000_000)
        result = sim.run(sample_ohlcv, days=20)
        assert result.initial_capital == 1_000_000

    def test_daily_records_continuity(self, sample_ohlcv):
        sim = MonthlySimulator(initial_capital=1_000_000)
        result = sim.run(sample_ohlcv, days=20)
        for r in result.daily_records:
            assert r.total_equity > 0
            assert r.cash >= 0

    def test_flat_price_no_crash(self, flat_price_df):
        sim = MonthlySimulator(initial_capital=1_000_000)
        result = sim.run(flat_price_df, days=20)
        assert isinstance(result, SimulationResult)


class TestSimulatorV4:
    def test_basic_run(self, uptrend_df):
        sim = MonthlySimulator(initial_capital=1_000_000)
        result = sim.run_v4(uptrend_df, days=30)
        assert isinstance(result, SimulationResult)

    def test_composite_score_not_nan(self, uptrend_df):
        """composite_score 不應為 NaN"""
        sim = MonthlySimulator(initial_capital=1_000_000)
        result = sim.run_v4(uptrend_df, days=30)
        for r in result.daily_records:
            assert not np.isnan(r.composite_score)
            assert not np.isinf(r.composite_score)

    def test_custom_params(self, uptrend_df):
        sim = MonthlySimulator(initial_capital=1_000_000)
        result = sim.run_v4(uptrend_df, days=30, params={"adx_min": 100})
        # 極高門檻，不應有交易
        assert result.total_trades == 0

    def test_max_drawdown(self, uptrend_df):
        sim = MonthlySimulator(initial_capital=1_000_000)
        result = sim.run_v4(uptrend_df, days=30)
        assert result.max_drawdown <= 0


class TestConvenienceFunctions:
    def test_run_simulation(self, sample_ohlcv):
        result = run_simulation(sample_ohlcv, initial_capital=500_000, days=15)
        assert isinstance(result, SimulationResult)
        assert result.initial_capital == 500_000

    def test_run_simulation_v4(self, uptrend_df):
        result = run_simulation_v4(uptrend_df, initial_capital=500_000, days=15)
        assert isinstance(result, SimulationResult)


class TestOutputFormatting:
    def test_simulation_to_dataframe(self, sample_ohlcv):
        sim = MonthlySimulator(initial_capital=1_000_000)
        result = sim.run(sample_ohlcv, days=10)
        df = simulation_to_dataframe(result)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == len(result.daily_records)
        expected_cols = ["日期", "收盤價", "訊號", "動作", "持有股數",
                         "現金", "持倉市值", "總權益", "當日損益", "當日報酬", "綜合評分"]
        for col in expected_cols:
            assert col in df.columns

    def test_format_summary(self, sample_ohlcv):
        sim = MonthlySimulator(initial_capital=1_000_000)
        result = sim.run(sample_ohlcv, days=10)
        summary = format_simulation_summary(result)
        assert isinstance(summary, str)
        assert "模擬交易績效摘要" in summary

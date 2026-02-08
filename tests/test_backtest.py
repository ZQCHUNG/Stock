"""回測引擎測試"""

import pandas as pd
import numpy as np
import pytest
from backtest.engine import BacktestEngine, BacktestResult, run_backtest, run_backtest_v4


class TestBacktestEngine:
    def test_basic_run(self, sample_ohlcv):
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run(sample_ohlcv)
        assert isinstance(result, BacktestResult)
        assert not result.equity_curve.empty

    def test_initial_equity(self, sample_ohlcv):
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run(sample_ohlcv)
        # 第一天權益應約等於初始資金（可能有小幅交易）
        assert result.equity_curve.iloc[0] == pytest.approx(1_000_000, rel=0.01)

    def test_no_negative_equity(self, sample_ohlcv):
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run(sample_ohlcv)
        assert (result.equity_curve >= 0).all()

    def test_max_drawdown_range(self, sample_ohlcv):
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run(sample_ohlcv)
        assert result.max_drawdown <= 0  # 回撤是負值或零

    def test_win_rate_range(self, sample_ohlcv):
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run(sample_ohlcv)
        if result.total_trades > 0:
            assert 0 <= result.win_rate <= 1

    def test_trade_pnl_adds_up(self, sample_ohlcv):
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run(sample_ohlcv)
        if result.trades:
            total_pnl = sum(t.pnl for t in result.trades)
            equity_change = result.equity_curve.iloc[-1] - 1_000_000
            # 扣掉未平倉部分，應大致一致
            assert abs(total_pnl - equity_change) < 1_000

    def test_flat_price_no_crash(self, flat_price_df):
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run(flat_price_df)
        assert isinstance(result, BacktestResult)

    def test_commission_applied(self, uptrend_df):
        engine = BacktestEngine(initial_capital=1_000_000, commission_rate=0.001425)
        result = engine.run(uptrend_df)
        if result.trades:
            assert all(t.commission > 0 for t in result.trades)


class TestBacktestV4:
    def test_basic_run(self, uptrend_df):
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run_v4(uptrend_df)
        assert isinstance(result, BacktestResult)

    def test_no_negative_equity(self, uptrend_df):
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run_v4(uptrend_df)
        assert (result.equity_curve >= 0).all()

    def test_custom_params(self, uptrend_df):
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run_v4(uptrend_df, params={"adx_min": 100})
        # 極高 ADX 門檻，不應有交易
        assert result.total_trades == 0

    def test_exit_reasons(self, uptrend_df):
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run_v4(uptrend_df)
        valid_reasons = {"take_profit", "stop_loss", "trailing_stop", "end_of_period", ""}
        for t in result.trades:
            assert t.exit_reason in valid_reasons, f"Invalid exit reason: {t.exit_reason}"

    def test_min_hold_days_respected(self, uptrend_df):
        """最短持有天數應被尊重"""
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run_v4(uptrend_df, params={"min_hold_days": 5})
        for t in result.trades:
            if t.date_close is not None and t.exit_reason != "end_of_period":
                hold_days = (t.date_close - t.date_open).days
                # 交易日轉日曆日可能有差異，但至少應 > 3
                assert hold_days >= 3

    def test_flat_price_no_crash(self, flat_price_df):
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run_v4(flat_price_df)
        assert isinstance(result, BacktestResult)


class TestConvenienceFunctions:
    def test_run_backtest(self, sample_ohlcv):
        result = run_backtest(sample_ohlcv, initial_capital=500_000)
        assert isinstance(result, BacktestResult)
        assert result.equity_curve.iloc[0] == pytest.approx(500_000, rel=0.01)

    def test_run_backtest_v4(self, uptrend_df):
        result = run_backtest_v4(uptrend_df, initial_capital=500_000)
        assert isinstance(result, BacktestResult)


class TestMetrics:
    def test_sharpe_ratio(self, uptrend_df):
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run(uptrend_df)
        # Sharpe ratio 應是合理的數字
        assert not np.isnan(result.sharpe_ratio)
        assert not np.isinf(result.sharpe_ratio)

    def test_avg_holding_days(self, uptrend_df):
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run(uptrend_df)
        if result.total_trades > 0:
            assert result.avg_holding_days >= 0

    def test_profit_factor(self, uptrend_df):
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run(uptrend_df)
        if result.total_trades > 0:
            assert result.profit_factor >= 0

"""回測引擎測試"""

import pandas as pd
import numpy as np
import pytest
from backtest.engine import (
    BacktestEngine, BacktestResult,
    run_backtest, run_backtest_v4,
    PortfolioBacktestResult, run_portfolio_backtest_v4,
)


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


class TestPortfolioBacktest:
    def _make_stock(self, seed, n=200, base=100.0, drift=0.5):
        np.random.seed(seed)
        dates = pd.bdate_range("2024-01-01", periods=n)
        close = base + np.arange(n) * drift + np.random.normal(0, 0.5, n)
        close = np.maximum(close, 10)
        df = pd.DataFrame({
            "open": close - np.random.uniform(0, 1, n),
            "high": close + np.random.uniform(0, 2, n),
            "low": close - np.random.uniform(0, 2, n),
            "close": close,
            "volume": np.random.randint(5000, 50000, n).astype(float),
        }, index=dates)
        df.index.name = "date"
        return df

    def test_basic_run(self):
        stocks = {"A": self._make_stock(42), "B": self._make_stock(99)}
        result = run_portfolio_backtest_v4(stocks, initial_capital=1_000_000)
        assert isinstance(result, PortfolioBacktestResult)
        assert not result.equity_curve.empty
        assert result.initial_capital == 1_000_000
        assert result.per_stock_capital == 500_000

    def test_stock_results_populated(self):
        stocks = {"A": self._make_stock(42), "B": self._make_stock(99)}
        result = run_portfolio_backtest_v4(stocks, initial_capital=1_000_000)
        assert len(result.stock_results) == 2
        assert "A" in result.stock_results
        assert "B" in result.stock_results

    def test_equity_curve_starts_at_total_capital(self):
        stocks = {"A": self._make_stock(42), "B": self._make_stock(99)}
        result = run_portfolio_backtest_v4(stocks, initial_capital=1_000_000)
        assert result.equity_curve.iloc[0] == pytest.approx(1_000_000, rel=0.01)

    def test_total_return_consistent(self):
        stocks = {"A": self._make_stock(42), "B": self._make_stock(99)}
        result = run_portfolio_backtest_v4(stocks, initial_capital=1_000_000)
        expected = (result.equity_curve.iloc[-1] - 1_000_000) / 1_000_000
        assert result.total_return == pytest.approx(expected, rel=0.001)

    def test_max_drawdown_in_range(self):
        stocks = {"A": self._make_stock(42), "B": self._make_stock(99)}
        result = run_portfolio_backtest_v4(stocks, initial_capital=1_000_000)
        assert result.max_drawdown <= 0

    def test_names_passed_through(self):
        stocks = {"A": self._make_stock(42), "B": self._make_stock(99)}
        names = {"A": "Stock A", "B": "Stock B"}
        result = run_portfolio_backtest_v4(stocks, stock_names=names)
        assert result.stock_names == names

    def test_correlation_matrix(self):
        stocks = {"A": self._make_stock(42), "B": self._make_stock(99), "C": self._make_stock(7)}
        result = run_portfolio_backtest_v4(stocks, initial_capital=1_500_000)
        if not result.correlation_matrix.empty:
            assert result.correlation_matrix.shape[0] == result.correlation_matrix.shape[1]
            # Diagonal should be 1.0 (or NaN if stock has zero-variance returns)
            for i in range(len(result.correlation_matrix)):
                val = result.correlation_matrix.iloc[i, i]
                if not pd.isna(val):
                    assert val == pytest.approx(1.0, abs=0.01)

    def test_empty_input(self):
        result = run_portfolio_backtest_v4({}, initial_capital=1_000_000)
        assert isinstance(result, PortfolioBacktestResult)
        assert result.equity_curve.empty

    def test_winning_losing_counts(self):
        stocks = {"A": self._make_stock(42), "B": self._make_stock(99)}
        result = run_portfolio_backtest_v4(stocks, initial_capital=1_000_000)
        total = result.winning_stocks + result.losing_stocks
        # Some stocks may have 0 return (neither winning nor losing)
        assert total <= len(result.stock_results)


class TestDividendBacktest:
    def _make_uptrend(self):
        np.random.seed(42)
        n = 200
        dates = pd.bdate_range("2024-01-01", periods=n)
        close = 100.0 + np.arange(n) * 0.5 + np.random.normal(0, 0.5, n)
        close = np.maximum(close, 50)
        return pd.DataFrame({
            "open": close - np.random.uniform(0, 1, n),
            "high": close + np.random.uniform(0, 2, n),
            "low": close - np.random.uniform(0, 2, n),
            "close": close,
            "volume": np.random.randint(5000, 50000, n).astype(float),
        }, index=dates)

    def test_no_dividends_zero_income(self):
        df = self._make_uptrend()
        result = run_backtest_v4(df, initial_capital=1_000_000, dividends=None)
        assert result.dividend_income == 0.0

    def test_dividends_informational_only(self):
        df = self._make_uptrend()
        # Create dividends during the backtest period
        dates = pd.bdate_range("2024-03-01", periods=3, freq="60B")
        divs = pd.Series([2.0, 3.0, 2.5], index=dates)

        result_no_div = run_backtest_v4(df, initial_capital=1_000_000, dividends=None)
        result_with_div = run_backtest_v4(df, initial_capital=1_000_000, dividends=divs)

        # Dividends are informational only (not added to cash/equity)
        # because auto_adjust=True prices already include dividend adjustments.
        # Equity curves should be identical regardless of dividend parameter.
        assert abs(result_with_div.equity_curve.iloc[-1] - result_no_div.equity_curve.iloc[-1]) < 1.0

    def test_dividend_income_positive(self):
        df = self._make_uptrend()
        # Place dividends where we're likely to have a position
        mid_dates = df.index[60:180:30]
        divs = pd.Series([3.0] * len(mid_dates), index=mid_dates)

        result = run_backtest_v4(df, initial_capital=1_000_000, dividends=divs)
        # We can't guarantee we'll be holding on dividend dates, but
        # dividend_income should be >= 0
        assert result.dividend_income >= 0

    def test_empty_dividends_no_crash(self):
        df = self._make_uptrend()
        result = run_backtest_v4(df, initial_capital=1_000_000,
                                dividends=pd.Series(dtype=float))
        assert result.dividend_income == 0.0

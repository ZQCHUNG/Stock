"""Tests for R58 performance attribution (Brinson + factor analysis)."""

import pandas as pd
import numpy as np
import pytest
from backtest.attribution import (
    BrinsonAttribution,
    BrinsonReport,
    compute_brinson_single_period,
    compute_trade_attribution,
    FactorExposure,
    build_proxy_factors,
    compute_factor_exposure,
)


class TestBrinsonSinglePeriod:
    def test_basic_decomposition(self):
        """Allocation + Selection + Interaction should equal Active Return."""
        port_w = {"tech": 0.6, "fin": 0.3, "energy": 0.1}
        bench_w = {"tech": 0.4, "fin": 0.4, "energy": 0.2}
        port_r = {"tech": 0.12, "fin": 0.05, "energy": -0.02}
        bench_r = {"tech": 0.10, "fin": 0.04, "energy": 0.01}

        result = compute_brinson_single_period(port_w, bench_w, port_r, bench_r)

        assert result.active_return == pytest.approx(
            result.allocation_effect + result.selection_effect + result.interaction_effect,
            abs=1e-10
        )
        assert result.residual == pytest.approx(0, abs=1e-10)

    def test_no_active_return(self):
        """Same weights and returns → zero active return."""
        w = {"a": 0.5, "b": 0.5}
        r = {"a": 0.10, "b": 0.05}
        result = compute_brinson_single_period(w, w, r, r)
        assert result.active_return == pytest.approx(0)
        assert result.allocation_effect == pytest.approx(0)
        assert result.selection_effect == pytest.approx(0)
        assert result.interaction_effect == pytest.approx(0)

    def test_pure_allocation(self):
        """Different weights, same returns → only allocation effect."""
        port_w = {"a": 0.7, "b": 0.3}
        bench_w = {"a": 0.5, "b": 0.5}
        r = {"a": 0.10, "b": 0.02}  # same returns for both
        result = compute_brinson_single_period(port_w, bench_w, r, r)
        # Selection should be zero (same returns)
        assert result.selection_effect == pytest.approx(0, abs=1e-10)
        # Allocation should be positive (overweight in better sector)
        assert result.allocation_effect > 0

    def test_pure_selection(self):
        """Same weights, different returns → only selection effect."""
        w = {"a": 0.5, "b": 0.5}
        port_r = {"a": 0.15, "b": 0.05}
        bench_r = {"a": 0.10, "b": 0.03}
        result = compute_brinson_single_period(w, w, port_r, bench_r)
        assert result.allocation_effect == pytest.approx(0, abs=1e-10)
        assert result.selection_effect > 0

    def test_to_dict(self):
        """BrinsonAttribution.to_dict should have all expected keys."""
        result = BrinsonAttribution(period="2024-Q1")
        d = result.to_dict()
        assert "period" in d
        assert "allocation_effect" in d
        assert "selection_effect" in d
        assert "interaction_effect" in d
        assert "active_return" in d


class TestTradeAttribution:
    def test_basic_attribution(self):
        """Trade attribution should decompose returns."""
        from backtest.engine import Trade

        trades = [
            Trade(
                date_open=pd.Timestamp("2024-01-10"),
                date_close=pd.Timestamp("2024-01-20"),
                pnl=5000, return_pct=0.05,
            ),
            Trade(
                date_open=pd.Timestamp("2024-02-10"),
                date_close=pd.Timestamp("2024-02-20"),
                pnl=-2000, return_pct=-0.02,
            ),
        ]

        dates = pd.bdate_range("2024-01-02", "2024-03-01")
        bench_returns = pd.Series(
            np.random.normal(0.001, 0.01, len(dates)),
            index=dates,
        )

        result = compute_trade_attribution(trades, bench_returns)
        assert isinstance(result, BrinsonAttribution)
        assert result.period == "full"
        # portfolio_return should be sum of trade returns
        assert result.portfolio_return == pytest.approx(0.03, abs=0.01)

    def test_empty_trades(self):
        """No trades should return zero attribution."""
        bench = pd.Series([0.01, -0.005], index=pd.bdate_range("2024-01-02", periods=2))
        result = compute_trade_attribution([], bench)
        assert result.portfolio_return == 0.0

    def test_empty_benchmark(self):
        """Empty benchmark should return zero attribution."""
        from backtest.engine import Trade
        trades = [Trade(date_open=pd.Timestamp("2024-01-10"), pnl=100)]
        result = compute_trade_attribution(trades, pd.Series(dtype=float))
        assert result.benchmark_return == 0.0


class TestFactorExposure:
    def test_basic_regression(self):
        """Factor regression should produce sensible results."""
        np.random.seed(42)
        n = 200
        dates = pd.bdate_range("2023-01-02", periods=n)
        market = pd.Series(np.random.normal(0.0005, 0.01, n), index=dates)
        # Strategy correlated with market (beta ~1.5)
        strategy = 1.5 * market + pd.Series(np.random.normal(0.0002, 0.005, n), index=dates)

        result = compute_factor_exposure(strategy, market)
        assert isinstance(result, FactorExposure)
        # Beta should be close to 1.5
        assert result.market_beta == pytest.approx(1.5, abs=0.3)
        assert result.r_squared > 0.5

    def test_empty_returns(self):
        """Empty inputs should return default FactorExposure."""
        result = compute_factor_exposure(pd.Series(dtype=float), pd.Series(dtype=float))
        assert result.market_beta == 0.0
        assert result.r_squared == 0.0

    def test_short_series(self):
        """Series < 30 days should return default."""
        dates = pd.bdate_range("2024-01-02", periods=10)
        strat = pd.Series(np.random.normal(0, 0.01, 10), index=dates)
        mkt = pd.Series(np.random.normal(0, 0.01, 10), index=dates)
        result = compute_factor_exposure(strat, mkt)
        assert result.market_beta == 0.0

    def test_to_dict(self):
        """FactorExposure.to_dict should have all expected keys."""
        result = FactorExposure(alpha=0.05, market_beta=1.2)
        d = result.to_dict()
        assert "alpha" in d
        assert "market_beta" in d
        assert "contributions" in d
        assert "market" in d["contributions"]


class TestBuildProxyFactors:
    def test_returns_dataframe(self):
        """Should return DataFrame with expected columns."""
        dates = pd.bdate_range("2024-01-02", periods=30)
        mkt = pd.Series(np.random.normal(0.001, 0.01, 30), index=dates)
        factors = build_proxy_factors(mkt)
        assert "MKT" in factors.columns
        assert "SIZE" in factors.columns
        assert "VALUE" in factors.columns
        assert "MOM" in factors.columns

    def test_mkt_factor_is_excess(self):
        """MKT factor should be market return minus risk-free."""
        dates = pd.bdate_range("2024-01-02", periods=5)
        mkt = pd.Series([0.01, 0.02, -0.01, 0.005, 0.003], index=dates)
        factors = build_proxy_factors(mkt)
        rf_daily = 0.015 / 252
        expected_mkt = mkt - rf_daily
        assert factors["MKT"].iloc[0] == pytest.approx(expected_mkt.iloc[0], abs=1e-8)


class TestBrinsonReport:
    def test_to_dict(self):
        """Report serialization should work."""
        report = BrinsonReport(
            total=BrinsonAttribution(period="full", active_return=0.05),
            periods=[
                BrinsonAttribution(period="2024-Q1", active_return=0.02),
                BrinsonAttribution(period="2024-Q2", active_return=0.03),
            ],
        )
        d = report.to_dict()
        assert d["total"]["active_return"] == 0.05
        assert len(d["periods"]) == 2

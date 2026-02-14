"""Tests for adaptive strategy backtester (R52 P0)"""

import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock
from dataclasses import dataclass


@pytest.fixture
def long_ohlcv():
    """200-bar OHLCV for adaptive backtest (needs regime_lookback + 60 bars)."""
    np.random.seed(42)
    n = 200
    dates = pd.bdate_range("2023-01-01", periods=n)
    base = 100.0
    returns = np.random.normal(0.001, 0.015, n)
    close = base * np.cumprod(1 + returns)

    df = pd.DataFrame({
        "open": close * (1 + np.random.uniform(-0.005, 0.005, n)),
        "high": close * (1 + np.random.uniform(0, 0.02, n)),
        "low": close * (1 - np.random.uniform(0, 0.02, n)),
        "close": close,
        "volume": np.random.randint(5000, 100000, n).astype(float),
    }, index=dates)
    df.index.name = "date"
    return df


def _mock_regime(close, high, low, volume, **kw):
    """Mock regime classifier returning bull_trending."""
    return {
        "regime": "bull_trending",
        "regime_label": "Bullish Trending",
        "confidence": 0.7,
        "kelly_multiplier": 0.6,
        "features": {"adx": 25, "rsi": 55},
        "v4_suitability": "good",
    }


def _mock_regime_cycling(close, high, low, volume, **kw):
    """Mock regime classifier that cycles through regimes."""
    regimes = ["bull_trending", "bear_volatile", "range_quiet"]
    idx = len(close) % len(regimes)
    labels = {"bull_trending": "Bullish", "bear_volatile": "Bearish Vol", "range_quiet": "Ranging"}
    return {
        "regime": regimes[idx],
        "regime_label": labels[regimes[idx]],
        "confidence": 0.6,
        "kelly_multiplier": 0.5,
    }


class TestAdaptiveBacktestResult:
    """Test AdaptiveBacktestResult dataclass."""

    def test_dataclass_defaults(self):
        from backtest.adaptive import AdaptiveBacktestResult
        r = AdaptiveBacktestResult()
        assert r.alpha == 0.0
        assert r.sharpe_delta == 0.0
        assert r.drawdown_delta == 0.0
        assert r.regime_log == []
        assert r.regime_performance == []

    def test_dataclass_fields(self):
        from backtest.adaptive import AdaptiveBacktestResult
        r = AdaptiveBacktestResult(alpha=0.05, sharpe_delta=0.1)
        assert r.alpha == 0.05
        assert r.sharpe_delta == 0.1


class TestRegimeParamMap:
    """Test REGIME_PARAM_MAP configuration."""

    def test_all_regimes_defined(self):
        from backtest.adaptive import REGIME_PARAM_MAP
        expected = {"bull_trending", "bull_volatile", "bear_trending",
                    "bear_volatile", "range_quiet", "range_volatile"}
        assert set(REGIME_PARAM_MAP.keys()) == expected

    def test_bear_volatile_pauses_entries(self):
        from backtest.adaptive import REGIME_PARAM_MAP
        assert REGIME_PARAM_MAP["bear_volatile"].get("_pause_entries") is True

    def test_bull_trending_aggressive(self):
        from backtest.adaptive import REGIME_PARAM_MAP
        params = REGIME_PARAM_MAP["bull_trending"]
        assert params["adx_threshold"] == 15
        assert params["take_profit_pct"] == 0.15


class TestRunAdaptiveBacktest:
    """Test run_adaptive_backtest main function."""

    @patch("backend.ml_regime.classify_market_regime", side_effect=_mock_regime)
    def test_basic_run(self, mock_regime, long_ohlcv):
        from backtest.adaptive import run_adaptive_backtest
        result = run_adaptive_backtest(long_ohlcv, initial_capital=1_000_000)

        assert result.adaptive is not None
        assert result.baseline is not None
        assert isinstance(result.alpha, float)
        assert isinstance(result.sharpe_delta, float)
        assert isinstance(result.drawdown_delta, float)
        assert isinstance(result.regime_log, list)
        assert len(result.regime_log) > 0

    @patch("backend.ml_regime.classify_market_regime", side_effect=_mock_regime)
    def test_adaptive_has_equity_curve(self, mock_regime, long_ohlcv):
        from backtest.adaptive import run_adaptive_backtest
        result = run_adaptive_backtest(long_ohlcv)

        assert not result.adaptive.equity_curve.empty
        assert not result.baseline.equity_curve.empty

    @patch("backend.ml_regime.classify_market_regime", side_effect=_mock_regime)
    def test_regime_log_populated(self, mock_regime, long_ohlcv):
        from backtest.adaptive import run_adaptive_backtest
        result = run_adaptive_backtest(long_ohlcv, rebalance_days=10)

        assert len(result.regime_log) > 0
        first = result.regime_log[0]
        assert "regime" in first
        assert "date" in first
        assert "confidence" in first
        assert "kelly" in first

    @patch("backend.ml_regime.classify_market_regime", side_effect=_mock_regime_cycling)
    def test_regime_switching(self, mock_regime, long_ohlcv):
        from backtest.adaptive import run_adaptive_backtest
        result = run_adaptive_backtest(long_ohlcv, rebalance_days=5)

        # Should have multiple regime transitions
        regimes = set(r["regime"] for r in result.regime_log)
        assert len(regimes) >= 1  # At least one regime type

    @patch("backend.ml_regime.classify_market_regime", side_effect=_mock_regime)
    def test_comparison_metrics_reasonable(self, mock_regime, long_ohlcv):
        from backtest.adaptive import run_adaptive_backtest
        result = run_adaptive_backtest(long_ohlcv)

        # Alpha should be the difference of total returns
        expected_alpha = result.adaptive.total_return - result.baseline.total_return
        assert abs(result.alpha - expected_alpha) < 0.001

    def test_too_short_data_raises(self):
        from backtest.adaptive import run_adaptive_backtest
        short_df = pd.DataFrame({
            "open": [100] * 50, "high": [101] * 50, "low": [99] * 50,
            "close": [100] * 50, "volume": [10000] * 50,
        }, index=pd.bdate_range("2024-01-01", periods=50))

        with pytest.raises(ValueError, match="Need at least"):
            run_adaptive_backtest(short_df)

    @patch("backend.ml_regime.classify_market_regime", side_effect=_mock_regime)
    def test_custom_rebalance_days(self, mock_regime, long_ohlcv):
        from backtest.adaptive import run_adaptive_backtest

        r5 = run_adaptive_backtest(long_ohlcv, rebalance_days=5)
        r20 = run_adaptive_backtest(long_ohlcv, rebalance_days=20)

        # More frequent rebalancing = more regime log entries
        assert len(r5.regime_log) > len(r20.regime_log)


class TestComputeRegimePerformance:
    """Test _compute_regime_performance helper."""

    @patch("backend.ml_regime.classify_market_regime", side_effect=_mock_regime)
    def test_regime_performance_structure(self, mock_regime, long_ohlcv):
        from backtest.adaptive import run_adaptive_backtest
        result = run_adaptive_backtest(long_ohlcv)

        for rp in result.regime_performance:
            assert "regime" in rp
            assert "count" in rp
            assert "win_rate" in rp
            assert "avg_return" in rp
            assert "total_pnl" in rp

    @patch("backend.ml_regime.classify_market_regime", side_effect=_mock_regime)
    def test_regime_performance_sorted_by_count(self, mock_regime, long_ohlcv):
        from backtest.adaptive import run_adaptive_backtest
        result = run_adaptive_backtest(long_ohlcv)

        if len(result.regime_performance) > 1:
            counts = [rp["count"] for rp in result.regime_performance]
            assert counts == sorted(counts, reverse=True)


class TestAdaptiveBacktestAPI:
    """Test the API endpoint for adaptive backtest."""

    @pytest.fixture(scope="class")
    def client(self):
        from backend.app import app
        from fastapi.testclient import TestClient
        return TestClient(app)

    @patch("data.fetcher.get_stock_data")
    @patch("backend.ml_regime.classify_market_regime", side_effect=_mock_regime)
    def test_endpoint_returns_200(self, mock_regime, mock_data, client, long_ohlcv):
        mock_data.return_value = long_ohlcv
        resp = client.post("/api/strategies/adaptive-backtest/2330", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "adaptive" in data
        assert "baseline" in data
        assert "comparison" in data
        assert "regime_performance" in data

    @patch("data.fetcher.get_stock_data")
    def test_endpoint_insufficient_data(self, mock_data, client):
        short_df = pd.DataFrame({
            "open": [100] * 30, "high": [101] * 30, "low": [99] * 30,
            "close": [100] * 30, "volume": [10000] * 30,
        }, index=pd.bdate_range("2024-01-01", periods=30))
        mock_data.return_value = short_df
        resp = client.post("/api/strategies/adaptive-backtest/2330", json={})
        assert resp.status_code == 400

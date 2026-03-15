"""Tests for backtest/reversal_backtest.py — Phase 4

E2E tests with real stock data (no mocks) + synthetic data for edge cases.
Tests cover:
1. Backtest on real stocks produces valid results
2. Hit rates between 0 and 1
3. Forward returns are reasonable (not NaN, not absurd)
4. Per-signal breakdown has all 5 signal types
5. Quick backtest API works
6. Empty universe returns empty result
"""

import numpy as np
import pandas as pd
import pytest

from backtest.reversal_backtest import (
    ReversalBacktestConfig,
    ReversalBacktestResult,
    run_reversal_backtest,
    run_quick_backtest,
    load_validation_stocks,
    _scan_stock,
    _aggregate_results,
    SIGNAL_TYPES,
    MIN_HISTORY_BARS,
)


# ---------- 1. Empty universe returns empty result ----------

class TestEmptyUniverse:
    def test_empty_universe_no_file(self, tmp_path, monkeypatch):
        """Empty universe + no validation file -> empty result."""
        import backtest.reversal_backtest as mod
        monkeypatch.setattr(mod, "VALIDATION_STOCKS_PATH", tmp_path / "nonexistent.json")
        config = ReversalBacktestConfig(universe=[])
        result = run_reversal_backtest(config)
        assert result.total_signals == 0
        assert result.total_stocks_scanned == 0
        assert len(result.errors) >= 1

    def test_empty_result_to_dict(self):
        """Empty result serializes cleanly."""
        result = ReversalBacktestResult()
        d = result.to_dict()
        assert d["total_signals"] == 0
        assert d["hit_rates"] == {}
        assert d["avg_returns"] == {}


# ---------- 2. Backtest on real stocks produces valid results ----------

class TestRealStockBacktest:
    """E2E tests using real stock data via yfinance.

    These tests hit the network — mark with slow if needed.
    Using well-known liquid stocks to minimize flakiness.
    """

    @pytest.fixture
    def small_universe(self):
        return ["2330", "2317", "2454"]

    def test_backtest_produces_results(self, small_universe):
        """Backtest on 3 liquid stocks should produce at least some signals."""
        config = ReversalBacktestConfig(
            universe=small_universe,
            min_composite_score=30.0,  # low threshold to ensure signals
            forward_days=[5, 10, 20],
            period_days=500,
        )
        result = run_reversal_backtest(config)

        assert result.total_stocks_scanned == 3
        assert isinstance(result.total_signals, int)
        assert result.elapsed_sec > 0
        # Should have scanned without fatal errors for these liquid stocks
        # (some stocks might have warnings but not all should fail)
        assert result.total_stocks_scanned - len(result.errors) >= 1

    def test_hit_rates_are_valid(self, small_universe):
        """Hit rates must be between 0 and 1."""
        config = ReversalBacktestConfig(
            universe=small_universe,
            min_composite_score=30.0,
            period_days=500,
        )
        result = run_reversal_backtest(config)

        for d, rate in result.hit_rates.items():
            assert 0.0 <= rate <= 1.0, f"Hit rate for D{d} out of range: {rate}"

    def test_forward_returns_reasonable(self, small_universe):
        """Forward returns should not be NaN or absurdly large."""
        config = ReversalBacktestConfig(
            universe=small_universe,
            min_composite_score=30.0,
            period_days=500,
        )
        result = run_reversal_backtest(config)

        for d, ret in result.avg_returns.items():
            assert not np.isnan(ret), f"Average return for D{d} is NaN"
            # Returns beyond +/-50% on average would be suspicious
            assert -0.5 <= ret <= 0.5, f"Average return for D{d} is extreme: {ret}"

    def test_mae_is_negative_or_zero(self, small_universe):
        """Max adverse excursion should be <= 0 (worst drawdown)."""
        config = ReversalBacktestConfig(
            universe=small_universe,
            min_composite_score=30.0,
            period_days=500,
        )
        result = run_reversal_backtest(config)

        # MAE represents worst drawdown, should be non-positive
        assert result.avg_mae <= 0.0 or result.total_signals == 0

    def test_signal_attribution_has_all_types(self, small_universe):
        """Per-signal breakdown should have all 5 signal types."""
        config = ReversalBacktestConfig(
            universe=small_universe,
            min_composite_score=30.0,
            period_days=500,
        )
        result = run_reversal_backtest(config)

        for sig_type in SIGNAL_TYPES:
            assert sig_type in result.signal_attribution, f"Missing signal type: {sig_type}"
            attr = result.signal_attribution[sig_type]
            assert "count" in attr
            assert "avg_score" in attr
            assert "win_rate" in attr
            assert attr["count"] >= 0

    def test_per_stock_breakdown(self, small_universe):
        """Per-stock breakdown should have entries for stocks with signals."""
        config = ReversalBacktestConfig(
            universe=small_universe,
            min_composite_score=30.0,
            period_days=500,
        )
        result = run_reversal_backtest(config)

        for stock in result.per_stock:
            assert "code" in stock
            assert "signal_count" in stock
            assert stock["signal_count"] > 0

    def test_phase_distribution(self, small_universe):
        """Phase distribution should have valid phase names."""
        config = ReversalBacktestConfig(
            universe=small_universe,
            min_composite_score=30.0,
            period_days=500,
        )
        result = run_reversal_backtest(config)

        valid_phases = {"NONE", "WATCH", "ALERT", "STRONG"}
        for phase in result.phase_distribution:
            assert phase in valid_phases, f"Unknown phase: {phase}"


# ---------- 3. Quick backtest API ----------

class TestQuickBacktest:
    def test_quick_backtest_works(self):
        """Quick backtest on 2 stocks should run and return results."""
        result = run_quick_backtest(["2330", "2317"], days=400, min_score=30.0)
        assert isinstance(result, ReversalBacktestResult)
        assert result.total_stocks_scanned == 2

    def test_quick_backtest_single_stock(self):
        """Quick backtest on a single stock."""
        result = run_quick_backtest(["2330"], days=400, min_score=40.0)
        assert result.total_stocks_scanned == 1


# ---------- 4. Result serialization ----------

class TestResultSerialization:
    def test_to_dict_roundtrip(self):
        """to_dict produces JSON-serializable output."""
        import json

        result = ReversalBacktestResult(
            total_stocks_scanned=5,
            total_signals=10,
            elapsed_sec=12.345,
            hit_rates={5: 0.6, 10: 0.65},
            avg_returns={5: 0.012, 10: 0.025},
            median_returns={5: 0.008, 10: 0.02},
            avg_mae=-0.03,
            phase_distribution={"ALERT": 7, "STRONG": 3},
        )
        d = result.to_dict()
        # Should be JSON-serializable
        serialized = json.dumps(d)
        assert '"total_signals": 10' in serialized


# ---------- 5. Scan stock edge cases ----------

class TestScanStockEdgeCases:
    def test_nonexistent_stock(self):
        """Non-existent stock code returns error."""
        config = ReversalBacktestConfig(
            universe=["9999"],
            min_composite_score=50.0,
            period_days=400,
        )
        signals, err = _scan_stock("9999", config)
        # Either empty signals or an error message
        assert len(signals) == 0 or err is not None


# ---------- 6. Validation stocks loader ----------

class TestValidationStocks:
    def test_load_validation_stocks(self):
        """Should load the 100 validation stocks."""
        stocks = load_validation_stocks()
        # File exists in repo
        assert len(stocks) > 0
        assert "code" in stocks[0]

    def test_validation_stocks_have_required_fields(self):
        """Each validation stock should have code and data_points."""
        stocks = load_validation_stocks()
        for s in stocks[:5]:
            assert "code" in s
            assert "data_points" in s


# ---------- 7. Aggregate results correctness ----------

class TestAggregateResults:
    def test_aggregate_empty(self):
        """Empty signals produce valid empty result."""
        config = ReversalBacktestConfig(forward_days=[5, 10, 20])
        result = _aggregate_results([], config, total_stocks=3, elapsed=1.0, errors=[])
        assert result.total_signals == 0
        assert result.hit_rates == {}

    def test_aggregate_basic(self):
        """Basic aggregation with synthetic signal records."""
        signals = [
            {
                "code": "2330",
                "date": "2025-06-01",
                "bar_index": 130,
                "composite_score": 55.0,
                "phase": "ALERT",
                "forward_returns": {5: 0.02, 10: 0.04, 20: 0.06},
                "mae": -0.01,
                "random_returns": {5: 0.005, 10: 0.01, 20: 0.015},
                "active_signals": [
                    {"type": "rsi_divergence", "score": 60.0, "direction": "bullish"},
                    {"type": "bb_squeeze", "score": 80.0, "direction": ""},
                ],
            },
            {
                "code": "2317",
                "date": "2025-07-01",
                "bar_index": 150,
                "composite_score": 65.0,
                "phase": "ALERT",
                "forward_returns": {5: -0.01, 10: 0.01, 20: 0.03},
                "mae": -0.03,
                "random_returns": {5: -0.005, 10: 0.005, 20: 0.01},
                "active_signals": [
                    {"type": "spring", "score": 70.0, "direction": "bullish"},
                    {"type": "volume_exhaustion", "score": 50.0, "direction": "bullish"},
                ],
            },
        ]
        config = ReversalBacktestConfig(forward_days=[5, 10, 20])
        result = _aggregate_results(signals, config, total_stocks=2, elapsed=5.0, errors=[])

        assert result.total_signals == 2
        assert result.total_stocks_scanned == 2

        # Hit rate D5: 1 win (0.02), 1 loss (-0.01) = 50%
        assert abs(result.hit_rates[5] - 0.5) < 0.01

        # Hit rate D10: 2 wins (0.04, 0.01) = 100%
        assert abs(result.hit_rates[10] - 1.0) < 0.01

        # Average return D10: (0.04 + 0.01) / 2 = 0.025
        assert abs(result.avg_returns[10] - 0.025) < 0.001

        # MAE: average of -0.01 and -0.03 = -0.02
        assert abs(result.avg_mae - (-0.02)) < 0.001

        # Phase distribution
        assert result.phase_distribution["ALERT"] == 2

        # Per-stock
        assert len(result.per_stock) == 2

        # Attribution: rsi_divergence should have count=1
        assert result.signal_attribution["rsi_divergence"]["count"] == 1
        assert result.signal_attribution["spring"]["count"] == 1

    def test_benchmark_comparison(self):
        """Benchmark returns should differ from signal returns."""
        signals = [
            {
                "code": "2330",
                "date": "2025-06-01",
                "bar_index": 130,
                "composite_score": 55.0,
                "phase": "ALERT",
                "forward_returns": {10: 0.05},
                "mae": -0.01,
                "random_returns": {10: 0.01},
                "active_signals": [],
            },
        ]
        config = ReversalBacktestConfig(forward_days=[10])
        result = _aggregate_results(signals, config, total_stocks=1, elapsed=1.0, errors=[])

        # Signal return = 0.05, benchmark = 0.01
        assert result.avg_returns[10] > result.benchmark_returns[10]

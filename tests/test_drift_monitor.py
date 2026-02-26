"""Tests for Backtest Drift Monitor (V1.3 P1)."""

import json
import pytest
import statistics
from datetime import datetime
from unittest.mock import patch, MagicMock


# ─── Signal-Level Drift ──────────────────────────────────────

class TestComputeSignalDrift:
    """Test per-signal drift computation."""

    def test_no_drift(self):
        from analysis.drift_monitor import compute_signal_drift
        result = compute_signal_drift(
            actual_return=0.05, expected_return=0.05, sigma=0.08,
        )
        assert result["raw_drift"] == 0.0
        assert result["z_score"] == 0.0
        assert result["is_drifting"] is False

    def test_positive_drift(self):
        from analysis.drift_monitor import compute_signal_drift
        result = compute_signal_drift(
            actual_return=0.20, expected_return=0.05, sigma=0.08,
        )
        assert result["raw_drift"] == pytest.approx(0.15)
        assert result["z_score"] == pytest.approx(1.875)
        assert result["is_drifting"] is True  # > 1.5σ

    def test_negative_drift(self):
        from analysis.drift_monitor import compute_signal_drift
        result = compute_signal_drift(
            actual_return=-0.10, expected_return=0.05, sigma=0.08,
        )
        assert result["raw_drift"] == pytest.approx(-0.15)
        assert result["z_score"] == pytest.approx(-1.875)
        assert result["is_drifting"] is True

    def test_within_threshold(self):
        from analysis.drift_monitor import compute_signal_drift
        result = compute_signal_drift(
            actual_return=0.06, expected_return=0.05, sigma=0.08,
        )
        assert result["z_score"] == pytest.approx(0.125)
        assert result["is_drifting"] is False

    def test_zero_sigma(self):
        from analysis.drift_monitor import compute_signal_drift
        result = compute_signal_drift(
            actual_return=0.10, expected_return=0.05, sigma=0.0,
        )
        assert result["z_score"] == 0.0
        assert result["is_drifting"] is False

    def test_none_sigma(self):
        from analysis.drift_monitor import compute_signal_drift
        result = compute_signal_drift(
            actual_return=0.10, expected_return=0.05, sigma=None,
        )
        assert result["z_score"] == 0.0


# ─── Portfolio-Level Drift ────────────────────────────────────

class TestComputePortfolioDrift:
    """Test portfolio-level drift aggregation."""

    def _make_signals(self, n=10, base_return=0.05, actual_offset=0.0):
        """Generate synthetic realized signals."""
        return [
            {
                "stock_code": f"{2000 + i}",
                "stock_name": f"Stock{i}",
                "signal_date": f"2026-02-{10 + i:02d}",
                "strategy": "v4",
                "actual_return_d21": base_return + actual_offset + (i * 0.001),
                "expected_mean_return": base_return,
                "ci_upper": base_return + 0.15,
                "ci_lower": base_return - 0.10,
            }
            for i in range(n)
        ]

    def test_no_signals(self):
        from analysis.drift_monitor import compute_portfolio_drift
        result = compute_portfolio_drift(signals=[])
        assert result["alert_level"] == "NORMAL"
        assert result["eligible_signals"] == 0

    def test_insufficient_samples(self):
        from analysis.drift_monitor import compute_portfolio_drift
        signals = self._make_signals(n=3)
        result = compute_portfolio_drift(signals=signals)
        assert "樣本不足" in result["alert_message"]

    def test_no_drift_normal(self):
        from analysis.drift_monitor import compute_portfolio_drift
        signals = self._make_signals(n=10, actual_offset=0.0)
        result = compute_portfolio_drift(signals=signals)
        assert result["alert_level"] == "NORMAL"
        assert result["is_drifting"] is False
        assert result["drift_direction"] == "NEUTRAL"

    def test_positive_drift_warning(self):
        from analysis.drift_monitor import compute_portfolio_drift
        # Large positive offset → positive drift
        signals = self._make_signals(n=10, actual_offset=0.15)
        result = compute_portfolio_drift(signals=signals)
        assert result["portfolio_drift"] > 0.10
        assert result["drift_direction"] == "POSITIVE"

    def test_negative_drift_warning(self):
        from analysis.drift_monitor import compute_portfolio_drift
        signals = self._make_signals(n=10, actual_offset=-0.15)
        result = compute_portfolio_drift(signals=signals)
        assert result["portfolio_drift"] < -0.10
        assert result["drift_direction"] == "NEGATIVE"

    def test_rolling_window_limits(self):
        from analysis.drift_monitor import compute_portfolio_drift, ROLLING_WINDOW
        signals = self._make_signals(n=30)
        result = compute_portfolio_drift(signals=signals)
        assert result["rolling_window"] <= ROLLING_WINDOW

    def test_missing_actual_returns_skipped(self):
        from analysis.drift_monitor import compute_portfolio_drift
        signals = self._make_signals(n=10)
        # Set some to None
        signals[0]["actual_return_d21"] = None
        signals[1]["actual_return_d21"] = None
        result = compute_portfolio_drift(signals=signals)
        assert result["eligible_signals"] == 8

    def test_per_stock_sigma_from_ci(self):
        """Verify σ is computed from CI (CTO: per-stock normalization)."""
        from analysis.drift_monitor import compute_portfolio_drift
        signals = self._make_signals(n=6)
        # Widen CI for some → lower Z-score for same drift
        for sig in signals[:3]:
            sig["ci_upper"] = 0.50  # Very wide CI
            sig["ci_lower"] = -0.40
        result = compute_portfolio_drift(signals=signals)
        # Should still compute without error
        assert result["eligible_signals"] >= 5


# ─── Expanding Negative Detection ─────────────────────────────

class TestExpandingNegative:
    """Test CTO [CRITICAL] expanding negative drift detection."""

    def test_no_expansion_with_few_signals(self):
        from analysis.drift_monitor import _detect_expanding_negative
        entries = [{"z_score": -2.0, "signal_date": "2026-02-20"}] * 10
        assert _detect_expanding_negative(entries) is False  # Not enough data

    def test_expanding_negative_detected(self):
        from analysis.drift_monitor import _detect_expanding_negative, ROLLING_WINDOW
        # Create 40 entries: index 0 = most recent = most negative
        # The function uses overlapping windows: window[0] = entries[0:20], window[1] = entries[10:30]
        # For "expanding": window[0] avg < window[1] avg (more recent = more negative)
        entries = []
        for i in range(40):
            # Most recent (i=0) should be most negative → expanding
            entries.append({
                "z_score": -2.0 + (i * 0.05),  # i=0: -2.0, i=39: -0.05
                "signal_date": f"2026-02-{1 + i:02d}" if i < 28 else f"2026-01-{i - 27:02d}",
            })
        result = _detect_expanding_negative(entries)
        assert result is True

    def test_stable_negative_not_expanding(self):
        from analysis.drift_monitor import _detect_expanding_negative
        # All same Z-score → not expanding
        entries = [{"z_score": -1.0, "signal_date": f"2026-02-{20-i:02d}"} for i in range(40)]
        assert _detect_expanding_negative(entries) is False


# ─── Alert Classification ─────────────────────────────────────

class TestClassifyAlert:
    """Test alert level classification."""

    def test_normal(self):
        from analysis.drift_monitor import _classify_alert
        level, msg = _classify_alert(0.02, 0.3, "POSITIVE", False)
        assert level == "NORMAL"
        assert msg == ""

    def test_warning_high_zscore(self):
        from analysis.drift_monitor import _classify_alert
        level, msg = _classify_alert(0.05, 2.0, "POSITIVE", False)
        assert level == "WARNING"
        assert "偏離" in msg

    def test_warning_high_drift(self):
        from analysis.drift_monitor import _classify_alert
        level, msg = _classify_alert(0.20, 1.0, "POSITIVE", False)
        assert level == "WARNING"

    def test_critical_expanding_negative(self):
        from analysis.drift_monitor import _classify_alert
        level, msg = _classify_alert(-0.10, -2.0, "NEGATIVE", True)
        assert level == "CRITICAL"
        assert "Aggressive Index" in msg

    def test_negative_but_not_expanding(self):
        from analysis.drift_monitor import _classify_alert
        level, msg = _classify_alert(-0.20, -2.5, "NEGATIVE", False)
        assert level == "WARNING"  # Still warning, not critical


# ─── Empty Result ─────────────────────────────────────────────

class TestEmptyResult:
    """Test empty result template."""

    def test_has_all_keys(self):
        from analysis.drift_monitor import _empty_result
        result = _empty_result("test")
        assert result["alert_level"] == "NORMAL"
        assert result["is_drifting"] is False
        assert result["expanding_negative"] is False
        assert "test" in result["alert_message"]


# ─── Morning Brief Integration ────────────────────────────────

class TestBriefIntegration:
    """Test Morning Brief integration helper."""

    @patch("analysis.drift_monitor.compute_portfolio_drift")
    def test_warning_returns_message(self, mock_drift):
        from analysis.drift_monitor import get_drift_alert_for_brief
        mock_drift.return_value = {
            "alert_level": "WARNING",
            "alert_message": "⚠️ 策略偏離警示: Live 與回測偏離",
        }
        result = get_drift_alert_for_brief()
        assert result is not None
        assert "偏離" in result

    @patch("analysis.drift_monitor.compute_portfolio_drift")
    def test_normal_returns_none(self, mock_drift):
        from analysis.drift_monitor import get_drift_alert_for_brief
        mock_drift.return_value = {"alert_level": "NORMAL", "alert_message": ""}
        result = get_drift_alert_for_brief()
        assert result is None

    @patch("analysis.drift_monitor.compute_portfolio_drift", side_effect=Exception("fail"))
    def test_exception_returns_none(self, mock_drift):
        from analysis.drift_monitor import get_drift_alert_for_brief
        result = get_drift_alert_for_brief()
        assert result is None


# ─── State Persistence ────────────────────────────────────────

class TestDriftHistory:
    """Test drift history persistence."""

    def test_load_missing_file(self, tmp_path):
        from analysis.drift_monitor import _load_drift_history
        with patch("analysis.drift_monitor.DRIFT_STATE_FILE", tmp_path / "nonexistent.json"):
            history = _load_drift_history()
        assert history == []

    def test_save_and_load(self, tmp_path):
        from analysis.drift_monitor import _save_drift_snapshot, _load_drift_history
        state_file = tmp_path / "drift_state.json"
        with patch("analysis.drift_monitor.DRIFT_STATE_FILE", state_file):
            _save_drift_snapshot({
                "timestamp": "2026-02-26T10:00:00",
                "portfolio_drift_pct": -5.2,
                "portfolio_zscore": -1.3,
                "alert_level": "NORMAL",
                "eligible_signals": 15,
            })
            history = _load_drift_history()
        assert len(history) == 1
        assert history[0]["drift_pct"] == -5.2

    def test_history_capped_at_60(self, tmp_path):
        from analysis.drift_monitor import _save_drift_snapshot, _load_drift_history
        state_file = tmp_path / "drift_state.json"
        # Pre-populate with 59 entries
        initial = [{"date": f"2026-01-{i:02d}", "drift_pct": 0, "zscore": 0,
                     "alert_level": "NORMAL", "eligible": 10} for i in range(1, 60)]
        state_file.write_text(json.dumps(initial), encoding="utf-8")
        with patch("analysis.drift_monitor.DRIFT_STATE_FILE", state_file):
            _save_drift_snapshot({
                "timestamp": "2026-02-26",
                "portfolio_drift_pct": 1.0,
                "portfolio_zscore": 0.5,
                "alert_level": "NORMAL",
                "eligible_signals": 20,
            })
            history = _load_drift_history()
        assert len(history) == 60


# ─── Trend Computation ────────────────────────────────────────

class TestComputeTrend:
    """Test drift trend computation."""

    def test_insufficient_data(self):
        from analysis.drift_monitor import _compute_trend
        assert _compute_trend([]) == "INSUFFICIENT_DATA"
        assert _compute_trend([{"zscore": 0}] * 2) == "INSUFFICIENT_DATA"

    def test_stable(self):
        from analysis.drift_monitor import _compute_trend
        history = [{"zscore": 0.5}] * 15
        assert _compute_trend(history) == "STABLE"

    def test_improving(self):
        from analysis.drift_monitor import _compute_trend
        # Older: negative, Recent: positive
        history = [{"zscore": -1.0}] * 10 + [{"zscore": 0.5}] * 5
        assert _compute_trend(history) == "IMPROVING"

    def test_deteriorating(self):
        from analysis.drift_monitor import _compute_trend
        # Older: positive, Recent: negative
        history = [{"zscore": 1.0}] * 10 + [{"zscore": -0.5}] * 5
        assert _compute_trend(history) == "DETERIORATING"


# ─── Full Report Generation ──────────────────────────────────

class TestGenerateDriftReport:
    """Test complete drift report generation."""

    @patch("analysis.drift_monitor._get_realized_signals")
    @patch("analysis.drift_monitor._get_backtest_baseline", return_value={})
    def test_full_report_with_data(self, mock_baseline, mock_signals, tmp_path):
        from analysis.drift_monitor import generate_drift_report
        signals = [
            {
                "stock_code": f"{2000+i}", "stock_name": f"S{i}",
                "signal_date": f"2026-02-{10+i:02d}", "strategy": "v4",
                "actual_return_d21": 0.03 + i * 0.002,
                "expected_mean_return": 0.03,
                "ci_upper": 0.15, "ci_lower": -0.08,
            }
            for i in range(10)
        ]
        mock_signals.return_value = signals
        with patch("analysis.drift_monitor.DRIFT_STATE_FILE", tmp_path / "state.json"):
            result = generate_drift_report(save_snapshot=True)
        assert "portfolio_drift" in result
        assert "trend_direction" in result
        assert result["eligible_signals"] == 10

    @patch("analysis.drift_monitor._get_realized_signals", return_value=[])
    def test_empty_report(self, mock_signals, tmp_path):
        from analysis.drift_monitor import generate_drift_report
        with patch("analysis.drift_monitor.DRIFT_STATE_FILE", tmp_path / "state.json"):
            result = generate_drift_report()
        assert result["alert_level"] == "NORMAL"
        assert result["eligible_signals"] == 0

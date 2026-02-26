"""Tests for V1.3 P2: Dynamic ATR Multiplier."""

import json
import pytest
from unittest.mock import patch, MagicMock


# ─── ATR Adjustment Computation ──────────────────────────────

class TestComputeAtrAdjustment:
    """Test core ATR adjustment logic."""

    def test_none_rate_neutral(self):
        from analysis.dynamic_atr import compute_atr_adjustment
        result = compute_atr_adjustment(None)
        assert result["adjustment"] == 0.0
        assert result["direction"] == "NEUTRAL"

    def test_high_shakeout_widens(self):
        from analysis.dynamic_atr import compute_atr_adjustment
        result = compute_atr_adjustment(0.35)  # > 30%
        assert result["adjustment"] == 0.2
        assert result["direction"] == "WIDEN"

    def test_low_shakeout_tightens(self):
        from analysis.dynamic_atr import compute_atr_adjustment
        result = compute_atr_adjustment(0.10)  # < 15%
        assert result["adjustment"] == -0.1
        assert result["direction"] == "TIGHTEN"

    def test_neutral_zone(self):
        from analysis.dynamic_atr import compute_atr_adjustment
        result = compute_atr_adjustment(0.20)  # between 15%-30%
        assert result["adjustment"] == 0.0
        assert result["direction"] == "NEUTRAL"

    def test_boundary_low_exact(self):
        from analysis.dynamic_atr import compute_atr_adjustment
        # At exact 15% boundary — NOT < 15%, so neutral
        result = compute_atr_adjustment(0.15)
        assert result["direction"] == "NEUTRAL"

    def test_boundary_high_exact(self):
        from analysis.dynamic_atr import compute_atr_adjustment
        # At exact 30% boundary — NOT > 30%, so neutral
        result = compute_atr_adjustment(0.30)
        assert result["direction"] == "NEUTRAL"

    def test_boundary_just_above_high(self):
        from analysis.dynamic_atr import compute_atr_adjustment
        result = compute_atr_adjustment(0.301)
        assert result["direction"] == "WIDEN"

    def test_boundary_just_below_low(self):
        from analysis.dynamic_atr import compute_atr_adjustment
        result = compute_atr_adjustment(0.149)
        assert result["direction"] == "TIGHTEN"

    def test_zero_rate_tightens(self):
        from analysis.dynamic_atr import compute_atr_adjustment
        result = compute_atr_adjustment(0.0)
        assert result["direction"] == "TIGHTEN"

    def test_100_pct_rate_widens(self):
        from analysis.dynamic_atr import compute_atr_adjustment
        result = compute_atr_adjustment(1.0)
        assert result["direction"] == "WIDEN"


# ─── Adjusted Multiplier Computation ─────────────────────────

class TestGetAdjustedMultiplier:
    """Test per-entry-type multiplier adjustment."""

    def test_squeeze_no_adjustment(self):
        from analysis.dynamic_atr import get_adjusted_multiplier
        result = get_adjusted_multiplier("squeeze_breakout", None)
        assert result["base_multiplier"] == 1.5
        assert result["adjusted_multiplier"] == 1.5
        assert result["clamped"] is False

    def test_squeeze_widen(self):
        from analysis.dynamic_atr import get_adjusted_multiplier
        result = get_adjusted_multiplier("squeeze_breakout", 0.40)  # widen +0.2
        assert result["adjusted_multiplier"] == 1.7
        assert result["clamped"] is False

    def test_squeeze_tighten_clamped_at_floor(self):
        from analysis.dynamic_atr import get_adjusted_multiplier
        # squeeze base=1.5, tighten -0.1 → 1.4, clamped to 1.5
        result = get_adjusted_multiplier("squeeze_breakout", 0.10)
        assert result["adjusted_multiplier"] == 1.5
        assert result["clamped"] is True

    def test_momentum_widen(self):
        from analysis.dynamic_atr import get_adjusted_multiplier
        result = get_adjusted_multiplier("momentum_breakout", 0.35)
        assert result["adjusted_multiplier"] == 2.2  # 2.0 + 0.2

    def test_momentum_tighten(self):
        from analysis.dynamic_atr import get_adjusted_multiplier
        result = get_adjusted_multiplier("momentum_breakout", 0.05)
        assert result["adjusted_multiplier"] == 1.9  # 2.0 - 0.1

    def test_unknown_entry_type_uses_fallback(self):
        from analysis.dynamic_atr import get_adjusted_multiplier
        result = get_adjusted_multiplier("unknown_type", 0.35)
        assert result["base_multiplier"] == 2.0  # fallback
        assert result["adjusted_multiplier"] == 2.2

    def test_ceiling_clamped(self):
        from analysis.dynamic_atr import get_adjusted_multiplier
        # Use custom base at 3.4, widen +0.2 → 3.6, clamped to 3.5
        result = get_adjusted_multiplier("test", 0.40, base_multipliers={"test": 3.4})
        assert result["adjusted_multiplier"] == 3.5
        assert result["clamped"] is True


# ─── All Multipliers ─────────────────────────────────────────

class TestGetAllAdjustedMultipliers:
    """Test batch multiplier computation."""

    def test_returns_all_entry_types(self):
        from analysis.dynamic_atr import get_all_adjusted_multipliers
        result = get_all_adjusted_multipliers(0.20)  # neutral
        assert "squeeze_breakout" in result
        assert "oversold_bounce" in result
        assert "volume_ramp" in result
        assert "momentum_breakout" in result

    def test_all_neutral_unchanged(self):
        from analysis.dynamic_atr import get_all_adjusted_multipliers
        result = get_all_adjusted_multipliers(0.20)
        assert result["squeeze_breakout"]["adjusted_multiplier"] == 1.5
        assert result["oversold_bounce"]["adjusted_multiplier"] == 2.0

    def test_all_widened(self):
        from analysis.dynamic_atr import get_all_adjusted_multipliers
        result = get_all_adjusted_multipliers(0.40)
        assert result["squeeze_breakout"]["adjusted_multiplier"] == 1.7
        assert result["oversold_bounce"]["adjusted_multiplier"] == 2.2


# ─── State Persistence ───────────────────────────────────────

class TestStatePersistence:
    """Test state file read/write."""

    def test_load_empty(self, tmp_path):
        from analysis.dynamic_atr import _load_state
        with patch("analysis.dynamic_atr.STATE_FILE", tmp_path / "nonexistent.json"):
            history = _load_state()
        assert history == []

    def test_save_and_load(self, tmp_path):
        from analysis.dynamic_atr import _save_snapshot, _load_state
        state_file = tmp_path / "state.json"
        with patch("analysis.dynamic_atr.STATE_FILE", state_file):
            _save_snapshot({
                "timestamp": "2026-02-26T20:30:00",
                "shake_out_rate": 0.25,
                "adjustment": 0.0,
                "direction": "NEUTRAL",
                "total_stopped": 10,
                "shake_out_count": 3,
            })
            history = _load_state()
        assert len(history) == 1
        assert history[0]["shake_out_rate"] == 0.25

    def test_history_capped_at_max(self, tmp_path):
        from analysis.dynamic_atr import _save_snapshot, _load_state, MAX_HISTORY
        state_file = tmp_path / "state.json"
        # Pre-populate with MAX_HISTORY-1 entries
        initial = [{"date": f"2026-01-{i:02d}", "shake_out_rate": 0.2,
                     "adjustment": 0.0, "direction": "NEUTRAL",
                     "total_stopped": 10, "shake_out_count": 2}
                    for i in range(1, MAX_HISTORY)]
        state_file.write_text(json.dumps(initial), encoding="utf-8")
        with patch("analysis.dynamic_atr.STATE_FILE", state_file):
            _save_snapshot({
                "timestamp": "2026-02-26",
                "shake_out_rate": 0.35,
                "adjustment": 0.2,
                "direction": "WIDEN",
                "total_stopped": 15,
                "shake_out_count": 6,
            })
            history = _load_state()
        assert len(history) == MAX_HISTORY

    def test_corrupted_file_returns_empty(self, tmp_path):
        from analysis.dynamic_atr import _load_state
        state_file = tmp_path / "state.json"
        state_file.write_text("not json", encoding="utf-8")
        with patch("analysis.dynamic_atr.STATE_FILE", state_file):
            history = _load_state()
        assert history == []


# ─── Trend Analysis ──────────────────────────────────────────

class TestAdjustmentTrend:
    """Test trend computation from history."""

    def test_insufficient_data(self):
        from analysis.dynamic_atr import _compute_adjustment_trend
        assert _compute_adjustment_trend([]) == "INSUFFICIENT_DATA"
        assert _compute_adjustment_trend([{"adjustment": 0}] * 3) == "INSUFFICIENT_DATA"

    def test_stable(self):
        from analysis.dynamic_atr import _compute_adjustment_trend
        history = [{"adjustment": 0.0}] * 10
        assert _compute_adjustment_trend(history) == "STABLE"

    def test_widening(self):
        from analysis.dynamic_atr import _compute_adjustment_trend
        # Older: no adjustment, Recent: widening
        history = [{"adjustment": 0.0}] * 5 + [{"adjustment": 0.2}] * 5
        assert _compute_adjustment_trend(history) == "WIDENING"

    def test_tightening(self):
        from analysis.dynamic_atr import _compute_adjustment_trend
        # Older: widening, Recent: tightening
        history = [{"adjustment": 0.2}] * 5 + [{"adjustment": -0.1}] * 5
        assert _compute_adjustment_trend(history) == "TIGHTENING"


# ─── Summary Formatting ──────────────────────────────────────

class TestFormatSummary:
    """Test human-readable summary."""

    def test_insufficient_data(self):
        from analysis.dynamic_atr import _format_summary
        adj = {"adjustment": 0.0, "direction": "NEUTRAL"}
        msg = _format_summary(adj, None, 3, 0, "INSUFFICIENT_DATA")
        assert "數據不足" in msg

    def test_widen_message(self):
        from analysis.dynamic_atr import _format_summary
        adj = {"adjustment": 0.2, "direction": "WIDEN"}
        msg = _format_summary(adj, 0.35, 10, 4, "STABLE")
        assert "WIDEN" in msg
        assert "+0.2" in msg
        assert "35.0%" in msg

    def test_tighten_message(self):
        from analysis.dynamic_atr import _format_summary
        adj = {"adjustment": -0.1, "direction": "TIGHTEN"}
        msg = _format_summary(adj, 0.10, 20, 2, "STABLE")
        assert "TIGHTEN" in msg
        assert "-0.1" in msg

    def test_neutral_message(self):
        from analysis.dynamic_atr import _format_summary
        adj = {"adjustment": 0.0, "direction": "NEUTRAL"}
        msg = _format_summary(adj, 0.20, 10, 2, "STABLE")
        assert "中性" in msg or "無" in msg


# ─── Report Generation ───────────────────────────────────────

class TestGenerateReport:
    """Test full report generation."""

    @patch("analysis.signal_log.detect_shake_outs")
    def test_full_report_with_data(self, mock_so, tmp_path):
        from analysis.dynamic_atr import generate_dynamic_atr_report
        mock_so.return_value = {
            "total_stopped_out": 10,
            "shake_out_count": 4,
            "shake_out_rate": 0.4,
            "rate_warning": True,
            "details": [],
        }
        with patch("analysis.dynamic_atr.STATE_FILE", tmp_path / "state.json"):
            result = generate_dynamic_atr_report(save_snapshot=True)

        assert result["shake_out_rate"] == 0.4
        assert result["adjustment"] == 0.2
        assert result["direction"] == "WIDEN"
        assert result["rate_warning"] is True
        assert "squeeze_breakout" in result["multipliers"]
        assert result["multipliers"]["squeeze_breakout"] == 1.7

    @patch("analysis.signal_log.detect_shake_outs")
    def test_insufficient_samples(self, mock_so, tmp_path):
        from analysis.dynamic_atr import generate_dynamic_atr_report
        mock_so.return_value = {
            "total_stopped_out": 3,
            "shake_out_count": 1,
            "shake_out_rate": 0.333,
            "rate_warning": False,
            "details": [],
        }
        with patch("analysis.dynamic_atr.STATE_FILE", tmp_path / "state.json"):
            result = generate_dynamic_atr_report(save_snapshot=False)

        # < MIN_STOPPED_SIGNALS → rate set to None → neutral
        assert result["shake_out_rate"] is None
        assert result["adjustment"] == 0.0

    @patch("analysis.signal_log.detect_shake_outs", side_effect=Exception("fail"))
    def test_exception_graceful(self, mock_so, tmp_path):
        from analysis.dynamic_atr import generate_dynamic_atr_report
        with patch("analysis.dynamic_atr.STATE_FILE", tmp_path / "state.json"):
            result = generate_dynamic_atr_report(save_snapshot=False)
        assert result["adjustment"] == 0.0
        assert result["direction"] == "NEUTRAL"

    @patch("analysis.signal_log.detect_shake_outs")
    def test_tighten_report(self, mock_so, tmp_path):
        from analysis.dynamic_atr import generate_dynamic_atr_report
        mock_so.return_value = {
            "total_stopped_out": 20,
            "shake_out_count": 2,
            "shake_out_rate": 0.10,
            "rate_warning": False,
            "details": [],
        }
        with patch("analysis.dynamic_atr.STATE_FILE", tmp_path / "state.json"):
            result = generate_dynamic_atr_report(save_snapshot=False)

        assert result["adjustment"] == -0.1
        assert result["direction"] == "TIGHTEN"
        assert result["multipliers"]["momentum_breakout"] == 1.9


# ─── Morning Brief Helper ────────────────────────────────────

class TestBriefHelper:
    """Test Morning Brief integration."""

    @patch("analysis.dynamic_atr.generate_dynamic_atr_report")
    def test_widen_returns_message(self, mock_report):
        from analysis.dynamic_atr import get_atr_alert_for_brief
        mock_report.return_value = {
            "direction": "WIDEN",
            "rate_warning": True,
            "summary_message": "🔓 Dynamic ATR [WIDEN]\n  洗盤率: 40.0%",
        }
        result = get_atr_alert_for_brief()
        assert result is not None
        assert "WIDEN" in result

    @patch("analysis.dynamic_atr.generate_dynamic_atr_report")
    def test_neutral_returns_none(self, mock_report):
        from analysis.dynamic_atr import get_atr_alert_for_brief
        mock_report.return_value = {
            "direction": "NEUTRAL",
            "rate_warning": False,
            "summary_message": "...",
        }
        result = get_atr_alert_for_brief()
        assert result is None

    @patch("analysis.dynamic_atr.generate_dynamic_atr_report")
    def test_rate_warning_even_if_neutral(self, mock_report):
        from analysis.dynamic_atr import get_atr_alert_for_brief
        # Rate > 40% warning but within neutral zone (edge case)
        mock_report.return_value = {
            "direction": "NEUTRAL",
            "rate_warning": True,
            "summary_message": "⚠️ Warning",
        }
        result = get_atr_alert_for_brief()
        assert result is not None

    @patch("analysis.dynamic_atr.generate_dynamic_atr_report", side_effect=Exception("fail"))
    def test_exception_returns_none(self, mock_report):
        from analysis.dynamic_atr import get_atr_alert_for_brief
        result = get_atr_alert_for_brief()
        assert result is None


# ─── stop_loss.py Integration ─────────────────────────────────

class TestStopLossIntegration:
    """Test that stop_loss.py correctly uses dynamic ATR adjustment."""

    def _make_df(self, n=30, price=100.0):
        import pandas as pd
        import numpy as np
        dates = pd.date_range("2026-01-01", periods=n)
        noise = np.random.RandomState(42).randn(n) * 2
        close = price + np.cumsum(noise)
        close = np.maximum(close, 50)  # keep positive
        return pd.DataFrame({
            "open": close + 0.5,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": [1000000] * n,
        }, index=dates)

    def test_no_adjustment(self):
        from analysis.stop_loss import calculate_stop_levels
        df = self._make_df()
        entry = float(df["close"].iloc[-1])
        result = calculate_stop_levels(df, entry, "momentum_breakout", atr_adjustment=0.0)
        assert result.atr_multiplier == 2.0

    def test_widen_adjustment(self):
        from analysis.stop_loss import calculate_stop_levels
        df = self._make_df()
        entry = float(df["close"].iloc[-1])
        result = calculate_stop_levels(df, entry, "momentum_breakout", atr_adjustment=0.2)
        assert result.atr_multiplier == pytest.approx(2.2)

    def test_tighten_adjustment(self):
        from analysis.stop_loss import calculate_stop_levels
        df = self._make_df()
        entry = float(df["close"].iloc[-1])
        result = calculate_stop_levels(df, entry, "momentum_breakout", atr_adjustment=-0.1)
        assert result.atr_multiplier == pytest.approx(1.9)

    def test_squeeze_floor_clamp(self):
        from analysis.stop_loss import calculate_stop_levels
        df = self._make_df()
        entry = float(df["close"].iloc[-1])
        # squeeze base=1.5, -0.1 = 1.4, should clamp to 1.5
        result = calculate_stop_levels(df, entry, "squeeze_breakout", atr_adjustment=-0.1)
        assert result.atr_multiplier == 1.5

    def test_trailing_stop_with_adjustment(self):
        from analysis.stop_loss import compute_trailing_stop
        # Phase 2 test: +1.5R reached but not +2R
        # entry=100, stop=90, r=10. +1.5R=115, +2R=120
        # highest=118 → highest_r=1.8 (≥1.5, <2.0) → Phase 2
        result = compute_trailing_stop(
            entry_price=100, current_price=118,
            highest_price=118, initial_stop=90,
            current_atr=5, r_value=10,
            atr_adjustment=0.2,
        )
        assert result["phase"] == 2
        # With +0.2: 118 - 2.2*5 = 107
        assert result["current_stop"] == 107.0

    def test_trailing_stop_phase3_with_adjustment(self):
        from analysis.stop_loss import compute_trailing_stop
        # Phase 3 test: +2R reached
        # entry=100, stop=90, r=10. +2R=120
        # highest=125 → highest_r=2.5 (≥2.0) → Phase 3
        result = compute_trailing_stop(
            entry_price=100, current_price=125,
            highest_price=125, initial_stop=90,
            current_atr=5, r_value=10,
            atr_adjustment=0.2,
        )
        assert result["phase"] == 3
        # With +0.2: 125 - 1.7*5 = 116.5
        assert result["current_stop"] == 116.5

    def test_trailing_stop_no_adjustment_backward_compatible(self):
        from analysis.stop_loss import compute_trailing_stop
        # Phase 2 without adjustment — same as before
        # highest=118, highest_r=1.8 (≥1.5, <2.0) → Phase 2
        result = compute_trailing_stop(
            entry_price=100, current_price=118,
            highest_price=118, initial_stop=90,
            current_atr=5, r_value=10,
        )
        assert result["phase"] == 2
        assert result["current_stop"] == 108.0  # 118 - 2.0*5


# ─── Constants Verification ──────────────────────────────────

class TestConstants:
    """Verify CTO-approved constants."""

    def test_thresholds(self):
        from analysis.dynamic_atr import SHAKEOUT_HIGH, SHAKEOUT_LOW
        assert SHAKEOUT_HIGH == 0.30
        assert SHAKEOUT_LOW == 0.15

    def test_steps(self):
        from analysis.dynamic_atr import ATR_WIDEN_STEP, ATR_TIGHTEN_STEP
        assert ATR_WIDEN_STEP == 0.2
        assert ATR_TIGHTEN_STEP == 0.1

    def test_bounds(self):
        from analysis.dynamic_atr import ATR_FLOOR, ATR_CEILING
        assert ATR_FLOOR == 1.5
        assert ATR_CEILING == 3.5

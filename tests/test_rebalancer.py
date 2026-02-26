"""Tests for Portfolio Rebalancing Engine (V1.3 P0)."""

import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock


# ─── Regime Classification ───────────────────────────────────

class TestClassifyRegime:
    """Test regime classification from Agg Index + Guard Level."""

    def test_lockdown_overrides_agg(self):
        from analysis.rebalancer import classify_regime
        assert classify_regime(80, guard_level=2) == "LOCKDOWN"

    def test_caution_overrides_agg(self):
        from analysis.rebalancer import classify_regime
        assert classify_regime(80, guard_level=1) == "CAUTION"

    def test_defensive_low_agg(self):
        from analysis.rebalancer import classify_regime
        assert classify_regime(30, guard_level=0) == "DEFENSIVE"

    def test_aggressive_high_agg(self):
        from analysis.rebalancer import classify_regime
        assert classify_regime(75, guard_level=0) == "AGGRESSIVE"

    def test_normal_mid_agg(self):
        from analysis.rebalancer import classify_regime
        assert classify_regime(50, guard_level=0) == "NORMAL"

    def test_none_agg_defaults_normal(self):
        from analysis.rebalancer import classify_regime
        assert classify_regime(None, guard_level=0) == "NORMAL"

    def test_boundary_40_is_normal(self):
        from analysis.rebalancer import classify_regime
        assert classify_regime(40, guard_level=0) == "NORMAL"

    def test_boundary_60_is_normal(self):
        from analysis.rebalancer import classify_regime
        assert classify_regime(60, guard_level=0) == "NORMAL"

    def test_boundary_39_is_defensive(self):
        from analysis.rebalancer import classify_regime
        assert classify_regime(39, guard_level=0) == "DEFENSIVE"

    def test_boundary_61_is_aggressive(self):
        from analysis.rebalancer import classify_regime
        assert classify_regime(61, guard_level=0) == "AGGRESSIVE"


class TestGetTargetExposure:
    """Test raw target exposure mapping."""

    def test_lockdown_zero(self):
        from analysis.rebalancer import get_target_exposure
        assert get_target_exposure("LOCKDOWN") == 0.0

    def test_caution_half(self):
        from analysis.rebalancer import get_target_exposure
        assert get_target_exposure("CAUTION") == 0.50

    def test_defensive_half(self):
        from analysis.rebalancer import get_target_exposure
        assert get_target_exposure("DEFENSIVE") == 0.50

    def test_normal_full(self):
        from analysis.rebalancer import get_target_exposure
        assert get_target_exposure("NORMAL") == 1.0

    def test_aggressive_full(self):
        from analysis.rebalancer import get_target_exposure
        assert get_target_exposure("AGGRESSIVE") == 1.0


# ─── Hysteresis (Anti-Churning) ──────────────────────────────

class TestHysteresis:
    """Test hysteresis buffer for regime changes."""

    def test_first_day_defensive_holds_normal(self):
        """Day 1 of defensive → still holds previous NORMAL target."""
        from analysis.rebalancer import apply_hysteresis
        state = {
            "prev_regime": "NORMAL",
            "regime_streak": 0,
            "last_date": "2026-02-24",
            "last_target_exposure": 1.0,
        }
        target, adj_type, new_state = apply_hysteresis(
            "DEFENSIVE", 0.50, state, "2026-02-25",
        )
        assert target == 1.0  # Held at NORMAL (hysteresis)
        assert adj_type == "HOLD"
        assert new_state["regime_streak"] == 1

    def test_second_day_defensive_triggers(self):
        """Day 2 of defensive → hysteresis met, reduce to 50%."""
        from analysis.rebalancer import apply_hysteresis
        state = {
            "prev_regime": "DEFENSIVE",
            "regime_streak": 1,
            "last_date": "2026-02-25",
            "last_target_exposure": 1.0,
        }
        target, adj_type, new_state = apply_hysteresis(
            "DEFENSIVE", 0.50, state, "2026-02-26",
        )
        assert target == 0.50
        assert adj_type == "STRUCTURAL"
        assert new_state["regime_streak"] == 2

    def test_regime_flip_resets_streak(self):
        """Regime flips from DEFENSIVE to NORMAL → streak resets."""
        from analysis.rebalancer import apply_hysteresis
        state = {
            "prev_regime": "DEFENSIVE",
            "regime_streak": 1,
            "last_date": "2026-02-25",
            "last_target_exposure": 0.50,
        }
        target, adj_type, new_state = apply_hysteresis(
            "NORMAL", 1.0, state, "2026-02-26",
        )
        assert target == 0.50  # Held (streak reset to 1, needs 2)
        assert new_state["regime_streak"] == 1

    def test_guard_caution_bypasses_hysteresis(self):
        """Guard CAUTION takes effect immediately — safety first."""
        from analysis.rebalancer import apply_hysteresis
        state = {
            "prev_regime": "NORMAL",
            "regime_streak": 0,
            "last_date": "2026-02-24",
            "last_target_exposure": 1.0,
        }
        target, adj_type, new_state = apply_hysteresis(
            "CAUTION", 0.50, state, "2026-02-25",
        )
        assert target == 0.50  # Immediate, no hysteresis
        assert adj_type == "STRUCTURAL"

    def test_guard_lockdown_bypasses_hysteresis(self):
        """Guard LOCKDOWN takes effect immediately."""
        from analysis.rebalancer import apply_hysteresis
        state = {
            "prev_regime": "NORMAL",
            "regime_streak": 0,
            "last_date": "2026-02-24",
            "last_target_exposure": 1.0,
        }
        target, adj_type, new_state = apply_hysteresis(
            "LOCKDOWN", 0.0, state, "2026-02-25",
        )
        assert target == 0.0
        assert adj_type == "STRUCTURAL"

    def test_same_day_no_double_count(self):
        """Same date doesn't increment streak."""
        from analysis.rebalancer import apply_hysteresis
        state = {
            "prev_regime": "DEFENSIVE",
            "regime_streak": 1,
            "last_date": "2026-02-25",
            "last_target_exposure": 1.0,
        }
        target, adj_type, new_state = apply_hysteresis(
            "DEFENSIVE", 0.50, state, "2026-02-25",
        )
        # Same date → streak doesn't change
        assert new_state["regime_streak"] == 1


# ─── Adjustment Classification ────────────────────────────────

class TestAdjustmentClassification:
    """Test two-tier adjustment classification (CTO directive)."""

    def test_hold_no_change(self):
        from analysis.rebalancer import _classify_adjustment
        assert _classify_adjustment(1.0, 1.0) == "HOLD"

    def test_light_small_change(self):
        from analysis.rebalancer import _classify_adjustment
        assert _classify_adjustment(1.0, 0.92) == "LIGHT"

    def test_structural_large_change(self):
        from analysis.rebalancer import _classify_adjustment
        assert _classify_adjustment(1.0, 0.50) == "STRUCTURAL"

    def test_structural_to_zero(self):
        from analysis.rebalancer import _classify_adjustment
        assert _classify_adjustment(1.0, 0.0) == "STRUCTURAL"


# ─── Position Actions ─────────────────────────────────────────

class TestPositionActions:
    """Test per-position rebalancing actions."""

    def _make_positions(self, n=3):
        return [
            {
                "code": f"{2330 + i}",
                "name": f"Stock{i}",
                "is_live": True,
                "entry_price": 100,
                "current_stop": 90,
                "trailing_phase": i,
                "rs_rating": 80 + i * 5,
                "priority_score": 70 + i * 10,
            }
            for i in range(n)
        ]

    def test_lockdown_all_exit(self):
        from analysis.rebalancer import compute_position_actions
        positions = self._make_positions(3)
        actions = compute_position_actions(positions, 0.0, "LOCKDOWN")
        assert all(a["action"] == "EXIT" for a in actions)
        assert all(a["urgency"] == "HIGH" for a in actions)

    def test_caution_all_reduce(self):
        from analysis.rebalancer import compute_position_actions
        positions = self._make_positions(3)
        actions = compute_position_actions(positions, 0.5, "CAUTION")
        assert all(a["action"] in ("REDUCE", "SKIP") for a in actions)

    def test_normal_all_hold(self):
        from analysis.rebalancer import compute_position_actions
        positions = self._make_positions(3)
        actions = compute_position_actions(positions, 1.0, "NORMAL")
        assert all(a["action"] == "HOLD" for a in actions)

    def test_aggressive_hold(self):
        from analysis.rebalancer import compute_position_actions
        positions = self._make_positions(3)
        actions = compute_position_actions(positions, 1.0, "AGGRESSIVE")
        assert all(a["action"] == "HOLD" for a in actions)

    def test_defensive_higher_priority_kept_more(self):
        """Higher priority_score positions should have higher target_weight."""
        from analysis.rebalancer import compute_position_actions
        positions = [
            {"code": "A", "name": "High", "is_live": True, "priority_score": 90,
             "entry_price": 100, "current_stop": 90, "trailing_phase": 0, "rs_rating": 95},
            {"code": "B", "name": "Low", "is_live": True, "priority_score": 20,
             "entry_price": 100, "current_stop": 90, "trailing_phase": 0, "rs_rating": 30},
        ]
        actions = compute_position_actions(positions, 0.5, "DEFENSIVE")
        # Find actions by code
        a_action = next(a for a in actions if a["code"] == "A")
        b_action = next(a for a in actions if a["code"] == "B")
        assert a_action["target_weight"] >= b_action["target_weight"]

    def test_empty_positions(self):
        from analysis.rebalancer import compute_position_actions
        actions = compute_position_actions([], 1.0, "NORMAL")
        assert actions == []


# ─── Full Report Generation ───────────────────────────────────

class TestGenerateRebalanceReport:
    """Test complete rebalance report generation."""

    def test_normal_report(self, tmp_path):
        from analysis.rebalancer import generate_rebalance_report
        with patch("analysis.rebalancer.STATE_FILE", tmp_path / "state.json"):
            with patch("analysis.rebalancer._fetch_live_positions", return_value=[]):
                result = generate_rebalance_report(
                    agg_score=55, guard_level=0, guard_label="NORMAL",
                )
        assert result["regime"] == "NORMAL"
        assert result["target_exposure"] == 1.0
        assert result["adjustment_type"] == "HOLD"
        assert "summary_message" in result

    def test_lockdown_report(self, tmp_path):
        from analysis.rebalancer import generate_rebalance_report
        positions = [
            {"code": "2330", "name": "TSMC", "is_live": True, "priority_score": 85,
             "entry_price": 980, "current_stop": 930, "trailing_phase": 2, "rs_rating": 99},
        ]
        with patch("analysis.rebalancer.STATE_FILE", tmp_path / "state.json"):
            result = generate_rebalance_report(
                agg_score=20, guard_level=2, guard_label="LOCKDOWN",
                positions=positions,
            )
        assert result["regime"] == "LOCKDOWN"
        assert result["target_exposure"] == 0.0
        assert len(result["position_actions"]) == 1
        assert result["position_actions"][0]["action"] == "EXIT"

    def test_caution_report(self, tmp_path):
        from analysis.rebalancer import generate_rebalance_report
        positions = [
            {"code": "2330", "name": "TSMC", "is_live": True, "priority_score": 85,
             "entry_price": 980, "current_stop": 930, "trailing_phase": 0, "rs_rating": 99},
        ]
        with patch("analysis.rebalancer.STATE_FILE", tmp_path / "state.json"):
            result = generate_rebalance_report(
                agg_score=50, guard_level=1, guard_label="CAUTION",
                positions=positions,
            )
        assert result["regime"] == "CAUTION"
        assert result["target_exposure"] == 0.5

    def test_report_includes_summary_message(self, tmp_path):
        from analysis.rebalancer import generate_rebalance_report
        with patch("analysis.rebalancer.STATE_FILE", tmp_path / "state.json"):
            with patch("analysis.rebalancer._fetch_live_positions", return_value=[]):
                result = generate_rebalance_report(agg_score=65, guard_level=0)
        assert "Regime" in result["summary_message"]

    def test_hysteresis_persisted(self, tmp_path):
        """Verify state file is written after report generation."""
        from analysis.rebalancer import generate_rebalance_report
        state_file = tmp_path / "state.json"
        with patch("analysis.rebalancer.STATE_FILE", state_file):
            with patch("analysis.rebalancer._fetch_live_positions", return_value=[]):
                generate_rebalance_report(agg_score=30, guard_level=0)
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["prev_regime"] == "DEFENSIVE"


# ─── Summary Formatting ──────────────────────────────────────

class TestFormatSummary:
    """Test summary message formatting."""

    def test_lockdown_mentions_exit(self):
        from analysis.rebalancer import _format_summary
        actions = [{"code": "2330", "name": "TSMC", "action": "EXIT",
                     "current_weight": 50, "target_weight": 0,
                     "reason": "LOCKDOWN", "urgency": "HIGH"}]
        msg = _format_summary("LOCKDOWN", 20, "LOCKDOWN", 0.0, "STRUCTURAL", False, actions)
        assert "出場" in msg
        assert "2330" in msg

    def test_no_positions_message(self):
        from analysis.rebalancer import _format_summary
        msg = _format_summary("NORMAL", 55, "NORMAL", 1.0, "HOLD", False, [])
        assert "無持倉" in msg

    def test_hysteresis_note(self):
        from analysis.rebalancer import _format_summary
        msg = _format_summary("DEFENSIVE", 35, "NORMAL", 1.0, "HOLD", True, [])
        assert "緩衝" in msg

    def test_structural_warning(self):
        from analysis.rebalancer import _format_summary
        msg = _format_summary("CAUTION", 45, "CAUTION", 0.5, "STRUCTURAL", False, [])
        assert "結構性調整" in msg


# ─── State Persistence ────────────────────────────────────────

class TestStatePersistence:
    """Test state file load/save."""

    def test_load_missing_file(self, tmp_path):
        from analysis.rebalancer import _load_state
        with patch("analysis.rebalancer.STATE_FILE", tmp_path / "nonexistent.json"):
            state = _load_state()
        assert state["prev_regime"] == "NORMAL"
        assert state["last_target_exposure"] == 1.0

    def test_save_and_load(self, tmp_path):
        from analysis.rebalancer import _save_state, _load_state
        state_file = tmp_path / "state.json"
        with patch("analysis.rebalancer.STATE_FILE", state_file):
            _save_state({
                "prev_regime": "DEFENSIVE",
                "regime_streak": 2,
                "last_date": "2026-02-26",
                "last_target_exposure": 0.5,
            })
            loaded = _load_state()
        assert loaded["prev_regime"] == "DEFENSIVE"
        assert loaded["regime_streak"] == 2

    def test_corrupted_file_returns_default(self, tmp_path):
        from analysis.rebalancer import _load_state
        state_file = tmp_path / "state.json"
        state_file.write_text("not json", encoding="utf-8")
        with patch("analysis.rebalancer.STATE_FILE", state_file):
            state = _load_state()
        assert state["prev_regime"] == "NORMAL"

"""Tests for R86 r_tracker.py — R-Multiple + System Expectancy."""

import pytest

from analysis.r_tracker import (
    compute_r_multiple,
    get_r_status,
    get_r_color,
    track_position_r,
    compute_system_expectancy,
    R_BREAKEVEN_ZONE,
    R_WINNER_THRESHOLD,
    R_HOME_RUN_THRESHOLD,
)


# ─── Test R-Multiple Computation ──────────────────────────────

class TestComputeRMultiple:
    def test_basic_profit(self):
        """Entry 100, stop 95, current 110 → R = 2.0"""
        r = compute_r_multiple(100.0, 110.0, 95.0)
        assert r == pytest.approx(2.0)

    def test_basic_loss(self):
        """Entry 100, stop 95, current 93 → R = -1.4"""
        r = compute_r_multiple(100.0, 93.0, 95.0)
        assert r == pytest.approx(-1.4)

    def test_at_stop(self):
        """At stop price → R = -1.0"""
        r = compute_r_multiple(100.0, 95.0, 95.0)
        assert r == pytest.approx(-1.0)

    def test_at_entry(self):
        """At entry → R = 0"""
        r = compute_r_multiple(100.0, 100.0, 95.0)
        assert r == pytest.approx(0.0)

    def test_home_run(self):
        """R ≥ 3.0"""
        r = compute_r_multiple(100.0, 115.0, 95.0)
        assert r == pytest.approx(3.0)

    def test_zero_risk(self):
        """Entry == stop → return 0"""
        r = compute_r_multiple(100.0, 110.0, 100.0)
        assert r == 0.0

    def test_negative_risk(self):
        """Stop above entry → return 0"""
        r = compute_r_multiple(100.0, 110.0, 105.0)
        assert r == 0.0


# ─── Test R Status Labels ─────────────────────────────────────

class TestRStatus:
    def test_home_run(self):
        assert get_r_status(3.5) == "Home Run"

    def test_one_r_winner(self):
        assert get_r_status(1.5) == "1R Winner"

    def test_partial_gain(self):
        assert get_r_status(0.5) == "Partial Gain"

    def test_breakeven(self):
        assert get_r_status(0.05) == "Breakeven"
        assert get_r_status(-0.05) == "Breakeven"

    def test_initial_risk(self):
        assert get_r_status(-0.5) == "Initial Risk"
        assert get_r_status(-2.0) == "Initial Risk"


# ─── Test R Colors ────────────────────────────────────────────

class TestRColor:
    def test_home_run_purple(self):
        assert get_r_color(3.5) == "#a855f7"

    def test_winner_green(self):
        assert get_r_color(1.5) == "#22c55e"

    def test_big_loser_red(self):
        assert get_r_color(-1.5) == "#ef4444"

    def test_breakeven_grey(self):
        assert get_r_color(0.0) == "#94a3b8"


# ─── Test Track Position R ────────────────────────────────────

class TestTrackPositionR:
    def test_open_position(self):
        positions = [
            {"code": "2330", "entry_price": 100.0, "current_price": 110.0, "stop_price": 95.0}
        ]
        results = track_position_r(positions)
        assert len(results) == 1
        assert results[0]["intended_r"] == 2.0
        assert results[0]["realized_r"] is None
        assert results[0]["r_status"] == "1R Winner"
        assert results[0]["is_closed"] is False

    def test_closed_position(self):
        positions = [
            {"code": "2330", "entry_price": 100.0, "current_price": 100.0,
             "stop_price": 95.0, "exit_price": 115.0}
        ]
        results = track_position_r(positions)
        assert len(results) == 1
        assert results[0]["realized_r"] == 3.0
        assert results[0]["r_status"] == "Home Run"
        assert results[0]["is_closed"] is True

    def test_multiple_positions(self):
        positions = [
            {"code": "2330", "entry_price": 100.0, "current_price": 105.0, "stop_price": 95.0},
            {"code": "2317", "entry_price": 50.0, "current_price": 45.0, "stop_price": 46.0},
        ]
        results = track_position_r(positions)
        assert len(results) == 2
        assert results[0]["intended_r"] == 1.0
        assert results[1]["intended_r"] == pytest.approx(-1.25)

    def test_display_text(self):
        positions = [
            {"code": "2330", "entry_price": 100.0, "current_price": 110.0, "stop_price": 95.0}
        ]
        results = track_position_r(positions)
        assert "Risking" in results[0]["display_text"]

    def test_empty_positions(self):
        results = track_position_r([])
        assert results == []


# ─── Test System Expectancy ───────────────────────────────────

class TestSystemExpectancy:
    def test_basic_expectancy(self):
        """50% win rate, avg win 2R, avg loss 1R → expectancy = 0.5"""
        trades = [
            {"realized_r": 2.0},
            {"realized_r": -1.0},
            {"realized_r": 2.0},
            {"realized_r": -1.0},
            {"realized_r": 2.0},
            {"realized_r": -1.0},
            {"realized_r": 2.0},
            {"realized_r": -1.0},
            {"realized_r": 2.0},
            {"realized_r": -1.0},
        ]
        result = compute_system_expectancy(trades)
        assert result["expectancy"] == pytest.approx(0.5, abs=0.01)
        assert result["win_rate"] == pytest.approx(0.5)
        assert result["avg_win_r"] == pytest.approx(2.0)
        assert result["avg_loss_r"] == pytest.approx(1.0)

    def test_market_wizard(self):
        """High win rate + big winners → expectancy > 1.0"""
        trades = [
            {"realized_r": 3.0},
            {"realized_r": 2.5},
            {"realized_r": -0.5},
            {"realized_r": 4.0},
            {"realized_r": 1.5},
            {"realized_r": -0.8},
            {"realized_r": 2.0},
            {"realized_r": 3.5},
            {"realized_r": -0.3},
            {"realized_r": 2.0},
        ]
        result = compute_system_expectancy(trades)
        assert result["expectancy"] > 1.0
        assert result["grade"] == "Market Wizard"
        assert result["grade_color"] == "#a855f7"

    def test_losing_system(self):
        """Low win rate + small winners → negative expectancy."""
        trades = [
            {"realized_r": 0.5},
            {"realized_r": -1.5},
            {"realized_r": -1.0},
            {"realized_r": -2.0},
            {"realized_r": 0.3},
            {"realized_r": -1.2},
            {"realized_r": -0.8},
            {"realized_r": -1.5},
            {"realized_r": 0.2},
            {"realized_r": -1.0},
        ]
        result = compute_system_expectancy(trades)
        assert result["expectancy"] < 0
        assert result["grade"] == "Losing System"

    def test_insufficient_data(self):
        trades = [{"realized_r": 2.0}, {"realized_r": -1.0}]
        result = compute_system_expectancy(trades)
        assert result["grade"] == "Insufficient Data"

    def test_empty_trades(self):
        result = compute_system_expectancy([])
        assert result["total_trades"] == 0
        assert result["expectancy"] == 0.0
        assert result["grade"] == "Insufficient Data"

    def test_r_distribution(self):
        trades = [
            {"realized_r": 4.0},    # home run
            {"realized_r": 2.5},    # big win
            {"realized_r": 1.5},    # win
            {"realized_r": 0.5},    # small win
            {"realized_r": 0.0},    # breakeven
            {"realized_r": -0.5},   # small loss
            {"realized_r": -1.5},   # loss
            {"realized_r": -3.0},   # big loss
            {"realized_r": 1.0},
            {"realized_r": -0.8},
        ]
        result = compute_system_expectancy(trades)
        dist = result["r_distribution"]
        assert dist["home_run_above_3"] == 1
        assert dist["big_win_2_to_3"] == 1
        assert dist["big_loss_below_neg2"] == 1

    def test_uses_realized_r(self):
        """Should prefer realized_r over intended_r."""
        trades = [
            {"realized_r": -2.0, "intended_r": -1.0},  # gap-down
        ] * 10
        result = compute_system_expectancy(trades)
        assert result["avg_loss_r"] == pytest.approx(2.0)

    def test_falls_back_to_intended_r(self):
        """If no realized_r, uses intended_r."""
        trades = [{"intended_r": 2.0}] * 10
        result = compute_system_expectancy(trades)
        assert result["avg_win_r"] == pytest.approx(2.0)

    def test_best_worst_r(self):
        trades = [
            {"realized_r": 5.0},
            {"realized_r": -2.0},
            {"realized_r": 1.0},
        ] * 4  # 12 trades for > 10 threshold
        result = compute_system_expectancy(trades)
        assert result["best_r"] == 5.0
        assert result["worst_r"] == -2.0

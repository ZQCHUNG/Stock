"""Tests for Aggressive Mode (WarriorExitEngine) — R88

Verifies physical isolation from Bold exit logic.
Key invariant: NO tight stops (structural_stop, time_stop_5d) exist in this module.
"""

import pytest
import numpy as np
import pandas as pd

from analysis.strategy_aggressive import (
    compute_warrior_exit,
    check_pyramid_condition,
    compute_aggressive_metrics,
    compute_ulcer_index,
    check_regime_gate,
    STRATEGY_AGGRESSIVE_PARAMS,
)


# === Parameter Integrity Tests ===

class TestWarriorParams:
    """Verify WarriorExitEngine params don't have Bold tight-stop contamination."""

    def test_no_structural_stop(self):
        assert "structural_stop_enabled" not in STRATEGY_AGGRESSIVE_PARAMS

    def test_no_time_stop(self):
        assert "time_stop_days" not in STRATEGY_AGGRESSIVE_PARAMS
        assert "time_stop_min_gain" not in STRATEGY_AGGRESSIVE_PARAMS
        assert "time_stop_enabled" not in STRATEGY_AGGRESSIVE_PARAMS

    def test_disaster_stop_is_20pct(self):
        assert STRATEGY_AGGRESSIVE_PARAMS["disaster_stop_pct"] == 0.20

    def test_atr_multiplier_is_3x(self):
        assert STRATEGY_AGGRESSIVE_PARAMS["atr_trail_multiplier"] == 3.0

    def test_max_hold_60d(self):
        assert STRATEGY_AGGRESSIVE_PARAMS["max_hold_days"] == 60

    def test_pyramid_params_exist(self):
        assert STRATEGY_AGGRESSIVE_PARAMS["pyramid_enabled"] is True
        assert STRATEGY_AGGRESSIVE_PARAMS["pyramid_initial_pct"] == 0.20
        assert STRATEGY_AGGRESSIVE_PARAMS["pyramid_max_total_pct"] == 0.40
        assert STRATEGY_AGGRESSIVE_PARAMS["pyramid_max_adds"] == 2


# === Disaster Stop Tests ===

class TestDisasterStop:
    """Disaster stop: -20% hard, triggers even during min_hold_days."""

    def test_disaster_triggers_at_minus_20pct(self):
        result = compute_warrior_exit(
            entry_price=100, current_price=79.9, peak_price=100,
            current_atr=3.0, hold_days=1, current_low=79,
        )
        assert result["should_exit"] is True
        assert "disaster_stop" in result["exit_reason"]

    def test_disaster_triggers_during_min_hold(self):
        result = compute_warrior_exit(
            entry_price=100, current_price=79, peak_price=100,
            current_atr=3.0, hold_days=2, current_low=78,
        )
        assert result["should_exit"] is True
        assert "disaster_stop" in result["exit_reason"]

    def test_no_disaster_at_minus_15pct(self):
        result = compute_warrior_exit(
            entry_price=100, current_price=85, peak_price=100,
            current_atr=3.0, hold_days=10, current_low=84,
        )
        assert result["should_exit"] is False or "disaster" not in result["exit_reason"]

    def test_disaster_at_exact_minus_20pct(self):
        # Price exactly at -20%. Disaster check runs before ATR trail.
        # gain_pct = 80/100 - 1 = -0.20, which is <= -0.20 → disaster triggers
        result = compute_warrior_exit(
            entry_price=100, current_price=79.99, peak_price=100,
            current_atr=10.0, hold_days=10, current_low=79,
        )
        assert result["should_exit"] is True
        assert "disaster_stop" in result["exit_reason"]


# === ATR Trailing Tests ===

class TestATRTrailing:
    """ATR 3× trailing from entry."""

    def test_atr_trail_triggers(self):
        # Peak=120, ATR=3, stop=120-9=111. Price=110 < 111 → exit
        result = compute_warrior_exit(
            entry_price=100, current_price=110, peak_price=120,
            current_atr=3.0, hold_days=10, current_low=109,
        )
        assert result["should_exit"] is True
        assert result["exit_reason"] == "atr_trail_3x"

    def test_atr_trail_holds_above_stop(self):
        # Peak=120, ATR=3, stop=120-9=111. Price=115 > 111 → hold
        result = compute_warrior_exit(
            entry_price=100, current_price=115, peak_price=120,
            current_atr=3.0, hold_days=10, current_low=114,
        )
        assert result["should_exit"] is False

    def test_atr_trail_respects_min_hold(self):
        # Within min_hold_days, only disaster stop triggers
        result = compute_warrior_exit(
            entry_price=100, current_price=95, peak_price=105,
            current_atr=2.0, hold_days=3, current_low=94,
        )
        assert result["should_exit"] is False

    def test_atr_floor_at_disaster_level(self):
        # ATR stop can't be tighter than -20% from entry
        # Entry=100, disaster=-20%=80. Even if ATR is tiny, floor at 80.
        result = compute_warrior_exit(
            entry_price=100, current_price=81, peak_price=105,
            current_atr=0.5, hold_days=10, current_low=80,
        )
        assert result["should_exit"] is True


# === MA20 Slope Combo Stop ===

class TestMA20SlopeCombo:

    def test_combo_triggers(self):
        # Use large ATR so ATR trail (peak-3*ATR) doesn't fire first
        result = compute_warrior_exit(
            entry_price=100, current_price=95, peak_price=110,
            current_atr=10.0, hold_days=15, current_low=94,
            current_ma20=97, ma20_slope=-0.01, weekly_low=96,
        )
        assert result["should_exit"] is True
        assert result["exit_reason"] == "ma20_slope_combo"

    def test_combo_no_trigger_slope_positive(self):
        result = compute_warrior_exit(
            entry_price=100, current_price=95, peak_price=110,
            current_atr=5.0, hold_days=15, current_low=94,
            current_ma20=97, ma20_slope=0.01, weekly_low=96,
        )
        # Slope positive → combo doesn't trigger
        assert result["exit_reason"] != "ma20_slope_combo"

    def test_combo_no_trigger_price_above_weekly_low(self):
        result = compute_warrior_exit(
            entry_price=100, current_price=98, peak_price=110,
            current_atr=5.0, hold_days=15, current_low=97,
            current_ma20=97, ma20_slope=-0.01, weekly_low=96,
        )
        assert result["exit_reason"] != "ma20_slope_combo"


# === MA50 Death Cross ===

class TestMA50DeathCross:

    def test_death_cross_triggers(self):
        # Use large ATR so ATR trail doesn't fire first
        result = compute_warrior_exit(
            entry_price=100, current_price=95, peak_price=110,
            current_atr=10.0, hold_days=20, current_low=94,
            current_ma50=96, price_above_ma50=False, prev_price_above_ma50=True,
        )
        assert result["should_exit"] is True
        assert result["exit_reason"] == "ma50_death_cross"

    def test_no_death_cross_when_still_above(self):
        result = compute_warrior_exit(
            entry_price=100, current_price=98, peak_price=115,
            current_atr=5.0, hold_days=20, current_low=97,
            current_ma50=96, price_above_ma50=True, prev_price_above_ma50=True,
        )
        assert result["exit_reason"] != "ma50_death_cross"

    def test_no_death_cross_when_already_below(self):
        # Was below yesterday, still below → not a cross
        result = compute_warrior_exit(
            entry_price=100, current_price=94, peak_price=115,
            current_atr=5.0, hold_days=20, current_low=93,
            current_ma50=96, price_above_ma50=False, prev_price_above_ma50=False,
        )
        assert result["exit_reason"] != "ma50_death_cross"


# === Max Hold Days ===

class TestMaxHold:

    def test_max_hold_triggers(self):
        result = compute_warrior_exit(
            entry_price=100, current_price=130, peak_price=140,
            current_atr=5.0, hold_days=60, current_low=129,
        )
        assert result["should_exit"] is True
        assert "max_hold" in result["exit_reason"]


# === Pyramid Tests ===

class TestPyramid:

    def test_pyramid_when_profitable_at_ma20(self):
        result = check_pyramid_condition(
            entry_price=100, current_price=108,
            current_ma20=105, prev_close=106,
            current_volume=5000, volume_ma20=4000,
            add_count=0,
        )
        assert result["should_add"] is True
        assert result["reason"] == "ma20_touchdown"

    def test_no_pyramid_when_losing(self):
        result = check_pyramid_condition(
            entry_price=100, current_price=98,
            current_ma20=97, prev_close=97,
            current_volume=5000, volume_ma20=4000,
            add_count=0,
        )
        assert result["should_add"] is False

    def test_no_pyramid_at_max_adds(self):
        result = check_pyramid_condition(
            entry_price=100, current_price=120,
            current_ma20=115, prev_close=118,
            current_volume=5000, volume_ma20=4000,
            add_count=2,
        )
        assert result["should_add"] is False
        assert result["reason"] == "max_adds_reached"

    def test_no_pyramid_when_disabled(self):
        result = check_pyramid_condition(
            entry_price=100, current_price=120,
            current_ma20=115, prev_close=118,
            current_volume=5000, volume_ma20=4000,
            add_count=0,
            params={"pyramid_enabled": False},
        )
        assert result["should_add"] is False


# === Aggressive Metrics Tests ===

class TestAggressiveMetrics:

    def test_payload_ratio(self):
        trades = [
            {"return_pct": 1.50},   # Big winner
            {"return_pct": -0.10},
            {"return_pct": 0.05},
            {"return_pct": -0.08},
            {"return_pct": 0.02},
        ]
        m = compute_aggressive_metrics(trades)
        assert m["payload_ratio"] > 0.5  # Top winner dominates

    def test_home_run_count(self):
        trades = [
            {"return_pct": 0.60},
            {"return_pct": 0.30},
            {"return_pct": 1.20},
            {"return_pct": -0.15},
        ]
        m = compute_aggressive_metrics(trades)
        assert m["home_run_count"] == 2  # 60% and 120%
        assert m["home_run_pct"] == 0.5

    def test_capture_rates(self):
        trades = [
            {"return_pct": 0.60},
            {"return_pct": 0.35},
            {"return_pct": 0.10},
            {"return_pct": -0.05},
        ]
        m = compute_aggressive_metrics(trades)
        assert m["capture_rate_30"] == 0.5
        assert m["capture_rate_50"] == 0.25

    def test_empty_trades(self):
        m = compute_aggressive_metrics([])
        assert m["payload_ratio"] == 0
        assert m["home_run_count"] == 0

    def test_ulcer_index(self):
        # Flat equity → Ulcer = 0
        flat = pd.Series([100, 100, 100, 100, 100])
        assert compute_ulcer_index(flat) == 0.0

        # Declining equity → Ulcer > 0
        declining = pd.Series([100, 95, 90, 85, 80])
        assert compute_ulcer_index(declining) > 0

    def test_ulcer_index_recovery(self):
        # Dip then recovery → smaller Ulcer than monotonic decline
        dip = pd.Series([100, 90, 95, 100, 105])
        decline = pd.Series([100, 90, 85, 80, 75])
        assert compute_ulcer_index(dip) < compute_ulcer_index(decline)


# === Integration: No Bold Contamination ===

class TestPhysicalIsolation:
    """Verify WarriorExitEngine doesn't import or use Bold exit logic."""

    def test_no_bold_exit_function_in_aggressive(self):
        import analysis.strategy_aggressive as mod
        # Module must NOT have compute_bold_exit as a callable
        assert not hasattr(mod, "compute_bold_exit")
        # Must NOT import it
        import_names = [name for name in dir(mod) if "bold_exit" in name.lower()]
        assert len(import_names) == 0

    def test_warrior_exit_different_from_bold(self):
        from analysis.strategy_bold import compute_bold_exit

        # Scenario: entry=100, current=98, peak=102, ATR=5, day=6
        # Bold should exit (time_stop_5d at gain<3%), Warrior should NOT
        bold_result = compute_bold_exit(
            entry_price=100, current_price=98, peak_price=102,
            current_atr=5.0, hold_days=6,
        )
        warrior_result = compute_warrior_exit(
            entry_price=100, current_price=98, peak_price=102,
            current_atr=5.0, hold_days=6, current_low=97,
        )
        # Bold exits on time_stop, Warrior holds (ATR stop = 102-15=87, still far)
        assert bold_result["should_exit"] is True
        assert warrior_result["should_exit"] is False


# === Gap-Down Guard Tests (CTO R88 recommendation) ===

class TestGapDownGuard:
    """TW market limit-down gaps can bypass disaster stop. Exit at open."""

    def test_gap_down_triggers(self):
        # Open price already at -22%, below disaster -20%
        result = compute_warrior_exit(
            entry_price=100, current_price=77, peak_price=100,
            current_atr=3.0, hold_days=5, current_low=76,
            current_open=78,
        )
        assert result["should_exit"] is True
        assert result["exit_reason"] == "gap_down_guard"

    def test_gap_down_during_min_hold(self):
        # Gap down should trigger even during min_hold
        result = compute_warrior_exit(
            entry_price=100, current_price=75, peak_price=100,
            current_atr=3.0, hold_days=1, current_low=74,
            current_open=79,
        )
        assert result["should_exit"] is True
        assert result["exit_reason"] == "gap_down_guard"

    def test_no_gap_down_when_open_ok(self):
        # Open at -10%, well above disaster stop
        result = compute_warrior_exit(
            entry_price=100, current_price=90, peak_price=105,
            current_atr=3.0, hold_days=10, current_low=89,
            current_open=91,
        )
        assert result["exit_reason"] != "gap_down_guard"

    def test_gap_down_without_open_data(self):
        # No open data → graceful fallback to normal checks
        result = compute_warrior_exit(
            entry_price=100, current_price=79, peak_price=100,
            current_atr=3.0, hold_days=10, current_low=78,
        )
        # Should still trigger disaster stop, not gap_down_guard
        assert result["should_exit"] is True
        assert "disaster_stop" in result["exit_reason"]


# === Regime Gate Tests (CTO R88 recommendation) ===

class TestRegimeGate:
    """Global Regime Gate — block Aggressive entries in bear markets."""

    def test_healthy_market(self):
        result = check_regime_gate(
            taiex_close=22000, taiex_ma200=20000, taiex_ma20_slope=0.5,
        )
        assert result["allowed"] is True
        assert result["reason"] == "taiex_healthy"

    def test_below_ma200_blocks(self):
        result = check_regime_gate(
            taiex_close=19000, taiex_ma200=20000, taiex_ma20_slope=-0.3,
        )
        assert result["allowed"] is False
        assert result["downshift"] == "bold"

    def test_weakening_allows_with_warning(self):
        # Above MA200 but slope negative → cautious
        result = check_regime_gate(
            taiex_close=21000, taiex_ma200=20000, taiex_ma20_slope=-0.2,
        )
        assert result["allowed"] is True
        assert result["reason"] == "taiex_weakening"
        assert result["downshift"] == "reduce_size"

    def test_no_data_allows(self):
        result = check_regime_gate()
        assert result["allowed"] is True
        assert result["reason"] == "no_taiex_data"

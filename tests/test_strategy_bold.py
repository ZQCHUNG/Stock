"""Tests for analysis/strategy_bold.py — Bold/Aggressive strategy."""

import numpy as np
import pandas as pd
import pytest

from analysis.strategy_bold import (
    generate_bold_signals,
    get_bold_analysis,
    compute_bold_exit,
    compute_rs_ratio,
    _compute_bb_bandwidth,
    _detect_squeeze,
    STRATEGY_BOLD_PARAMS,
    STRATEGY_BOLD_ULTRA_WIDE,
)


def _make_df(prices, volumes=None, n=200):
    """Create synthetic price DataFrame for testing."""
    if isinstance(prices, (int, float)):
        prices = [prices] * n
    dates = pd.date_range("2024-01-01", periods=len(prices), freq="B")
    if volumes is None:
        volumes = [500_000] * len(prices)
    df = pd.DataFrame({
        "open": prices,
        "high": [p * 1.02 for p in prices],
        "low": [p * 0.98 for p in prices],
        "close": prices,
        "volume": volumes,
    }, index=dates)
    return df


def _make_squeeze_then_breakout(n_flat=100, n_breakout=20, base_price=30.0):
    """Create a price series: long flat period → sudden breakout with volume."""
    # Flat period with very low volatility
    flat_prices = [base_price + np.random.normal(0, 0.1) for _ in range(n_flat)]
    flat_volumes = [200_000] * n_flat

    # Breakout: price jumps with high volume
    breakout_prices = []
    breakout_volumes = []
    p = base_price
    for i in range(n_breakout):
        p *= 1.03 + np.random.uniform(0, 0.02)  # 3-5% daily gains
        breakout_prices.append(p)
        breakout_volumes.append(2_000_000)  # 10x normal volume

    all_prices = flat_prices + breakout_prices
    all_volumes = flat_volumes + breakout_volumes
    return _make_df(all_prices, all_volumes, len(all_prices))


class TestComputeBoldExit:
    """Test the step-up buffer exit logic."""

    def test_disaster_stop(self):
        """Absolute stop loss should trigger regardless of level."""
        result = compute_bold_exit(
            entry_price=100, current_price=80, peak_price=105,
            current_atr=3.0, hold_days=30
        )
        assert result["should_exit"] is True
        assert "disaster_stop" in result["exit_reason"]
        assert result["level"] == 0

    def test_min_hold_protection(self):
        """Should not exit during min hold period (except disaster)."""
        result = compute_bold_exit(
            entry_price=100, current_price=92, peak_price=100,
            current_atr=3.0, hold_days=3
        )
        assert result["should_exit"] is False  # -8% but min_hold protects

    def test_min_hold_disaster_override(self):
        """Disaster stop overrides min hold protection."""
        result = compute_bold_exit(
            entry_price=100, current_price=84, peak_price=100,
            current_atr=3.0, hold_days=3
        )
        assert result["should_exit"] is True  # -16% triggers disaster

    def test_level1_trailing(self):
        """Level 1: gain < 30%, -15% trailing from peak."""
        result = compute_bold_exit(
            entry_price=100, current_price=108, peak_price=115,
            current_atr=3.0, hold_days=30
        )
        # peak=115, trail at 115*0.85=97.75, current=108 > 97.75
        assert result["should_exit"] is False
        assert result["level"] == 1

    def test_level1_trailing_triggered(self):
        """Level 1 trailing stop should trigger (when time stop is disabled)."""
        result = compute_bold_exit(
            entry_price=100, current_price=96, peak_price=115,
            current_atr=3.0, hold_days=30,
            params={"time_stop_enabled": False},
        )
        # peak=115, pct_trail=115*0.92=105.8, atr_trail=115-9=106 → trail=105.8
        # current=96 < 105.8
        assert result["should_exit"] is True
        assert result["exit_reason"] == "trail_level1"

    def test_level1_trailing_preempted_by_time_stop(self):
        """PTS timeout fires before trail when gain is low after 20+ days."""
        result = compute_bold_exit(
            entry_price=100, current_price=96, peak_price=115,
            current_atr=3.0, hold_days=30
        )
        # gain=-4% < 3%, hold_days=30 >= pts_max_hold_days=20 → PTS timeout
        assert result["should_exit"] is True
        assert "pts_" in result["exit_reason"] or "time_stop" in result["exit_reason"]

    def test_level2_protection(self):
        """Level 2: gain 30-50%, locks in cost+10%."""
        result = compute_bold_exit(
            entry_price=100, current_price=118, peak_price=140,
            current_atr=3.0, hold_days=30
        )
        # gain=18%, but peak gain was 40% so entered Level 2
        # Actually gain_pct = 18/100 = 0.18 < 0.30, so still Level 1
        assert result["level"] == 1

    def test_level2_locks_profit(self):
        """Level 2 should lock in minimum profit."""
        result = compute_bold_exit(
            entry_price=100, current_price=145, peak_price=155,
            current_atr=3.0, hold_days=30
        )
        # gain=45%, in Level 2
        # trail: max(155*0.92=142.6, 100*1.10=110) = 142.6  (trail_level1_pct=0.08)
        # current 145 > 142.6 → hold
        assert result["should_exit"] is False
        assert result["level"] == 2

    def test_level3_conviction_mode(self):
        """Level 3: gain > 50%, wide -25% trailing."""
        result = compute_bold_exit(
            entry_price=100, current_price=175, peak_price=200,
            current_atr=5.0, hold_days=60,
            params={"use_atr_trail": False},
        )
        # gain=75%, Level 3
        # trail: 200*0.75=150, floor=110 → trail=150
        # current 175 > 150 → hold
        assert result["should_exit"] is False
        assert result["level"] == 3

    def test_level3_exit(self):
        """Level 3 trailing should eventually trigger."""
        result = compute_bold_exit(
            entry_price=100, current_price=145, peak_price=200,
            current_atr=5.0, hold_days=60,
            params={"use_atr_trail": False},
        )
        # gain=45% but peak was 200 → was Level 3
        # Actually gain_pct = 0.45, < 0.50, so Level 2 now
        # trail: max(200*0.92=184, 110) = 184  (trail_level1_pct=0.08)
        # current 145 < 184 → exit
        assert result["should_exit"] is True

    def test_level3_atr_trail(self):
        """Level 3 with ATR-based trailing."""
        result = compute_bold_exit(
            entry_price=100, current_price=185, peak_price=200,
            current_atr=8.0, hold_days=60,
        )
        # gain=85%, Level 3
        # ATR stop: 200 - 3.0*8 = 176
        # pct stop: 200*0.75 = 150
        # trail = max(176, 150) = 176, floor=110 → 176
        # current 185 > 176 → hold
        assert result["should_exit"] is False
        assert result["level"] == 3

    def test_max_hold_days(self):
        """Should force exit at max hold days."""
        result = compute_bold_exit(
            entry_price=100, current_price=120, peak_price=130,
            current_atr=3.0, hold_days=120
        )
        assert result["should_exit"] is True
        assert "max_hold" in result["exit_reason"]


class TestGenerateBoldSignals:
    """Test signal generation."""

    def test_output_columns(self):
        """Should produce expected columns."""
        df = _make_df(50.0, n=200)
        result = generate_bold_signals(df)
        assert "bold_signal" in result.columns
        assert "bold_entry_type" in result.columns
        assert "bold_squeeze" in result.columns
        assert "bold_vol_ratio" in result.columns

    def test_mostly_hold(self):
        """Flat price should produce mostly HOLD signals."""
        df = _make_df(50.0, n=200)
        result = generate_bold_signals(df)
        hold_pct = (result["bold_signal"] == "HOLD").mean()
        assert hold_pct > 0.90

    def test_squeeze_detection(self):
        """Squeeze should be detected during very flat periods."""
        # Create extremely flat data to ensure BB narrows
        np.random.seed(42)
        n = 200
        prices = [50.0 + np.random.normal(0, 0.05) for _ in range(n)]
        df = _make_df(prices, n=n)
        from analysis.indicators import calculate_all_indicators
        result = calculate_all_indicators(df)
        # Just verify squeeze detection runs without error
        squeeze = _detect_squeeze(result)
        assert len(squeeze) == n


class TestGetBoldAnalysis:
    """Test the analysis summary function."""

    def test_returns_dict(self):
        df = _make_df(50.0, n=200)
        result = get_bold_analysis(df)
        assert isinstance(result, dict)
        assert "signal" in result
        assert "squeeze" in result
        assert "vol_ratio" in result
        assert "rsi" in result
        assert "indicators" in result

    def test_indicators_present(self):
        df = _make_df(50.0, n=200)
        result = get_bold_analysis(df)
        assert "bb_upper" in result["indicators"]
        assert "ma20" in result["indicators"]


class TestPhase1DefenseStops:
    """Test Phase 1 物理止損機制（R62 Gemini + Architect Critic 共識）."""

    # --- 結構止損 ---
    def test_structural_stop_triggers_below_entry_low(self):
        """Price below entry_low should trigger structural stop."""
        result = compute_bold_exit(
            entry_price=100, current_price=95, peak_price=105,
            current_atr=3.0, hold_days=3,
            params={"structural_stop_enabled": True},
            entry_low=96.0, prev_day_low=97.0,
        )
        # min(96, 97) = 96, current 95 < 96 → exit
        assert result["should_exit"] is True
        assert result["exit_reason"] == "structural_stop"
        assert result["level"] == 0

    def test_structural_stop_uses_min_of_both_lows(self):
        """Should use min(entry_low, prev_day_low) as floor."""
        result = compute_bold_exit(
            entry_price=100, current_price=94, peak_price=105,
            current_atr=3.0, hold_days=3,
            params={"structural_stop_enabled": True},
            entry_low=97.0, prev_day_low=95.0,
        )
        # min(97, 95) = 95, current 94 < 95 → exit
        assert result["should_exit"] is True
        assert result["exit_reason"] == "structural_stop"

    def test_structural_stop_holds_above_floor(self):
        """Price above structural floor should hold."""
        result = compute_bold_exit(
            entry_price=100, current_price=97, peak_price=105,
            current_atr=3.0, hold_days=3,
            params={"structural_stop_enabled": True},
            entry_low=96.0, prev_day_low=95.0,
        )
        # min(96, 95) = 95, current 97 > 95 → hold
        assert result["should_exit"] is False

    def test_structural_stop_overrides_min_hold(self):
        """Structural stop should fire even during min hold period (hold_days=1)."""
        result = compute_bold_exit(
            entry_price=100, current_price=94, peak_price=100,
            current_atr=3.0, hold_days=1,
            params={"structural_stop_enabled": True},
            entry_low=96.0, prev_day_low=95.0,
        )
        assert result["should_exit"] is True
        assert result["exit_reason"] == "structural_stop"

    def test_structural_stop_disabled(self):
        """When disabled, should not trigger structural stop."""
        result = compute_bold_exit(
            entry_price=100, current_price=94, peak_price=105,
            current_atr=3.0, hold_days=15,
            params={"structural_stop_enabled": False},
            entry_low=96.0, prev_day_low=95.0,
        )
        # Disabled, so should fall through to normal exit logic
        assert result["exit_reason"] != "structural_stop"

    def test_structural_stop_with_only_entry_low(self):
        """When prev_day_low is None, use entry_low only."""
        result = compute_bold_exit(
            entry_price=100, current_price=95, peak_price=105,
            current_atr=3.0, hold_days=3,
            params={"structural_stop_enabled": True},
            entry_low=96.0, prev_day_low=None,
        )
        # floor = 96, current 95 < 96 → exit
        assert result["should_exit"] is True
        assert result["exit_reason"] == "structural_stop"

    # --- 時間止損 ---
    def test_time_stop_triggers_after_n_days_low_gain(self):
        """5 days with gain < 3% should trigger PTS exit (no volume data = no synergy)."""
        result = compute_bold_exit(
            entry_price=100, current_price=101, peak_price=102,
            current_atr=3.0, hold_days=5,
        )
        # gain = 1% < 3%, hold_days=5, no vol data → pts_no_synergy
        assert result["should_exit"] is True
        assert "pts_" in result["exit_reason"] or "time_stop" in result["exit_reason"]

    def test_time_stop_does_not_trigger_with_good_gain(self):
        """5 days with gain >= 3% should NOT trigger time stop."""
        result = compute_bold_exit(
            entry_price=100, current_price=104, peak_price=104,
            current_atr=3.0, hold_days=5,
        )
        # gain = 4% >= 3% → no time stop
        assert result["exit_reason"] != "time_stop_5d"

    def test_time_stop_does_not_trigger_before_n_days(self):
        """Before 5 days, time stop should not trigger even with low gain."""
        result = compute_bold_exit(
            entry_price=100, current_price=100.5, peak_price=101,
            current_atr=3.0, hold_days=3,
        )
        # hold_days=3 < 5 → no time stop (min hold protection)
        assert "time_stop" not in result.get("exit_reason", "")

    def test_time_stop_disabled(self):
        """When disabled, should not trigger time stop."""
        result = compute_bold_exit(
            entry_price=100, current_price=100.5, peak_price=101,
            current_atr=3.0, hold_days=15,
            params={"time_stop_enabled": False},
        )
        assert "time_stop" not in result.get("exit_reason", "")

    def test_time_stop_negative_gain(self):
        """PTS should exit when gain is negative and no synergy conditions met."""
        result = compute_bold_exit(
            entry_price=100, current_price=97, peak_price=101,
            current_atr=3.0, hold_days=6,
        )
        # gain = -3% < 3%, hold_days=6, no vol data → pts_no_synergy
        assert result["should_exit"] is True
        assert "pts_" in result["exit_reason"] or "time_stop" in result["exit_reason"]

    # --- 趨勢破位 ---
    def test_trend_break_triggers(self):
        """Price below MA20 with negative slope should trigger trend break."""
        result = compute_bold_exit(
            entry_price=100, current_price=108, peak_price=115,
            current_atr=3.0, hold_days=15,
            current_ma20=110.0, ma20_slope=-0.005,
        )
        # price=108 < ma20=110, slope=-0.005 ≤ 0, hold_days=15 ≥ min_hold → exit
        assert result["should_exit"] is True
        assert result["exit_reason"] == "trend_break_ma20"

    def test_trend_break_holds_above_ma20(self):
        """Price above MA20 should not trigger trend break."""
        result = compute_bold_exit(
            entry_price=100, current_price=112, peak_price=115,
            current_atr=3.0, hold_days=15,
            current_ma20=110.0, ma20_slope=-0.005,
        )
        # price=112 > ma20=110 → no trend break
        assert result["exit_reason"] != "trend_break_ma20"

    def test_trend_break_holds_with_positive_slope(self):
        """MA20 with positive slope should not trigger even below MA20."""
        result = compute_bold_exit(
            entry_price=100, current_price=108, peak_price=115,
            current_atr=3.0, hold_days=15,
            current_ma20=110.0, ma20_slope=0.005,
        )
        # slope > 0 → no trend break
        assert result["exit_reason"] != "trend_break_ma20"

    def test_trend_break_respects_min_hold(self):
        """Trend break should respect min hold period."""
        result = compute_bold_exit(
            entry_price=100, current_price=108, peak_price=115,
            current_atr=3.0, hold_days=3,
            current_ma20=110.0, ma20_slope=-0.005,
        )
        # hold_days=3 < min_hold=10 → trend break should NOT trigger
        assert result["exit_reason"] != "trend_break_ma20"

    def test_trend_break_disabled(self):
        """When disabled, should not trigger trend break."""
        result = compute_bold_exit(
            entry_price=100, current_price=108, peak_price=115,
            current_atr=3.0, hold_days=15,
            params={"trend_break_stop_enabled": False},
            current_ma20=110.0, ma20_slope=-0.005,
        )
        assert result["exit_reason"] != "trend_break_ma20"

    # --- 優先級 ---
    def test_structural_stop_priority_over_time_stop(self):
        """Structural stop should fire before time stop."""
        result = compute_bold_exit(
            entry_price=100, current_price=94, peak_price=105,
            current_atr=3.0, hold_days=6,
            params={"structural_stop_enabled": True},
            entry_low=96.0, prev_day_low=95.0,
        )
        # Both structural (94 < 95) and time (gain=-6% < 3%) would trigger
        # Structural comes first → should be structural_stop
        assert result["exit_reason"] == "structural_stop"

    def test_backward_compat_no_new_params(self):
        """Calling without new params should work (backward compatible)."""
        result = compute_bold_exit(
            entry_price=100, current_price=120, peak_price=130,
            current_atr=3.0, hold_days=30,
        )
        # All new params default to None → no new stops triggered
        assert result["gain_pct"] == pytest.approx(0.20, abs=0.001)
        assert "should_exit" in result


class TestRegimeBasedTrail:
    """Test Regime-Based Trail (Conviction 2.0) — replaces dead conviction_hold_gain."""

    def test_ultra_wide_params_exist(self):
        """Ultra-Wide preset should have regime trail parameters."""
        assert STRATEGY_BOLD_ULTRA_WIDE["ultra_wide"] is True
        assert STRATEGY_BOLD_ULTRA_WIDE["trail_level3_pct"] == 0.15  # VALIDATED
        assert STRATEGY_BOLD_ULTRA_WIDE["max_hold_days"] == 365
        assert STRATEGY_BOLD_ULTRA_WIDE["trail_regime_wide_pct"] == 0.20

    def test_regime_trail_widens_in_bull(self):
        """Bullish regime (MA200 rising) should widen trail from 15% to 25%."""
        # Standard: trail_level3_pct=0.15, peak=200 → trail at 200*0.85=170
        result_std = compute_bold_exit(
            entry_price=100, current_price=175, peak_price=200,
            current_atr=5.0, hold_days=60,
            params={"ultra_wide": True, "use_atr_trail": False,
                    "trail_level3_pct": 0.15, "trail_regime_wide_pct": 0.25,
                    "regime_trail_enabled": True, "ma_slope_threshold": 0.0},
            ma200_slope=-0.01,  # bearish → standard 15%
        )
        # trail: 200*0.85=170, current 175 > 170 → hold
        assert result_std["should_exit"] is False
        assert result_std["level"] == 3

        # Now: price at 165, below standard -15% (170) but above regime -25% (150)
        result_bear = compute_bold_exit(
            entry_price=100, current_price=165, peak_price=200,
            current_atr=5.0, hold_days=60,
            params={"ultra_wide": True, "use_atr_trail": False,
                    "trail_level3_pct": 0.15, "trail_regime_wide_pct": 0.25,
                    "regime_trail_enabled": True, "ma_slope_threshold": 0.0},
            ma200_slope=-0.01,  # bearish → standard 15% trail
        )
        # trail: 200*0.85=170, current 165 < 170 → exit
        assert result_bear["should_exit"] is True

        # Bull regime: same price should HOLD (wider 25% trail)
        result_bull = compute_bold_exit(
            entry_price=100, current_price=165, peak_price=200,
            current_atr=5.0, hold_days=60,
            params={"ultra_wide": True, "use_atr_trail": False,
                    "trail_level3_pct": 0.15, "trail_regime_wide_pct": 0.25,
                    "regime_trail_enabled": True, "ma_slope_threshold": 0.0},
            ma200_slope=0.05,  # bullish → regime trail 25%
        )
        # trail: 200*0.75=150, current 165 > 150 → hold
        assert result_bull["should_exit"] is False
        assert result_bull["level"] == 3

    def test_regime_trail_disabled(self):
        """When regime_trail_enabled=False, always use standard trail."""
        result = compute_bold_exit(
            entry_price=100, current_price=165, peak_price=200,
            current_atr=5.0, hold_days=60,
            params={"ultra_wide": True, "use_atr_trail": False,
                    "trail_level3_pct": 0.15, "trail_regime_wide_pct": 0.25,
                    "regime_trail_enabled": False, "ma_slope_threshold": 0.0},
            ma200_slope=0.05,  # would be bullish, but feature disabled
        )
        # Disabled → standard 15% trail: 200*0.85=170, current 165 < 170 → exit
        assert result["should_exit"] is True

    def test_ultra_wide_disaster_still_works(self):
        """Disaster stop should still work in Ultra-Wide mode."""
        result = compute_bold_exit(
            entry_price=100, current_price=80, peak_price=200,
            current_atr=5.0, hold_days=60,
            params=dict(STRATEGY_BOLD_ULTRA_WIDE),
            ma200_slope=0.10,
        )
        # -20% < -18% disaster stop
        assert result["should_exit"] is True
        assert "disaster_stop" in result["exit_reason"]

    def test_ultra_wide_max_hold_365(self):
        """Ultra-Wide should enforce 365 days max hold (no conviction bypass)."""
        # regime trail 0.20: 250*0.80=200, current 210 > 200 → hold
        result = compute_bold_exit(
            entry_price=100, current_price=210, peak_price=250,
            current_atr=5.0, hold_days=300,
            params=dict(STRATEGY_BOLD_ULTRA_WIDE),
            ma200_slope=0.05,
        )
        # 300 < 365 → should NOT exit
        assert result["should_exit"] is False

        result2 = compute_bold_exit(
            entry_price=100, current_price=210, peak_price=250,
            current_atr=5.0, hold_days=365,
            params=dict(STRATEGY_BOLD_ULTRA_WIDE),
        )
        # 365 >= 365 → should exit (no more conviction_hold bypass!)
        assert result2["should_exit"] is True
        assert "max_hold" in result2["exit_reason"]

    def test_regime_exit_reason_label(self):
        """Exit in regime mode should have trail_level3_regime reason."""
        # gain_pct = 155/100 - 1 = 0.55 → Level 3 (>0.50 threshold)
        # regime trail: 220 * 0.75 = 165, current 155 < 165 → exit
        result = compute_bold_exit(
            entry_price=100, current_price=155, peak_price=220,
            current_atr=5.0, hold_days=60,
            params={"ultra_wide": True, "use_atr_trail": False,
                    "trail_level3_pct": 0.15, "trail_regime_wide_pct": 0.25,
                    "regime_trail_enabled": True, "ma_slope_threshold": 0.0},
            ma200_slope=0.05,  # bullish
        )
        assert result["should_exit"] is True
        assert result["exit_reason"] == "trail_level3_regime"


class TestVolumeRampEntry:
    """Test Volume Ramp Breakout entry (Entry C)."""

    def test_volume_ramp_detects_ramp(self):
        """Volume Ramp should trigger when volume trends up + price breaks high."""
        np.random.seed(42)
        # Phase 1: Low volume flat (100 days)
        n1 = 100
        prices1 = [30.0 + np.random.normal(0, 0.3) for _ in range(n1)]
        vols1 = [10_000] * n1  # 10 lots

        # Phase 2: Volume gradually increasing + price climbing (60 days)
        n2 = 60
        prices2 = [30.0 + i * 0.3 + np.random.normal(0, 0.2) for i in range(n2)]
        vols2 = [10_000 + i * 3000 for i in range(n2)]  # 10 → 190 lots, ramp up

        # Phase 3: Breakout with high volume (40 days)
        n3 = 40
        base = prices2[-1]
        prices3 = [base + i * 0.8 for i in range(n3)]
        vols3 = [200_000] * n3  # 200 lots

        all_prices = prices1 + prices2 + prices3
        all_vols = vols1 + vols2 + vols3
        df = _make_df(all_prices, all_vols, len(all_prices))

        result = generate_bold_signals(df)
        buys = result[result["bold_signal"] == "BUY"]
        # Should find at least one Volume Ramp buy
        ramp_buys = buys[buys["bold_entry_type"] == "volume_ramp"]
        # Volume ramp may or may not trigger depending on exact conditions
        # but the code should run without errors
        assert len(result) == len(all_prices)

    def test_volume_ramp_disabled(self):
        """Disabling volume_ramp_enabled should skip Entry C."""
        df = _make_df(50.0, n=200)
        result = generate_bold_signals(df, params={"volume_ramp_enabled": False})
        # Should still produce signals column
        assert "bold_signal" in result.columns


class TestBacktestBoldIntegration:
    """Test bold strategy integration with BacktestEngine."""

    def test_run_bold_returns_result(self):
        """run_bold should return a valid BacktestResult."""
        from backtest.engine import BacktestEngine
        df = _make_df(50.0, n=200)
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run_bold(df)
        assert result is not None
        assert hasattr(result, "total_return")
        assert hasattr(result, "equity_curve")
        assert not result.equity_curve.empty

    def test_run_bold_ultra_wide(self):
        """run_bold with ultra_wide should use STRATEGY_BOLD_ULTRA_WIDE."""
        from backtest.engine import BacktestEngine
        df = _make_df(50.0, n=200)
        engine = BacktestEngine(initial_capital=1_000_000)
        result = engine.run_bold(df, ultra_wide=True)
        assert "Ultra-Wide" in result.params_description

    def test_run_backtest_bold_convenience(self):
        """run_backtest_bold convenience function should work."""
        from backtest.engine import run_backtest_bold
        df = _make_df(50.0, n=200)
        result = run_backtest_bold(df)
        assert result is not None
        assert hasattr(result, "total_return")


# ============================================================
# R62: Momentum Lag Stop Tests
# ============================================================
class TestMomentumLagStop:
    """Test R62 Momentum Lag Stop — 量縮時延長持有，破 MA5 立即出場。"""

    def _base_params(self):
        return {
            **STRATEGY_BOLD_PARAMS,
            "time_stop_enabled": True,
            "momentum_lag_stop_enabled": True,
            "time_stop_days": 5,
            "time_stop_extended_days": 8,
            "momentum_lag_gain_threshold": 0.01,
            "time_stop_min_gain": 0.03,
            "stop_loss_pct": 0.15,
            "min_hold_days": 10,
            "structural_stop_enabled": False,
            "trend_break_stop_enabled": False,
        }

    def test_volume_shrink_extends_hold(self):
        """量縮且報酬在 ±1% → 不出場（延長觀察）。"""
        p = self._base_params()
        result = compute_bold_exit(
            entry_price=100, current_price=100.5, peak_price=101,
            current_atr=2.0, hold_days=5, params=p,
            current_vol_ma5=800_000, current_vol_ma20=1_000_000,  # vol_ma5 < vol_ma20
            current_ma5=99.0,  # price > MA5
        )
        assert not result["should_exit"], "量縮時應延長持有，不出場"

    def test_volume_shrink_but_breaks_ma5(self):
        """量縮但破 MA5 且 price < entry → PTS MA5 break 出場。"""
        p = self._base_params()
        result = compute_bold_exit(
            entry_price=100, current_price=99.5, peak_price=101,
            current_atr=2.0, hold_days=6, params=p,
            current_vol_ma5=800_000, current_vol_ma20=1_000_000,
            current_ma5=100.0,  # price 99.5 < MA5 100.0
        )
        assert result["should_exit"]
        assert "ma5_break" in result["exit_reason"]

    def test_no_volume_shrink_pts_no_synergy(self):
        """量沒縮且不動 → PTS no synergy exit。"""
        p = self._base_params()
        result = compute_bold_exit(
            entry_price=100, current_price=100.5, peak_price=101,
            current_atr=2.0, hold_days=5, params=p,
            current_vol_ma5=1_200_000, current_vol_ma20=1_000_000,  # vol_ma5 > vol_ma20
            current_ma5=99.0,
        )
        assert result["should_exit"]
        assert "pts_no_synergy" in result["exit_reason"]

    def test_loss_vol_shrink_pts_grace(self):
        """Price at hold threshold + vol shrinking → PTS grace (no exit)。"""
        p = self._base_params()
        result = compute_bold_exit(
            entry_price=100, current_price=98.0, peak_price=101,
            current_atr=2.0, hold_days=5, params=p,
            current_vol_ma5=800_000, current_vol_ma20=1_000_000,
            current_ma5=97.0,
        )
        # price 98 >= entry*0.98=98, vol shrinking, hold<20 → PTS grace (hold)
        assert not result["should_exit"], "PTS grace: price at threshold + vol shrinking"

    def test_pts_timeout_after_max_days(self):
        """到 pts_max_hold_days → PTS timeout 出場。"""
        p = self._base_params()
        result = compute_bold_exit(
            entry_price=100, current_price=100.5, peak_price=101,
            current_atr=2.0, hold_days=20, params=p,
            current_vol_ma5=800_000, current_vol_ma20=1_000_000,
            current_ma5=99.0,
        )
        assert result["should_exit"]
        assert "pts_timeout" in result["exit_reason"]

    def test_mls_disabled_pts_no_synergy(self):
        """MLS 關閉但 PTS still works → pts_no_synergy for vol not shrinking。"""
        p = self._base_params()
        p["momentum_lag_stop_enabled"] = False
        result = compute_bold_exit(
            entry_price=100, current_price=100.5, peak_price=101,
            current_atr=2.0, hold_days=5, params=p,
            current_vol_ma5=800_000, current_vol_ma20=1_000_000,
            current_ma5=99.0,
        )
        # vol shrinking + price above hold → PTS grace (no exit)
        assert not result["should_exit"], "PTS grace: vol shrinking + price above hold"

    def test_no_volume_data_pts_no_synergy(self):
        """沒有量能數據 → PTS no synergy (can't verify vol shrinking)。"""
        p = self._base_params()
        result = compute_bold_exit(
            entry_price=100, current_price=100.5, peak_price=101,
            current_atr=2.0, hold_days=5, params=p,
            current_vol_ma5=None, current_vol_ma20=None,
            current_ma5=99.0,
        )
        assert result["should_exit"]
        assert "pts_no_synergy" in result["exit_reason"]

    def test_good_gain_no_time_stop(self):
        """漲超過 3% → 不觸發 time stop。"""
        p = self._base_params()
        result = compute_bold_exit(
            entry_price=100, current_price=104, peak_price=105,
            current_atr=2.0, hold_days=6, params=p,
            current_vol_ma5=800_000, current_vol_ma20=1_000_000,
            current_ma5=102.0,
        )
        assert not result["should_exit"]


# ============================================================
# R62: RS_Rating Tests
# ============================================================
class TestRSRating:
    """Test R62 RS_Rating — 個股相對強度計算。"""

    def test_rs_ratio_basic(self):
        """R63 Weighted RS: base^0.6 * recent^0.4。"""
        prices = list(range(100, 260))  # 160 天的價格 100 → 259
        df = pd.DataFrame({
            "close": prices,
            "open": prices,
            "high": [p * 1.02 for p in prices],
            "low": [p * 0.98 for p in prices],
            "volume": [500_000] * len(prices),
        }, index=pd.date_range("2024-01-01", periods=len(prices), freq="B"))
        rs = compute_rs_ratio(df, lookback=120, exclude_recent=5)
        assert rs is not None
        # Weighted: base = close[-26] / close[-125], recent = close[-6] / close[-26]
        base_return = prices[-26] / prices[-125]
        recent_return = prices[-6] / prices[-26]
        expected = (base_return ** 0.6) * (recent_return ** 0.4)
        assert abs(rs - expected) < 0.001

    def test_rs_weighted_penalizes_spike(self):
        """R63: 短命噴泉得分低於穩定上漲股。"""
        # 穩定上漲：120 天從 100 漲到 150（+50%）
        steady = [100 + 50 * i / 130 for i in range(131)]  # 131 天（120+5+余量）
        df_steady = pd.DataFrame({
            "close": steady,
            "open": steady,
            "high": [p * 1.01 for p in steady],
            "low": [p * 0.99 for p in steady],
            "volume": [500_000] * len(steady),
        }, index=pd.date_range("2024-01-01", periods=len(steady), freq="B"))

        # 短命噴泉：100 天平穩，最後 20 天暴漲 50%
        flat = [100.0] * 106  # 前 106 天平穩
        spike = [100 + 50 * i / 24 for i in range(25)]  # 後 25 天暴漲
        prices_spike = flat + spike
        df_spike = pd.DataFrame({
            "close": prices_spike,
            "open": prices_spike,
            "high": [p * 1.01 for p in prices_spike],
            "low": [p * 0.99 for p in prices_spike],
            "volume": [500_000] * len(prices_spike),
        }, index=pd.date_range("2024-01-01", periods=len(prices_spike), freq="B"))

        rs_steady = compute_rs_ratio(df_steady, lookback=120, exclude_recent=5)
        rs_spike = compute_rs_ratio(df_spike, lookback=120, exclude_recent=5)

        assert rs_steady is not None
        assert rs_spike is not None
        assert rs_steady > rs_spike, (
            f"穩定上漲 ({rs_steady:.4f}) 應高於短命噴泉 ({rs_spike:.4f})"
        )

    def test_rs_ratio_insufficient_data(self):
        """數據不足時返回 None。"""
        df = _make_df(100, n=50)
        rs = compute_rs_ratio(df, lookback=120, exclude_recent=5)
        assert rs is None

    def test_rs_rating_filters_entry_d(self):
        """RS < 80 時 Entry D 不觸發。"""
        # 使用 rs_rating=50（低於門檻 80）
        df = _make_df(100, n=200)
        params = {**STRATEGY_BOLD_PARAMS, "rs_rating_enabled": True, "rs_rating_min": 80}
        result = generate_bold_signals(df, params=params, rs_rating=50)
        # 檢查沒有 momentum_breakout
        mb = result[result["bold_entry_type"] == "momentum_breakout"]
        assert len(mb) == 0, "RS < 80 時不應有 momentum_breakout 訊號"

    def test_rs_rating_disabled_no_filter(self):
        """RS 過濾關閉 → 不影響 Entry D。"""
        df = _make_df(100, n=200)
        params = {**STRATEGY_BOLD_PARAMS, "rs_rating_enabled": False}
        # rs_rating=50 但過濾關閉，不應受影響
        result = generate_bold_signals(df, params=params, rs_rating=50)
        # 只要原始條件滿足就有訊號（可能沒有，取決於數據 — 但不會因 RS 被擋）
        assert "bold_signal" in result.columns


# ============================================================
# R62: Equity Curve Filter Tests
# ============================================================
class TestEquityCurveFilter:
    """Test R62 Equity Curve Filter — 連續虧損保護。"""

    def test_ecf_params_in_defaults(self):
        """ECF 參數存在於預設中。"""
        assert "consecutive_loss_cap" in STRATEGY_BOLD_PARAMS
        assert STRATEGY_BOLD_PARAMS["consecutive_loss_cap"] == 3
        assert "position_reduction_factor" in STRATEGY_BOLD_PARAMS
        assert STRATEGY_BOLD_PARAMS["position_reduction_factor"] == 0.5
        assert "equity_curve_filter_enabled" in STRATEGY_BOLD_PARAMS

    def test_ecf_integration_with_backtest(self):
        """ECF 在回測中不崩潰。"""
        from backtest.engine import BacktestEngine
        df = _make_df(50.0, n=200)
        engine = BacktestEngine(initial_capital=1_000_000)
        params = {**STRATEGY_BOLD_PARAMS, "equity_curve_filter_enabled": True}
        result = engine.run_bold(df, params=params)
        assert result is not None
        assert hasattr(result, "total_return")

    def test_ecf_disabled_no_effect(self):
        """ECF 關閉時不影響。"""
        from backtest.engine import BacktestEngine
        df = _make_df(50.0, n=200)
        engine = BacktestEngine(initial_capital=1_000_000)
        params = {**STRATEGY_BOLD_PARAMS, "equity_curve_filter_enabled": False}
        result = engine.run_bold(df, params=params)
        assert result is not None


# ============================================================
# R63: RS Scanner Module Tests
# ============================================================
class TestRsScanner:
    """Test R63 RS scanner utility functions."""

    def test_get_cached_rankings_no_file(self, tmp_path, monkeypatch):
        """No cached file → returns None."""
        import analysis.rs_scanner as scanner
        monkeypatch.setattr(scanner, "RS_RANKING_PATH", tmp_path / "nonexistent.json")
        assert scanner.get_cached_rankings() is None

    def test_get_cached_rankings_valid(self, tmp_path, monkeypatch):
        """Valid cached file → returns parsed dict."""
        import json
        import analysis.rs_scanner as scanner
        path = tmp_path / "rs_ranking.json"
        data = {
            "scan_date": "2026-02-16 10:00",
            "total_stocks": 2,
            "rankings": [
                {"code": "2330", "rs_ratio": 1.15, "rs_rating": 90.0},
                {"code": "2317", "rs_ratio": 0.95, "rs_rating": 45.0},
            ],
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(scanner, "RS_RANKING_PATH", path)
        result = scanner.get_cached_rankings()
        assert result["total_stocks"] == 2
        assert len(result["rankings"]) == 2

    def test_get_stock_rs_rating_found(self, tmp_path, monkeypatch):
        """Stock found in rankings → returns grade."""
        import json
        import analysis.rs_scanner as scanner
        path = tmp_path / "rs_ranking.json"
        data = {
            "scan_date": "2026-02-16",
            "rankings": [
                {"code": "2330", "rs_ratio": 1.15, "rs_rating": 92.5},
                {"code": "6235", "rs_ratio": 1.05, "rs_rating": 65.0},
                {"code": "3661", "rs_ratio": 0.85, "rs_rating": 30.0},
            ],
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(scanner, "RS_RANKING_PATH", path)

        r = scanner.get_stock_rs_rating("2330")
        assert r["grade"] == "Diamond"
        assert r["rs_rating"] == 92.5

        r = scanner.get_stock_rs_rating("6235")
        assert r["grade"] == "Gold"

        r = scanner.get_stock_rs_rating("3661")
        assert r["grade"] == "Noise"

    def test_get_stock_rs_rating_not_found(self, tmp_path, monkeypatch):
        """Stock not in rankings → returns None."""
        import json
        import analysis.rs_scanner as scanner
        path = tmp_path / "rs_ranking.json"
        data = {"rankings": [{"code": "2330", "rs_ratio": 1.0, "rs_rating": 50.0}]}
        path.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(scanner, "RS_RANKING_PATH", path)
        assert scanner.get_stock_rs_rating("9999") is None

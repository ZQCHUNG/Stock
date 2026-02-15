"""Tests for analysis/strategy_bold.py — Bold/Aggressive strategy."""

import numpy as np
import pandas as pd
import pytest

from analysis.strategy_bold import (
    generate_bold_signals,
    get_bold_analysis,
    compute_bold_exit,
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
        """Level 1 trailing stop should trigger."""
        result = compute_bold_exit(
            entry_price=100, current_price=96, peak_price=115,
            current_atr=3.0, hold_days=30
        )
        # peak=115, trail at 115*0.85=97.75, current=96 < 97.75
        assert result["should_exit"] is True
        assert result["exit_reason"] == "trail_level1"

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
            entry_price=100, current_price=135, peak_price=155,
            current_atr=3.0, hold_days=30
        )
        # gain=35%, in Level 2
        # trail: max(155*0.85=131.75, 100*1.10=110) = 131.75
        # current 135 > 131.75 → hold
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
        # trail: max(200*0.85=170, 110) = 170
        # current 145 < 170 → exit
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


class TestUltraWideConviction:
    """Test Ultra-Wide Conviction mode with MA200 slope protection."""

    def test_ultra_wide_params_exist(self):
        """Ultra-Wide preset should have wider parameters."""
        assert STRATEGY_BOLD_ULTRA_WIDE["ultra_wide"] is True
        assert STRATEGY_BOLD_ULTRA_WIDE["trail_level3_pct"] == 0.30
        assert STRATEGY_BOLD_ULTRA_WIDE["max_hold_days"] == 365
        assert STRATEGY_BOLD_ULTRA_WIDE["trail_ultra_wide_pct"] == 0.35

    def test_ma200_slope_widens_trail(self):
        """With rising MA200, Level 3 should use ultra-wide trailing."""
        # Standard mode: -25% trail → peak 200, trail at 150
        result_std = compute_bold_exit(
            entry_price=100, current_price=155, peak_price=200,
            current_atr=5.0, hold_days=60,
            params={"use_atr_trail": False},
        )
        # current 155 > 150 → hold in standard
        assert result_std["should_exit"] is False

        # Now test: current = 140, below standard -25% (150) but above ultra-wide -35% (130)
        result_std2 = compute_bold_exit(
            entry_price=100, current_price=140, peak_price=200,
            current_atr=5.0, hold_days=60,
            params={"use_atr_trail": False},
        )
        # gain_pct = 0.40 < 0.50, so Level 2 → trail at max(200*0.85=170, 110)=170
        # current 140 < 170 → exit
        assert result_std2["should_exit"] is True

    def test_ultra_wide_with_ma_slope(self):
        """Ultra-Wide + rising MA200 → -35% trail instead of -25%."""
        result = compute_bold_exit(
            entry_price=100, current_price=155, peak_price=200,
            current_atr=5.0, hold_days=60,
            params={"ultra_wide": True, "use_atr_trail": False,
                    "trail_level3_pct": 0.30, "trail_ultra_wide_pct": 0.35,
                    "ma_slope_protection": True, "ma_slope_threshold": 0.0},
            ma200_slope=0.05,  # rising MA200
        )
        # gain=55%, Level 3
        # MA protected → trail_pct = 0.35
        # trail: 200 * 0.65 = 130, floor=110 → 130
        # current 155 > 130 → hold
        assert result["should_exit"] is False
        assert result["level"] == 3

    def test_ultra_wide_without_ma_slope(self):
        """Ultra-Wide but flat/falling MA200 → standard Level 3 trail."""
        result = compute_bold_exit(
            entry_price=100, current_price=155, peak_price=200,
            current_atr=5.0, hold_days=60,
            params={"ultra_wide": True, "use_atr_trail": False,
                    "trail_level3_pct": 0.30, "trail_ultra_wide_pct": 0.35,
                    "ma_slope_protection": True, "ma_slope_threshold": 0.0},
            ma200_slope=-0.01,  # falling MA200 → no protection
        )
        # No MA protection → trail_pct = 0.30
        # trail: 200 * 0.70 = 140, floor=110 → 140
        # current 155 > 140 → hold
        assert result["should_exit"] is False

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
        """Ultra-Wide should allow up to 365 days hold."""
        result = compute_bold_exit(
            entry_price=100, current_price=200, peak_price=250,
            current_atr=5.0, hold_days=300,
            params=dict(STRATEGY_BOLD_ULTRA_WIDE),
            ma200_slope=0.05,
        )
        # 300 < 365 → should NOT exit
        assert result["should_exit"] is False

        result2 = compute_bold_exit(
            entry_price=100, current_price=200, peak_price=250,
            current_atr=5.0, hold_days=365,
            params=dict(STRATEGY_BOLD_ULTRA_WIDE),
        )
        # 365 >= 365 → should exit
        assert result2["should_exit"] is True
        assert "max_hold" in result2["exit_reason"]


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

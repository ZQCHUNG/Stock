"""Tests for R86 stop_loss.py — ATR-Based Stop Calculator."""

import numpy as np
import pandas as pd
import pytest

from analysis.stop_loss import (
    calculate_stop_levels,
    compute_trailing_stop,
    get_stop_context,
    _find_recent_swing_low,
    _calculate_structural_stop,
    _calculate_atr_stop,
    _calculate_percentage_stop,
    _estimate_gap_risk,
    ATR_MULT_SQUEEZE,
    ATR_MULT_OVERSOLD,
    ATR_MULT_VOL_RAMP,
    ATR_MULT_MOMENTUM,
    HARD_STOP_FLOOR,
    VCP_OVERRIDE_SCORE,
    VCP_CANDIDATE_SCORE,
    TRAIL_BREAKEVEN_R,
    TRAIL_ACTIVATE_R,
    TRAIL_TIGHTEN_R,
)


# ─── Helpers ──────────────────────────────────────────────────

def _make_ohlcv(n=60, base_price=100.0, atr_pct=0.02):
    """Create synthetic OHLCV DataFrame."""
    dates = pd.bdate_range("2024-01-01", periods=n)
    np.random.seed(42)
    closes = base_price + np.cumsum(np.random.randn(n) * base_price * 0.01)
    closes = np.maximum(closes, base_price * 0.5)
    highs = closes * (1 + np.random.uniform(0, atr_pct, n))
    lows = closes * (1 - np.random.uniform(0, atr_pct, n))
    opens = (closes + np.roll(closes, 1)) / 2
    opens[0] = base_price
    volumes = np.random.randint(1000, 10000, n).astype(float)

    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }, index=dates)

    # Add ATR
    from analysis.indicators import calculate_atr
    df = calculate_atr(df, period=14, method="sma", _inplace=True)
    # calculate_atr also adds atr_pct; we only need 'atr' column here

    return df


def _make_swing_low_data(n=30, base=100.0, swing_low_price=95.0, swing_pos=-10):
    """Create data with a clear swing low at a specific position."""
    df = _make_ohlcv(n, base)
    idx = len(df) + swing_pos
    if 0 <= idx < len(df):
        df.iloc[idx, df.columns.get_loc("low")] = swing_low_price
        df.iloc[idx, df.columns.get_loc("close")] = swing_low_price + 0.5
    return df


# ─── Test Constants ───────────────────────────────────────────

class TestConstants:
    def test_atr_multipliers_converged(self):
        """Momentum was reduced from 2.5 to 2.0 per Gemini mandate."""
        assert ATR_MULT_SQUEEZE == 1.5
        assert ATR_MULT_OVERSOLD == 2.0
        assert ATR_MULT_VOL_RAMP == 2.0
        assert ATR_MULT_MOMENTUM == 2.0  # [CONVERGED: GEMINI_R86_TIGHTER]

    def test_hard_stop_floor(self):
        assert HARD_STOP_FLOOR == 0.07

    def test_trailing_phases(self):
        assert TRAIL_BREAKEVEN_R == 1.0
        assert TRAIL_ACTIVATE_R == 1.5
        assert TRAIL_TIGHTEN_R == 2.0

    def test_vcp_thresholds(self):
        assert VCP_OVERRIDE_SCORE == 70
        assert VCP_CANDIDATE_SCORE == 50


# ─── Test Swing Low Detection ─────────────────────────────────

class TestSwingLow:
    def test_finds_swing_low(self):
        df = _make_swing_low_data(30, 100.0, 90.0, -10)
        sl = _find_recent_swing_low(df, lookback=20, window=3)
        assert sl is not None
        assert sl <= 95.0  # should find something near the injected low

    def test_returns_none_for_short_data(self):
        df = _make_ohlcv(3)
        result = _find_recent_swing_low(df, lookback=20)
        assert result is None

    def test_fallback_to_minimum(self):
        df = _make_ohlcv(25)
        # Even without a perfect swing, should return min of last N bars
        result = _find_recent_swing_low(df, lookback=20, window=5)
        assert result is not None
        assert result > 0


# ─── Test ATR Stop ────────────────────────────────────────────

class TestATRStop:
    def test_squeeze_stop(self):
        atr = 2.0
        entry = 100.0
        stop = _calculate_atr_stop(entry, atr, "squeeze_breakout")
        assert stop == entry - 1.5 * atr  # 97.0

    def test_oversold_stop(self):
        stop = _calculate_atr_stop(100.0, 2.0, "oversold_bounce")
        assert stop == 96.0

    def test_momentum_stop_converged(self):
        """Momentum is 2.0x (not 2.5x) per Gemini convergence."""
        stop = _calculate_atr_stop(100.0, 2.0, "momentum_breakout")
        assert stop == 96.0  # 100 - 2.0*2 = 96

    def test_unknown_entry_uses_default(self):
        stop = _calculate_atr_stop(100.0, 2.0, "unknown_type")
        assert stop == 96.0  # default 2.0x


# ─── Test Percentage Stop ─────────────────────────────────────

class TestPercentageStop:
    def test_seven_percent_floor(self):
        stop = _calculate_percentage_stop(100.0)
        assert stop == 93.0

    def test_high_price(self):
        stop = _calculate_percentage_stop(1000.0)
        assert stop == pytest.approx(930.0)


# ─── Test Structural Stop with VCP ────────────────────────────

class TestStructuralStop:
    def test_vcp_override_score_70(self):
        """VCP score ≥70: mandatory pivot override."""
        df = _make_ohlcv(30)
        vcp = {"has_vcp": True, "vcp_score": 75, "pivot_price": 98.0}
        stop = _calculate_structural_stop(df, 100.0, vcp)
        # pivot - 1 tick: 98 - 0.1 = 97.9 (price < 100 → tick = 0.1)
        assert stop == pytest.approx(97.9, abs=0.01)

    def test_vcp_candidate_score_50(self):
        """VCP score 50-69: uses max(swing_low, pivot)."""
        df = _make_swing_low_data(30, 100.0, 95.0, -10)
        vcp = {"has_vcp": True, "vcp_score": 55, "pivot_price": 97.0}
        stop = _calculate_structural_stop(df, 100.0, vcp)
        # Should be max(swing_low ≈ 95, pivot - tick ≈ 96.9)
        assert stop >= 95.0  # At least the swing low

    def test_no_vcp(self):
        df = _make_swing_low_data(30, 100.0, 90.0, -10)
        stop = _calculate_structural_stop(df, 100.0, None)
        assert stop > 0

    def test_vcp_below_threshold(self):
        """VCP score <50: no pivot influence."""
        df = _make_swing_low_data(30, 100.0, 90.0, -10)
        vcp = {"has_vcp": True, "vcp_score": 30, "pivot_price": 98.0}
        stop_with_vcp = _calculate_structural_stop(df, 100.0, vcp)
        stop_without = _calculate_structural_stop(df, 100.0, None)
        assert stop_with_vcp == stop_without


# ─── Test Gap Risk ────────────────────────────────────────────

class TestGapRisk:
    def test_no_gaps_returns_zero(self):
        """If all opens == prev close, gap risk is 0."""
        df = _make_ohlcv(60)
        # Make opens match prev close
        df["open"] = df["close"].shift(1).bfill()
        risk = _estimate_gap_risk(df)
        assert risk == 0.0

    def test_with_gap_downs(self):
        df = _make_ohlcv(100)
        # Inject some gap-downs
        for i in [20, 40, 60, 80]:
            df.iloc[i, df.columns.get_loc("open")] = df.iloc[i - 1, df.columns.get_loc("close")] * 0.95
        risk = _estimate_gap_risk(df)
        assert risk > 0.01  # Should detect significant gaps

    def test_short_data(self):
        df = _make_ohlcv(5)
        risk = _estimate_gap_risk(df)
        # May return 0 with few data points
        assert risk >= 0.0


# ─── Test Calculate Stop Levels (Integration) ─────────────────

class TestCalculateStopLevels:
    def test_basic_calculation(self):
        df = _make_ohlcv(60, 100.0)
        levels = calculate_stop_levels(df, 100.0, "squeeze_breakout")
        assert levels.initial_stop > 0
        assert levels.initial_stop < 100.0
        assert levels.risk_pct > 0
        assert levels.r_value > 0
        assert levels.entry_price == 100.0
        assert levels.entry_type == "squeeze_breakout"

    def test_atr_multiplier_stored(self):
        df = _make_ohlcv(60)
        levels = calculate_stop_levels(df, 100.0, "squeeze_breakout")
        assert levels.atr_multiplier == 1.5

    def test_trailing_targets(self):
        df = _make_ohlcv(60, 100.0)
        levels = calculate_stop_levels(df, 100.0, "squeeze_breakout")
        r = levels.r_value
        assert levels.trail_breakeven_price == pytest.approx(100.0 + 1.0 * r, abs=0.01)
        assert levels.trail_activate_price == pytest.approx(100.0 + 1.5 * r, abs=0.01)
        assert levels.trail_tighten_price == pytest.approx(100.0 + 2.0 * r, abs=0.01)

    def test_gap_warning_flag(self):
        df = _make_ohlcv(100, 100.0)
        # Inject massive gap-downs
        for i in range(10, 100, 10):
            df.iloc[i, df.columns.get_loc("open")] = df.iloc[i - 1, df.columns.get_loc("close")] * 0.85
        levels = calculate_stop_levels(df, 100.0, "squeeze_breakout")
        # With 15% gaps, gap risk should exceed most stop distances
        assert levels.gap_risk_pct > 0

    def test_vcp_override(self):
        df = _make_ohlcv(60, 100.0, atr_pct=0.01)
        vcp = {"has_vcp": True, "vcp_score": 80, "pivot_price": 99.0}
        levels = calculate_stop_levels(df, 100.0, "squeeze_breakout", vcp)
        assert levels.vcp_pivot_stop is not None
        # With tight ATR and high VCP score, pivot should potentially override
        if levels.vcp_override:
            assert levels.stop_method == "vcp_pivot"

    def test_to_dict(self):
        df = _make_ohlcv(60)
        levels = calculate_stop_levels(df, 100.0, "squeeze_breakout")
        d = levels.to_dict()
        assert "initial_stop" in d
        assert "targets" in d
        assert "target_1r" in d["targets"]
        assert "target_2r" in d["targets"]
        assert "target_3r" in d["targets"]

    def test_zero_entry_price(self):
        df = _make_ohlcv(60)
        levels = calculate_stop_levels(df, 0.0)
        assert levels.initial_stop == 0.0

    def test_short_data(self):
        df = _make_ohlcv(3)
        levels = calculate_stop_levels(df, 100.0)
        assert levels.initial_stop == 0.0

    def test_no_atr_column(self):
        """Should compute ATR from raw data if column missing."""
        df = _make_ohlcv(60)
        df = df.drop(columns=["atr"])
        levels = calculate_stop_levels(df, 100.0, "squeeze_breakout")
        assert levels.current_atr > 0
        assert levels.initial_stop > 0


# ─── Test Trailing Stop ───────────────────────────────────────

class TestTrailingStop:
    def test_phase_0_initial(self):
        result = compute_trailing_stop(
            entry_price=100.0, current_price=101.0, highest_price=101.0,
            initial_stop=95.0, current_atr=2.0, r_value=5.0
        )
        assert result["phase"] == 0
        assert result["current_stop"] == 95.0

    def test_phase_1_breakeven(self):
        # +1R = 105, current at 106
        result = compute_trailing_stop(
            entry_price=100.0, current_price=106.0, highest_price=106.0,
            initial_stop=95.0, current_atr=2.0, r_value=5.0
        )
        assert result["phase"] == 1
        assert result["current_stop"] == 100.0  # breakeven

    def test_phase_2_atr_trail(self):
        # +1.5R = 107.5
        result = compute_trailing_stop(
            entry_price=100.0, current_price=108.0, highest_price=108.0,
            initial_stop=95.0, current_atr=2.0, r_value=5.0
        )
        assert result["phase"] == 2
        # highest(108) - 2.0*ATR(2.0) = 104.0
        assert result["current_stop"] == 104.0

    def test_phase_3_tighten(self):
        # +2R = 110
        result = compute_trailing_stop(
            entry_price=100.0, current_price=112.0, highest_price=112.0,
            initial_stop=95.0, current_atr=2.0, r_value=5.0
        )
        assert result["phase"] == 3
        # highest(112) - 1.5*ATR(2.0) = 109.0
        assert result["current_stop"] == 109.0

    def test_trail_never_below_entry(self):
        """Trailing stop floor is always entry price once activated."""
        result = compute_trailing_stop(
            entry_price=100.0, current_price=110.0, highest_price=110.0,
            initial_stop=95.0, current_atr=20.0, r_value=5.0  # huge ATR
        )
        # 110 - 2.0*20 = 70, but floor is 100 (entry)
        assert result["current_stop"] >= 100.0

    def test_zero_r_value(self):
        result = compute_trailing_stop(
            entry_price=100.0, current_price=105.0, highest_price=105.0,
            initial_stop=100.0, current_atr=2.0, r_value=0.0
        )
        assert result["phase"] == 0


# ─── Test get_stop_context (API entry point) ──────────────────

class TestGetStopContext:
    def test_returns_dict(self):
        df = _make_ohlcv(60)
        result = get_stop_context(df, 100.0, "squeeze_breakout")
        assert isinstance(result, dict)
        assert "initial_stop" in result
        assert "targets" in result

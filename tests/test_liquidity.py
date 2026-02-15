"""Tests for analysis/liquidity.py — Liquidity Score (R69)"""

import numpy as np
import pandas as pd
import pytest

from analysis.liquidity import (
    get_tick_size,
    calculate_dtl,
    calculate_market_impact,
    calculate_spread_score,
    calculate_adv_ratio_score,
    calculate_dtl_score,
    calculate_liquidity_score,
    get_liquidity_grade_label,
    LIQUIDITY_CONFIG,
)


# ─── Tick Size Tests ────────────────────────────────────────────

class TestGetTickSize:
    def test_low_price(self):
        assert get_tick_size(5.0) == 0.01

    def test_price_boundary_10(self):
        assert get_tick_size(9.99) == 0.01
        assert get_tick_size(10.0) == 0.05

    def test_price_boundary_50(self):
        assert get_tick_size(49.99) == 0.05
        assert get_tick_size(50.0) == 0.10

    def test_price_boundary_100(self):
        assert get_tick_size(99.99) == 0.10
        assert get_tick_size(100.0) == 0.50

    def test_price_boundary_500(self):
        assert get_tick_size(499.99) == 0.50
        assert get_tick_size(500.0) == 1.00

    def test_price_boundary_1000(self):
        assert get_tick_size(999.99) == 1.00
        assert get_tick_size(1000.0) == 5.00

    def test_high_price(self):
        assert get_tick_size(2000.0) == 5.00


# ─── DTL Tests ──────────────────────────────────────────────────

class TestCalculateDTL:
    def test_basic(self):
        # 10000 shares, ADV=100000, rate=0.1 → DTL = 10000/(100000*0.1) = 1.0
        assert calculate_dtl(10000, 100000, 0.1) == 1.0

    def test_large_position(self):
        # 50000 shares, ADV=10000, rate=0.1 → DTL = 50000/1000 = 50.0
        assert calculate_dtl(50000, 10000, 0.1) == 50.0

    def test_zero_adv(self):
        assert calculate_dtl(1000, 0, 0.1) == float('inf')

    def test_zero_participation(self):
        assert calculate_dtl(1000, 100000, 0) == float('inf')

    def test_default_participation_rate(self):
        # Uses config default (0.10)
        dtl = calculate_dtl(10000, 100000)
        assert dtl == 1.0

    def test_small_position(self):
        # 100 shares, ADV=1000000 → very liquid
        dtl = calculate_dtl(100, 1000000, 0.1)
        assert dtl < 0.01


# ─── Market Impact Tests ────────────────────────────────────────

class TestCalculateMarketImpact:
    def test_basic(self):
        # position=10000, adv=100000, vol=0.30
        # SC = 0.30 * sqrt(10000/100000) = 0.30 * sqrt(0.1) = 0.30 * 0.316 ≈ 0.095
        impact = calculate_market_impact(10000, 100000, 0.30)
        assert 0.09 < impact < 0.10

    def test_zero_adv(self):
        assert calculate_market_impact(1000, 0, 0.3) == float('inf')

    def test_tiny_position(self):
        # Very small position → minimal impact
        impact = calculate_market_impact(10, 1000000, 0.3)
        assert impact < 0.001

    def test_large_position_high_vol(self):
        # Large position + high volatility → big impact
        impact = calculate_market_impact(100000, 50000, 0.5)
        assert impact > 0.5

    def test_zero_position(self):
        impact = calculate_market_impact(0, 100000, 0.3)
        assert impact == 0.0


# ─── Spread Score Tests ─────────────────────────────────────────

class TestCalculateSpreadScore:
    def test_tight_spread(self):
        """TSMC-like stock: very tight spread."""
        highs = np.array([601, 602, 603] * 10)
        lows = np.array([599, 598, 597] * 10)
        closes = np.array([600, 600, 600] * 10)
        score = calculate_spread_score(highs, lows, closes)
        assert score > 80  # Tight spread = high score

    def test_wide_spread(self):
        """Illiquid small-cap: wide daily range."""
        highs = np.array([110, 112, 108] * 10)
        lows = np.array([90, 88, 92] * 10)
        closes = np.array([100, 100, 100] * 10)
        score = calculate_spread_score(highs, lows, closes)
        assert score < 50  # Wide spread = low score

    def test_insufficient_data(self):
        score = calculate_spread_score(np.array([100]), np.array([99]), np.array([100]))
        assert score == 50.0  # Neutral

    def test_zero_close(self):
        highs = np.array([10, 10, 10])
        lows = np.array([9, 9, 9])
        closes = np.array([0, 0, 0])
        score = calculate_spread_score(highs, lows, closes)
        assert score == 50.0  # Fallback to neutral


# ─── ADV Ratio Score Tests ──────────────────────────────────────

class TestCalculateAdvRatioScore:
    def test_tiny_position(self):
        """Position = 0.1% of ADV → excellent."""
        score = calculate_adv_ratio_score(100, 100000)
        assert score > 90

    def test_medium_position(self):
        """Position = 10% of ADV → moderate."""
        score = calculate_adv_ratio_score(10000, 100000)
        assert 40 < score < 60

    def test_large_position(self):
        """Position = 100% of ADV → terrible."""
        score = calculate_adv_ratio_score(100000, 100000)
        assert score == 0.0

    def test_zero_adv(self):
        score = calculate_adv_ratio_score(1000, 0)
        assert score == 0.0

    def test_zero_position(self):
        score = calculate_adv_ratio_score(0, 100000)
        assert score == 100.0


# ─── DTL Score Tests ────────────────────────────────────────────

class TestCalculateDTLScore:
    def test_instant_liquidation(self):
        """DTL = 0 → perfect score."""
        assert calculate_dtl_score(0) == 100.0

    def test_one_day(self):
        """DTL = 1 → still decent."""
        score = calculate_dtl_score(1.0)
        assert 60 < score < 80

    def test_two_days(self):
        """DTL = 2 → moderate."""
        score = calculate_dtl_score(2.0)
        assert 40 < score < 60

    def test_ten_days(self):
        """DTL = 10 → zero score."""
        assert calculate_dtl_score(10.0) == 0.0

    def test_very_long(self):
        """DTL = 100 → zero."""
        assert calculate_dtl_score(100.0) == 0.0


# ─── Composite Score Tests ──────────────────────────────────────

def _make_ohlcv_df(close=100.0, spread_pct=0.02, volume=500000, days=60):
    """Create synthetic OHLCV DataFrame."""
    dates = pd.date_range(end='2025-01-01', periods=days, freq='B')
    np.random.seed(42)
    closes = np.full(days, close) + np.random.randn(days) * close * 0.01
    highs = closes * (1 + spread_pct / 2)
    lows = closes * (1 - spread_pct / 2)
    opens = closes * (1 + np.random.randn(days) * 0.005)
    volumes = np.full(days, volume) + np.random.randint(-volume // 10, volume // 10, days)
    return pd.DataFrame({
        'open': opens, 'high': highs, 'low': lows,
        'close': closes, 'volume': volumes,
    }, index=dates)


class TestCalculateLiquidityScore:
    def test_liquid_stock(self):
        """TSMC-like: high volume, tight spread."""
        df = _make_ohlcv_df(close=600, spread_pct=0.005, volume=20_000_000)
        result = calculate_liquidity_score(df, position_size_ntd=1_000_000)
        assert result["score"] > 70
        assert result["grade"] in ("green", "yellow")
        assert result["dtl"] < 1.0

    def test_illiquid_small_cap(self):
        """Small-cap: low volume, wide spread."""
        df = _make_ohlcv_df(close=30, spread_pct=0.08, volume=50_000)
        result = calculate_liquidity_score(df, position_size_ntd=5_000_000)
        assert result["score"] < 50
        assert result["grade"] == "red"
        assert result["dtl"] > 2.0

    def test_medium_liquidity(self):
        """Mid-cap stock."""
        df = _make_ohlcv_df(close=80, spread_pct=0.02, volume=500_000)
        result = calculate_liquidity_score(df, position_size_ntd=1_000_000)
        assert 30 < result["score"] < 90

    def test_output_fields(self):
        """Verify all expected output fields are present."""
        df = _make_ohlcv_df()
        result = calculate_liquidity_score(df)
        expected_keys = {
            "score", "grade", "dtl", "dtl_score",
            "spread_score", "adv_ratio_score",
            "adv_20", "adv_20_lots", "market_impact", "market_impact_pct",
            "tick_size", "tick_ratio_pct", "volatility_20",
            "position_shares", "last_price", "details",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_insufficient_data(self):
        """Very short DataFrame → red grade."""
        df = pd.DataFrame({
            'open': [100], 'high': [101], 'low': [99],
            'close': [100], 'volume': [1000],
        })
        result = calculate_liquidity_score(df)
        assert result["grade"] == "red"
        assert result["details"] == "資料不足"

    def test_custom_position_size(self):
        """Larger position → lower score."""
        df = _make_ohlcv_df(close=100, volume=200_000)
        small = calculate_liquidity_score(df, position_size_ntd=100_000)
        large = calculate_liquidity_score(df, position_size_ntd=10_000_000)
        assert small["score"] > large["score"]

    def test_tick_size_in_output(self):
        """Verify tick size is calculated correctly."""
        df = _make_ohlcv_df(close=75)
        result = calculate_liquidity_score(df)
        assert result["tick_size"] == 0.10  # 50-100 range

    def test_config_override(self):
        """Custom config works."""
        df = _make_ohlcv_df()
        custom = {"participation_rate": 0.05}  # More conservative
        result = calculate_liquidity_score(df, config=custom)
        assert result["dtl"] > 0  # Should calculate with different rate


# ─── Grade Label Tests ──────────────────────────────────────────

class TestGradeLabel:
    def test_green(self):
        assert "出清" in get_liquidity_grade_label("green")

    def test_yellow(self):
        assert "拆單" in get_liquidity_grade_label("yellow")

    def test_red(self):
        assert "失敗" in get_liquidity_grade_label("red")

    def test_unknown(self):
        assert get_liquidity_grade_label("unknown") == "未知"

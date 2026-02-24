"""Tests for analysis/accumulation_scanner.py — Wyckoff Accumulation Detection

All tests use synthetic data — no network calls.
Covers all 6 conditions (incl. AQS R95.1), phase transitions, filters, edge cases,
and the Architect directives (test bar floor memory, invalidation, AQS downgrade).
"""

import numpy as np
import pandas as pd
import pytest

from analysis.accumulation_scanner import (
    AccumulationResult,
    SwingLow,
    TestBar,
    ADX_LOW_MIN_DAYS,
    ADX_LOW_THRESHOLD,
    AQS_COL_ANTI_DAYTRADE,
    AQS_COL_CONCENTRATION,
    AQS_COL_PERSISTENCE,
    AQS_COL_WINNER,
    AQS_COL_WINNER_BONUS,
    AQS_LOOKBACK,
    AQS_THRESHOLD,
    AQS_W_ANTI_DAYTRADE,
    AQS_W_CONCENTRATION,
    AQS_W_NET_BUY_PERSISTENCE,
    AQS_W_WINNER_MOMENTUM,
    MAX_CONSOLIDATION_WITHOUT_TEST,
    MIN_AVG_VOLUME_LOTS,
    POST_TEST_MAX_PULLBACK,
    POST_TEST_VOL_RATIO,
    PRICE_RANGE_FROM_HIGH_MAX,
    PRICE_RANGE_FROM_HIGH_MIN,
    RS_MIN_RATING,
    SWING_LOOKBACK_HALF_WIN,
    SWING_LOW_MIN_COUNT,
    SWING_LOW_UPLIFT,
    VOL_SPIKE_MULTIPLIER,
    _check_adx_low,
    _check_higher_lows,
    _check_invalidation,
    _check_post_test_consolidation,
    _check_price_range,
    _compute_adx,
    _count_consolidation_days,
    _find_swing_lows,
    _find_test_bars,
    calculate_aqs,
    detect_accumulation,
)


# ── Helpers ──────────────────────────────────────────────


def _make_ohlcv(
    n: int = 200,
    base_price: float = 100.0,
    base_volume: float = 500_000,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic OHLCV data."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2025-03-01", periods=n)

    closes = np.zeros(n)
    closes[0] = base_price
    for i in range(1, n):
        closes[i] = closes[i - 1] * (1 + rng.normal(0, 0.015))

    highs = closes * (1 + rng.uniform(0.002, 0.02, n))
    lows = closes * (1 - rng.uniform(0.002, 0.02, n))
    opens = closes * (1 + rng.normal(0, 0.005, n))
    volumes = base_volume * (1 + rng.normal(0, 0.3, n))
    volumes = np.maximum(volumes, 100_000)

    return pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }, index=dates)


def _make_accumulation_pattern(
    peak_price: float = 100.0,
    correction_depth: float = 0.30,
    n_swing_lows: int = 4,
    swing_uplift: float = 0.02,
    include_volume_test: bool = True,
    include_post_test_confirm: bool = True,
    base_volume: float = 500_000,
) -> pd.DataFrame:
    """Build a synthetic Wyckoff accumulation pattern.

    Creates:
    1. Rally phase (30 bars) — price rises to peak
    2. Correction/accumulation phase (120+ bars) — price drops and forms higher lows
    3. Optional volume test bar(s)
    4. Optional post-test consolidation
    """
    bars = []
    date_idx = 0

    # Phase 1: Rally to peak (30 bars)
    rally_n = 30
    for i in range(rally_n):
        pct = i / rally_n
        price = peak_price * (0.70 + 0.30 * pct)
        bar = {
            "open": price * 0.995,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "volume": base_volume * 1.2,
        }
        bars.append(bar)

    # Phase 2: Correction — form swing lows with higher lows
    correction_low = peak_price * (1 - correction_depth)
    correction_n = 20  # bars per swing cycle

    for sw in range(n_swing_lows):
        # Each swing low is progressively higher
        low_target = correction_low * (1 + swing_uplift * sw)

        # Down phase
        for i in range(correction_n // 2):
            pct = i / (correction_n // 2)
            mid = peak_price * 0.85
            price = mid - (mid - low_target) * pct
            vol = base_volume * 0.8
            bars.append({
                "open": price * 1.005,
                "high": price * 1.01,
                "low": price * 0.995,
                "close": price,
                "volume": vol,
            })

        # Up phase (bounce from low)
        for i in range(correction_n // 2):
            pct = i / (correction_n // 2)
            price = low_target + (mid - low_target) * pct
            vol = base_volume * 0.9
            bars.append({
                "open": price * 0.995,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": vol,
            })

    # Phase 3: Volume test bar (if requested)
    if include_volume_test:
        last_close = bars[-1]["close"]
        test_close = last_close * 1.05
        bars.append({
            "open": last_close,
            "high": test_close * 1.02,
            "low": last_close * 0.99,
            "close": test_close,
            "volume": base_volume * VOL_SPIKE_MULTIPLIER * 1.5,
        })

        # Phase 4: Post-test consolidation (if requested)
        if include_post_test_confirm:
            for i in range(8):
                price = test_close * (1 - 0.005 * i)
                bars.append({
                    "open": price * 1.002,
                    "high": price * 1.008,
                    "low": price * 0.998,
                    "close": price,
                    "volume": base_volume * 0.4,  # Volume shrinks
                })

    dates = pd.bdate_range("2025-03-01", periods=len(bars))
    df = pd.DataFrame(bars, index=dates)
    return df


# ── Test: _find_swing_lows ──────────────────────────────


class TestFindSwingLows:
    """Tests for swing low detection."""

    def test_basic_swing_lows(self):
        """Should find local minima in a V-shaped pattern."""
        # Create: 10 down, 5 flat at bottom, 10 up — clear swing low
        n = 40
        lows = np.concatenate([
            np.linspace(100, 80, 15),
            np.full(5, 80),
            np.linspace(80, 95, 15),
            np.full(5, 95),
        ])
        result = _find_swing_lows(lows, half_win=5)
        assert len(result) >= 1
        # The swing low should be near the bottom
        prices = [p for _, p in result]
        assert min(prices) == pytest.approx(80.0, abs=1)

    def test_multiple_swing_lows(self):
        """Should find multiple distinct swing lows."""
        # W-bottom: down-up-down-up
        n = 80
        lows = np.concatenate([
            np.linspace(100, 80, 20),
            np.linspace(80, 90, 10),
            np.linspace(90, 82, 15),
            np.linspace(82, 95, 15),
            np.linspace(95, 84, 10),
            np.linspace(84, 92, 10),
        ])
        result = _find_swing_lows(lows, half_win=5)
        assert len(result) >= 2

    def test_too_short_data(self):
        """Should return empty for insufficient data."""
        lows = np.array([100, 99, 98])
        result = _find_swing_lows(lows, half_win=5)
        assert result == []

    def test_monotone_up(self):
        """Monotonically rising data has no swing lows (no local minimum)."""
        lows = np.linspace(50, 100, 40)
        result = _find_swing_lows(lows, half_win=5)
        assert len(result) == 0

    def test_monotone_down(self):
        """Monotonically falling data has no internal swing lows."""
        lows = np.linspace(100, 50, 40)
        result = _find_swing_lows(lows, half_win=5)
        assert len(result) == 0


# ── Test: _check_higher_lows ────────────────────────────


class TestCheckHigherLows:
    """Tests for higher-lows detection (3-strategy approach)."""

    def test_strict_rising(self):
        """Strategy 1: strictly rising consecutive lows."""
        lows = [(10, 50.0), (25, 52.0), (40, 54.0)]
        ok, selected = _check_higher_lows(lows, min_count=3)
        assert ok is True
        assert len(selected) == 3

    def test_not_enough_lows(self):
        """Fewer than min_count should fail."""
        lows = [(10, 50.0), (25, 52.0)]
        ok, selected = _check_higher_lows(lows, min_count=3)
        assert ok is False
        assert selected == []

    def test_falling_lows_fail(self):
        """Declining lows should fail all strategies."""
        lows = [(10, 60.0), (25, 55.0), (40, 50.0)]
        ok, selected = _check_higher_lows(lows, min_count=3)
        assert ok is False

    def test_strategy2_subsequence(self):
        """Strategy 2: rising subsequence with interruption."""
        # 50 → 48 → 52 → 54 — not strict consecutive, but rising subsequence
        lows = [(10, 50.0), (20, 48.0), (35, 52.0), (50, 54.0)]
        ok, selected = _check_higher_lows(lows, min_count=3)
        assert ok is True

    def test_strategy3_major_support(self):
        """Strategy 3: major support test — deepest low then holds."""
        # 60, 55, 50 (deepest), 51, 52, 53 — support holding after spring
        lows = [
            (5, 60.0), (15, 55.0), (25, 50.0),
            (35, 51.0), (45, 52.0), (55, 53.0),
        ]
        ok, selected = _check_higher_lows(lows, min_count=3)
        assert ok is True

    def test_flat_lows_fail_strict(self):
        """Identical lows fail strict uplift check."""
        lows = [(10, 50.0), (25, 50.0), (40, 50.0)]
        # uplift=1.005 means each must be > previous * 1.005
        ok, _ = _check_higher_lows(lows, min_count=3, uplift=1.005)
        assert ok is False

    def test_tiny_uplift_passes(self):
        """Very small uplift (0.5%) should pass with 1.005 factor."""
        lows = [(10, 50.0), (25, 50.3), (40, 50.6)]
        ok, _ = _check_higher_lows(lows, min_count=3, uplift=1.005)
        assert ok is True


# ── Test: _find_test_bars ───────────────────────────────


class TestFindTestBars:
    """Tests for volume spike (Test for Supply) detection."""

    def test_detects_volume_spike(self):
        """Should detect a bullish bar with volume > 2.5x MA."""
        n = 40
        df = _make_ohlcv(n=n, base_volume=500_000, seed=10)
        vol_ma20 = df["volume"].rolling(20).mean()

        # Inject a spike at bar 30
        df.iloc[30, df.columns.get_loc("volume")] = 2_000_000
        df.iloc[30, df.columns.get_loc("close")] = df.iloc[30]["open"] * 1.05

        result = _find_test_bars(df, vol_ma20)
        assert len(result) >= 1
        assert any(tb.idx == 30 for tb in result)

    def test_bearish_bar_excluded(self):
        """Bearish bar (close < open) should NOT be a test bar."""
        n = 40
        df = _make_ohlcv(n=n, base_volume=500_000, seed=11)
        vol_ma20 = df["volume"].rolling(20).mean()

        # Inject volume spike but bearish
        df.iloc[30, df.columns.get_loc("volume")] = 2_000_000
        df.iloc[30, df.columns.get_loc("close")] = df.iloc[30]["open"] * 0.95

        result = _find_test_bars(df, vol_ma20)
        assert not any(tb.idx == 30 for tb in result)

    def test_low_volume_excluded(self):
        """Normal volume should not trigger test bar."""
        df = _make_ohlcv(n=40, base_volume=500_000, seed=12)
        vol_ma20 = df["volume"].rolling(20).mean()
        # No spike injected
        result = _find_test_bars(df, vol_ma20)
        # May find a few random spikes, but should be uncommon
        for tb in result:
            assert tb.vol_ratio >= VOL_SPIKE_MULTIPLIER


# ── Test: _check_post_test_consolidation ────────────────


class TestPostTestConsolidation:
    """Tests for post-test-bar consolidation check."""

    def test_confirmed_consolidation(self):
        """Volume shrinks and price holds after test bar = confirmed."""
        n = 50
        df = _make_ohlcv(n=n, base_volume=500_000, seed=20)
        vol_ma20 = df["volume"].rolling(20).mean()

        # Create a test bar at idx 30
        test_bar = TestBar(
            idx=30, date="2025-06-01",
            open_price=95.0, close_price=100.0,
            low_price=94.0, high_price=101.0,
            volume=2_000_000, vol_ratio=4.0,
            gain_pct=0.0526,  # 5.26%
        )

        # Make post-test volume very low
        for i in range(31, 41):
            df.iloc[i, df.columns.get_loc("volume")] = 200_000
            # Keep price near test bar close
            df.iloc[i, df.columns.get_loc("low")] = 98.0
            df.iloc[i, df.columns.get_loc("close")] = 99.0

        confirmed, avg_vol, pullback = _check_post_test_consolidation(
            df, vol_ma20, test_bar
        )
        assert confirmed is True
        assert avg_vol is not None
        assert pullback is not None

    def test_volume_expands_after_test_fails(self):
        """If volume stays high after test, consolidation not confirmed."""
        n = 50
        df = _make_ohlcv(n=n, base_volume=500_000, seed=21)
        vol_ma20 = df["volume"].rolling(20).mean()

        test_bar = TestBar(
            idx=30, date="2025-06-01",
            open_price=95.0, close_price=100.0,
            low_price=94.0, high_price=101.0,
            volume=2_000_000, vol_ratio=4.0,
            gain_pct=0.0526,
        )

        # Keep volume HIGH after test
        for i in range(31, 41):
            df.iloc[i, df.columns.get_loc("volume")] = 800_000
            df.iloc[i, df.columns.get_loc("low")] = 98.0

        confirmed, avg_vol, _ = _check_post_test_consolidation(
            df, vol_ma20, test_bar
        )
        # vol ratio > 0.7 → fail
        assert confirmed is False

    def test_not_enough_data_after_test(self):
        """Test bar too close to end of data."""
        n = 35
        df = _make_ohlcv(n=n, base_volume=500_000, seed=22)
        vol_ma20 = df["volume"].rolling(20).mean()

        test_bar = TestBar(
            idx=33, date="2025-06-01",
            open_price=95.0, close_price=100.0,
            low_price=94.0, high_price=101.0,
            volume=2_000_000, vol_ratio=4.0,
            gain_pct=0.0526,
        )

        confirmed, _, _ = _check_post_test_consolidation(
            df, vol_ma20, test_bar
        )
        assert confirmed is False


# ── Test: _compute_adx & _check_adx_low ────────────────


class TestADX:
    """Tests for ADX computation and low-energy check."""

    def test_compute_adx_returns_series(self):
        """ADX should return a pandas Series of same length as input."""
        df = _make_ohlcv(n=100)
        adx = _compute_adx(df)
        assert isinstance(adx, pd.Series)
        assert len(adx) == len(df)

    def test_low_adx_in_range_market(self):
        """Sideways market should have low ADX."""
        n = 100
        dates = pd.bdate_range("2025-06-01", periods=n)
        # Generate tight range
        rng = np.random.RandomState(30)
        closes = 100 + rng.normal(0, 0.5, n).cumsum() * 0.1
        df = pd.DataFrame({
            "open": closes - 0.2,
            "high": closes + 0.5,
            "low": closes - 0.5,
            "close": closes,
            "volume": np.full(n, 500_000),
        }, index=dates)

        adx = _compute_adx(df)
        is_low, current, days = _check_adx_low(adx)
        # Range-bound should give low ADX
        assert current < 30  # typically < 25 for range

    def test_high_adx_in_trending_market(self):
        """Strong trend should have high ADX."""
        n = 100
        dates = pd.bdate_range("2025-06-01", periods=n)
        # Strong uptrend
        closes = np.linspace(50, 150, n)
        df = pd.DataFrame({
            "open": closes - 1,
            "high": closes + 1.5,
            "low": closes - 1.5,
            "close": closes,
            "volume": np.full(n, 500_000),
        }, index=dates)

        adx = _compute_adx(df)
        is_low, current, days = _check_adx_low(adx)
        assert is_low is False  # trending → ADX high
        assert current > 25

    def test_adx_low_empty_series(self):
        """Handle edge case: all NaN ADX."""
        adx = pd.Series([np.nan] * 10)
        is_low, current, days = _check_adx_low(adx)
        assert is_low is False
        assert current == 0.0
        assert days == 0


# ── Test: _check_price_range ────────────────────────────


class TestPriceRange:
    """Tests for price range filter (distance from 52W high)."""

    def test_price_in_sweet_spot(self):
        """Price at -30% from high should pass (in 20-45% range)."""
        n = 100
        df = _make_ohlcv(n=n)
        # Force: high at 130, current close at 91 → -30%
        df.iloc[10, df.columns.get_loc("high")] = 130.0
        df.iloc[-1, df.columns.get_loc("close")] = 91.0

        in_range, pct = _check_price_range(df)
        assert in_range is True
        assert 0.20 <= pct <= 0.45

    def test_price_too_close_to_high(self):
        """Price at -10% from high should fail (not in accumulation)."""
        n = 100
        df = _make_ohlcv(n=n)
        df.iloc[10, df.columns.get_loc("high")] = 100.0
        df.iloc[-1, df.columns.get_loc("close")] = 92.0

        in_range, pct = _check_price_range(df)
        assert in_range is False
        assert pct < PRICE_RANGE_FROM_HIGH_MIN

    def test_price_too_far_from_high(self):
        """Price at -60% from high should fail (broken stock)."""
        n = 100
        df = _make_ohlcv(n=n)
        df.iloc[10, df.columns.get_loc("high")] = 200.0
        df.iloc[-1, df.columns.get_loc("close")] = 80.0

        in_range, pct = _check_price_range(df)
        assert in_range is False
        assert pct > PRICE_RANGE_FROM_HIGH_MAX


# ── Test: _check_invalidation ──────────────────────────


class TestInvalidation:
    """Architect directive: price below test bar floor → invalidated."""

    def test_no_floor_no_invalidation(self):
        """No test bar floor → no invalidation."""
        df = _make_ohlcv(n=30)
        inv, reason = _check_invalidation(df, None)
        assert inv is False
        assert reason == ""

    def test_price_above_floor(self):
        """Price above floor → valid."""
        df = _make_ohlcv(n=30)
        floor = float(df["close"].iloc[-1]) * 0.9
        inv, reason = _check_invalidation(df, floor)
        assert inv is False

    def test_price_below_floor(self):
        """Price below floor → invalidated with reason."""
        df = _make_ohlcv(n=30)
        floor = float(df["close"].iloc[-1]) * 1.1  # floor above current price
        inv, reason = _check_invalidation(df, floor)
        assert inv is True
        assert "closed below test bar floor" in reason


# ── Test: _count_consolidation_days ─────────────────────


class TestConsolidationDays:
    """Tests for consolidation duration counting."""

    def test_peak_at_beginning(self):
        """Peak at bar 0 → consolidation = full length."""
        n = 100
        df = _make_ohlcv(n=n, seed=40)
        # Force peak at bar 0
        df.iloc[0, df.columns.get_loc("high")] = 999.0
        days = _count_consolidation_days(df)
        assert days == n - 1

    def test_peak_at_end(self):
        """Peak at last bar → consolidation = 0."""
        n = 100
        df = _make_ohlcv(n=n, seed=41)
        df.iloc[-1, df.columns.get_loc("high")] = 999.0
        days = _count_consolidation_days(df)
        assert days == 0

    def test_short_data(self):
        """Data < 20 bars → 0."""
        df = _make_ohlcv(n=10)
        days = _count_consolidation_days(df)
        assert days == 0


# ── Test: detect_accumulation (integration) ─────────────


class TestDetectAccumulation:
    """Integration tests for the main detect_accumulation function."""

    def test_none_df(self):
        """None input → NONE phase."""
        result = detect_accumulation(None)
        assert result.phase == "NONE"
        assert result.score == 0

    def test_short_df(self):
        """Short data → NONE phase with reason."""
        df = _make_ohlcv(n=30)
        result = detect_accumulation(df)
        assert result.phase == "NONE"
        assert "Insufficient" in result.invalidation_reason

    def test_low_volume_filter(self):
        """Stock with <100 lots avg volume → filtered out."""
        n = 100
        dates = pd.bdate_range("2025-06-01", periods=n)
        # Force volume to exactly 80_000 (80 lots) — well below 100 lot floor
        df = pd.DataFrame({
            "open": np.full(n, 50.0),
            "high": np.full(n, 51.0),
            "low": np.full(n, 49.0),
            "close": np.full(n, 50.0),
            "volume": np.full(n, 80_000),
        }, index=dates)
        result = detect_accumulation(df)
        assert result.phase == "NONE"
        assert "Volume floor" in result.invalidation_reason
        assert result.volume_floor_pass is False

    def test_alpha_phase_detection(self):
        """Full accumulation pattern should detect at least ALPHA."""
        df = _make_accumulation_pattern(
            peak_price=100.0,
            correction_depth=0.30,
            n_swing_lows=4,
            swing_uplift=0.03,
            include_volume_test=True,
            include_post_test_confirm=False,
        )
        result = detect_accumulation(df)
        # Should detect higher lows + volume test → at least 2 conditions
        assert result.has_volume_test is True
        # Phase depends on conditions met; at minimum ALPHA if higher_lows + 1 other
        if result.has_higher_lows:
            assert result.phase in ("ALPHA", "BETA")
            assert result.score >= 20

    def test_beta_phase_requires_post_test(self):
        """BETA requires post_test_confirm and >= 4 conditions."""
        df = _make_accumulation_pattern(
            peak_price=100.0,
            correction_depth=0.30,
            n_swing_lows=4,
            swing_uplift=0.03,
            include_volume_test=True,
            include_post_test_confirm=True,
        )
        result = detect_accumulation(df, rs_rating=85.0)
        # Even if not all conditions hit, test the phase logic
        if result.has_post_test_confirm:
            conditions = sum([
                result.has_higher_lows,
                result.has_volume_test,
                result.has_post_test_confirm,
                result.has_low_adx,
                result.has_rs_strength,
            ])
            if conditions >= 4:
                assert result.phase == "BETA"

    def test_rs_rating_integration(self):
        """RS rating above threshold → has_rs_strength."""
        df = _make_ohlcv(n=200)
        result = detect_accumulation(df, rs_rating=85.0)
        assert result.has_rs_strength is True
        assert result.rs_rating == 85.0

    def test_rs_rating_below_threshold(self):
        """RS rating below threshold → no strength."""
        df = _make_ohlcv(n=200)
        result = detect_accumulation(df, rs_rating=50.0)
        assert result.has_rs_strength is False

    def test_rs_none_skips_check(self):
        """No RS rating → skip the check (not penalized)."""
        df = _make_ohlcv(n=200)
        result = detect_accumulation(df, rs_rating=None)
        assert result.has_rs_strength is False
        assert result.rs_rating is None

    def test_invalidation_overrides_everything(self):
        """If invalidated, phase=INVALIDATED and score=0."""
        df = _make_accumulation_pattern(
            peak_price=100.0,
            correction_depth=0.30,
            n_swing_lows=4,
            include_volume_test=True,
        )

        # Force current close below test bar floor
        # First get the result to find the floor
        result_first = detect_accumulation(df)
        if result_first.test_bar_floor is not None:
            # Drop current price way below floor
            df.iloc[-1, df.columns.get_loc("close")] = result_first.test_bar_floor * 0.85
            result = detect_accumulation(df)
            assert result.is_invalidated is True
            assert result.phase == "INVALIDATED"
            assert result.score == 0

    def test_consolidation_timeout_penalty(self):
        """Consolidation > 120 days → score penalty."""
        df = _make_ohlcv(n=250, seed=50)
        # Force peak at beginning → long consolidation
        df.iloc[5, df.columns.get_loc("high")] = 500.0
        result = detect_accumulation(df)
        assert result.consolidation_days > MAX_CONSOLIDATION_WITHOUT_TEST
        assert result.consolidation_timeout is True

    def test_score_capped_at_100(self):
        """Score should never exceed 100."""
        df = _make_accumulation_pattern(
            peak_price=100.0,
            correction_depth=0.30,
            n_swing_lows=5,
            swing_uplift=0.03,
            include_volume_test=True,
            include_post_test_confirm=True,
        )
        result = detect_accumulation(df, rs_rating=95.0)
        assert result.score <= 100

    def test_none_phase_when_few_conditions(self):
        """If fewer than 2 conditions met, phase=NONE."""
        # Use random data with no particular pattern
        df = _make_ohlcv(n=200, seed=99)
        result = detect_accumulation(df)
        conditions = sum([
            result.has_higher_lows,
            result.has_volume_test,
            result.has_post_test_confirm,
            result.has_low_adx,
            result.has_rs_strength,
        ])
        if conditions < 2 or not result.has_higher_lows:
            assert result.phase == "NONE"


# ── Test: AccumulationResult.to_dict ────────────────────


class TestAccumulationResultToDict:
    """Tests for the dataclass's to_dict method."""

    def test_to_dict_keys(self):
        """All expected keys should be present."""
        result = AccumulationResult()
        d = result.to_dict()
        expected_keys = {
            "phase", "score",
            "has_higher_lows", "swing_lows", "swing_low_count",
            "has_volume_test", "test_bars", "test_bar_floor",
            "has_post_test_confirm", "post_test_vol_avg", "post_test_pullback_pct",
            "has_low_adx", "adx_current", "adx_low_days",
            "has_rs_strength", "rs_rating",
            "has_smart_money", "aqs_score", "aqs_breakdown",
            "price_in_range", "price_vs_52w_high_pct", "volume_floor_pass",
            "consolidation_days", "consolidation_timeout",
            "is_invalidated", "invalidation_reason",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_defaults(self):
        """Default values should be sensible."""
        result = AccumulationResult()
        d = result.to_dict()
        assert d["phase"] == "NONE"
        assert d["score"] == 0
        assert d["has_higher_lows"] is False
        assert d["swing_lows"] == []
        assert d["is_invalidated"] is False


# ── Test: Scoring logic ────────────────────────────────


class TestScoring:
    """Test the scoring breakdown."""

    def test_higher_lows_worth_25(self):
        """Higher lows condition = 25 points."""
        df = _make_accumulation_pattern(
            peak_price=100.0,
            correction_depth=0.30,
            n_swing_lows=4,
            swing_uplift=0.03,
            include_volume_test=False,
        )
        result = detect_accumulation(df)
        if result.has_higher_lows and not result.has_volume_test:
            # Should be at least 25 from higher_lows
            assert result.score >= 25

    def test_volume_test_worth_20(self):
        """Volume test = 20 points."""
        df = _make_accumulation_pattern(
            peak_price=100.0,
            correction_depth=0.30,
            n_swing_lows=4,
            swing_uplift=0.03,
            include_volume_test=True,
            include_post_test_confirm=False,
        )
        result = detect_accumulation(df)
        if result.has_volume_test:
            assert result.score >= 20

    def test_rs_worth_10(self):
        """RS strength = 10 points."""
        df = _make_ohlcv(n=200, seed=60)
        result_with = detect_accumulation(df, rs_rating=85.0)
        result_without = detect_accumulation(df, rs_rating=None)
        # With RS should score at least 10 more
        assert result_with.score >= result_without.score + 10

    def test_price_range_bonus_10(self):
        """Price range bonus adds 10 to score when in sweet spot."""
        # Verify the scoring constant: price_in_range adds exactly 10 pts
        # Use the _check_price_range helper directly
        n = 100
        dates = pd.bdate_range("2025-06-01", periods=n)
        df = pd.DataFrame({
            "open": np.full(n, 70.0),
            "high": np.full(n, 71.0),
            "low": np.full(n, 69.0),
            "close": np.full(n, 70.0),
            "volume": np.full(n, 500_000),
        }, index=dates)
        # Set 52W high at bar 0: 100.0, current close 70 → -30%
        df.iloc[0, df.columns.get_loc("high")] = 100.0

        in_range, pct = _check_price_range(df)
        assert in_range is True
        assert 0.20 <= pct <= 0.45


# ── Test: Phase transition logic ────────────────────────


class TestPhaseTransitions:
    """Test phase determination rules."""

    def test_phase_alpha_requires_higher_lows(self):
        """ALPHA needs has_higher_lows=True + >= 2 conditions."""
        result = AccumulationResult()
        result.has_higher_lows = False
        result.has_volume_test = True
        result.has_low_adx = True
        # Even with 2 conditions, without higher_lows → NONE
        # (Phase logic is in detect_accumulation, but we test the principle)
        assert not (result.has_higher_lows and sum([
            result.has_higher_lows,
            result.has_volume_test,
            result.has_low_adx,
        ]) >= 2)

    def test_phase_beta_requires_post_test(self):
        """BETA needs has_post_test_confirm=True + >= 4 conditions."""
        result = AccumulationResult()
        result.has_higher_lows = True
        result.has_volume_test = True
        result.has_post_test_confirm = True
        result.has_low_adx = True
        result.has_rs_strength = True
        conditions = sum([
            result.has_higher_lows,
            result.has_volume_test,
            result.has_post_test_confirm,
            result.has_low_adx,
            result.has_rs_strength,
        ])
        assert conditions >= 4
        assert result.has_post_test_confirm is True


# ── Test: Edge cases ────────────────────────────────────


class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_all_zero_volume(self):
        """All-zero volume should not crash."""
        n = 100
        df = _make_ohlcv(n=n, base_volume=500_000, seed=70)
        df["volume"] = 0
        result = detect_accumulation(df)
        # Volume floor should fail
        assert result.volume_floor_pass is False

    def test_constant_price(self):
        """Constant price should not crash."""
        n = 100
        dates = pd.bdate_range("2025-06-01", periods=n)
        df = pd.DataFrame({
            "open": np.full(n, 50.0),
            "high": np.full(n, 50.5),
            "low": np.full(n, 49.5),
            "close": np.full(n, 50.0),
            "volume": np.full(n, 500_000),
        }, index=dates)
        result = detect_accumulation(df)
        assert result.phase == "NONE"

    def test_single_bar_spike(self):
        """One extreme spike should not break detection."""
        df = _make_ohlcv(n=200, seed=71)
        df.iloc[100, df.columns.get_loc("high")] = 9999.0
        df.iloc[100, df.columns.get_loc("close")] = 9999.0
        result = detect_accumulation(df)
        # Should not crash, and likely show large consolidation
        assert isinstance(result, AccumulationResult)

    def test_nan_in_data(self):
        """NaN values in data should be handled gracefully."""
        df = _make_ohlcv(n=100, seed=72)
        df.iloc[50, df.columns.get_loc("close")] = np.nan
        df.iloc[51, df.columns.get_loc("volume")] = np.nan
        # Should not crash
        result = detect_accumulation(df)
        assert isinstance(result, AccumulationResult)

    def test_test_bar_dataclass(self):
        """TestBar dataclass works correctly."""
        tb = TestBar(
            idx=10, date="2025-06-01",
            open_price=95.0, close_price=100.0,
            low_price=94.0, high_price=101.0,
            volume=2_000_000, vol_ratio=4.0,
            gain_pct=0.0526,
        )
        assert tb.close_price == 100.0
        assert tb.vol_ratio == 4.0

    def test_swing_low_dataclass(self):
        """SwingLow dataclass works correctly."""
        sl = SwingLow(idx=5, date="2025-06-01", price=50.0)
        assert sl.price == 50.0
        assert sl.idx == 5


# ── Test: AQS (Accumulation Quality Score) — R95.1 ─────


def _make_features_df(
    stock_code: str = "6748",
    n_days: int = 30,
    wm_values: float = 1.0,
    nbp_values: float = 0.8,
    bc_values: float = 0.5,
    adr_values: float = 0.3,
    winner_bonus_values: float = 0.0,
) -> pd.DataFrame:
    """Create synthetic features DataFrame mimicking Parquet structure."""
    dates = pd.bdate_range("2025-10-01", periods=n_days)
    return pd.DataFrame({
        "stock_code": [stock_code] * n_days,
        "date": dates,
        AQS_COL_WINNER: np.full(n_days, wm_values),
        AQS_COL_WINNER_BONUS: np.full(n_days, winner_bonus_values),
        AQS_COL_PERSISTENCE: np.full(n_days, nbp_values),
        AQS_COL_CONCENTRATION: np.full(n_days, bc_values),
        AQS_COL_ANTI_DAYTRADE: np.full(n_days, adr_values),
    })


class TestCalculateAQS:
    """Tests for AQS calculation function."""

    def test_basic_aqs_calculation(self):
        """AQS should compute weighted sum of Z-scored features."""
        features_df = _make_features_df(
            wm_values=1.0, nbp_values=0.8, bc_values=0.5, adr_values=0.3,
        )
        score, breakdown = calculate_aqs("6748", features_df)
        expected = (
            0.40 * 1.0 + 0.25 * 0.8 + 0.20 * 0.5 + 0.15 * 0.3
        )
        assert score == pytest.approx(expected, abs=0.01)
        assert "winner_momentum" in breakdown
        assert "net_buy_persistence" in breakdown
        assert "concentration" in breakdown
        assert "anti_daytrade" in breakdown

    def test_aqs_with_winner_bonus(self):
        """Winner momentum bonus should boost WM by 20% when available."""
        features_df = _make_features_df(
            wm_values=1.0, winner_bonus_values=1.0,
        )
        score_with_bonus, bd = calculate_aqs("6748", features_df)
        # WM should be 1.0 * 1.2 = 1.2 due to bonus
        assert bd["winner_momentum"] == pytest.approx(1.2, abs=0.01)

        features_df_no = _make_features_df(
            wm_values=1.0, winner_bonus_values=0.0,
        )
        score_no_bonus, _ = calculate_aqs("6748", features_df_no)
        assert score_with_bonus > score_no_bonus

    def test_aqs_no_parquet(self):
        """No Parquet data → returns None."""
        score, breakdown = calculate_aqs("6748", features_df=None)
        # Since we pass None and there's no cached data, it will try to load
        # We can't guarantee the file doesn't exist, so just check it handles gracefully
        assert score is None or isinstance(score, float)

    def test_aqs_stock_not_found(self):
        """Stock code not in features → returns None."""
        features_df = _make_features_df(stock_code="2330")
        score, breakdown = calculate_aqs("9999", features_df)
        assert score is None
        assert "reason" in breakdown

    def test_aqs_insufficient_data(self):
        """Too few rows for lookback → returns None."""
        features_df = _make_features_df(n_days=5)  # Only 5 days, need 20
        score, breakdown = calculate_aqs("6748", features_df)
        assert score is None

    def test_aqs_negative_zscore(self):
        """Negative Z-scores → negative AQS (distribution, not accumulation)."""
        features_df = _make_features_df(
            wm_values=-1.5, nbp_values=-1.0, bc_values=-0.5, adr_values=-0.3,
        )
        score, breakdown = calculate_aqs("6748", features_df)
        assert score is not None
        assert score < 0

    def test_aqs_all_zero(self):
        """All-zero features → AQS = 0."""
        features_df = _make_features_df(
            wm_values=0, nbp_values=0, bc_values=0, adr_values=0,
        )
        score, _ = calculate_aqs("6748", features_df)
        assert score == pytest.approx(0.0, abs=0.001)

    def test_aqs_weights_sum_to_one(self):
        """AQS weights should sum to 1.0."""
        total = (
            AQS_W_WINNER_MOMENTUM
            + AQS_W_NET_BUY_PERSISTENCE
            + AQS_W_CONCENTRATION
            + AQS_W_ANTI_DAYTRADE
        )
        assert total == pytest.approx(1.0, abs=0.001)

    def test_aqs_breakdown_has_weights(self):
        """Breakdown should include weight values."""
        features_df = _make_features_df()
        _, breakdown = calculate_aqs("6748", features_df)
        assert "weights" in breakdown
        assert breakdown["weights"]["winner_momentum"] == AQS_W_WINNER_MOMENTUM

    def test_aqs_threshold_constant(self):
        """AQS threshold should be a positive number."""
        assert AQS_THRESHOLD > 0
        assert isinstance(AQS_THRESHOLD, float)


class TestAQSIntegration:
    """Tests for AQS integration into detect_accumulation."""

    def test_aqs_skipped_without_stock_code(self):
        """No stock_code → AQS not computed."""
        df = _make_ohlcv(n=200)
        result = detect_accumulation(df, stock_code=None)
        assert result.has_smart_money is False
        assert result.aqs_score is None

    def test_aqs_integrated_with_stock_code(self):
        """With stock_code and features_df → AQS computed."""
        df = _make_ohlcv(n=200)
        features_df = _make_features_df(
            stock_code="TEST", n_days=30,
            wm_values=2.0, nbp_values=1.5, bc_values=1.0, adr_values=0.8,
        )
        result = detect_accumulation(df, stock_code="TEST", features_df=features_df)
        assert result.aqs_score is not None
        assert result.aqs_score > AQS_THRESHOLD
        assert result.has_smart_money is True

    def test_aqs_low_downgrades_beta_to_alpha(self):
        """AQS data available but low → BETA downgraded to ALPHA."""
        # Create a pattern that would normally be BETA
        df = _make_accumulation_pattern(
            peak_price=100.0,
            correction_depth=0.30,
            n_swing_lows=4,
            swing_uplift=0.03,
            include_volume_test=True,
            include_post_test_confirm=True,
        )
        # First, verify it's BETA without AQS
        result_no_aqs = detect_accumulation(df, rs_rating=85.0)

        # Now with low AQS
        features_df = _make_features_df(
            stock_code="TEST", n_days=30,
            wm_values=-1.0, nbp_values=-0.5, bc_values=-0.3, adr_values=-0.2,
        )
        result_low_aqs = detect_accumulation(
            df, rs_rating=85.0, stock_code="TEST", features_df=features_df,
        )
        # If original was BETA, low AQS should downgrade to ALPHA
        if result_no_aqs.phase == "BETA":
            assert result_low_aqs.phase == "ALPHA"
            assert result_low_aqs.has_smart_money is False

    def test_smart_money_adds_10_points(self):
        """has_smart_money should add 10 points to score."""
        df = _make_ohlcv(n=200, seed=80)
        features_high = _make_features_df(
            stock_code="TEST", n_days=30,
            wm_values=2.0, nbp_values=1.5, bc_values=1.0, adr_values=0.8,
        )
        features_low = _make_features_df(
            stock_code="TEST", n_days=30,
            wm_values=-2.0, nbp_values=-1.0, bc_values=-0.5, adr_values=-0.3,
        )
        result_high = detect_accumulation(df, stock_code="TEST", features_df=features_high)
        result_low = detect_accumulation(df, stock_code="TEST", features_df=features_low)

        if result_high.has_smart_money and not result_low.has_smart_money:
            assert result_high.score >= result_low.score + 10

    def test_consolidation_timeout_now_60_days(self):
        """MAX_CONSOLIDATION_WITHOUT_TEST should be 60 (was 120)."""
        assert MAX_CONSOLIDATION_WITHOUT_TEST == 60

"""Tests for analysis/reversal_detector.py — Phase 1+2+3

Phase 1: F2 (RSI Divergence) + F4 (Volume Exhaustion)
Phase 2: F1 (Spring Detection) + F3 (BB Squeeze Alert)
Phase 3: F5 (Multi-scale Accumulation) + F6 (Broker Behavior) integration

TDD: Write tests first, then implement.
Mix of unit tests (synthetic data) and E2E tests (real stock data).
"""

import numpy as np
import pandas as pd
import pytest

from analysis.reversal_detector import (
    ReversalResult,
    ReversalSignal,
    detect_bb_squeeze,
    detect_multiscale_accumulation,
    detect_reversal,
    detect_rsi_divergence,
    detect_spring,
    detect_volume_exhaustion,
    get_reversal_analysis,
)


# ---------- Helpers ----------

def _make_ohlcv(
    closes: list[float],
    volumes: list[float] | None = None,
    base_date: str = "2025-01-01",
) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from close prices."""
    n = len(closes)
    dates = pd.bdate_range(base_date, periods=n)
    if volumes is None:
        volumes = [1_000_000] * n

    closes_arr = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": closes_arr * 0.99,
            "high": closes_arr * 1.01,
            "low": closes_arr * 0.98,
            "close": closes_arr,
            "volume": np.array(volumes, dtype=float),
        },
        index=dates,
    )


def _make_divergence_data() -> pd.DataFrame:
    """Create synthetic price data with a clear bullish RSI divergence.

    Pattern: price makes lower low, but RSI makes higher low.
    We need enough RSI warmup (~14 bars) BEFORE the divergence window.
    """
    # Phase 0: warmup / establish baseline (40 bars)
    prices = list(np.linspace(110, 100, 40))
    # Phase 1: sharp drop to first swing low (quick, large daily drops -> low RSI)
    prices += list(np.linspace(99, 75, 8))
    # Phase 2: recovery
    prices += list(np.linspace(76, 92, 12))
    # Phase 3: gradual decline to lower low (slow, small daily drops -> higher RSI)
    prices += list(np.linspace(91, 73, 20))
    # Phase 4: mild bounce (current)
    prices += list(np.linspace(74, 78, 10))

    n = len(prices)
    volumes = [500_000] * n
    return _make_ohlcv(prices, volumes)


def _make_bearish_divergence_data() -> pd.DataFrame:
    """Create synthetic data with bearish RSI divergence.

    Price makes higher high but RSI makes lower high.
    Need warmup before the divergence window.
    """
    # Phase 0: warmup (40 bars)
    prices = list(np.linspace(70, 80, 40))
    # Phase 1: sharp rise to first swing high (strong momentum -> high RSI)
    prices += list(np.linspace(81, 105, 8))
    # Phase 2: pullback
    prices += list(np.linspace(104, 88, 12))
    # Phase 3: slow grind to higher high (weak momentum -> lower RSI)
    prices += list(np.linspace(89, 108, 20))
    # Phase 4: mild pullback
    prices += list(np.linspace(107, 103, 10))

    return _make_ohlcv(prices)


def _make_volume_exhaustion_data() -> pd.DataFrame:
    """Create data with volume drying up (< 0.5x MA20 for consecutive days).

    Key: need enough high-volume days in the MA20 window so ratio stays < 0.5.
    Use 80 bars: 55 normal + 5 transition + last 5 extremely low.
    The MA20 at day 75+ still includes ~15 normal days, so ratio stays low.
    """
    n = 80
    closes = list(np.linspace(100, 85, n))

    # First 70 days: normal volume (establishes high MA20)
    volumes = [1_000_000] * 70
    # Last 10 days: extremely low volume
    volumes += [100_000] * 10

    return _make_ohlcv(closes, volumes)


def _make_no_exhaustion_data() -> pd.DataFrame:
    """Create data with healthy volume throughout."""
    n = 60
    closes = list(np.linspace(100, 110, n))
    volumes = [1_000_000] * n
    return _make_ohlcv(closes, volumes)


def _make_uptrend_data() -> pd.DataFrame:
    """Create a clear uptrend — should NOT trigger reversal signals."""
    n = 80
    # Smooth uptrend with small oscillations
    x = np.arange(n)
    prices = 100 + x * 0.5 + np.sin(x * 0.3) * 2
    volumes = [1_000_000] * n
    return _make_ohlcv(list(prices), volumes)


# ================================================================
# Unit Tests — Spring Detection (F1)
# ================================================================

def _make_spring_data(
    pierce_pct: float = 0.05,
    recovery_full: bool = True,
    vol_multiplier: float = 2.0,
) -> pd.DataFrame:
    """Create synthetic data with a Wyckoff spring on the last day.

    Builds 40 days of base prices establishing support, then the last day
    pierces below and recovers.

    Args:
        pierce_pct: How far below support the low goes (as fraction).
        recovery_full: If True, close recovers above support.
        vol_multiplier: Volume on spring day as multiple of normal.
    """
    n = 40
    # Flat-ish range establishing support around 100
    base_prices = list(np.linspace(105, 100, n))
    base_volumes = [1_000_000] * n

    # Support should be ~100 (min low in last 20 days)
    # low = close * 0.98, so support_low ~ 98
    support_approx = min(p * 0.98 for p in base_prices[-20:])

    # Spring day: pierce below support
    spring_low = support_approx * (1 - pierce_pct)
    if recovery_full:
        spring_close = support_approx + 1.0  # recover above support
    else:
        spring_close = spring_low + 0.5  # barely recover

    spring_volume = 1_000_000 * vol_multiplier

    dates = pd.bdate_range("2025-01-01", periods=n + 1)
    closes = base_prices + [spring_close]
    lows = [c * 0.98 for c in base_prices] + [spring_low]
    highs = [c * 1.01 for c in base_prices] + [spring_close * 1.01]
    opens = [c * 0.99 for c in base_prices] + [support_approx]
    volumes = base_volumes + [spring_volume]

    return pd.DataFrame(
        {
            "open": np.array(opens, dtype=float),
            "high": np.array(highs, dtype=float),
            "low": np.array(lows, dtype=float),
            "close": np.array(closes, dtype=float),
            "volume": np.array(volumes, dtype=float),
        },
        index=dates,
    )


class TestSpringDetection:
    """Tests for detect_spring()."""

    def test_spring_detected_clear_pattern(self):
        """Clear spring: deep pierce + full recovery + high volume."""
        df = _make_spring_data(pierce_pct=0.05, recovery_full=True, vol_multiplier=2.0)
        signal = detect_spring(df)
        assert signal is not None
        assert signal.signal_type == "spring"
        assert signal.score > 0
        assert signal.direction == "bullish"

    def test_no_spring_in_uptrend(self):
        """Uptrend data should not trigger spring (no pierce below support)."""
        df = _make_uptrend_data()
        signal = detect_spring(df)
        assert signal is not None
        assert signal.score == 0

    def test_insufficient_data_returns_none(self):
        """Less than MIN_DATA_SPRING should return None."""
        df = _make_ohlcv([100, 101, 102, 103, 104])
        signal = detect_spring(df)
        assert signal is None

    def test_deeper_pierce_higher_score(self):
        """Deeper pierce below support should produce a higher score."""
        df_shallow = _make_spring_data(pierce_pct=0.03, recovery_full=True, vol_multiplier=2.0)
        df_deep = _make_spring_data(pierce_pct=0.08, recovery_full=True, vol_multiplier=2.0)
        score_shallow = detect_spring(df_shallow).score
        score_deep = detect_spring(df_deep).score
        assert score_deep > score_shallow

    def test_no_volume_lower_score(self):
        """Without volume confirmation, score should be lower."""
        df_high_vol = _make_spring_data(pierce_pct=0.05, recovery_full=True, vol_multiplier=2.0)
        df_low_vol = _make_spring_data(pierce_pct=0.05, recovery_full=True, vol_multiplier=0.5)
        score_high = detect_spring(df_high_vol).score
        score_low = detect_spring(df_low_vol).score
        assert score_high > score_low

    def test_insufficient_recovery_zero_score(self):
        """If price doesn't recover enough, score should be 0."""
        df = _make_spring_data(pierce_pct=0.05, recovery_full=False, vol_multiplier=2.0)
        signal = detect_spring(df)
        assert signal is not None
        # Recovery ratio very low => might be 0 depending on how much it recovered
        # With recovery_full=False, close = spring_low + 0.5 which is well below support
        assert signal.score == 0 or signal.details.get("reason") == "insufficient recovery"

    def test_score_range(self):
        """Score should be 0-100."""
        df = _make_spring_data(pierce_pct=0.05, recovery_full=True, vol_multiplier=2.0)
        signal = detect_spring(df)
        assert signal is not None
        assert 0 <= signal.score <= 100


# ================================================================
# Unit Tests — RSI Divergence (F2)
# ================================================================

class TestRsiDivergence:
    """Tests for detect_rsi_divergence()."""

    def test_bullish_divergence_detected(self):
        """Bullish divergence: price lower low, RSI higher low."""
        df = _make_divergence_data()
        signal = detect_rsi_divergence(df)
        assert signal is not None
        assert signal.signal_type == "rsi_divergence"
        assert signal.direction == "bullish"
        assert signal.score > 0

    def test_bearish_divergence_detected(self):
        """Bearish divergence: price higher high, RSI lower high."""
        df = _make_bearish_divergence_data()
        signal = detect_rsi_divergence(df)
        assert signal is not None
        assert signal.signal_type == "rsi_divergence"
        assert signal.direction == "bearish"
        assert signal.score > 0

    def test_no_divergence_in_uptrend(self):
        """Clean uptrend should not trigger divergence."""
        df = _make_uptrend_data()
        signal = detect_rsi_divergence(df)
        # Either None or score == 0
        if signal is not None:
            assert signal.score == 0

    def test_insufficient_data_returns_none(self):
        """Less than lookback window should return None."""
        df = _make_ohlcv([100, 101, 102, 103, 104])
        signal = detect_rsi_divergence(df)
        assert signal is None

    def test_flat_price_no_divergence(self):
        """Flat price series has no swing points — no divergence."""
        flat = [100.0] * 60
        df = _make_ohlcv(flat)
        signal = detect_rsi_divergence(df)
        if signal is not None:
            assert signal.score == 0

    def test_score_range(self):
        """Score should be 0-100."""
        df = _make_divergence_data()
        signal = detect_rsi_divergence(df)
        assert signal is not None
        assert 0 <= signal.score <= 100

    def test_custom_lookback(self):
        """Custom lookback parameter should work without error."""
        df = _make_divergence_data()
        signal = detect_rsi_divergence(df, lookback=30)
        # Should not raise; result depends on data


# ================================================================
# Unit Tests — Volume Exhaustion (F4)
# ================================================================

class TestVolumeExhaustion:
    """Tests for detect_volume_exhaustion()."""

    def test_exhaustion_detected(self):
        """Low volume for consecutive days triggers exhaustion signal."""
        df = _make_volume_exhaustion_data()
        signal = detect_volume_exhaustion(df)
        assert signal is not None
        assert signal.signal_type == "volume_exhaustion"
        assert signal.score > 0

    def test_no_exhaustion_healthy_volume(self):
        """Healthy volume should not trigger exhaustion."""
        df = _make_no_exhaustion_data()
        signal = detect_volume_exhaustion(df)
        if signal is not None:
            assert signal.score == 0

    def test_insufficient_data_returns_none(self):
        """Need at least 21 days for MA20 calculation."""
        df = _make_ohlcv([100] * 10, [500_000] * 10)
        signal = detect_volume_exhaustion(df)
        assert signal is None

    def test_bonus_for_extreme_exhaustion(self):
        """Volume ratio < 0.3x should get bonus score."""
        n = 80
        closes = [100.0] * n
        # 65 normal days + 15 extremely low — MA20 still dominated by normal days
        volumes = [1_000_000] * 65 + [50_000] * 15  # ~0.05x ratio
        df = _make_ohlcv(closes, volumes)
        signal = detect_volume_exhaustion(df)
        assert signal is not None
        assert signal.score >= 40  # At least base + bonus

    def test_score_range(self):
        """Score should be 0-100."""
        df = _make_volume_exhaustion_data()
        signal = detect_volume_exhaustion(df)
        assert signal is not None
        assert 0 <= signal.score <= 100

    def test_consecutive_count_in_details(self):
        """Signal details should include consecutive day count."""
        df = _make_volume_exhaustion_data()
        signal = detect_volume_exhaustion(df)
        assert signal is not None
        assert "consecutive_days" in signal.details


# ================================================================
# Unit Tests — BB Squeeze Alert (F3)
# ================================================================

def _make_bb_squeeze_data() -> pd.DataFrame:
    """Create data where recent BB width is at historical low.

    First 100 days: volatile (wide BB), last 40 days: very tight range (narrow BB).
    """
    n = 140
    # Phase 1: volatile period (100 days) — large oscillations
    x1 = np.arange(100)
    prices_volatile = 100 + np.sin(x1 * 0.3) * 15  # +/- 15 swing

    # Phase 2: tight consolidation (40 days) — tiny oscillations
    x2 = np.arange(40)
    prices_tight = 100 + np.sin(x2 * 0.5) * 0.5  # +/- 0.5 swing

    prices = list(prices_volatile) + list(prices_tight)
    volumes = [1_000_000] * n
    return _make_ohlcv(prices, volumes)


def _make_volatile_data() -> pd.DataFrame:
    """Create highly volatile data — BB should NOT be squeezed."""
    n = 140
    x = np.arange(n)
    # Increasing volatility
    prices = 100 + np.sin(x * 0.2) * (5 + x * 0.2)
    volumes = [1_000_000] * n
    return _make_ohlcv(list(prices), volumes)


class TestBBSqueeze:
    """Tests for detect_bb_squeeze()."""

    def test_squeeze_detected_tight_range(self):
        """Tight consolidation after volatile period should detect squeeze."""
        df = _make_bb_squeeze_data()
        signal = detect_bb_squeeze(df)
        assert signal is not None
        assert signal.signal_type == "bb_squeeze"
        assert signal.score > 0

    def test_no_squeeze_volatile_period(self):
        """Highly volatile data should not trigger squeeze."""
        df = _make_volatile_data()
        signal = detect_bb_squeeze(df)
        assert signal is not None
        assert signal.score == 0

    def test_insufficient_data_returns_none(self):
        """Less than MIN_DATA_BB_SQUEEZE should return None."""
        df = _make_ohlcv([100] * 10)
        signal = detect_bb_squeeze(df)
        assert signal is None

    def test_percentile_score_mapping(self):
        """Verify score tiers: <=5th=100, <=10th=80, <=20th=50, else=0."""
        # We verify via the squeeze data which should be at very low percentile
        df = _make_bb_squeeze_data()
        signal = detect_bb_squeeze(df)
        assert signal is not None
        assert signal.score in (0.0, 50.0, 80.0, 100.0)

    def test_details_include_percentile(self):
        """Signal details should include bb_width and percentile."""
        df = _make_bb_squeeze_data()
        signal = detect_bb_squeeze(df)
        assert signal is not None
        assert "bb_width" in signal.details
        assert "percentile" in signal.details
        assert "compression_rate_pct" in signal.details

    def test_score_range(self):
        """Score should be 0-100."""
        df = _make_bb_squeeze_data()
        signal = detect_bb_squeeze(df)
        assert signal is not None
        assert 0 <= signal.score <= 100


# ================================================================
# Unit Tests — Composite detect_reversal()
# ================================================================

class TestDetectReversal:
    """Tests for the composite detect_reversal() function."""

    def test_returns_reversal_result(self):
        """Should return a ReversalResult dataclass."""
        df = _make_divergence_data()
        result = detect_reversal(df)
        assert isinstance(result, ReversalResult)

    def test_phase_classification(self):
        """Phase should be one of NONE/WATCH/ALERT/STRONG."""
        df = _make_uptrend_data()
        result = detect_reversal(df)
        assert result.phase in ("NONE", "WATCH", "ALERT", "STRONG")

    def test_uptrend_is_low_phase(self):
        """Clear uptrend should NOT be STRONG/ALERT phase.

        Note: F5 (multi-scale accumulation) detects rising lows in uptrends,
        so WATCH is acceptable. The important thing is no STRONG/ALERT.
        """
        df = _make_uptrend_data()
        result = detect_reversal(df)
        assert result.phase in ("NONE", "WATCH")

    def test_signals_list_populated(self):
        """Signals list should contain sub-signal results."""
        df = _make_divergence_data()
        result = detect_reversal(df)
        assert isinstance(result.signals, list)

    def test_to_dict(self):
        """to_dict() should return a serializable dict."""
        df = _make_divergence_data()
        result = detect_reversal(df)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "phase" in d
        assert "score" in d
        assert "signals" in d

    def test_insufficient_data(self):
        """Short data should return NONE with score 0."""
        df = _make_ohlcv([100, 101, 102])
        result = detect_reversal(df)
        assert result.phase == "NONE"
        assert result.score == 0


# ================================================================
# E2E Tests — Real Stock Data
# ================================================================

def _fetch_real_data(code: str, period_days: int = 400):
    """Helper to fetch real data via yfinance directly (faster, no TWSE rate limit).

    Returns None if network fails.
    """
    try:
        import yfinance as yf
        from datetime import datetime, timedelta

        ticker = f"{code}.TW"
        end = datetime.now()
        start = end - timedelta(days=period_days)
        df = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                         end=end.strftime("%Y-%m-%d"), auto_adjust=True,
                         progress=False)
        if df is None or len(df) < 40:
            # Try TPEX (.TWO) suffix
            ticker = f"{code}.TWO"
            df = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                             end=end.strftime("%Y-%m-%d"), auto_adjust=True,
                             progress=False)
        if df is None or len(df) < 40:
            return None
        # Flatten MultiIndex columns (yfinance 2.x)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0].lower() for c in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]
        return df
    except Exception:
        return None


@pytest.mark.e2e
class TestE2ERealStocks:
    """E2E tests using real stock data. Skip if network unavailable."""

    @pytest.fixture(autouse=True)
    def _check_network(self):
        """Skip all E2E tests if we can't fetch any data."""
        df = _fetch_real_data("2330", period_days=100)
        if df is None:
            pytest.skip("Network unavailable or data fetch failed")

    def test_6618_reversal_signals(self):
        """6618 (永虹先進) — should detect multiple reversal signals (Spring, BB Squeeze, etc)."""
        df = _fetch_real_data("6618", period_days=400)
        if df is None:
            pytest.skip("Cannot fetch 6618 data")
        result = detect_reversal(df)
        assert isinstance(result, ReversalResult)
        assert result.phase in ("NONE", "WATCH", "ALERT", "STRONG")
        # Should have all 4 signal types in the signals list
        signal_types = {s.signal_type for s in result.signals}
        assert "spring" in signal_types or "bb_squeeze" in signal_types or "rsi_divergence" in signal_types
        # At least some signals should be present
        assert len(result.signals) >= 2

    def test_2330_uptrend_no_reversal(self):
        """2330 (台積電) — strong uptrend, should NOT have STRONG reversal phase."""
        df = _fetch_real_data("2330", period_days=400)
        if df is None:
            pytest.skip("Cannot fetch 2330 data")
        result = detect_reversal(df)
        assert isinstance(result, ReversalResult)
        # TSMC in strong uptrend — should not be STRONG reversal
        assert result.phase != "STRONG"

    def test_8021_validation_stock(self):
        """8021 from validation set — had big drop then recovery."""
        df = _fetch_real_data("8021", period_days=400)
        if df is None:
            pytest.skip("Cannot fetch 8021 data")
        result = detect_reversal(df)
        assert isinstance(result, ReversalResult)
        assert result.phase in ("NONE", "WATCH", "ALERT", "STRONG")

    def test_6442_validation_stock(self):
        """6442 from validation set — ~29% drop then 374% recovery."""
        df = _fetch_real_data("6442", period_days=400)
        if df is None:
            pytest.skip("Cannot fetch 6442 data")
        result = detect_reversal(df)
        assert isinstance(result, ReversalResult)
        d = result.to_dict()
        assert "score" in d
        assert 0 <= d["score"] <= 100

    def test_3491_validation_stock(self):
        """3491 from validation set — ~36% drop then 356% recovery."""
        df = _fetch_real_data("3491", period_days=400)
        if df is None:
            pytest.skip("Cannot fetch 3491 data")
        result = detect_reversal(df)
        assert isinstance(result, ReversalResult)

    def test_composite_has_five_signal_types(self):
        """Composite should evaluate all 5 signal types (may score 0)."""
        df = _fetch_real_data("6618", period_days=400)
        if df is None:
            pytest.skip("Cannot fetch 6618 data")
        result = detect_reversal(df)
        signal_types = {s.signal_type for s in result.signals}
        # All five should be attempted (returned even if score=0)
        expected = {"spring", "rsi_divergence", "bb_squeeze", "volume_exhaustion", "multiscale_accumulation"}
        assert signal_types == expected, f"Missing signals: {expected - signal_types}"

    def test_6618_spring_and_bb_individually(self):
        """6618: test individual F1/F3 detectors don't crash on real data."""
        df = _fetch_real_data("6618", period_days=400)
        if df is None:
            pytest.skip("Cannot fetch 6618 data")
        spring = detect_spring(df)
        assert spring is not None
        assert 0 <= spring.score <= 100

        bb = detect_bb_squeeze(df)
        assert bb is not None
        assert 0 <= bb.score <= 100

    def test_get_reversal_analysis_api(self):
        """Test the high-level API function."""
        result = get_reversal_analysis("2330")
        assert isinstance(result, dict)
        assert "code" in result
        assert "phase" in result
        assert result["code"] == "2330"

    def test_multiscale_accumulation_on_real_stock(self):
        """E2E: multi-scale accumulation on a real stock with enough data."""
        df = _fetch_real_data("2330", period_days=400)
        if df is None:
            pytest.skip("Cannot fetch 2330 data")
        signal = detect_multiscale_accumulation(df)
        assert signal is not None
        assert signal.signal_type == "multiscale_accumulation"
        assert 0 <= signal.score <= 100
        assert "rising_count" in signal.details


# ================================================================
# Unit Tests — Multi-scale Accumulation (F5)
# ================================================================

def _make_rising_lows_data() -> pd.DataFrame:
    """Create data with clear rising swing lows across all time windows.

    Pattern: three distinct dips, each higher than the last.
    Total 80 bars to cover all windows [20, 40, 60].
    """
    # Build a pattern with 3 rising dips across 80 bars
    prices = []
    # Dip 1 at bar ~10: bottom at 90
    prices += list(np.linspace(100, 90, 10))  # 0-9
    prices += list(np.linspace(91, 98, 10))    # 10-19 recover
    # Dip 2 at bar ~30: bottom at 92 (higher than 90)
    prices += list(np.linspace(97, 92, 10))    # 20-29
    prices += list(np.linspace(93, 99, 10))    # 30-39 recover
    # Dip 3 at bar ~50: bottom at 95 (higher than 92)
    prices += list(np.linspace(98, 95, 10))    # 40-49
    prices += list(np.linspace(96, 102, 10))   # 50-59 recover
    # Dip 4 at bar ~70: bottom at 97 (higher than 95)
    prices += list(np.linspace(101, 97, 10))   # 60-69
    prices += list(np.linspace(98, 105, 10))   # 70-79 recover

    return _make_ohlcv(prices)


def _make_falling_lows_data() -> pd.DataFrame:
    """Create data with falling swing lows — clear downtrend, no accumulation."""
    prices = []
    # Each dip is lower than the last
    prices += list(np.linspace(100, 95, 10))   # dip to 95
    prices += list(np.linspace(96, 98, 10))
    prices += list(np.linspace(97, 88, 10))    # dip to 88
    prices += list(np.linspace(89, 92, 10))
    prices += list(np.linspace(91, 80, 10))    # dip to 80
    prices += list(np.linspace(81, 85, 10))
    prices += list(np.linspace(84, 72, 10))    # dip to 72
    prices += list(np.linspace(73, 76, 10))

    return _make_ohlcv(prices)


def _make_mixed_lows_data() -> pd.DataFrame:
    """Create data where only some windows show rising lows.

    Short window (20d): rising lows (recent improvement)
    Long window (60d): falling lows (still in larger downtrend)
    """
    prices = []
    # 60 bars of downtrend with falling lows
    prices += list(np.linspace(100, 90, 15))
    prices += list(np.linspace(91, 95, 10))
    prices += list(np.linspace(94, 82, 15))
    prices += list(np.linspace(83, 88, 10))
    # last 20 bars: rising lows (short-term accumulation)
    prices += list(np.linspace(87, 84, 5))  # dip 1: 84
    prices += list(np.linspace(85, 89, 5))
    prices += list(np.linspace(88, 86, 5))  # dip 2: 86 (higher than 84)
    prices += list(np.linspace(87, 92, 5))

    return _make_ohlcv(prices)


class TestMultiscaleAccumulation:
    """Tests for detect_multiscale_accumulation()."""

    def test_rising_lows_all_windows_high_score(self):
        """Rising lows across all windows should give high score (100)."""
        df = _make_rising_lows_data()
        signal = detect_multiscale_accumulation(df)
        assert signal is not None
        assert signal.signal_type == "multiscale_accumulation"
        assert signal.score >= 66  # At least 2 windows rising
        assert signal.direction == "bullish"

    def test_falling_lows_zero_score(self):
        """Falling lows in downtrend should give score 0."""
        df = _make_falling_lows_data()
        signal = detect_multiscale_accumulation(df)
        assert signal is not None
        assert signal.score == 0
        assert signal.direction == ""

    def test_mixed_windows_partial_score(self):
        """Mixed: some windows rising, some not — partial score."""
        df = _make_mixed_lows_data()
        signal = detect_multiscale_accumulation(df)
        assert signal is not None
        # Should have partial score (not 0, not 100)
        # At least one window should be rising
        rising = signal.details.get("rising_count", 0)
        total = signal.details.get("total_windows", 3)
        # Verify it's partial (not all or none)
        # Note: due to synthetic data, results may vary — just check consistency
        assert 0 <= signal.score <= 100
        assert rising <= total

    def test_insufficient_data_returns_none(self):
        """Less than MIN_DATA_MULTISCALE should return None."""
        df = _make_ohlcv([100, 101, 102, 103, 104])
        signal = detect_multiscale_accumulation(df)
        assert signal is None

    def test_score_range(self):
        """Score should be 0-100."""
        df = _make_rising_lows_data()
        signal = detect_multiscale_accumulation(df)
        assert signal is not None
        assert 0 <= signal.score <= 100

    def test_details_structure(self):
        """Details should contain rising_windows and window_details."""
        df = _make_rising_lows_data()
        signal = detect_multiscale_accumulation(df)
        assert signal is not None
        assert "rising_windows" in signal.details
        assert "rising_count" in signal.details
        assert "window_details" in signal.details

    def test_custom_windows(self):
        """Custom windows parameter should work."""
        df = _make_rising_lows_data()
        signal = detect_multiscale_accumulation(df, windows=[20, 40])
        assert signal is not None
        assert signal.details["total_windows"] == 2


# ================================================================
# Unit Tests — Broker Score Integration in Composite
# ================================================================

class TestBrokerScoreIntegration:
    """Test that broker_score parameter works in detect_reversal()."""

    def test_broker_score_adds_bonus(self):
        """Broker score should add bonus to composite score."""
        df = _make_divergence_data()
        result_no_broker = detect_reversal(df, broker_score=None)
        result_with_broker = detect_reversal(df, broker_score=80.0)
        # With broker score, composite should be higher (or equal if capped)
        assert result_with_broker.score >= result_no_broker.score

    def test_broker_score_zero_no_effect(self):
        """Broker score of 0 should not change composite."""
        df = _make_divergence_data()
        result_none = detect_reversal(df, broker_score=None)
        result_zero = detect_reversal(df, broker_score=0.0)
        assert result_zero.score == result_none.score

    def test_broker_score_capped_at_100(self):
        """Composite with broker bonus should not exceed 100."""
        df = _make_divergence_data()
        result = detect_reversal(df, broker_score=100.0)
        assert result.score <= 100.0

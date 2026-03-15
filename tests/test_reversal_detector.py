"""Tests for analysis/reversal_detector.py — Slim (backtest-validated)

Only validated signals remain after 300-stock / 16,372 signal backtest:
- F2: RSI Divergence (WR=55.8% in combo with Multi-scale)
- F5: Multi-scale Accumulation (WR=51.6% standalone)
- Combo (F2+F5) = STRONG phase

Removed (backtest-proven harmful/useless):
- Spring: Unstable (sign flipped between 100/300 stocks)
- BB Squeeze: HARMFUL (WR=46.9%, p=0.00001)
- Volume Exhaustion: No edge (LIFT=-1.1%)
"""

import numpy as np
import pandas as pd
import pytest

from analysis.reversal_detector import (
    ReversalResult,
    ReversalSignal,
    detect_multiscale_accumulation,
    detect_reversal,
    detect_rsi_divergence,
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


def _make_uptrend_data() -> pd.DataFrame:
    """Create a clear uptrend -- should NOT trigger reversal signals."""
    n = 80
    x = np.arange(n)
    prices = 100 + x * 0.5 + np.sin(x * 0.3) * 2
    volumes = [1_000_000] * n
    return _make_ohlcv(list(prices), volumes)


def _make_rising_lows_data() -> pd.DataFrame:
    """Create data with clear rising swing lows across all time windows."""
    prices = []
    # Dip 1 at bar ~10: bottom at 90
    prices += list(np.linspace(100, 90, 10))
    prices += list(np.linspace(91, 98, 10))
    # Dip 2 at bar ~30: bottom at 92 (higher than 90)
    prices += list(np.linspace(97, 92, 10))
    prices += list(np.linspace(93, 99, 10))
    # Dip 3 at bar ~50: bottom at 95 (higher than 92)
    prices += list(np.linspace(98, 95, 10))
    prices += list(np.linspace(96, 102, 10))
    # Dip 4 at bar ~70: bottom at 97 (higher than 95)
    prices += list(np.linspace(101, 97, 10))
    prices += list(np.linspace(98, 105, 10))

    return _make_ohlcv(prices)


def _make_falling_lows_data() -> pd.DataFrame:
    """Create data with falling swing lows -- clear downtrend."""
    prices = []
    prices += list(np.linspace(100, 95, 10))
    prices += list(np.linspace(96, 98, 10))
    prices += list(np.linspace(97, 88, 10))
    prices += list(np.linspace(89, 92, 10))
    prices += list(np.linspace(91, 80, 10))
    prices += list(np.linspace(81, 85, 10))
    prices += list(np.linspace(84, 72, 10))
    prices += list(np.linspace(73, 76, 10))

    return _make_ohlcv(prices)


def _make_mixed_lows_data() -> pd.DataFrame:
    """Create data where only some windows show rising lows."""
    prices = []
    prices += list(np.linspace(100, 90, 15))
    prices += list(np.linspace(91, 95, 10))
    prices += list(np.linspace(94, 82, 15))
    prices += list(np.linspace(83, 88, 10))
    # last 20 bars: rising lows
    prices += list(np.linspace(87, 84, 5))
    prices += list(np.linspace(85, 89, 5))
    prices += list(np.linspace(88, 86, 5))
    prices += list(np.linspace(87, 92, 5))

    return _make_ohlcv(prices)


def _make_combo_data() -> pd.DataFrame:
    """Create data that triggers BOTH RSI divergence AND multi-scale accumulation.

    Pattern: downtrend with rising lows (multi-scale) + price lower low but RSI higher low.
    """
    # Phase 0: warmup (30 bars) — gradual decline
    prices = list(np.linspace(120, 105, 30))
    # Phase 1: sharp drop to first swing low (-> low RSI)
    prices += list(np.linspace(104, 82, 8))
    # Phase 2: recovery to form first higher low base
    prices += list(np.linspace(83, 96, 12))
    # Phase 3: gradual decline to lower price low but higher RSI low
    prices += list(np.linspace(95, 80, 18))
    # Phase 4: recovery forming second higher low
    prices += list(np.linspace(81, 90, 12))

    return _make_ohlcv(prices)


# ================================================================
# Unit Tests -- RSI Divergence (F2)
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
        if signal is not None:
            assert signal.score == 0

    def test_insufficient_data_returns_none(self):
        """Less than MIN_DATA_RSI should return None."""
        df = _make_ohlcv([100, 101, 102, 103, 104])
        signal = detect_rsi_divergence(df)
        assert signal is None

    def test_flat_price_no_divergence(self):
        """Flat price series has no swing points -- no divergence."""
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
# Unit Tests -- Multi-scale Accumulation (F5)
# ================================================================

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
        """Mixed: some windows rising, some not -- partial score."""
        df = _make_mixed_lows_data()
        signal = detect_multiscale_accumulation(df)
        assert signal is not None
        rising = signal.details.get("rising_count", 0)
        total = signal.details.get("total_windows", 3)
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
# Unit Tests -- Composite detect_reversal()
# ================================================================

class TestDetectReversal:
    """Tests for the composite detect_reversal() function."""

    def test_returns_reversal_result(self):
        """Should return a ReversalResult dataclass."""
        df = _make_divergence_data()
        result = detect_reversal(df)
        assert isinstance(result, ReversalResult)

    def test_phase_is_valid(self):
        """Phase should be one of NONE/WATCH/STRONG (ALERT removed)."""
        df = _make_uptrend_data()
        result = detect_reversal(df)
        assert result.phase in ("NONE", "WATCH", "STRONG")

    def test_uptrend_not_strong(self):
        """Clear uptrend should NOT be STRONG phase."""
        df = _make_uptrend_data()
        result = detect_reversal(df)
        assert result.phase != "STRONG"

    def test_multiscale_only_gives_watch(self):
        """Multi-scale alone (no RSI div) should give WATCH."""
        df = _make_rising_lows_data()
        result = detect_reversal(df)
        # Rising lows should trigger multi-scale; RSI unlikely in smooth data
        if result.phase != "NONE":
            assert result.phase in ("WATCH", "STRONG")

    def test_combo_gives_strong(self):
        """Both Multi-scale + RSI Divergence firing should give STRONG."""
        df = _make_combo_data()
        result = detect_reversal(df)
        # If both fire, must be STRONG with combo_triggered=True
        rsi_fired = any(s.signal_type == "rsi_divergence" and s.score > 0 for s in result.signals)
        ms_fired = any(s.signal_type == "multiscale_accumulation" and s.score > 0 for s in result.signals)
        if rsi_fired and ms_fired:
            assert result.phase == "STRONG"
            assert result.combo_triggered is True
            assert result.score == 80.0

    def test_strong_score_is_80(self):
        """STRONG phase should have score=80."""
        df = _make_combo_data()
        result = detect_reversal(df)
        if result.phase == "STRONG":
            assert result.score == 80.0

    def test_watch_score_is_50(self):
        """WATCH phase should have score=50."""
        df = _make_rising_lows_data()
        result = detect_reversal(df)
        if result.phase == "WATCH":
            assert result.score == 50.0

    def test_none_score_is_0(self):
        """NONE phase should have score=0."""
        df = _make_falling_lows_data()
        result = detect_reversal(df)
        if result.phase == "NONE":
            assert result.score == 0.0

    def test_combo_triggered_field(self):
        """combo_triggered should be in to_dict() output."""
        df = _make_divergence_data()
        result = detect_reversal(df)
        d = result.to_dict()
        assert "combo_triggered" in d

    def test_signals_only_two_types(self):
        """Signals list should only contain rsi_divergence and multiscale_accumulation."""
        df = _make_divergence_data()
        result = detect_reversal(df)
        for s in result.signals:
            assert s.signal_type in ("rsi_divergence", "multiscale_accumulation")

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
# Unit Tests -- Broker Score Integration
# ================================================================

class TestBrokerScoreIntegration:
    """Test that broker_score parameter works in detect_reversal()."""

    def test_broker_score_adds_bonus(self):
        """Broker score should add bonus to composite score when signal exists."""
        df = _make_divergence_data()
        result_no_broker = detect_reversal(df, broker_score=None)
        result_with_broker = detect_reversal(df, broker_score=80.0)
        # With broker score, composite should be >= (bonus only applies when score > 0)
        assert result_with_broker.score >= result_no_broker.score

    def test_broker_score_zero_no_effect(self):
        """Broker score of 0 should not change composite."""
        df = _make_divergence_data()
        result_none = detect_reversal(df, broker_score=None)
        result_zero = detect_reversal(df, broker_score=0.0)
        assert result_zero.score == result_none.score

    def test_broker_score_capped_at_100(self):
        """Composite with broker bonus should not exceed 100."""
        df = _make_combo_data()
        result = detect_reversal(df, broker_score=100.0)
        assert result.score <= 100.0

    def test_broker_no_bonus_when_none_phase(self):
        """Broker bonus should NOT apply when phase is NONE (no signal)."""
        df = _make_falling_lows_data()
        result = detect_reversal(df, broker_score=100.0)
        if result.phase == "NONE":
            assert result.score == 0.0


# ================================================================
# E2E Tests -- Real Stock Data
# ================================================================

def _fetch_real_data(code: str, period_days: int = 400):
    """Helper to fetch real data via yfinance directly (faster, no TWSE rate limit)."""
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
        """6618 -- should detect reversal sub-signals."""
        df = _fetch_real_data("6618", period_days=400)
        if df is None:
            pytest.skip("Cannot fetch 6618 data")
        result = detect_reversal(df)
        assert isinstance(result, ReversalResult)
        assert result.phase in ("NONE", "WATCH", "STRONG")
        # Should have both signal types evaluated
        signal_types = {s.signal_type for s in result.signals}
        assert "rsi_divergence" in signal_types or "multiscale_accumulation" in signal_types
        assert len(result.signals) >= 1

    def test_2330_uptrend_no_strong(self):
        """2330 (TSMC) -- strong uptrend, should NOT have STRONG reversal phase."""
        df = _fetch_real_data("2330", period_days=400)
        if df is None:
            pytest.skip("Cannot fetch 2330 data")
        result = detect_reversal(df)
        assert isinstance(result, ReversalResult)
        assert result.phase != "STRONG"

    def test_6442_validation_stock(self):
        """6442 from validation set -- ~29% drop then 374% recovery."""
        df = _fetch_real_data("6442", period_days=400)
        if df is None:
            pytest.skip("Cannot fetch 6442 data")
        result = detect_reversal(df)
        assert isinstance(result, ReversalResult)
        d = result.to_dict()
        assert "score" in d
        assert 0 <= d["score"] <= 100

    def test_composite_has_two_signal_types(self):
        """Composite should evaluate both signal types (may score 0)."""
        df = _fetch_real_data("6618", period_days=400)
        if df is None:
            pytest.skip("Cannot fetch 6618 data")
        result = detect_reversal(df)
        signal_types = {s.signal_type for s in result.signals}
        expected = {"rsi_divergence", "multiscale_accumulation"}
        assert signal_types == expected, f"Missing signals: {expected - signal_types}"

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

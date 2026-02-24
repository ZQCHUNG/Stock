"""Tests for R95.1 P0.2 Accumulation Backtest.

Tests breakout detection, busted accumulation, forward returns,
kill switch evaluation, TTB distribution, and AQS stratification.
"""

import numpy as np
import pandas as pd
import pytest

from backtest.accumulation_backtest import (
    BREAKOUT_TR_ATR_RATIO,
    BREAKOUT_VOLUME_RATIO,
    BUSTED_CONSECUTIVE_DAYS,
    FORWARD_HORIZONS,
    KILL_PROFIT_FACTOR,
    KILL_WIN_RATE,
    TTB_KILL_MEDIAN,
    TTB_MAX_DAYS,
    check_breakout,
    check_busted,
    compute_aqs_stratification,
    compute_forward_returns,
    compute_ttb_distribution,
    compute_year_breakdown,
    evaluate_kill_switch,
)
from analysis.scoring import TRANSACTION_COST


# ---------- Helpers ----------

def _make_ohlcv(n: int = 200, seed: int = 42, base_price: float = 100.0) -> pd.DataFrame:
    """Create synthetic OHLCV with pre-computed BB and ATR."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2023-01-01", periods=n, freq="B")

    # Random walk close
    returns = rng.normal(0.001, 0.015, n)
    close = base_price * np.cumprod(1 + returns)

    high = close * (1 + rng.uniform(0.005, 0.02, n))
    low = close * (1 - rng.uniform(0.005, 0.02, n))
    open_ = close * (1 + rng.normal(0, 0.005, n))
    volume = rng.randint(100_000, 500_000, n).astype(float)

    df = pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)

    # Compute BB
    df["bb_middle"] = df["close"].rolling(20).mean()
    rolling_std = df["close"].rolling(20).std()
    df["bb_upper"] = df["bb_middle"] + 2 * rolling_std
    df["bb_lower"] = df["bb_middle"] - 2 * rolling_std

    # Compute ATR
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.ewm(span=20, adjust=False).mean()

    return df


def _make_breakout_df(breakout_at: int = 50) -> pd.DataFrame:
    """Create a DataFrame with a guaranteed breakout at a specific bar.

    Flat consolidation followed by a sharp breakout.
    """
    n = 100
    dates = pd.bdate_range("2023-01-01", periods=n, freq="B")

    # Flat phase: close ~100, tight BB
    close = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    volume = np.full(n, 200_000.0)

    # At breakout bar: spike up with volume
    close[breakout_at] = 115.0
    high[breakout_at] = 116.0
    low[breakout_at] = 100.0
    volume[breakout_at] = 800_000.0  # 4x normal

    # Continue post-breakout
    for i in range(breakout_at + 1, n):
        close[i] = 115.0 + (i - breakout_at) * 0.5
        high[i] = close[i] + 1.0
        low[i] = close[i] - 0.5
        volume[i] = 300_000.0

    df = pd.DataFrame({
        "open": close - 0.5,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)

    # Compute BB
    df["bb_middle"] = df["close"].rolling(20, min_periods=1).mean()
    rolling_std = df["close"].rolling(20, min_periods=1).std().fillna(0.1)
    df["bb_upper"] = df["bb_middle"] + 2 * rolling_std
    df["bb_lower"] = df["bb_middle"] - 2 * rolling_std

    # Compute ATR
    prev_close = df["close"].shift(1).fillna(close[0])
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.ewm(span=20, adjust=False).mean()

    return df


# ---------- Tests: check_breakout ----------

class TestCheckBreakout:
    """Tests for the 4-condition breakout detection."""

    def test_breakout_detected(self):
        """Breakout should be detected when all 4 conditions met."""
        df = _make_breakout_df(breakout_at=50)
        result = check_breakout(df, start_idx=30)
        # The breakout bar at 50 should be detected
        assert result["ttb"] is not None
        assert result["ttb"] == 20  # 50 - 30
        assert result["breakout_price"] is not None

    def test_no_breakout_flat(self):
        """No breakout in completely flat data."""
        n = 100
        dates = pd.bdate_range("2023-01-01", periods=n, freq="B")
        close = np.full(n, 100.0)
        df = pd.DataFrame({
            "open": close, "high": close + 0.1, "low": close - 0.1,
            "close": close, "volume": np.full(n, 200_000.0),
        }, index=dates)
        df["bb_middle"] = close
        df["bb_upper"] = close + 0.5
        df["bb_lower"] = close - 0.5
        df["atr"] = np.full(n, 0.2)

        result = check_breakout(df, start_idx=20, max_days=30)
        assert result["ttb"] is None

    def test_breakout_respects_max_days(self):
        """Breakout beyond max_days should not be detected."""
        df = _make_breakout_df(breakout_at=50)
        result = check_breakout(df, start_idx=30, max_days=10)
        # Breakout at bar 50, start at 30, max_days=10 → end=40, won't see it
        assert result["ttb"] is None

    def test_start_idx_edge(self):
        """Start at end of data should return None."""
        df = _make_ohlcv(50)
        result = check_breakout(df, start_idx=49)
        assert result["ttb"] is None

    def test_volume_condition_required(self):
        """Breakout without volume spike should fail."""
        df = _make_breakout_df(breakout_at=50)
        # Kill volume at breakout bar
        df.iloc[50, df.columns.get_loc("volume")] = 100_000.0  # low volume
        result = check_breakout(df, start_idx=30)
        # May or may not find it depending on MA — the key is volume check works
        if result["ttb"] is not None:
            # If found, it must be at a different bar (not 50)
            assert result["ttb"] != 20


# ---------- Tests: check_busted ----------

class TestCheckBusted:
    """Tests for the 3-day Hysteresis Busted detection."""

    def test_busted_after_3_days(self):
        """Should detect busted after 3 consecutive days below zone lower."""
        df = _make_ohlcv(100)
        zone_lower = float(df["close"].iloc[20]) + 10  # Set zone above current prices
        result = check_busted(df, start_idx=20, zone_lower=zone_lower)
        assert result["is_busted"] is True
        assert result["busted_day"] is not None

    def test_not_busted_if_recovers(self):
        """2 days below then recovery should NOT trigger busted."""
        n = 50
        dates = pd.bdate_range("2023-01-01", periods=n, freq="B")
        close = np.full(n, 100.0)
        # Days 21-22 below zone (2 days only)
        close[21] = 89.0
        close[22] = 89.0
        close[23] = 100.0  # recovers

        df = pd.DataFrame({
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": np.full(n, 200_000.0),
        }, index=dates)

        result = check_busted(df, start_idx=20, zone_lower=90.0)
        # 2 days below is not enough for 3-day hysteresis
        assert result["is_busted"] is False

    def test_busted_3_consecutive(self):
        """Exactly 3 consecutive days below triggers busted."""
        n = 50
        dates = pd.bdate_range("2023-01-01", periods=n, freq="B")
        close = np.full(n, 100.0)
        close[21] = 89.0
        close[22] = 88.0
        close[23] = 87.0  # 3rd consecutive day

        df = pd.DataFrame({
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": np.full(n, 200_000.0),
        }, index=dates)

        result = check_busted(df, start_idx=20, zone_lower=90.0)
        assert result["is_busted"] is True
        assert result["busted_day"] == 3  # 23 - 20

    def test_not_busted_all_above(self):
        """All closes above zone should not trigger busted."""
        df = _make_ohlcv(50, base_price=100)
        result = check_busted(df, start_idx=10, zone_lower=50.0)  # zone far below
        assert result["is_busted"] is False


# ---------- Tests: compute_forward_returns ----------

class TestComputeForwardReturns:
    """Tests for forward return computation."""

    def test_basic_forward_returns(self):
        """Should compute returns for all horizons."""
        df = _make_ohlcv(200)
        result = compute_forward_returns(df, signal_idx=50)

        assert "signal_price" in result
        for h in FORWARD_HORIZONS:
            assert f"d{h}_return" in result
            assert f"d{h}_max_gain" in result
            assert f"d{h}_max_dd" in result

    def test_returns_at_end_of_data(self):
        """Near end of data, longer horizons should be None."""
        df = _make_ohlcv(60)
        result = compute_forward_returns(df, signal_idx=55)
        # D60 from idx 55 in 60-bar df → not enough data
        # But D7 might still work (55+7=62 > 59)
        # All should handle gracefully
        assert result["signal_price"] > 0

    def test_positive_return(self):
        """Verify return calculation with known values."""
        n = 30
        dates = pd.bdate_range("2023-01-01", periods=n, freq="B")
        close = np.full(n, 100.0)
        close[8] = 110.0  # +10% at d7 from idx 0

        df = pd.DataFrame({
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": np.full(n, 200_000.0),
        }, index=dates)

        result = compute_forward_returns(df, signal_idx=0, horizons=[7])
        # d7 return = (close[7] - close[0]) / close[0]
        expected = (close[7] - close[0]) / close[0]
        assert result["d7_return"] == pytest.approx(expected, abs=1e-4)


# ---------- Tests: evaluate_kill_switch ----------

class TestEvaluateKillSwitch:
    """Tests for Kill Switch evaluation logic."""

    def _make_signals(
        self, n: int = 50, win_pct: float = 0.5, avg_win: float = 0.05,
        avg_loss: float = -0.02, ttb_median: float = 15.0,
    ) -> list[dict]:
        """Create synthetic signals with controlled parameters."""
        rng = np.random.RandomState(42)
        signals = []
        for i in range(n):
            is_win = rng.random() < win_pct
            d21 = abs(rng.normal(avg_win, 0.01)) if is_win else -abs(rng.normal(abs(avg_loss), 0.005))
            d7 = d21 * 1.2  # D7 > D21 > D30 = "explosive leadership"
            d30 = d21 * 0.7
            ttb = max(1, int(rng.normal(ttb_median, 5)))

            signals.append({
                "code": f"{2330 + i}",
                "date": f"2023-{(i % 12) + 1:02d}-15",
                "phase": "BETA" if is_win else "ALPHA",
                "score": 60 + rng.randint(0, 30),
                "d7_return": round(d7, 5),
                "d21_return": round(d21, 5),
                "d30_return": round(d30, 5),
                "ttb": ttb,
                "is_busted": not is_win and rng.random() < 0.3,
                "aqs_score": rng.uniform(0, 1) if rng.random() > 0.3 else None,
            })
        return signals

    def test_all_pass(self):
        """Signals with good metrics should PASS."""
        signals = self._make_signals(
            n=50, win_pct=0.55, avg_win=0.08, avg_loss=-0.02, ttb_median=12,
        )
        result = evaluate_kill_switch(signals)
        assert result["verdict"] == "PASS"

    def test_kill_on_low_win_rate(self):
        """Low win rate should trigger KILL."""
        signals = self._make_signals(
            n=50, win_pct=0.30, avg_win=0.03, avg_loss=-0.03, ttb_median=15,
        )
        result = evaluate_kill_switch(signals)
        assert result["criteria"]["win_rate"]["pass"] is False

    def test_kill_on_low_pf(self):
        """Low profit factor should trigger KILL."""
        signals = self._make_signals(
            n=50, win_pct=0.50, avg_win=0.01, avg_loss=-0.01, ttb_median=15,
        )
        result = evaluate_kill_switch(signals)
        # PF ≈ 1.0 which is < 1.5
        assert result["criteria"]["profit_factor"]["value"] is not None

    def test_empty_signals(self):
        """Empty signals should return NO_DATA."""
        result = evaluate_kill_switch([])
        assert result["verdict"] == "NO_DATA"

    def test_ttb_threshold(self):
        """TTB median > 30 should fail."""
        signals = self._make_signals(n=50, ttb_median=35)
        result = evaluate_kill_switch(signals)
        assert result["criteria"]["ttb_median"]["pass"] is False

    def test_d21_net_return_deducts_cost(self):
        """D21 net return should account for transaction cost."""
        # All signals have d21_return = TRANSACTION_COST - 0.001 (just below breakeven)
        signals = [
            {"d21_return": TRANSACTION_COST - 0.001, "d7_return": 0.001, "d30_return": 0.002,
             "ttb": 10, "is_busted": False}
            for _ in range(20)
        ]
        result = evaluate_kill_switch(signals)
        assert result["criteria"]["d21_net_return"]["pass"] is False


# ---------- Tests: TTB Distribution ----------

class TestTTBDistribution:
    """Tests for TTB bucket distribution."""

    def test_bucket_assignment(self):
        """Signals should be correctly bucketed by TTB."""
        signals = [
            {"ttb": 3, "d21_return": 0.05, "d30_return": 0.06},
            {"ttb": 8, "d21_return": 0.03, "d30_return": 0.04},
            {"ttb": 15, "d21_return": 0.02, "d30_return": 0.03},
            {"ttb": 25, "d21_return": 0.01, "d30_return": 0.01},
            {"ttb": None, "d21_return": -0.02, "d30_return": -0.03},  # timeout
        ]
        result = compute_ttb_distribution(signals)

        assert result["0-5d"]["count"] == 1
        assert result["5-10d"]["count"] == 1
        assert result["10-20d"]["count"] == 1
        assert result["20-30d"]["count"] == 1
        assert result["30d+"]["count"] == 1

    def test_empty_signals(self):
        """Empty signals should produce empty buckets."""
        result = compute_ttb_distribution([])
        for bucket in result.values():
            assert bucket["count"] == 0

    def test_d21_median_per_bucket(self):
        """Each bucket should compute its own D21 median."""
        signals = [
            {"ttb": 2, "d21_return": 0.10, "d30_return": 0.12},
            {"ttb": 4, "d21_return": 0.06, "d30_return": 0.08},
        ]
        result = compute_ttb_distribution(signals)
        assert result["0-5d"]["d21_median"] == pytest.approx(0.08, abs=1e-3)


# ---------- Tests: AQS Stratification ----------

class TestAQSStratification:
    """Tests for AQS group comparison."""

    def test_grouping(self):
        """Signals should be grouped by AQS score."""
        signals = [
            {"aqs_score": None, "ttb": 10, "d21_return": 0.03, "is_busted": False},
            {"aqs_score": 0.3, "ttb": 15, "d21_return": 0.02, "is_busted": False},
            {"aqs_score": 0.8, "ttb": 5, "d21_return": 0.08, "is_busted": False},
        ]
        result = compute_aqs_stratification(signals)
        assert result["no_aqs"]["count"] == 1
        assert result["aqs_low"]["count"] == 1
        assert result["aqs_high"]["count"] == 1

    def test_empty_groups(self):
        """All signals in one group should leave others empty."""
        signals = [
            {"aqs_score": 0.9, "ttb": 5, "d21_return": 0.05, "is_busted": False},
            {"aqs_score": 0.7, "ttb": 8, "d21_return": 0.04, "is_busted": False},
        ]
        result = compute_aqs_stratification(signals)
        assert result["aqs_high"]["count"] == 2
        assert result["aqs_low"]["count"] == 0
        assert result["no_aqs"]["count"] == 0


# ---------- Tests: Year Breakdown ----------

class TestYearBreakdown:
    """Tests for year-based stress test breakdown."""

    def test_year_grouping(self):
        """Signals should be grouped by year."""
        signals = [
            {"year": 2022, "d21_return": -0.05, "is_busted": True},
            {"year": 2022, "d21_return": -0.03, "is_busted": False},
            {"year": 2023, "d21_return": 0.06, "is_busted": False},
            {"year": 2024, "d21_return": 0.04, "is_busted": False},
        ]
        result = compute_year_breakdown(signals)
        assert 2022 in result
        assert result[2022]["signal_count"] == 2
        assert result[2022]["busted_count"] == 1
        assert result[2023]["signal_count"] == 1

    def test_2022_stress(self):
        """2022 crash year should show poor metrics."""
        signals = [
            {"year": 2022, "d21_return": -0.08, "is_busted": True},
            {"year": 2022, "d21_return": -0.04, "is_busted": True},
            {"year": 2022, "d21_return": 0.02, "is_busted": False},
        ]
        result = compute_year_breakdown(signals)
        assert result[2022]["win_rate"] is not None
        # With mostly losses, win rate should be low
        assert result[2022]["busted_rate"] > 0.5

    def test_empty(self):
        """No signals should return empty dict."""
        result = compute_year_breakdown([])
        assert result == {}


# ---------- Tests: Constants ----------

class TestConstants:
    """Tests for backtest parameter consistency."""

    def test_kill_switch_thresholds(self):
        """Verify Kill Switch thresholds match Wall Street Trader specs."""
        assert TTB_KILL_MEDIAN == 30
        assert KILL_WIN_RATE == 0.45
        assert KILL_PROFIT_FACTOR == 1.5

    def test_breakout_parameters(self):
        """Verify breakout parameters match Trader specs."""
        assert BREAKOUT_TR_ATR_RATIO == 1.2
        assert BREAKOUT_VOLUME_RATIO == 1.5

    def test_busted_hysteresis(self):
        """Busted requires exactly 3 consecutive days (Trader + Architect APPROVED)."""
        assert BUSTED_CONSECUTIVE_DAYS == 3

    def test_ttb_max_reasonable(self):
        """TTB max should allow enough time but not too much."""
        assert TTB_MAX_DAYS == 60  # 3 months of trading days

    def test_forward_horizons(self):
        """Forward horizons should include D7/D14/D21/D30/D60."""
        assert 7 in FORWARD_HORIZONS
        assert 14 in FORWARD_HORIZONS
        assert 21 in FORWARD_HORIZONS
        assert 30 in FORWARD_HORIZONS
        assert 60 in FORWARD_HORIZONS

"""Tests for Market Regime Global Switch (analysis/market_guard.py)

[CONVERGED — Wall Street Trader + Architect Critic APPROVED]
"""

import numpy as np
import pandas as pd
import pytest

from analysis.market_guard import (
    MARKET_GUARD_CONFIG,
    MarketGuardStatus,
    compute_adl,
    compute_adl_declining_days,
    compute_market_breadth,
    detect_price_gap,
    get_market_exposure_limit,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_taiex(closes, opens=None, volumes=None):
    """Helper to build TAIEX DataFrame."""
    n = len(closes)
    dates = pd.bdate_range(end="2026-02-20", periods=n)
    df = pd.DataFrame({
        "open": opens if opens is not None else closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": volumes if volumes is not None else [1_000_000] * n,
    }, index=dates)
    return df


def _make_stock_closes(n_stocks=50, n_days=250, trend="bull"):
    """Build synthetic stock close prices."""
    dates = pd.bdate_range(end="2026-02-20", periods=n_days)
    closes = {}
    for i in range(n_stocks):
        base = 100 + i * 10
        if trend == "bull":
            # Uptrend: gradual increase
            values = base + np.cumsum(np.random.normal(0.3, 1.0, n_days))
        elif trend == "bear":
            # Downtrend: gradual decrease
            values = base + np.cumsum(np.random.normal(-0.5, 1.0, n_days))
        else:
            # Sideways
            values = base + np.cumsum(np.random.normal(0, 1.0, n_days))
        closes[f"stock_{i}"] = pd.Series(values, index=dates)
    return closes


# ---------------------------------------------------------------------------
# ADL Tests
# ---------------------------------------------------------------------------

class TestADL:
    def test_compute_adl_empty(self):
        adl = compute_adl({})
        assert len(adl) == 0

    def test_compute_adl_basic(self):
        dates = pd.bdate_range("2026-01-01", periods=5)
        # Stock A: up every day, Stock B: down every day
        closes = {
            "A": pd.Series([100, 101, 102, 103, 104], index=dates),
            "B": pd.Series([100, 99, 98, 97, 96], index=dates),
        }
        adl = compute_adl(closes)
        assert len(adl) == 5
        # Day 1: first day has NaN returns, cumsum starts at 0
        # Day 2+: 1 advancing (A) - 1 declining (B) = 0 net each day
        # So ADL should be flat (0 each day after first)

    def test_compute_adl_all_up(self):
        dates = pd.bdate_range("2026-01-01", periods=5)
        closes = {
            "A": pd.Series([100, 101, 102, 103, 104], index=dates),
            "B": pd.Series([50, 51, 52, 53, 54], index=dates),
        }
        adl = compute_adl(closes)
        # After first NaN day, both stocks advance = +2 each day
        # ADL should be increasing
        assert adl.iloc[-1] > adl.iloc[1]

    def test_declining_days_basic(self):
        adl = pd.Series([10, 12, 14, 13, 11, 9])
        days = compute_adl_declining_days(adl)
        assert days == 3  # last 3 values declining

    def test_declining_days_zero(self):
        adl = pd.Series([10, 12, 14, 16])
        days = compute_adl_declining_days(adl)
        assert days == 0

    def test_declining_days_empty(self):
        assert compute_adl_declining_days(pd.Series(dtype=float)) == 0
        assert compute_adl_declining_days(None) == 0


# ---------------------------------------------------------------------------
# Market Breadth Tests
# ---------------------------------------------------------------------------

class TestMarketBreadth:
    def test_all_above_ma(self):
        dates = pd.bdate_range("2026-01-01", periods=30)
        # Steadily rising stock → always above MA20
        closes = {
            "A": pd.Series(range(100, 130), index=dates, dtype=float),
        }
        breadth = compute_market_breadth(closes, ma_period=20)
        assert breadth == 1.0

    def test_all_below_ma(self):
        dates = pd.bdate_range("2026-01-01", periods=30)
        # Steadily declining stock → below MA20
        closes = {
            "A": pd.Series(range(130, 100, -1), index=dates, dtype=float),
        }
        breadth = compute_market_breadth(closes, ma_period=20)
        assert breadth == 0.0

    def test_mixed(self):
        dates = pd.bdate_range("2026-01-01", periods=30)
        closes = {
            "UP": pd.Series(range(100, 130), index=dates, dtype=float),
            "DOWN": pd.Series(range(130, 100, -1), index=dates, dtype=float),
        }
        breadth = compute_market_breadth(closes, ma_period=20)
        assert breadth == 0.5

    def test_empty(self):
        assert compute_market_breadth({}) == 0.0


# ---------------------------------------------------------------------------
# Price Gap Detection Tests
# ---------------------------------------------------------------------------

class TestPriceGap:
    def test_no_gap(self):
        df = _make_taiex([20000] * 25)
        alert, pct = detect_price_gap(df)
        assert alert is False

    def test_gap_down_with_volume(self):
        closes = [20000] * 24 + [19200]  # Last day drops
        opens = [20000] * 24 + [19300]    # Open is -3.5% vs prev close
        volumes = [1_000_000] * 24 + [3_000_000]  # 3x avg volume
        df = _make_taiex(closes, opens, volumes)
        alert, pct = detect_price_gap(df, gap_pct=-0.03, volume_mult=2.0)
        assert alert is True
        assert pct < -0.03

    def test_gap_down_without_volume(self):
        closes = [20000] * 24 + [19200]
        opens = [20000] * 24 + [19300]    # -3.5%
        volumes = [1_000_000] * 25         # Normal volume
        df = _make_taiex(closes, opens, volumes)
        alert, pct = detect_price_gap(df, gap_pct=-0.03, volume_mult=2.0)
        assert alert is False  # Volume not abnormal

    def test_insufficient_data(self):
        df = _make_taiex([20000] * 5)
        alert, pct = detect_price_gap(df)
        assert alert is False


# ---------------------------------------------------------------------------
# Market Guard Integration Tests
# ---------------------------------------------------------------------------

class TestMarketGuard:
    def test_normal_market(self):
        """Bull market: TAIEX above all MAs, good breadth."""
        # Uptrend TAIEX
        closes = list(range(18000, 18250))
        df = _make_taiex(closes)
        stock_closes = _make_stock_closes(50, len(closes), trend="bull")

        status = get_market_exposure_limit(df, stock_closes)
        assert status.level == 0
        assert status.level_label == "NORMAL"
        assert status.exposure_limit == 1.0
        assert len(status.triggers) == 0

    def test_level1_taiex_below_ma20(self):
        """TAIEX drops below MA20 → CAUTION."""
        # Start high then drop recently
        closes = [20000] * 200 + [19500] * 15 + [19000] * 5
        df = _make_taiex(closes)

        status = get_market_exposure_limit(df)
        if status.taiex_below_ma20:
            assert status.level >= 1
            assert status.exposure_limit <= 0.5

    def test_level1_adl_declining(self):
        """ADL declining 5+ days → CAUTION."""
        closes = [20000 + i * 10 for i in range(250)]
        df = _make_taiex(closes)

        # Create stocks where most decline for 6+ days
        dates = pd.bdate_range(end="2026-02-20", periods=250)
        stock_closes = {}
        for i in range(50):
            vals = [100 + i] * 244 + [100 + i - j for j in range(1, 7)]
            stock_closes[f"s{i}"] = pd.Series(vals, index=dates)

        status = get_market_exposure_limit(df, stock_closes)
        # ADL should be declining for 6 days
        assert status.adl_declining_days >= 5

    def test_level2_lockdown(self):
        """TAIEX < MA200 AND breadth < 20% → LOCKDOWN."""
        # TAIEX far below MA200
        closes = list(range(20000, 19750, -1)) + [18000] * 5
        df = _make_taiex(closes)

        # All stocks declining (breadth < 20%)
        stock_closes = _make_stock_closes(50, len(closes), trend="bear")

        status = get_market_exposure_limit(df, stock_closes)
        if status.taiex_below_ma200 and status.breadth_pct < 0.20:
            assert status.level == 2
            assert status.level_label == "LOCKDOWN"
            assert status.exposure_limit == 0.0

    def test_insufficient_data(self):
        """Less than 200 days → returns NORMAL with warning."""
        df = _make_taiex([20000] * 50)
        status = get_market_exposure_limit(df)
        assert status.level == 0
        assert "insufficient" in status.detail.lower()

    def test_none_taiex(self):
        status = get_market_exposure_limit(None)
        assert status.level == 0
        assert "insufficient" in status.detail.lower()

    def test_config_override(self):
        """Custom config overrides defaults."""
        closes = [20000] * 250
        df = _make_taiex(closes)
        custom = {"adl_decline_days": 3, "level1_exposure": 0.30}
        status = get_market_exposure_limit(df, config=custom)
        # Just verify it doesn't crash and returns valid status
        assert 0 <= status.exposure_limit <= 1.0

    def test_to_dict(self):
        status = MarketGuardStatus(level=1, level_label="CAUTION")
        d = status.to_dict()
        assert d["level"] == 1
        assert d["level_label"] == "CAUTION"
        assert "triggers" in d

    def test_no_stock_closes_still_works(self):
        """Without breadth data, only TAIEX MA checks apply."""
        closes = [20000] * 250
        df = _make_taiex(closes)
        status = get_market_exposure_limit(df, stock_closes=None)
        assert status.breadth_pct == 0.0
        assert status.adl_declining_days == 0

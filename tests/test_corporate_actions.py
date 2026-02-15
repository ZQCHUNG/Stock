"""Tests for R58 corporate action detection."""

import pandas as pd
import numpy as np
import pytest
from data.corporate_actions import (
    CorporateAction,
    CorporateActionReport,
    detect_limit_hits,
    detect_price_gaps,
    detect_zero_volume_days,
    detect_corporate_actions,
    annotate_trades_with_actions,
)


def _make_df(closes, highs=None, lows=None, volumes=None, start="2024-01-02"):
    """Helper: create OHLCV DataFrame."""
    n = len(closes)
    dates = pd.bdate_range(start, periods=n)
    data = {
        "close": closes,
        "open": closes,
        "high": highs if highs is not None else [c * 1.01 for c in closes],
        "low": lows if lows is not None else [c * 0.99 for c in closes],
    }
    if volumes is not None:
        data["volume"] = volumes
    else:
        data["volume"] = [1_000_000] * n
    return pd.DataFrame(data, index=dates)


class TestDetectLimitHits:
    def test_limit_up(self):
        """Stock hitting limit up (+10%) should be detected."""
        closes = [100, 110]  # +10% exactly
        highs = [100.5, 110.0]
        df = _make_df(closes, highs=highs)
        actions = detect_limit_hits(df)
        assert len(actions) == 1
        assert actions[0].action_type == "limit_up"

    def test_limit_down(self):
        """Stock hitting limit down (-10%) should be detected."""
        closes = [100, 90]
        lows = [100, 90.0]
        df = _make_df(closes, lows=lows)
        actions = detect_limit_hits(df)
        assert len(actions) == 1
        assert actions[0].action_type == "limit_down"

    def test_no_limit(self):
        """Normal price movement should not trigger."""
        closes = [100, 103, 101, 105]
        df = _make_df(closes)
        actions = detect_limit_hits(df)
        assert len(actions) == 0

    def test_both_limit_up_and_down(self):
        """Multiple limit hits across days."""
        closes = [100, 110, 99]  # day 2: +10%, day 3: -10%
        highs = [100.5, 110.0, 99.5]
        lows = [99.5, 109.5, 99.0]
        df = _make_df(closes, highs=highs, lows=lows)
        actions = detect_limit_hits(df)
        assert any(a.action_type == "limit_up" for a in actions)
        assert any(a.action_type == "limit_down" for a in actions)


class TestDetectPriceGaps:
    def test_large_gap_detected(self):
        """Overnight gap >15% should be detected."""
        closes = [100, 120]  # +20% gap
        df = _make_df(closes)
        actions = detect_price_gaps(df)
        assert len(actions) == 1
        assert actions[0].action_type == "price_gap"
        assert actions[0].gap_pct == pytest.approx(0.20)

    def test_small_gap_ignored(self):
        """Normal overnight movement (<15%) should not trigger."""
        closes = [100, 105, 103, 107]
        df = _make_df(closes)
        actions = detect_price_gaps(df)
        assert len(actions) == 0

    def test_negative_gap(self):
        """Large negative gap should also be detected."""
        closes = [100, 80]  # -20%
        df = _make_df(closes)
        actions = detect_price_gaps(df)
        assert len(actions) == 1
        assert actions[0].gap_pct == pytest.approx(-0.20)


class TestDetectZeroVolumeDays:
    def test_zero_volume_detected(self):
        """Days with zero volume indicate possible halt."""
        df = _make_df([100, 100, 100], volumes=[1e6, 0, 1e6])
        actions = detect_zero_volume_days(df)
        assert len(actions) == 1
        assert actions[0].action_type == "halt"

    def test_no_zero_volume(self):
        """Normal trading days should not trigger."""
        df = _make_df([100, 101], volumes=[1e6, 2e6])
        actions = detect_zero_volume_days(df)
        assert len(actions) == 0

    def test_no_volume_column(self):
        """DataFrame without volume column should return empty."""
        df = pd.DataFrame({"close": [100, 101]}, index=pd.bdate_range("2024-01-02", periods=2))
        actions = detect_zero_volume_days(df)
        assert len(actions) == 0


class TestDetectCorporateActions:
    def test_combines_all_sources(self):
        """Should detect dividends, limits, and gaps together."""
        closes = [100, 110, 112, 95]  # day 2: limit up
        highs = [100.5, 110.0, 112.5, 96]
        lows = [99.5, 109.5, 111.5, 95.0]
        df = _make_df(closes, highs=highs, lows=lows)

        dividends = pd.Series([2.5], index=[df.index[1]])

        report = detect_corporate_actions(
            stock_code="2330", df=df,
            dividends=dividends,
        )
        assert isinstance(report, CorporateActionReport)
        assert report.stock_code == "2330"
        assert report.has_dividends
        assert len(report.dividend_dates) == 1

    def test_empty_df(self):
        """Empty DataFrame should return empty report."""
        df = pd.DataFrame()
        report = detect_corporate_actions("9999", df)
        assert len(report.actions) == 0

    def test_with_splits(self):
        """Splits from yfinance should be included."""
        df = _make_df([100, 101, 102])
        splits = pd.Series([5.0], index=[df.index[1]])  # 1→5 split
        report = detect_corporate_actions("2330", df, splits=splits)
        assert report.has_splits
        split_actions = [a for a in report.actions if a.action_type == "split"]
        assert len(split_actions) == 1
        assert split_actions[0].split_ratio == 5.0

    def test_summary_format(self):
        """Summary dict should have expected keys."""
        df = _make_df([100, 101])
        report = detect_corporate_actions("2330", df)
        summary = report.summary()
        assert "stock_code" in summary
        assert "total_actions" in summary
        assert "splits" in summary
        assert "dividends" in summary
        assert "limit_hits" in summary
        assert "halts" in summary
        assert "actions" in summary


class TestCorporateActionReport:
    def test_properties(self):
        report = CorporateActionReport(
            stock_code="2330",
            actions=[
                CorporateAction(date=pd.Timestamp("2024-06-01"), action_type="dividend"),
                CorporateAction(date=pd.Timestamp("2024-07-01"), action_type="split", split_ratio=5.0),
                CorporateAction(date=pd.Timestamp("2024-08-01"), action_type="limit_up"),
                CorporateAction(date=pd.Timestamp("2024-09-01"), action_type="halt"),
            ],
        )
        assert report.has_splits
        assert report.has_dividends
        assert len(report.split_dates) == 1
        assert len(report.dividend_dates) == 1
        assert len(report.limit_hit_dates) == 1
        assert len(report.halt_dates) == 1

    def test_total_actions(self):
        report = CorporateActionReport(stock_code="1234", actions=[])
        s = report.summary()
        assert s["total_actions"] == 0


class TestAnnotateTradesWithActions:
    def test_trade_overlapping_split(self):
        """Trade holding through a split should generate warning."""
        from backtest.engine import Trade
        trades = [
            Trade(
                date_open=pd.Timestamp("2024-06-01"),
                date_close=pd.Timestamp("2024-06-30"),
                shares=1000, price_open=100, price_close=110,
            ),
        ]
        report = CorporateActionReport(
            stock_code="2330",
            actions=[
                CorporateAction(
                    date=pd.Timestamp("2024-06-15"),
                    action_type="split",
                    details="股票分割 1:5",
                    split_ratio=5.0,
                ),
            ],
        )
        warnings = annotate_trades_with_actions(trades, report)
        assert len(warnings) == 1
        assert "股票分割" in warnings[0]

    def test_trade_overlapping_dividend(self):
        """Trade holding through ex-dividend should generate warning."""
        from backtest.engine import Trade
        trades = [
            Trade(
                date_open=pd.Timestamp("2024-07-01"),
                date_close=pd.Timestamp("2024-08-01"),
            ),
        ]
        report = CorporateActionReport(
            stock_code="2330",
            actions=[
                CorporateAction(
                    date=pd.Timestamp("2024-07-15"),
                    action_type="dividend",
                    details="除息 2.50 元/股",
                ),
            ],
        )
        warnings = annotate_trades_with_actions(trades, report)
        assert len(warnings) == 1
        assert "除息" in warnings[0]

    def test_no_overlap(self):
        """Trade not overlapping any action should produce no warnings."""
        from backtest.engine import Trade
        trades = [
            Trade(
                date_open=pd.Timestamp("2024-01-01"),
                date_close=pd.Timestamp("2024-01-31"),
            ),
        ]
        report = CorporateActionReport(
            stock_code="2330",
            actions=[
                CorporateAction(date=pd.Timestamp("2024-06-15"), action_type="split"),
            ],
        )
        warnings = annotate_trades_with_actions(trades, report)
        assert len(warnings) == 0

    def test_empty_inputs(self):
        """Empty trades or actions should produce no warnings."""
        report = CorporateActionReport(stock_code="2330", actions=[])
        warnings = annotate_trades_with_actions([], report)
        assert warnings == []

"""Tests for TWSE/TPEX data provider (data/twse_provider.py).

Offline tests only — no network requests.
Uses a temporary SQLite database for isolation.
"""

import sqlite3
from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest

# Patch the DB path before importing the module
import tempfile
import os

_test_db = os.path.join(tempfile.gettempdir(), "test_market_data.db")


@pytest.fixture(autouse=True)
def _patch_db(monkeypatch):
    """Use a temporary database for all tests."""
    from pathlib import Path

    monkeypatch.setattr("data.twse_provider._DB_PATH", Path(_test_db))
    # Re-init the DB with the new path
    import data.twse_provider as tp
    tp._init_db()
    yield
    # Cleanup
    try:
        os.unlink(_test_db)
    except FileNotFoundError:
        pass
    try:
        os.unlink(_test_db + "-wal")
    except FileNotFoundError:
        pass
    try:
        os.unlink(_test_db + "-shm")
    except FileNotFoundError:
        pass


class TestDateHelpers:
    def test_to_roc_date(self):
        from data.twse_provider import _to_roc_date
        dt = datetime(2026, 2, 15)
        assert _to_roc_date(dt) == "115/02/15"

    def test_parse_roc_date(self):
        from data.twse_provider import _parse_roc_date
        assert _parse_roc_date("115/02/13") == "2026-02-13"
        assert _parse_roc_date("114/12/31") == "2025-12-31"
        assert _parse_roc_date("bad") == ""

    def test_safe_float(self):
        from data.twse_provider import _safe_float
        assert _safe_float("1,234.56") == 1234.56
        assert _safe_float("-") is None
        assert _safe_float("N/A") is None
        assert _safe_float(None) is None
        assert _safe_float("0") == 0.0

    def test_safe_int(self):
        from data.twse_provider import _safe_int
        assert _safe_int("1,234") == 1234
        assert _safe_int("-") is None


class TestSQLiteLayer:
    def test_init_db_creates_tables(self):
        from data.twse_provider import _get_conn
        with _get_conn() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {t[0] for t in tables}
            assert "price_daily" in table_names
            assert "corporate_actions" in table_names
            assert "taiex_daily" in table_names
            assert "fetch_log" in table_names

    def test_save_and_read_price(self):
        from data.twse_provider import _save_price_rows, get_stock_data_from_db

        rows = [
            {"date": "2026-02-10", "open": 1750, "high": 1765, "low": 1745, "close": 1760, "volume": 30000000},
            {"date": "2026-02-11", "open": 1760, "high": 1780, "low": 1755, "close": 1775, "volume": 28000000},
            {"date": "2026-02-12", "open": 1775, "high": 1790, "low": 1770, "close": 1785, "volume": 32000000},
        ]
        _save_price_rows("2330", rows, "twse")

        df = get_stock_data_from_db("2330", "2026-02-10", "2026-02-12", adjusted=False)
        assert len(df) == 3
        assert df.iloc[0]["close"] == 1760
        assert df.iloc[2]["close"] == 1785
        assert df.index.name == "date"

    def test_upsert_behavior(self):
        from data.twse_provider import _save_price_rows, get_stock_data_from_db

        rows1 = [{"date": "2026-02-10", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000}]
        _save_price_rows("9999", rows1, "twse")

        # Upsert with different close
        rows2 = [{"date": "2026-02-10", "open": 100, "high": 105, "low": 99, "close": 999, "volume": 1000}]
        _save_price_rows("9999", rows2, "twse")

        df = get_stock_data_from_db("9999", "2026-02-10", "2026-02-10", adjusted=False)
        assert len(df) == 1
        assert df.iloc[0]["close"] == 999  # Updated

    def test_empty_read(self):
        from data.twse_provider import get_stock_data_from_db
        df = get_stock_data_from_db("0000", "2026-01-01", "2026-01-31")
        assert df.empty


class TestFetchLog:
    def test_month_tracking(self):
        from data.twse_provider import _month_already_fetched, _log_fetch

        assert not _month_already_fetched("2330", 2026, 2, "twse")
        _log_fetch("2330", 2026, 2, "twse", 20)
        assert _month_already_fetched("2330", 2026, 2, "twse")

    def test_zero_rows_still_logged(self):
        from data.twse_provider import _month_already_fetched, _log_fetch

        _log_fetch("2330", 2026, 1, "twse", 0)
        # Zero rows means "we tried but got nothing" — should NOT count as fetched
        assert not _month_already_fetched("2330", 2026, 1, "twse")


class TestFetchTwseMonth:
    def test_parse_response(self):
        """Test parsing a simulated TWSE STOCK_DAY response."""
        from data.twse_provider import fetch_twse_month

        mock_response = {
            "stat": "OK",
            "date": "11502",
            "title": "115年02月 2330 台積電           各日成交資訊",
            "fields": ["日期", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌價差", "成交筆數"],
            "data": [
                ["115/02/03", "33,342,359", "58,467,099,660", "1,750.00", "1,765.00", "1,745.00", "1,765.00", "-10.00", "227,693"],
                ["115/02/04", "30,386,718", "54,587,495,232", "1,810.00", "1,810.00", "1,785.00", "1,800.00", "+35.00", "63,370"],
            ],
        }

        with patch("data.twse_provider._twse_get", return_value=mock_response):
            rows = fetch_twse_month("2330", 2026, 2)

        assert len(rows) == 2
        assert rows[0]["date"] == "2026-02-03"
        assert rows[0]["open"] == 1750.0
        assert rows[0]["close"] == 1765.0
        assert rows[0]["volume"] == 33342359
        assert rows[1]["close"] == 1800.0

    def test_no_data(self):
        from data.twse_provider import fetch_twse_month

        with patch("data.twse_provider._twse_get", return_value={"stat": "OK", "data": None}):
            rows = fetch_twse_month("2330", 2026, 1)
        assert rows == []

    def test_api_failure(self):
        from data.twse_provider import fetch_twse_month

        with patch("data.twse_provider._twse_get", return_value=None):
            rows = fetch_twse_month("2330", 2026, 1)
        assert rows == []


class TestFetchTpexMonth:
    def test_parse_response(self):
        """Test parsing new TPEX tradingStock API response (2024+ format)."""
        from data.twse_provider import fetch_tpex_month

        # New format: tables[0].data, volume in 張 (lots), turnover in 仟元
        mock_response = {
            "stat": "ok",
            "tables": [{
                "title": "個股日成交資訊",
                "subtitle": "6510 精測 115年02月",
                "date": "20260201",
                "totalCount": 2,
                "fields": ["日 期", "成交張數", "成交仟元", "開盤", "最高", "最低", "收盤", "漲跌", "筆數"],
                "data": [
                    ["115/02/03", "836", "2,834,391", "55.00", "56.50", "54.80", "56.00", "+1.20", "890"],
                    ["115/02/04", "1,200", "3,456,789", "56.00", "57.00", "55.50", "56.80", "+0.80", "1,200"],
                ],
            }],
            "date": "20260201",
            "code": "6510",
            "name": "精測",
        }

        with patch("data.twse_provider._tpex_get", return_value=mock_response):
            rows = fetch_tpex_month("6510", 2026, 2)

        assert len(rows) == 2
        assert rows[0]["date"] == "2026-02-03"
        assert rows[0]["close"] == 56.0
        assert rows[0]["volume"] == 836000  # 836 lots × 1000 = 836,000 shares
        assert rows[1]["volume"] == 1200000  # 1,200 lots × 1000

    def test_stat_not_ok(self):
        from data.twse_provider import fetch_tpex_month

        with patch("data.twse_provider._tpex_get", return_value={"stat": "error"}):
            rows = fetch_tpex_month("6510", 2026, 1)
        assert rows == []

    def test_empty_tables(self):
        from data.twse_provider import fetch_tpex_month

        with patch("data.twse_provider._tpex_get", return_value={"stat": "ok", "tables": [{"data": []}]}):
            rows = fetch_tpex_month("6510", 2026, 1)
        assert rows == []


class TestCorporateActions:
    def test_save_and_read(self):
        from data.twse_provider import save_corporate_actions, _get_conn

        actions = [
            {"ticker": "2330", "ex_date": "2025-07-15", "cash_dividend": 14.0, "stock_dividend": 0},
            {"ticker": "2330", "ex_date": "2024-07-16", "cash_dividend": 13.5, "stock_dividend": 0},
        ]
        save_corporate_actions(actions)

        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM corporate_actions WHERE ticker='2330' ORDER BY ex_date"
            ).fetchall()
        assert len(rows) == 2
        assert rows[0][2] == 13.5  # cash_dividend for 2024
        assert rows[1][2] == 14.0  # cash_dividend for 2025


class TestAdjustmentFactors:
    def test_forward_adjustment(self):
        """Test that adjustment factors are computed correctly."""
        from data.twse_provider import (
            _save_price_rows, save_corporate_actions,
            compute_adjustment_factors, get_stock_data_from_db,
        )

        # Simulate: stock at 1000, then ex-dividend of 10 TWD
        prices = [
            {"date": "2025-07-14", "open": 1000, "high": 1005, "low": 995, "close": 1000, "volume": 10000},
            {"date": "2025-07-15", "open": 990, "high": 995, "low": 985, "close": 990, "volume": 12000},
            {"date": "2025-07-16", "open": 992, "high": 998, "low": 988, "close": 995, "volume": 11000},
        ]
        _save_price_rows("TEST1", prices, "twse")

        # Ex-dividend on 2025-07-15: 10 TWD cash
        actions = [{"ticker": "TEST1", "ex_date": "2025-07-15", "cash_dividend": 10.0, "stock_dividend": 0}]
        save_corporate_actions(actions)

        compute_adjustment_factors("TEST1")

        # Read adjusted data
        df_adj = get_stock_data_from_db("TEST1", "2025-07-14", "2025-07-16", adjusted=True)
        df_raw = get_stock_data_from_db("TEST1", "2025-07-14", "2025-07-16", adjusted=False)

        # Pre-dividend close should be adjusted downward
        # Factor = (1000 - 10) / 1000 = 0.99
        # Adjusted pre-div close = 1000 * 0.99 = 990
        assert df_raw.iloc[0]["close"] == 1000  # Raw unchanged
        assert abs(df_adj.iloc[0]["close"] - 990) < 1  # Adjusted ≈ 990

        # Post-dividend prices should be unadjusted (factor = 1.0)
        assert df_adj.iloc[1]["close"] == 990  # Already post-div
        assert df_adj.iloc[2]["close"] == 995

    def test_no_actions_factor_one(self):
        from data.twse_provider import (
            _save_price_rows, compute_adjustment_factors, _get_conn,
        )

        prices = [
            {"date": "2025-01-10", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 5000},
        ]
        _save_price_rows("NOACT", prices, "twse")
        compute_adjustment_factors("NOACT")

        with _get_conn() as conn:
            factor = conn.execute(
                "SELECT adj_factor FROM price_daily WHERE ticker='NOACT'"
            ).fetchone()[0]
        assert factor == 1.0


class TestTaiex:
    def test_parse_response(self):
        from data.twse_provider import fetch_taiex_month

        mock_response = {
            "stat": "OK",
            "data": [
                ["115/02/03", "22,500.00", "22,650.00", "22,400.00", "22,600.00"],
                ["115/02/04", "22,600.00", "22,800.00", "22,550.00", "22,750.00"],
            ],
        }

        with patch("data.twse_provider._twse_get", return_value=mock_response):
            rows = fetch_taiex_month(2026, 2)

        assert len(rows) == 2
        assert rows[0]["close"] == 22600.0
        assert rows[1]["open"] == 22600.0

    def test_save_and_read_taiex(self):
        from data.twse_provider import _get_conn, get_taiex_from_db

        with _get_conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO taiex_daily (date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    ("2026-02-10", 22500, 22650, 22400, 22600, 0),
                    ("2026-02-11", 22600, 22800, 22550, 22750, 0),
                ],
            )

        df = get_taiex_from_db("2026-02-10", "2026-02-11")
        assert len(df) == 2
        assert df.iloc[0]["close"] == 22600


class TestDbStats:
    def test_empty_db(self):
        from data.twse_provider import get_db_stats
        stats = get_db_stats()
        assert stats["price_rows"] == 0
        assert stats["tickers"] == 0

    def test_with_data(self):
        from data.twse_provider import _save_price_rows, get_db_stats

        rows = [
            {"date": "2026-02-10", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 5000},
            {"date": "2026-02-11", "open": 103, "high": 108, "low": 102, "close": 107, "volume": 6000},
        ]
        _save_price_rows("2330", rows, "twse")
        _save_price_rows("2317", rows[:1], "twse")

        stats = get_db_stats()
        assert stats["price_rows"] == 3
        assert stats["tickers"] == 2


class TestSplitDetector:
    """Tests for R72 auto stock split detection."""

    def test_detect_forward_split(self):
        """Detect a 4:1 forward split (price drops ~75%)."""
        from data.twse_provider import _save_price_rows, detect_splits_from_prices

        # Normal prices, then a 4:1 split on 2025-06-11
        prices = [
            {"date": "2025-06-09", "open": 185, "high": 190, "low": 184, "close": 188, "volume": 5000000},
            {"date": "2025-06-10", "open": 186, "high": 189, "low": 185, "close": 188.65, "volume": 4800000},
            # Split happens: 188.65 → ~47.16
            {"date": "2025-06-11", "open": 47, "high": 48, "low": 46.5, "close": 47.57, "volume": 20000000},
            {"date": "2025-06-12", "open": 47.5, "high": 48.5, "low": 47, "close": 48, "volume": 18000000},
        ]
        _save_price_rows("0050", prices, "twse")

        detected = detect_splits_from_prices("0050")
        assert len(detected) == 1
        assert detected[0]["ex_date"] == "2025-06-11"
        assert detected[0]["ratio"] == 4
        assert detected[0]["stock_dividend"] == 30.0  # (4-1)*10
        assert detected[0]["source"] == "auto_detect"

    def test_no_split_normal_prices(self):
        """Normal price movements should not trigger detection."""
        from data.twse_provider import _save_price_rows, detect_splits_from_prices

        prices = [
            {"date": "2025-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 5000},
            {"date": "2025-01-03", "open": 103, "high": 108, "low": 101, "close": 106, "volume": 6000},
            {"date": "2025-01-06", "open": 106, "high": 110, "low": 104, "close": 108, "volume": 5500},
        ]
        _save_price_rows("NORM", prices, "twse")

        detected = detect_splits_from_prices("NORM")
        assert len(detected) == 0

    def test_skip_if_corporate_action_exists(self):
        """Don't flag gaps that already have a corporate_action entry."""
        from data.twse_provider import (
            _save_price_rows, save_corporate_actions, detect_splits_from_prices,
        )

        prices = [
            {"date": "2025-06-10", "open": 186, "high": 189, "low": 185, "close": 188, "volume": 4800000},
            {"date": "2025-06-11", "open": 47, "high": 48, "low": 46.5, "close": 47, "volume": 20000000},
        ]
        _save_price_rows("KNOWN", prices, "twse")

        # Insert the known corporate action
        save_corporate_actions([{
            "ticker": "KNOWN", "ex_date": "2025-06-11",
            "cash_dividend": 0, "stock_dividend": 30,
        }])

        detected = detect_splits_from_prices("KNOWN")
        assert len(detected) == 0  # Already explained

    def test_detect_2_to_1_split(self):
        """Detect a 2:1 split (price drops ~50%)."""
        from data.twse_provider import _save_price_rows, detect_splits_from_prices

        prices = [
            {"date": "2025-03-14", "open": 500, "high": 510, "low": 495, "close": 505, "volume": 1000000},
            {"date": "2025-03-17", "open": 250, "high": 258, "low": 248, "close": 255, "volume": 3000000},
        ]
        _save_price_rows("SPLIT2", prices, "twse")

        detected = detect_splits_from_prices("SPLIT2")
        assert len(detected) == 1
        assert detected[0]["ratio"] == 2
        assert detected[0]["stock_dividend"] == 10.0  # (2-1)*10

    def test_auto_fix_splits(self):
        """auto_fix_splits should detect, insert, and recompute."""
        from data.twse_provider import (
            _save_price_rows, auto_fix_splits, _get_conn,
            get_stock_data_from_db,
        )

        # Simulate 4:1 split
        prices = [
            {"date": "2025-06-09", "open": 185, "high": 190, "low": 184, "close": 188, "volume": 5000000},
            {"date": "2025-06-10", "open": 186, "high": 189, "low": 185, "close": 188, "volume": 4800000},
            {"date": "2025-06-11", "open": 47, "high": 48, "low": 46.5, "close": 47, "volume": 20000000},
            {"date": "2025-06-12", "open": 47.5, "high": 48.5, "low": 47, "close": 48, "volume": 18000000},
        ]
        _save_price_rows("AUTOFIX", prices, "twse")

        fixed = auto_fix_splits("AUTOFIX")
        assert fixed == 1

        # Check corporate_actions was inserted
        with _get_conn() as conn:
            actions = conn.execute(
                "SELECT stock_dividend, source FROM corporate_actions WHERE ticker='AUTOFIX'"
            ).fetchall()
        assert len(actions) == 1
        assert actions[0][0] == 30.0  # stock_dividend for 4:1
        assert actions[0][1] == "auto_detect"

        # Check adjustment factors were recomputed
        df_adj = get_stock_data_from_db("AUTOFIX", "2025-06-09", "2025-06-12", adjusted=True)
        # Pre-split prices should be adjusted: 188 * 0.25 = 47
        assert abs(df_adj.iloc[0]["close"] - 47) < 1
        # Post-split prices should be unchanged
        assert abs(df_adj.iloc[2]["close"] - 47) < 1

    def test_auto_fix_no_splits(self):
        """auto_fix_splits returns 0 when no splits detected."""
        from data.twse_provider import _save_price_rows, auto_fix_splits

        prices = [
            {"date": "2025-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 5000},
            {"date": "2025-01-03", "open": 103, "high": 106, "low": 102, "close": 105, "volume": 6000},
        ]
        _save_price_rows("NOSPLIT", prices, "twse")

        fixed = auto_fix_splits("NOSPLIT")
        assert fixed == 0

    def test_empty_db(self):
        """No crash on empty data."""
        from data.twse_provider import detect_splits_from_prices
        detected = detect_splits_from_prices("EMPTY")
        assert detected == []

    def test_limit_down_not_detected_as_split(self):
        """A ~10% limit-down should NOT trigger split detection (below 35% threshold)."""
        from data.twse_provider import _save_price_rows, detect_splits_from_prices

        prices = [
            {"date": "2025-01-02", "open": 100, "high": 100, "low": 90, "close": 90, "volume": 10000},
            {"date": "2025-01-03", "open": 90, "high": 91, "low": 81, "close": 81, "volume": 15000},  # -10%
        ]
        _save_price_rows("LIMIT", prices, "twse")

        detected = detect_splits_from_prices("LIMIT")
        assert len(detected) == 0


class TestHistoryBackfiller:
    def test_backfiller_with_mock(self):
        from data.twse_provider import HistoryBackfiller

        mock_data = {
            "data": [
                ["115/02/03", "1,000", "100,000", "50.00", "51.00", "49.00", "50.50", "+0.50", "100"],
            ],
        }

        with patch("data.twse_provider._twse_get", return_value=mock_data):
            bf = HistoryBackfiller(delay_range=(0, 0.01))
            bf.add_stocks(["9999"])
            results = bf.run(months_back=1, with_dividends=False)

        assert "9999" in results
        assert results["9999"] >= 0


class TestSyncStock:
    def test_auto_detect_source(self):
        """Test that sync_stock tries TWSE first, then TPEX."""
        from data.twse_provider import sync_stock

        twse_data = {
            "data": [
                ["115/02/03", "1,000", "100,000", "50.00", "51.00", "49.00", "50.50", "+0.50", "100"],
            ],
        }

        with patch("data.twse_provider._twse_get", return_value=twse_data):
            with patch("data.twse_provider._tpex_get", return_value=None):
                count = sync_stock("2330", months_back=1)

        assert count > 0

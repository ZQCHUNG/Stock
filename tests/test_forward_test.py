"""Tests for R59 forward testing engine."""

import os
import tempfile
from pathlib import Path

import pytest

# Override DB path for testing
_test_db = None


def setup_module():
    """Use temp DB for all tests."""
    global _test_db
    _test_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    _test_db.close()
    import backtest.forward_test as ft
    ft._DB_PATH = Path(_test_db.name)


def teardown_module():
    """Clean up temp DB."""
    if _test_db and os.path.exists(_test_db.name):
        os.unlink(_test_db.name)


class TestForwardTestDB:
    def test_db_init(self):
        """Database should initialize tables."""
        from backtest.forward_test import get_db
        with get_db() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [t["name"] for t in tables]
            assert "forward_signals" in table_names
            assert "forward_positions" in table_names


class TestForwardSignals:
    def test_insert_signal(self):
        """Should insert and retrieve a signal."""
        from backtest.forward_test import get_db, ForwardSignal
        with get_db() as conn:
            conn.execute(
                """INSERT INTO forward_signals
                (scan_date, stock_code, signal_type, signal_price, confidence, status)
                VALUES (?, ?, ?, ?, ?, ?)""",
                ("2024-06-01", "2330", "BUY", 580.0, 0.85, "pending"),
            )
            row = conn.execute(
                "SELECT * FROM forward_signals WHERE stock_code='2330' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            assert row is not None
            assert row["stock_code"] == "2330"
            assert row["signal_price"] == 580.0
            assert row["status"] == "pending"


class TestOpenVirtualPosition:
    def test_open_position(self):
        """Should create a position from a signal."""
        from backtest.forward_test import get_db, open_virtual_position

        # Insert a test signal
        with get_db() as conn:
            cursor = conn.execute(
                """INSERT INTO forward_signals
                (scan_date, stock_code, signal_type, signal_price, confidence,
                 volume_lots, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("2024-06-01", "2330", "BUY", 100.0, 0.8, 5000, "pending"),
            )
            signal_id = cursor.lastrowid

        pos = open_virtual_position(signal_id, capital=500_000)
        assert pos is not None
        assert pos.stock_code == "2330"
        assert pos.shares > 0
        assert pos.open_price > 100.0  # slippage added
        assert pos.tp_price > pos.open_price
        assert pos.sl_price < pos.open_price

        # Signal should be marked as opened
        with get_db() as conn:
            sig = conn.execute(
                "SELECT status FROM forward_signals WHERE id=?",
                (signal_id,),
            ).fetchone()
            assert sig["status"] == "opened"

    def test_open_position_nonexistent_signal(self):
        """Non-existent signal should return None."""
        from backtest.forward_test import open_virtual_position
        pos = open_virtual_position(99999)
        assert pos is None

    def test_position_size_rounds_to_lots(self):
        """Position size should be rounded to 1000-share lots."""
        from backtest.forward_test import get_db, open_virtual_position
        with get_db() as conn:
            cursor = conn.execute(
                """INSERT INTO forward_signals
                (scan_date, stock_code, signal_price, volume_lots, status)
                VALUES (?, ?, ?, ?, ?)""",
                ("2024-06-02", "2317", 50.0, 10000, "pending"),
            )
            sid = cursor.lastrowid
        pos = open_virtual_position(sid, capital=100_000)
        assert pos is not None
        assert pos.shares % 1000 == 0


class TestGetSummary:
    def test_summary_structure(self):
        """Summary should have all expected fields."""
        from backtest.forward_test import get_summary
        s = get_summary()
        assert hasattr(s, "total_signals")
        assert hasattr(s, "win_rate")
        assert hasattr(s, "total_pnl")
        assert hasattr(s, "open_positions")
        assert hasattr(s, "closed_positions")

    def test_summary_counts(self):
        """Summary should reflect DB state."""
        from backtest.forward_test import get_summary
        s = get_summary()
        # We've inserted signals in previous tests
        assert s.total_signals >= 2
        assert s.signals_opened >= 1


class TestGetSignalsAndPositions:
    def test_get_signals(self):
        """Should return list of dicts."""
        from backtest.forward_test import get_signals
        signals = get_signals(limit=10)
        assert isinstance(signals, list)
        if signals:
            assert "stock_code" in signals[0]

    def test_get_signals_filtered(self):
        """Should filter by status."""
        from backtest.forward_test import get_signals
        opened = get_signals(status="opened")
        for s in opened:
            assert s["status"] == "opened"

    def test_get_positions(self):
        """Should return list of dicts."""
        from backtest.forward_test import get_positions
        positions = get_positions(limit=10)
        assert isinstance(positions, list)


class TestCompareWithBacktest:
    def test_compare_structure(self):
        """Comparison result should have expected structure."""
        from backtest.forward_test import compare_with_backtest
        result = compare_with_backtest()
        assert "forward" in result
        assert "comparison" in result
        assert "total_trades" in result["forward"]
        assert "sufficient_data" in result["comparison"]


class TestForwardTestAPI:
    """Test API endpoints (via TestClient)."""

    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient
        from backend.app import app
        return TestClient(app)

    def test_summary_endpoint(self, client):
        resp = client.get("/api/backtest/forward-test/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_signals" in data

    def test_signals_endpoint(self, client):
        resp = client.get("/api/backtest/forward-test/signals")
        assert resp.status_code == 200

    def test_positions_endpoint(self, client):
        resp = client.get("/api/backtest/forward-test/positions")
        assert resp.status_code == 200

    def test_compare_endpoint(self, client):
        resp = client.get("/api/backtest/forward-test/compare")
        assert resp.status_code == 200
        data = resp.json()
        assert "forward" in data

    def test_update_endpoint(self, client):
        resp = client.post("/api/backtest/forward-test/update")
        assert resp.status_code == 200
        data = resp.json()
        assert "actions" in data

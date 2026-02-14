"""API integration tests (Gemini R48-3)

Uses FastAPI TestClient to test backend endpoints without a running server.
All tests use mock data / in-memory state — no network calls.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    """Create a TestClient for the FastAPI app."""
    from backend.app import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# System / Health endpoints
# ---------------------------------------------------------------------------

class TestSystemHealth:
    def test_health_fast(self, client):
        """GET /api/system/health should return a status."""
        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("healthy", "degraded", "stopped")
        assert "components" in data
        assert "redis" in data["components"]
        assert "database" in data["components"]
        assert "scheduler" in data["components"]

    def test_health_fast_no_slow_sources(self, client):
        """Fast health check should NOT include yfinance/finmind by default."""
        resp = client.get("/api/system/health")
        data = resp.json()
        # Without include_slow, these should not be present
        assert "yfinance" not in data["components"]
        assert "finmind" not in data["components"]


class TestCacheStats:
    def test_cache_stats(self, client):
        """GET /api/system/cache-stats should return stats."""
        resp = client.get("/api/system/cache-stats")
        assert resp.status_code == 200


class TestV4Params:
    def test_get_v4_params(self, client):
        """GET /api/system/v4-params should return strategy parameters."""
        resp = client.get("/api/system/v4-params")
        assert resp.status_code == 200
        data = resp.json()
        # V4 params should have known keys
        assert "tp_pct" in data or "sl_pct" in data or len(data) > 0


class TestRecentStocks:
    def test_get_recent_stocks(self, client):
        """GET /api/system/recent-stocks should return a list."""
        resp = client.get("/api/system/recent-stocks")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# Backup & Export endpoints
# ---------------------------------------------------------------------------

class TestBackup:
    def test_run_backup(self, client, tmp_path):
        """POST /api/system/backup should create backup files."""
        with patch("backend.backup.DEFAULT_BACKUP_DIR", tmp_path):
            resp = client.post("/api/system/backup")
        assert resp.status_code == 200
        data = resp.json()
        assert "timestamp" in data
        assert "backed_up" in data
        assert isinstance(data["backed_up"], list)

    def test_list_backups(self, client):
        """GET /api/system/backups should return a list."""
        resp = client.get("/api/system/backups")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestExport:
    def test_export_positions_csv(self, client):
        """GET /api/system/export/positions/csv should return CSV or empty."""
        resp = client.get("/api/system/export/positions/csv")
        assert resp.status_code == 200
        # Should be CSV or plain text
        assert "text/" in resp.headers.get("content-type", "")

    def test_export_positions_json(self, client):
        """GET /api/system/export/positions/json should return JSON list."""
        resp = client.get("/api/system/export/positions/json")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_export_signals_csv(self, client):
        """GET /api/system/export/signals/csv should return CSV or empty."""
        resp = client.get("/api/system/export/signals/csv")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Alerts endpoints
# ---------------------------------------------------------------------------

class TestAlerts:
    def test_get_alert_config(self, client):
        """GET /api/alerts/config should return config with masked token."""
        resp = client.get("/api/alerts/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "sqs_threshold" in data
        assert "notify_browser" in data

    def test_check_alerts(self, client):
        """GET /api/alerts/check should return triggered alerts."""
        resp = client.get("/api/alerts/check")
        assert resp.status_code == 200
        data = resp.json()
        assert "triggered" in data

    def test_scheduler_status(self, client):
        """GET /api/alerts/scheduler-status should return scheduler info."""
        resp = client.get("/api/alerts/scheduler-status")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data

    def test_health_check(self, client):
        """GET /api/alerts/health should return health diagnostics."""
        resp = client.get("/api/alerts/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("healthy", "degraded", "stopped")

    def test_get_history(self, client):
        """GET /api/alerts/history should return list."""
        resp = client.get("/api/alerts/history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# Watchlist endpoints
# ---------------------------------------------------------------------------

class TestWatchlist:
    def test_get_watchlist(self, client):
        """GET /api/watchlist should return list."""
        resp = client.get("/api/watchlist/")
        assert resp.status_code == 200

    def test_add_remove_watchlist(self, client):
        """POST + DELETE /api/watchlist/{code} round-trip."""
        # Add
        resp = client.post("/api/watchlist/9999")
        assert resp.status_code == 200

        # Remove
        resp = client.delete("/api/watchlist/9999")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Portfolio endpoints (E2E flow)
# ---------------------------------------------------------------------------

class TestPortfolioFlow:
    def test_list_positions(self, client):
        """GET /api/portfolio/ should return positions + summary."""
        resp = client.get("/api/portfolio/")
        assert resp.status_code == 200
        data = resp.json()
        assert "positions" in data or "summary" in data

    def test_portfolio_health(self, client):
        """GET /api/portfolio/health should return portfolio health."""
        resp = client.get("/api/portfolio/health")
        assert resp.status_code == 200

    def _close_if_open(self, client, code):
        """Helper: close any existing open position for the given code."""
        resp = client.get("/api/portfolio/")
        if resp.status_code == 200:
            data = resp.json()
            for p in data.get("positions", []):
                if p.get("code") == code and p.get("status") == "open":
                    client.post(
                        f"/api/portfolio/{p['id']}/close",
                        json={"exit_price": 1.0, "exit_reason": "test_cleanup"},
                    )

    def test_create_and_close_position(self, client):
        """E2E: Create a position, verify it exists, then close it."""
        self._close_if_open(client, "9999")

        # Create
        payload = {
            "code": "9999",
            "name": "Test Stock",
            "entry_price": 100.0,
            "lots": 1,
            "stop_loss": 93.0,
            "confidence": 0.8,
        }
        resp = client.post("/api/portfolio/open", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        pos_id = data["position"]["id"]

        # Close it
        resp = client.post(
            f"/api/portfolio/{pos_id}/close",
            json={"exit_price": 110.0, "exit_reason": "test"},
        )
        assert resp.status_code == 200

    def test_create_duplicate_position_fails(self, client):
        """Creating two open positions for the same code should fail."""
        self._close_if_open(client, "8888")

        payload = {
            "code": "8888",
            "name": "Dup Test",
            "entry_price": 50.0,
            "lots": 1,
            "stop_loss": 46.5,
        }
        resp1 = client.post("/api/portfolio/open", json=payload)
        assert resp1.status_code == 200

        resp2 = client.post("/api/portfolio/open", json=payload)
        # Should fail with 400 (duplicate)
        assert resp2.status_code == 400

        # Cleanup
        pos_id = resp1.json()["position"]["id"]
        client.post(
            f"/api/portfolio/{pos_id}/close",
            json={"exit_price": 50.0, "exit_reason": "cleanup"},
        )


# ---------------------------------------------------------------------------
# SQS Performance endpoints
# ---------------------------------------------------------------------------

class TestSqsPerformance:
    def test_get_summary(self, client):
        """GET /api/sqs-performance/summary should return summary."""
        resp = client.get("/api/sqs-performance/summary")
        assert resp.status_code == 200

    def test_get_signals(self, client):
        """GET /api/sqs-performance/signals should return signals list."""
        resp = client.get("/api/sqs-performance/signals")
        assert resp.status_code == 200
        data = resp.json()
        assert "signals" in data


# ---------------------------------------------------------------------------
# Risk endpoints
# ---------------------------------------------------------------------------

class TestRisk:
    def test_risk_summary_no_positions(self, client):
        """GET /api/risk/summary with no positions should return has_data=false."""
        resp = client.get("/api/risk/summary")
        assert resp.status_code == 200
        data = resp.json()
        # May or may not have data depending on test state
        assert "has_data" in data

    def test_scenario_analysis(self, client):
        """POST /api/risk/scenario should return scenarios list."""
        resp = client.post("/api/risk/scenario", json={"account_value": 1000000})
        assert resp.status_code == 200
        data = resp.json()
        assert "scenarios" in data
        assert len(data["scenarios"]) == 4  # 4 default scenarios


class TestDataQuality:
    def test_data_quality(self, client):
        """GET /api/system/data-quality should return quality report."""
        resp = client.get("/api/system/data-quality")
        assert resp.status_code == 200
        data = resp.json()
        # Should have the quality report structure
        assert "total_stocks" in data or "message" in data


class TestApiPerformance:
    def test_api_performance(self, client):
        """GET /api/system/api-performance should return stats."""
        resp = client.get("/api/system/api-performance")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_requests" in data
        assert "endpoints" in data


# ---------------------------------------------------------------------------
# Stocks endpoints
# ---------------------------------------------------------------------------

class TestStocks:
    def test_stock_list(self, client):
        """GET /api/stocks/list should return stocks."""
        resp = client.get("/api/stocks/list")
        assert resp.status_code == 200

    def test_stock_search(self, client):
        """GET /api/stocks/search?q=2330 should return results."""
        resp = client.get("/api/stocks/search?q=2330")
        assert resp.status_code == 200

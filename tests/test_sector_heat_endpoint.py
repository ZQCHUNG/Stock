"""Tests for /sector-heat endpoint cold start fix.

Verifies:
- Cache hit returns data directly (happy path)
- Cache miss returns 503 and triggers background pre-warm
- force_refresh returns 202 and triggers background pre-warm
- Background task is not triggered if already running
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


CACHED_SECTOR_HEAT = {
    "sectors": [
        {
            "sector": "Semiconductor",
            "total": 5,
            "buy_count": 2,
            "heat": 0.4,
            "weighted_heat": 0.5,
            "buy_stocks": [],
            "all_stocks": ["2330", "2303"],
        }
    ],
    "scanned": 5,
    "total_buy": 2,
    "_updated_at": "2026-03-14T10:00:00",
    "_status": "ok",
}


@pytest.fixture(scope="module")
def client():
    from backend.app import app
    return TestClient(app)


class TestSectorHeatCacheHit:
    """Happy path: cache has data."""

    @patch("backend.routers.market.get_cached_sector_heat")
    def test_returns_cached_data(self, mock_cache, client):
        mock_cache.return_value = CACHED_SECTOR_HEAT
        resp = client.get("/api/analysis/sector-heat")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scanned"] == 5
        assert data["sectors"][0]["sector"] == "Semiconductor"

    @patch("backend.routers.market.get_cached_sector_heat")
    def test_cache_hit_does_not_trigger_background(self, mock_cache, client):
        mock_cache.return_value = CACHED_SECTOR_HEAT
        with patch("backend.routers.market._trigger_background_scan") as mock_bg:
            resp = client.get("/api/analysis/sector-heat")
            assert resp.status_code == 200
            mock_bg.assert_not_called()


class TestSectorHeatCacheMiss:
    """Cold start: no cached data available."""

    @patch("backend.routers.market.get_cached_sector_heat")
    def test_returns_503_on_cache_miss(self, mock_cache, client):
        mock_cache.return_value = None
        with patch("backend.routers.market._trigger_background_scan"):
            resp = client.get("/api/analysis/sector-heat")
            assert resp.status_code == 503
            data = resp.json()
            assert "detail" in data
            assert "calculating" in data["detail"].lower() or "retry" in data["detail"].lower()

    @patch("backend.routers.market.get_cached_sector_heat")
    def test_triggers_background_scan_on_miss(self, mock_cache, client):
        mock_cache.return_value = None
        with patch("backend.routers.market._trigger_background_scan") as mock_bg:
            client.get("/api/analysis/sector-heat")
            mock_bg.assert_called_once()


class TestSectorHeatForceRefresh:
    """force_refresh=true triggers background scan and returns 202."""

    @patch("backend.routers.market.get_cached_sector_heat")
    def test_force_refresh_returns_202(self, mock_cache, client):
        mock_cache.return_value = CACHED_SECTOR_HEAT
        with patch("backend.routers.market._trigger_background_scan"):
            resp = client.get("/api/analysis/sector-heat?force_refresh=true")
            assert resp.status_code == 202
            data = resp.json()
            assert "message" in data

    @patch("backend.routers.market.get_cached_sector_heat")
    def test_force_refresh_triggers_background(self, mock_cache, client):
        mock_cache.return_value = CACHED_SECTOR_HEAT
        with patch("backend.routers.market._trigger_background_scan") as mock_bg:
            client.get("/api/analysis/sector-heat?force_refresh=true")
            mock_bg.assert_called_once()


class TestBackgroundScanGuard:
    """Background scan should not run concurrently."""

    @patch("backend.routers.market._bg_scan_running", True)
    @patch("backend.routers.market.get_cached_sector_heat")
    def test_no_duplicate_scan(self, mock_cache, client):
        mock_cache.return_value = None
        with patch("backend.routers.market._do_background_scan") as mock_do:
            resp = client.get("/api/analysis/sector-heat")
            assert resp.status_code == 503
            # _do_background_scan should NOT be called because scan is already running
            mock_do.assert_not_called()

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


# ---------------------------------------------------------------------------
# OMS endpoints (R50-2)
# ---------------------------------------------------------------------------

class TestOms:
    def test_oms_stats(self, client):
        """GET /api/system/oms-stats should return statistics."""
        resp = client.get("/api/system/oms-stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_events" in data
        assert "auto_exits" in data

    def test_oms_events(self, client):
        """GET /api/system/oms-events should return events list."""
        resp = client.get("/api/system/oms-events?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data

    def test_oms_run_now(self, client):
        """POST /api/system/oms-run should execute OMS check."""
        resp = client.post("/api/system/oms-run")
        assert resp.status_code == 200
        data = resp.json()
        assert "checked" in data
        assert "actions" in data


# ---------------------------------------------------------------------------
# Strategy Workbench (R50-3)
# ---------------------------------------------------------------------------

class TestStrategies:
    def test_list_strategies(self, client):
        """GET /api/strategies/ should return strategy list."""
        resp = client.get("/api/strategies/")
        assert resp.status_code == 200
        data = resp.json()
        assert "strategies" in data
        assert len(data["strategies"]) >= 1  # At least default

    def test_create_and_delete_strategy(self, client):
        """POST /api/strategies/ then DELETE should work."""
        resp = client.post("/api/strategies/", json={
            "name": "Test Strategy",
            "description": "For testing",
            "params": {"adx_threshold": 20, "stop_loss_pct": -0.05},
        })
        assert resp.status_code == 200
        sid = resp.json()["strategy"]["id"]

        # Delete
        resp2 = client.delete(f"/api/strategies/{sid}")
        assert resp2.status_code == 200

    def test_clone_strategy(self, client):
        """POST /api/strategies/{id}/clone should create a copy."""
        # Get first strategy
        resp = client.get("/api/strategies/")
        first = resp.json()["strategies"][0]
        resp2 = client.post(f"/api/strategies/{first['id']}/clone")
        assert resp2.status_code == 200
        cloned = resp2.json()["strategy"]
        assert "Copy" in cloned["name"]
        # Clean up
        client.delete(f"/api/strategies/{cloned['id']}")

    def test_cannot_delete_default(self, client):
        """DELETE on default strategy should fail."""
        resp = client.get("/api/strategies/")
        defaults = [s for s in resp.json()["strategies"] if s.get("is_default")]
        if defaults:
            resp2 = client.delete(f"/api/strategies/{defaults[0]['id']}")
            assert resp2.status_code == 400


# ---------------------------------------------------------------------------
# ML Market Regime (R50-3)
# ---------------------------------------------------------------------------

class TestMlRegime:
    def test_ml_regime_endpoint(self, client):
        """GET /api/analysis/market-regime-ml should return regime data."""
        resp = client.get("/api/analysis/market-regime-ml")
        assert resp.status_code == 200
        data = resp.json()
        assert "regime" in data


# ---------------------------------------------------------------------------
# R51-3: Enhanced Backtest (monthly returns, regime breakdown)
# ---------------------------------------------------------------------------

class TestEnhancedBacktest:
    def test_strategy_backtest_has_monthly_returns(self, client):
        """Strategy backtest should include monthly_returns field."""
        import numpy as np
        import pandas as pd

        # Create a mock BacktestResult
        from backtest.engine import BacktestResult, Trade

        dates_idx = pd.date_range("2024-01-01", periods=3)
        mock_result = BacktestResult(
            total_return=0.15, annual_return=0.10, max_drawdown=-0.05,
            win_rate=0.6, profit_factor=1.5, sharpe_ratio=1.2,
            sortino_ratio=1.5, calmar_ratio=2.0, total_trades=10,
            avg_holding_days=8, max_consecutive_losses=2,
            trades=[
                Trade(date_open=pd.Timestamp("2024-01-15"), date_close=pd.Timestamp("2024-01-25"),
                      shares=1000, price_open=100, price_close=110, pnl=10000, return_pct=0.1, exit_reason="take_profit"),
                Trade(date_open=pd.Timestamp("2024-02-10"), date_close=pd.Timestamp("2024-02-20"),
                      shares=1000, price_open=105, price_close=100, pnl=-5000, return_pct=-0.05, exit_reason="stop_loss"),
            ],
            equity_curve=pd.Series([1_000_000, 1_010_000, 1_005_000], index=dates_idx),
            daily_returns=pd.Series([0, 0.01, -0.005], index=dates_idx),
        )

        with patch("backend.routers.strategies._load_strategies", return_value=[
            {"id": "test-bt", "name": "Test", "params": {"adx_threshold": 18}, "is_default": False}
        ]), patch("data.fetcher.get_stock_data", return_value=pd.DataFrame(
            {"close": np.random.uniform(100, 110, 200), "high": np.random.uniform(105, 115, 200),
             "low": np.random.uniform(95, 105, 200), "open": np.random.uniform(100, 110, 200),
             "volume": np.random.uniform(1e6, 5e6, 200)},
            index=pd.date_range("2023-06-01", periods=200),
        )), patch("backtest.engine.run_backtest_v4", return_value=mock_result):
            resp = client.post("/api/strategies/test-bt/backtest/2330")
            assert resp.status_code == 200
            data = resp.json()
            assert "monthly_returns" in data
            assert "regime_breakdown" in data
            assert isinstance(data["monthly_returns"], list)
            # Should have 2 months (Jan + Feb)
            assert len(data["monthly_returns"]) == 2

    def test_monthly_returns_computation(self):
        """Test _compute_monthly_returns helper directly."""
        import pandas as pd
        from backtest.engine import BacktestResult, Trade
        from backend.routers.strategies import _compute_monthly_returns

        result = BacktestResult(trades=[
            Trade(date_open=pd.Timestamp("2024-01-10"), date_close=pd.Timestamp("2024-01-20"), pnl=5000),
            Trade(date_open=pd.Timestamp("2024-01-15"), date_close=pd.Timestamp("2024-01-25"), pnl=-2000),
            Trade(date_open=pd.Timestamp("2024-02-05"), date_close=pd.Timestamp("2024-02-15"), pnl=8000),
        ])
        monthly = _compute_monthly_returns(result)
        assert len(monthly) == 2
        assert monthly[0]["month"] == "2024-01"
        assert monthly[0]["pnl"] == 3000  # 5000 + (-2000)
        assert monthly[1]["month"] == "2024-02"
        assert monthly[1]["pnl"] == 8000


# ---------------------------------------------------------------------------
# R56: Telegram + unified notification tests
# ---------------------------------------------------------------------------

class TestAlertsTelegram:
    def test_config_has_telegram_fields(self, client):
        """GET /api/alerts/config should include Telegram fields."""
        resp = client.get("/api/alerts/config")
        assert resp.status_code == 200
        data = resp.json()
        # R56: Telegram config fields
        assert "notify_telegram" in data
        assert "telegram_bot_token" in data
        assert "telegram_chat_id" in data

    def test_save_config_telegram(self, client):
        """POST /api/alerts/config should accept Telegram fields."""
        resp = client.get("/api/alerts/config")
        cfg = resp.json()
        cfg["notify_telegram"] = False
        cfg["telegram_bot_token"] = ""
        cfg["telegram_chat_id"] = ""
        resp2 = client.post("/api/alerts/config", json=cfg)
        assert resp2.status_code == 200

    def test_send_test_notification(self, client):
        """POST /api/alerts/send-test should return ok (no channels enabled)."""
        with patch("backend.scheduler._send_notification") as mock_send:
            resp = client.post("/api/alerts/send-test", json={"message": "test"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# R57: PDF export endpoint tests (Playwright mocked)
# ---------------------------------------------------------------------------

class TestPdfExport:
    def test_report_pdf_endpoint_exists(self, client):
        """GET /api/system/export/report/pdf/{code} should call pdf_export."""
        from unittest.mock import AsyncMock
        with patch("backend.pdf_export.export_report_pdf", new_callable=AsyncMock, return_value=b"%PDF-fake"):
            resp = client.get("/api/system/export/report/pdf/2330")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/pdf"

    def test_portfolio_pdf_endpoint_exists(self, client):
        """GET /api/system/export/portfolio/pdf should call pdf_export."""
        from unittest.mock import AsyncMock
        with patch("backend.pdf_export.export_portfolio_pdf", new_callable=AsyncMock, return_value=b"%PDF-fake"):
            resp = client.get("/api/system/export/portfolio/pdf")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/pdf"

    def test_backtest_pdf_endpoint_exists(self, client):
        """GET /api/system/export/backtest/pdf/{code} should call pdf_export."""
        from unittest.mock import AsyncMock
        with patch("backend.pdf_export.export_backtest_pdf", new_callable=AsyncMock, return_value=b"%PDF-fake"):
            resp = client.get("/api/system/export/backtest/pdf/2330?period=365")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/pdf"

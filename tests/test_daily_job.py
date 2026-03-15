"""Tests for cloud/daily_job.py — freshness check + alert levels.

Unit tests with synthetic data (no network, no real files).
"""

import sys
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cloud.daily_job import (
    ALERT_ABORT,
    ALERT_SUCCESS,
    ALERT_WARNING,
    determine_alert_level,
    is_trading_day,
)


# ---------------------------------------------------------------------------
# is_trading_day
# ---------------------------------------------------------------------------


class TestIsTradingDay:
    """Tests for is_trading_day()."""

    def test_monday_is_trading_day(self):
        # 2026-03-16 is Monday
        assert is_trading_day(date(2026, 3, 16)) is True

    def test_friday_is_trading_day(self):
        # 2026-03-20 is Friday
        assert is_trading_day(date(2026, 3, 20)) is True

    def test_saturday_not_trading_day(self):
        # 2026-03-14 is Saturday
        assert is_trading_day(date(2026, 3, 14)) is False

    def test_sunday_not_trading_day(self):
        # 2026-03-15 is Sunday
        assert is_trading_day(date(2026, 3, 15)) is False

    def test_wednesday_is_trading_day(self):
        assert is_trading_day(date(2026, 3, 18)) is True

    def test_default_uses_today(self):
        """Default arg should not raise."""
        result = is_trading_day()
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# determine_alert_level
# ---------------------------------------------------------------------------


class TestDetermineAlertLevel:
    """Tests for determine_alert_level()."""

    def test_success_all_ok(self):
        results = {
            "daily_update": {"status": "ok", "result": {"stock_count": 1096}},
            "data_freshness": {"status": "ok"},
            "build_features": {"status": "ok", "elapsed_s": 600},
            "gcs_upload": {"status": "ok", "uploaded": 8, "failed": 0},
            "total_elapsed_s": 900,
        }
        level, issues = determine_alert_level(results)
        assert level == ALERT_SUCCESS
        assert issues == []

    def test_abort_daily_update_failed(self):
        results = {
            "daily_update": {"status": "error", "error": "Connection timeout"},
            "data_freshness": {"status": "skipped"},
            "build_features": {"status": "skipped"},
            "gcs_upload": {"status": "skipped"},
            "total_elapsed_s": 10,
        }
        level, issues = determine_alert_level(results)
        assert level == ALERT_ABORT
        assert "Daily update failed" in issues[0]

    def test_abort_freshness_failed(self):
        results = {
            "daily_update": {"status": "ok", "result": {}},
            "data_freshness": {"status": "error", "error": "Data is stale"},
            "build_features": {"status": "ok"},
            "gcs_upload": {"status": "ok", "uploaded": 8, "failed": 0},
            "total_elapsed_s": 100,
        }
        level, issues = determine_alert_level(results)
        assert level == ALERT_ABORT
        assert "freshness" in issues[0].lower()

    def test_abort_features_failed(self):
        results = {
            "daily_update": {"status": "ok", "result": {}},
            "data_freshness": {"status": "ok"},
            "build_features": {"status": "error", "error": "OOM"},
            "gcs_upload": {"status": "ok", "uploaded": 8, "failed": 0},
            "total_elapsed_s": 100,
        }
        level, issues = determine_alert_level(results)
        assert level == ALERT_ABORT

    def test_warning_failed_stocks(self):
        results = {
            "daily_update": {"status": "ok", "result": {"failed_stocks": 5, "stock_count": 1091}},
            "data_freshness": {"status": "ok"},
            "build_features": {"status": "ok"},
            "gcs_upload": {"status": "ok", "uploaded": 8, "failed": 0},
            "total_elapsed_s": 600,
        }
        level, issues = determine_alert_level(results)
        assert level == ALERT_WARNING
        assert any("5 stocks failed" in i for i in issues)

    def test_warning_slow_build(self):
        results = {
            "daily_update": {"status": "ok", "result": {"stock_count": 1096}},
            "data_freshness": {"status": "ok"},
            "build_features": {"status": "ok"},
            "gcs_upload": {"status": "ok", "uploaded": 8, "failed": 0},
            "total_elapsed_s": 2400,  # 40 min > 30 min threshold
        }
        level, issues = determine_alert_level(results)
        assert level == ALERT_WARNING
        assert any("Build time" in i for i in issues)

    def test_warning_stock_count_drop(self):
        results = {
            "daily_update": {
                "status": "ok",
                "result": {"stock_count": 900, "prev_stock_count": 1096},
            },
            "data_freshness": {"status": "ok"},
            "build_features": {"status": "ok"},
            "gcs_upload": {"status": "ok", "uploaded": 8, "failed": 0},
            "total_elapsed_s": 600,
        }
        level, issues = determine_alert_level(results)
        assert level == ALERT_WARNING
        assert any("dropped" in i.lower() for i in issues)

    def test_warning_gcs_partial_failure(self):
        results = {
            "daily_update": {"status": "ok", "result": {}},
            "data_freshness": {"status": "ok"},
            "build_features": {"status": "ok"},
            "gcs_upload": {"status": "ok", "uploaded": 6, "failed": 2},
            "total_elapsed_s": 600,
        }
        level, issues = determine_alert_level(results)
        assert level == ALERT_WARNING
        assert any("GCS" in i for i in issues)

    def test_warning_multiple_issues(self):
        results = {
            "daily_update": {
                "status": "ok",
                "result": {"failed_stocks": 3, "stock_count": 1093},
            },
            "data_freshness": {"status": "ok"},
            "build_features": {"status": "ok"},
            "gcs_upload": {"status": "ok", "uploaded": 6, "failed": 2},
            "total_elapsed_s": 2400,
        }
        level, issues = determine_alert_level(results)
        assert level == ALERT_WARNING
        assert len(issues) >= 2  # Multiple issues stacked

    def test_success_skipped_features(self):
        """Skipped features is not an error — should be SUCCESS."""
        results = {
            "daily_update": {"status": "ok", "result": {"stock_count": 1096}},
            "data_freshness": {"status": "ok"},
            "build_features": {"status": "skipped"},
            "gcs_upload": {"status": "ok", "uploaded": 8, "failed": 0},
            "total_elapsed_s": 300,
        }
        level, issues = determine_alert_level(results)
        assert level == ALERT_SUCCESS

    def test_success_no_stock_drop_when_no_prev(self):
        """No previous stock count available — should not trigger warning."""
        results = {
            "daily_update": {"status": "ok", "result": {"stock_count": 1096}},
            "data_freshness": {"status": "ok"},
            "build_features": {"status": "ok"},
            "gcs_upload": {"status": "ok", "uploaded": 8, "failed": 0},
            "total_elapsed_s": 600,
        }
        level, issues = determine_alert_level(results)
        assert level == ALERT_SUCCESS

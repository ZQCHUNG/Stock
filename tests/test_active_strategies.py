"""Tests for ACTIVE_STRATEGIES config flag and strategy freeze gate."""

import pytest
from unittest.mock import patch, MagicMock


class TestActiveStrategiesConfig:
    """Test the ACTIVE_STRATEGIES config value."""

    def test_default_only_v4(self):
        from config import ACTIVE_STRATEGIES
        assert ACTIVE_STRATEGIES == ["v4"]

    def test_v4_is_active(self):
        from config import ACTIVE_STRATEGIES
        assert "v4" in ACTIVE_STRATEGIES

    def test_v5_is_frozen(self):
        from config import ACTIVE_STRATEGIES
        assert "v5" not in ACTIVE_STRATEGIES

    def test_bold_is_frozen(self):
        from config import ACTIVE_STRATEGIES
        assert "bold" not in ACTIVE_STRATEGIES

    def test_adaptive_is_frozen(self):
        from config import ACTIVE_STRATEGIES
        assert "adaptive" not in ACTIVE_STRATEGIES


class TestSignalTrackerGate:
    """Test that signal_tracker respects ACTIVE_STRATEGIES."""

    @patch("config.ACTIVE_STRATEGIES", ["v4"])
    @patch("data.fetcher.get_stock_data")
    @patch("analysis.strategy_v4.get_v4_analysis")
    def test_v4_signal_recorded_when_active(self, mock_v4, mock_fetch, tmp_path):
        """V4 BUY signal should be recorded when v4 is active."""
        import pandas as pd
        import numpy as np

        dates = pd.date_range("2025-01-01", periods=100, freq="B")
        df = pd.DataFrame({
            "open": np.random.uniform(100, 110, 100),
            "high": np.random.uniform(110, 120, 100),
            "low": np.random.uniform(90, 100, 100),
            "close": np.random.uniform(100, 110, 100),
            "volume": np.random.randint(1000, 5000, 100),
        }, index=dates)
        mock_fetch.return_value = df
        mock_v4.return_value = {"signal": "BUY", "entry_type": "support"}

        # Import after patching
        from analysis.signal_tracker import record_daily_signals
        with patch("analysis.signal_tracker.DB_PATH", tmp_path / "test.db"):
            result = record_daily_signals(stocks={"2330": "TSMC"}, max_workers=1)

        assert result["total_signals"] >= 1
        assert result["by_strategy"]["V4"] >= 1

    @patch("config.ACTIVE_STRATEGIES", ["v4"])
    @patch("data.fetcher.get_stock_data")
    @patch("analysis.strategy_v4.get_v4_analysis")
    def test_v5_signal_skipped_when_frozen(self, mock_v4, mock_fetch, tmp_path):
        """V5 signal should NOT be recorded when v5 is not in ACTIVE_STRATEGIES."""
        import pandas as pd
        import numpy as np

        dates = pd.date_range("2025-01-01", periods=100, freq="B")
        df = pd.DataFrame({
            "open": np.random.uniform(100, 110, 100),
            "high": np.random.uniform(110, 120, 100),
            "low": np.random.uniform(90, 100, 100),
            "close": np.random.uniform(100, 110, 100),
            "volume": np.random.randint(1000, 5000, 100),
        }, index=dates)
        mock_fetch.return_value = df
        mock_v4.return_value = {"signal": "HOLD"}

        from analysis.signal_tracker import record_daily_signals
        with patch("analysis.signal_tracker.DB_PATH", tmp_path / "test.db"):
            result = record_daily_signals(stocks={"2330": "TSMC"}, max_workers=1)

        # V5 should be 0 since it's frozen
        assert result["by_strategy"]["V5"] == 0

    @patch("config.ACTIVE_STRATEGIES", ["v4"])
    @patch("data.fetcher.get_stock_data")
    @patch("analysis.strategy_v4.get_v4_analysis")
    def test_adaptive_signal_skipped_when_frozen(self, mock_v4, mock_fetch, tmp_path):
        """Adaptive signal should NOT be recorded when not in ACTIVE_STRATEGIES."""
        import pandas as pd
        import numpy as np

        dates = pd.date_range("2025-01-01", periods=100, freq="B")
        df = pd.DataFrame({
            "open": np.random.uniform(100, 110, 100),
            "high": np.random.uniform(110, 120, 100),
            "low": np.random.uniform(90, 100, 100),
            "close": np.random.uniform(100, 110, 100),
            "volume": np.random.randint(1000, 5000, 100),
        }, index=dates)
        mock_fetch.return_value = df
        mock_v4.return_value = {"signal": "HOLD"}

        from analysis.signal_tracker import record_daily_signals
        with patch("analysis.signal_tracker.DB_PATH", tmp_path / "test.db"):
            result = record_daily_signals(stocks={"2330": "TSMC"}, max_workers=1)

        assert result["by_strategy"]["Adaptive"] == 0


class TestDashboardStatusBar:
    """Test the new dashboard status bar endpoint."""

    def test_status_bar_returns_expected_keys(self):
        """Status bar should have all required keys."""
        from backend.routers.system import _dashboard_status_bar
        with patch("backend.routers.system.Path") as mock_path:
            # Make parquet files not exist to test graceful fallback
            mock_path.return_value.resolve.return_value.parent.parent.parent.__truediv__ = MagicMock()
            result = _dashboard_status_bar()

        assert "latest_data_date" in result
        assert "stock_count" in result
        assert "last_update" in result
        assert "regime" in result
        assert "regime_level" in result

    def test_status_bar_handles_missing_files(self):
        """Status bar should not crash when data files are missing."""
        from backend.routers.system import _dashboard_status_bar
        with patch("pandas.read_parquet", side_effect=FileNotFoundError):
            result = _dashboard_status_bar()

        # Should still return a valid dict, just with None/0 values
        assert isinstance(result, dict)
        assert result["stock_count"] == 0 or result["stock_count"] is not None

    def test_dashboard_endpoint_structure(self):
        """Dashboard endpoint should return 3 sections."""
        from backend.routers.system import dashboard_summary
        with patch("backend.routers.system._dashboard_status_bar") as mock_sb:
            mock_sb.return_value = {
                "latest_data_date": "2025-03-14",
                "stock_count": 1096,
                "last_update": "2025-03-14T20:15:00",
                "regime": "NORMAL",
                "regime_level": 0,
            }
            result = dashboard_summary()

        assert "status_bar" in result
        assert "scan" in result
        assert "portfolio" in result
        assert result["scan"]["enabled"] is False
        assert result["portfolio"]["enabled"] is False
        assert result["status_bar"]["latest_data_date"] == "2025-03-14"

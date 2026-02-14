"""Tests for backend/order_manager.py (R50-2: Simulated OMS)"""

import pytest
from unittest.mock import patch, MagicMock
from backend.order_manager import (
    check_positions_and_execute,
    _update_trailing_stop,
    TAKE_PROFIT_PCT,
    STOP_LOSS_PCT,
    TRAILING_STOP_PCT,
    MIN_HOLD_DAYS,
)


def _mock_position(code="2330", entry_price=100.0, stop_loss=93.0,
                    trailing_stop=None, days_ago=10, lots=1, pid="test1"):
    """Create a mock position dict."""
    from datetime import datetime, timedelta
    entry_date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    return {
        "id": pid,
        "code": code,
        "name": f"Test {code}",
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "trailing_stop": trailing_stop,
        "lots": lots,
        "entry_date": entry_date,
    }


@patch("backend.order_manager.db")
@patch("backend.order_manager._fetch_current_prices")
class TestCheckPositions:
    def test_no_positions(self, mock_prices, mock_db):
        mock_db.get_open_positions.return_value = []
        result = check_positions_and_execute()
        assert result["checked"] == 0
        assert result["actions"] == []

    def test_stop_loss_triggered(self, mock_prices, mock_db):
        """Position below stop_loss should be auto-closed."""
        pos = _mock_position(stop_loss=93.0)
        mock_db.get_open_positions.return_value = [pos]
        mock_prices.return_value = {"2330": 92.0}  # Below stop_loss
        mock_db.close_position.return_value = {
            "net_pnl": -9000, "exit_price": 92.0,
        }
        mock_db.insert_order_event = MagicMock()

        result = check_positions_and_execute()
        assert len(result["actions"]) == 1
        assert result["actions"][0]["exit_reason"] == "stop_loss"
        mock_db.close_position.assert_called_once_with(pos["id"], 92.0, "stop_loss")

    def test_take_profit_triggered(self, mock_prices, mock_db):
        """Position above +10% should be auto-closed."""
        pos = _mock_position(entry_price=100.0, stop_loss=93.0)
        mock_db.get_open_positions.return_value = [pos]
        mock_prices.return_value = {"2330": 111.0}  # +11%
        mock_db.close_position.return_value = {
            "net_pnl": 10000, "exit_price": 111.0,
        }
        mock_db.insert_order_event = MagicMock()

        result = check_positions_and_execute()
        assert len(result["actions"]) == 1
        assert result["actions"][0]["exit_reason"] == "take_profit"

    def test_trailing_stop_triggered(self, mock_prices, mock_db):
        """Position below trailing_stop (after min hold) should be auto-closed."""
        pos = _mock_position(trailing_stop=105.0, days_ago=10)
        mock_db.get_open_positions.return_value = [pos]
        mock_prices.return_value = {"2330": 104.0}  # Below trailing
        mock_db.close_position.return_value = {
            "net_pnl": 3000, "exit_price": 104.0,
        }
        mock_db.insert_order_event = MagicMock()

        result = check_positions_and_execute()
        assert len(result["actions"]) == 1
        assert result["actions"][0]["exit_reason"] == "trailing_stop"

    def test_trailing_stop_not_triggered_before_min_hold(self, mock_prices, mock_db):
        """Trailing stop should NOT trigger before MIN_HOLD_DAYS."""
        pos = _mock_position(trailing_stop=105.0, days_ago=3)  # Only 3 days
        mock_db.get_open_positions.return_value = [pos]
        mock_prices.return_value = {"2330": 104.0}  # Below trailing
        mock_db.insert_order_event = MagicMock()
        mock_db.update_position = MagicMock()

        result = check_positions_and_execute()
        assert len(result["actions"]) == 0  # No exit, too early

    def test_no_exit_normal_price(self, mock_prices, mock_db):
        """Position with normal price should not trigger any exit."""
        pos = _mock_position(entry_price=100.0, stop_loss=93.0)
        mock_db.get_open_positions.return_value = [pos]
        mock_prices.return_value = {"2330": 105.0}  # +5%, within bounds
        mock_db.update_position = MagicMock()
        mock_db.insert_order_event = MagicMock()

        result = check_positions_and_execute()
        assert len(result["actions"]) == 0

    def test_trailing_stop_ratchets_up(self, mock_prices, mock_db):
        """Trailing stop should update upward when price rises."""
        pos = _mock_position(entry_price=100.0, trailing_stop=102.0, days_ago=10)
        mock_db.get_open_positions.return_value = [pos]
        mock_prices.return_value = {"2330": 112.0}  # High price, trailing should ratchet up
        mock_db.update_position = MagicMock(return_value=True)
        mock_db.insert_order_event = MagicMock()

        result = check_positions_and_execute()
        # Should trigger take_profit since +12% > +10%
        assert len(result["actions"]) == 1
        assert result["actions"][0]["exit_reason"] == "take_profit"

    def test_stop_loss_priority_over_trailing(self, mock_prices, mock_db):
        """Stop-loss should take priority when both SL and TS are hit."""
        pos = _mock_position(entry_price=100.0, stop_loss=93.0, trailing_stop=95.0, days_ago=10)
        mock_db.get_open_positions.return_value = [pos]
        mock_prices.return_value = {"2330": 90.0}  # Below both SL and TS
        mock_db.close_position.return_value = {"net_pnl": -11000, "exit_price": 90.0}
        mock_db.insert_order_event = MagicMock()

        result = check_positions_and_execute()
        assert len(result["actions"]) == 1
        assert result["actions"][0]["exit_reason"] == "stop_loss"  # SL checked first


@patch("backend.order_manager.db")
class TestUpdateTrailingStop:
    def test_ratchet_up(self, mock_db):
        """Trailing stop should increase when price goes higher."""
        pos = _mock_position(entry_price=100.0, trailing_stop=102.0, days_ago=10)
        mock_db.update_position = MagicMock(return_value=True)
        mock_db.insert_order_event = MagicMock()

        _update_trailing_stop(pos, current_price=108.0, days_held=10)
        # New trailing = 108 * (1 - 0.02) = 105.84
        mock_db.update_position.assert_called_once()
        call_args = mock_db.update_position.call_args
        new_ts = call_args[0][1]["trailing_stop"]
        assert new_ts == round(108.0 * 0.98, 2)

    def test_no_ratchet_down(self, mock_db):
        """Trailing stop should NOT decrease."""
        pos = _mock_position(entry_price=100.0, trailing_stop=106.0, days_ago=10)
        mock_db.update_position = MagicMock()
        mock_db.insert_order_event = MagicMock()

        _update_trailing_stop(pos, current_price=105.0, days_held=10)
        # 105 * 0.98 = 102.9 < current 106, should NOT update
        mock_db.update_position.assert_not_called()

    def test_no_update_before_min_hold(self, mock_db):
        """Trailing stop should not be set before MIN_HOLD_DAYS."""
        pos = _mock_position(entry_price=100.0, trailing_stop=0, days_ago=2)
        mock_db.update_position = MagicMock()
        mock_db.insert_order_event = MagicMock()

        _update_trailing_stop(pos, current_price=108.0, days_held=2)
        mock_db.update_position.assert_not_called()

    def test_no_trailing_below_entry(self, mock_db):
        """Trailing stop should not be set below entry price."""
        pos = _mock_position(entry_price=100.0, trailing_stop=0, days_ago=10)
        mock_db.update_position = MagicMock()
        mock_db.insert_order_event = MagicMock()

        _update_trailing_stop(pos, current_price=100.5, days_held=10)
        # 100.5 * 0.98 = 98.49 < entry 100, should NOT set
        mock_db.update_position.assert_not_called()

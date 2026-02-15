"""Tests for WebSocket market feed — QuoteData parsing, Fugle aggregates parsing, factory."""

import os
import pytest


class TestQuoteData:
    """Test TWSE MIS API quote parsing."""

    def test_basic_parse(self):
        from backend.ws_manager import QuoteData
        raw = {
            "c": "2330",
            "n": "台積電",
            "z": "580.00",
            "y": "575.00",
            "o": "576.00",
            "h": "582.00",
            "l": "574.00",
            "v": "25000",
            "tlong": "1700000000000",
            "b": "579.00|578.00|577.00",
            "g": "100|200|300",
            "a": "580.00|581.00|582.00",
            "f": "150|250|350",
        }
        q = QuoteData(raw)
        assert q.code == "2330"
        assert q.name == "台積電"
        assert q.last_price == 580.0
        assert q.prev_close == 575.0
        assert q.open == 576.0
        assert q.high == 582.0
        assert q.low == 574.0
        assert q.volume == 25000
        assert q.change == 5.0
        assert q.change_pct == pytest.approx(0.87, abs=0.01)
        assert len(q.bid_prices) == 3
        assert q.bid_prices[0] == 579.0

    def test_no_trade(self):
        from backend.ws_manager import QuoteData
        raw = {"c": "2330", "n": "台積電", "z": "-", "y": "575.00"}
        q = QuoteData(raw)
        assert q.last_price is None
        assert q.change is None

    def test_to_dict(self):
        from backend.ws_manager import QuoteData
        raw = {"c": "2330", "n": "T", "z": "100", "y": "99", "tlong": "0"}
        q = QuoteData(raw)
        d = q.to_dict()
        assert d["code"] == "2330"
        assert d["last_price"] == 100.0
        assert "bid_prices" in d


class TestFugleParseAggregates:
    """Test Fugle aggregates data parsing."""

    def test_basic_aggregates(self):
        from backend.ws_manager import FugleMarketFeed, ConnectionManager
        mgr = ConnectionManager()
        feed = FugleMarketFeed(mgr)

        data = {
            "symbol": "2330",
            "name": "台積電",
            "lastPrice": 580,
            "previousClose": 575,
            "openPrice": 576,
            "highPrice": 582,
            "lowPrice": 574,
            "change": 5,
            "changePercent": 0.87,
            "total": {"tradeVolume": 25000},
            "bids": [
                {"price": 579, "size": 100},
                {"price": 578, "size": 200},
            ],
            "asks": [
                {"price": 580, "size": 150},
                {"price": 581, "size": 250},
            ],
        }
        result = feed._parse_aggregates(data)
        assert result is not None
        assert result["code"] == "2330"
        assert result["last_price"] == 580
        assert result["change"] == 5
        assert result["change_pct"] == 0.87
        assert result["open"] == 576
        assert result["high"] == 582
        assert result["low"] == 574
        assert result["prev_close"] == 575
        assert result["volume"] == 25000
        assert len(result["bid_prices"]) == 2
        assert result["bid_prices"][0] == 579
        assert len(result["ask_prices"]) == 2

    def test_empty_symbol(self):
        from backend.ws_manager import FugleMarketFeed, ConnectionManager
        feed = FugleMarketFeed(ConnectionManager())
        assert feed._parse_aggregates({}) is None
        assert feed._parse_aggregates({"symbol": ""}) is None

    def test_missing_bids_asks(self):
        from backend.ws_manager import FugleMarketFeed, ConnectionManager
        feed = FugleMarketFeed(ConnectionManager())
        data = {"symbol": "2330", "lastPrice": 100}
        result = feed._parse_aggregates(data)
        assert result["bid_prices"] == []
        assert result["ask_prices"] == []


class TestCreateMarketFeed:
    """Test factory function for market feed creation."""

    def test_default_twse(self):
        from backend.ws_manager import create_market_feed, ConnectionManager, MarketFeed
        os.environ.pop("MARKET_FEED_PROVIDER", None)
        os.environ.pop("FUGLE_API_KEY", None)
        mgr = ConnectionManager()
        feed = create_market_feed(mgr)
        assert isinstance(feed, MarketFeed)

    def test_fugle_without_key_falls_back(self):
        from backend.ws_manager import create_market_feed, ConnectionManager, MarketFeed
        os.environ["MARKET_FEED_PROVIDER"] = "fugle"
        os.environ.pop("FUGLE_API_KEY", None)
        mgr = ConnectionManager()
        feed = create_market_feed(mgr)
        # Falls back to TWSE since no API key
        assert isinstance(feed, MarketFeed)
        os.environ.pop("MARKET_FEED_PROVIDER", None)

    def test_fugle_with_key(self):
        from backend.ws_manager import create_market_feed, ConnectionManager, FugleMarketFeed
        os.environ["MARKET_FEED_PROVIDER"] = "fugle"
        os.environ["FUGLE_API_KEY"] = "test_key_123"
        mgr = ConnectionManager()
        feed = create_market_feed(mgr)
        assert isinstance(feed, FugleMarketFeed)
        os.environ.pop("MARKET_FEED_PROVIDER", None)
        os.environ.pop("FUGLE_API_KEY", None)

    def test_explicit_twse(self):
        from backend.ws_manager import create_market_feed, ConnectionManager, MarketFeed
        os.environ["MARKET_FEED_PROVIDER"] = "twse"
        mgr = ConnectionManager()
        feed = create_market_feed(mgr)
        assert isinstance(feed, MarketFeed)
        os.environ.pop("MARKET_FEED_PROVIDER", None)


class TestConnectionManagerObserver:
    """R58: Test event-driven code change notifications."""

    def test_callback_on_subscribe(self):
        """Callback should fire when codes change."""
        import asyncio
        from backend.ws_manager import ConnectionManager

        mgr = ConnectionManager()
        changes = []

        def on_change(added, removed):
            changes.append((added.copy(), removed.copy()))

        mgr.on_codes_changed(on_change)

        # Simulate subscribe
        async def _test():
            conn_id = "test123"
            async with mgr._lock:
                mgr.active_connections[conn_id] = None
                mgr.subscriptions[conn_id] = set()
            await mgr.subscribe(conn_id, ["2330", "2317"])

        asyncio.get_event_loop().run_until_complete(_test())
        assert len(changes) == 1
        assert "2330" in changes[0][0]
        assert "2317" in changes[0][0]

    def test_callback_on_unsubscribe(self):
        """Callback should fire with removed codes."""
        import asyncio
        from backend.ws_manager import ConnectionManager

        mgr = ConnectionManager()
        changes = []

        def on_change(added, removed):
            changes.append((added.copy(), removed.copy()))

        mgr.on_codes_changed(on_change)

        async def _test():
            conn_id = "test456"
            async with mgr._lock:
                mgr.active_connections[conn_id] = None
                mgr.subscriptions[conn_id] = {"2330", "2317"}
                mgr._all_codes = {"2330", "2317"}
            await mgr.unsubscribe(conn_id, ["2317"])

        asyncio.get_event_loop().run_until_complete(_test())
        assert len(changes) == 1
        assert "2317" in changes[0][1]  # removed

    def test_off_callback(self):
        """Removing callback should stop notifications."""
        from backend.ws_manager import ConnectionManager
        mgr = ConnectionManager()
        called = []
        def cb(a, r): called.append(1)
        mgr.on_codes_changed(cb)
        mgr.off_codes_changed(cb)
        mgr._rebuild_codes()  # Should not trigger callback
        assert len(called) == 0


class TestFugleDebounce:
    """R58: Test FugleMarketFeed debounced subscription changes."""

    def test_pending_add_remove(self):
        """Pending adds and removes should be tracked."""
        from backend.ws_manager import FugleMarketFeed, ConnectionManager
        mgr = ConnectionManager()
        feed = FugleMarketFeed(mgr)

        # Simulate code change callback (not running, so no task created)
        feed._on_codes_changed({"2330", "2317"}, set())
        assert "2330" in feed._pending_add
        assert "2317" in feed._pending_add

        feed._on_codes_changed(set(), {"2317"})
        assert "2317" in feed._pending_remove


class TestFugleStatus:
    """Test FugleMarketFeed status reporting."""

    def test_status(self):
        from backend.ws_manager import FugleMarketFeed, ConnectionManager
        feed = FugleMarketFeed(ConnectionManager())
        status = feed.get_status()
        assert status["provider"] == "fugle"
        assert status["running"] is False
        assert status["ws_connected"] is False

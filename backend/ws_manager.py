"""WebSocket 連線管理器 + 即時行情推送

R55-1: 即時行情 WebSocket
- ConnectionManager: 管理 WebSocket 連線與訂閱
- MarketFeed (TWSE): 輪詢 TWSE/TPEX MIS API，推送即時報價
- 支援 tse (上市) + otc (上櫃) 股票
- 交易時段 (09:00-13:30 UTC+8) 每 5 秒輪詢
- 非交易時段停止輪詢，但保持連線

R57: Fugle WebSocket 即時行情
- FugleMarketFeed: 使用 Fugle MarketData WebSocket API（延遲 <1s）
- 支援 aggregates channel（OHLCV + 五檔）
- Config 切換數據源 (TWSE / Fugle)
"""

import asyncio
import json as _json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)

TW_TZ = timezone(timedelta(hours=8))

# TWSE MIS API for real-time quotes
TWSE_MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"


def _parse_float(val: str | None) -> float | None:
    """Parse TWSE string value to float, handling '-' (no trade)."""
    if not val or val == "-" or val == "":
        return None
    try:
        return float(val.replace(",", ""))
    except (ValueError, TypeError):
        return None


def _parse_int(val: str | None) -> int | None:
    if not val or val == "-" or val == "":
        return None
    try:
        return int(val.replace(",", ""))
    except (ValueError, TypeError):
        return None


class QuoteData:
    """Parsed real-time quote from TWSE MIS API."""
    __slots__ = (
        "code", "name", "last_price", "change", "change_pct",
        "open", "high", "low", "prev_close", "volume",
        "bid_prices", "bid_volumes", "ask_prices", "ask_volumes",
        "timestamp",
    )

    def __init__(self, raw: dict):
        self.code: str = raw.get("c", "")
        self.name: str = raw.get("n", "")
        self.last_price = _parse_float(raw.get("z"))
        self.prev_close = _parse_float(raw.get("y"))
        self.open = _parse_float(raw.get("o"))
        self.high = _parse_float(raw.get("h"))
        self.low = _parse_float(raw.get("l"))
        self.volume = _parse_int(raw.get("v"))
        self.timestamp = int(raw.get("tlong", "0")) // 1000 or int(time.time())

        # Bid/Ask 5 levels
        self.bid_prices = [_parse_float(p) for p in (raw.get("b") or "").split("|")]
        self.bid_volumes = [_parse_int(v) for v in (raw.get("g") or "").split("|")]
        self.ask_prices = [_parse_float(p) for p in (raw.get("a") or "").split("|")]
        self.ask_volumes = [_parse_int(v) for v in (raw.get("f") or "").split("|")]

        # Calculate change
        if self.last_price is not None and self.prev_close is not None and self.prev_close > 0:
            self.change = round(self.last_price - self.prev_close, 2)
            self.change_pct = round(self.change / self.prev_close * 100, 2)
        else:
            self.change = None
            self.change_pct = None

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "last_price": self.last_price,
            "change": self.change,
            "change_pct": self.change_pct,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "prev_close": self.prev_close,
            "volume": self.volume,
            "bid_prices": self.bid_prices,
            "bid_volumes": self.bid_volumes,
            "ask_prices": self.ask_prices,
            "ask_volumes": self.ask_volumes,
            "timestamp": self.timestamp,
        }


class ConnectionManager:
    """Manages WebSocket connections and their stock subscriptions."""

    def __init__(self):
        # conn_id -> WebSocket
        self.active_connections: dict[str, object] = {}
        # conn_id -> set of stock codes
        self.subscriptions: dict[str, set[str]] = {}
        # Union of all subscribed codes
        self._all_codes: set[str] = set()
        self._lock = asyncio.Lock()
        # R58: Observer callbacks for code changes
        self._code_change_callbacks: list = []

    async def connect(self, websocket) -> str:
        """Accept WebSocket connection, return connection ID."""
        await websocket.accept()
        conn_id = str(uuid4())[:8]
        async with self._lock:
            self.active_connections[conn_id] = websocket
            self.subscriptions[conn_id] = set()
        logger.info(f"WS connected: {conn_id} (total: {len(self.active_connections)})")
        return conn_id

    async def disconnect(self, conn_id: str):
        """Remove connection and its subscriptions."""
        async with self._lock:
            self.active_connections.pop(conn_id, None)
            self.subscriptions.pop(conn_id, None)
            self._rebuild_codes()
        logger.info(f"WS disconnected: {conn_id} (total: {len(self.active_connections)})")

    async def subscribe(self, conn_id: str, codes: list[str]):
        """Subscribe a connection to stock codes."""
        async with self._lock:
            if conn_id in self.subscriptions:
                self.subscriptions[conn_id].update(codes)
                self._rebuild_codes()
        logger.debug(f"WS {conn_id} subscribed: {codes}")

    async def unsubscribe(self, conn_id: str, codes: list[str]):
        """Unsubscribe a connection from stock codes."""
        async with self._lock:
            if conn_id in self.subscriptions:
                self.subscriptions[conn_id].difference_update(codes)
                self._rebuild_codes()

    def _rebuild_codes(self):
        """Rebuild the union of all subscribed codes and notify observers."""
        old_codes = self._all_codes.copy()
        self._all_codes = set()
        for codes in self.subscriptions.values():
            self._all_codes.update(codes)

        # R58: Notify observers of code changes (event-driven)
        added = self._all_codes - old_codes
        removed = old_codes - self._all_codes
        if added or removed:
            for cb in self._code_change_callbacks:
                try:
                    cb(added, removed)
                except Exception as e:
                    logger.debug(f"Code change callback error: {e}")

    def on_codes_changed(self, callback):
        """R58: Register callback for code change events.

        Callback signature: fn(added: set[str], removed: set[str])
        """
        self._code_change_callbacks.append(callback)

    def off_codes_changed(self, callback):
        """R58: Unregister a code change callback."""
        try:
            self._code_change_callbacks.remove(callback)
        except ValueError:
            pass

    @property
    def all_subscribed_codes(self) -> set[str]:
        return self._all_codes.copy()

    @property
    def connection_count(self) -> int:
        return len(self.active_connections)

    async def send_to_subscribers(self, code: str, data: dict):
        """Send data to all connections subscribed to this code."""
        dead = []
        for conn_id, codes in self.subscriptions.items():
            if code in codes:
                ws = self.active_connections.get(conn_id)
                if ws:
                    try:
                        await ws.send_json(data)
                    except Exception as e:
                        logger.debug(f"WS send failed for {conn_id}, marking dead: {e}")
                        dead.append(conn_id)
        # Clean dead connections
        for conn_id in dead:
            await self.disconnect(conn_id)

    async def broadcast(self, data: dict):
        """Send data to all connected clients."""
        dead = []
        for conn_id, ws in self.active_connections.items():
            try:
                await ws.send_json(data)
            except Exception as e:
                logger.debug(f"WS broadcast failed for {conn_id}: {e}")
                dead.append(conn_id)
        for conn_id in dead:
            await self.disconnect(conn_id)


class MarketFeed:
    """Polls TWSE/TPEX MIS API and pushes quotes via WebSocket.

    - During market hours (09:00-13:30 TWN): polls every `poll_interval` seconds
    - Outside market hours: idles (no polling)
    - Detects exchange (tse/otc) from stock list cache
    """

    def __init__(self, manager: ConnectionManager, poll_interval: float = 5.0):
        self.manager = manager
        self.poll_interval = poll_interval
        self._running = False
        self._task: asyncio.Task | None = None
        self._exchange_cache: dict[str, str] = {}  # code -> "tse" or "otc"
        self._quote_cache: dict[str, dict] = {}  # code -> last quote dict
        self._client: httpx.AsyncClient | None = None
        self._consecutive_errors = 0
        self._last_poll_time: float = 0

    async def start(self):
        """Start the polling loop."""
        if self._running:
            return
        self._running = True
        self._client = httpx.AsyncClient(timeout=10.0)
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("MarketFeed started")

    async def stop(self):
        """Stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
        logger.info("MarketFeed stopped")

    def _load_exchange_map(self):
        """Load exchange info from stock list cache."""
        try:
            from data.stock_list import get_all_stocks
            stocks = get_all_stocks()
            for code, info in stocks.items():
                market = info.get("market", "上市")
                self._exchange_cache[code] = "otc" if market == "上櫃" else "tse"
        except Exception as e:
            logger.warning(f"Failed to load exchange map: {e}")

    def _get_exchange(self, code: str) -> str:
        """Get exchange prefix for a stock code."""
        if not self._exchange_cache:
            self._load_exchange_map()
        return self._exchange_cache.get(code, "tse")

    def is_market_hours(self) -> bool:
        """Check if Taiwan market is open (Mon-Fri 09:00-13:30 UTC+8)."""
        now = datetime.now(TW_TZ)
        if now.weekday() >= 5:  # Weekend
            return False
        t = now.time()
        from datetime import time as dtime
        return dtime(8, 55) <= t <= dtime(13, 35)

    async def _poll_loop(self):
        """Main polling loop."""
        while self._running:
            try:
                codes = self.manager.all_subscribed_codes
                if codes and self.is_market_hours():
                    await self._fetch_and_broadcast(codes)
                    self._consecutive_errors = 0
                elif codes:
                    # Outside market hours: send cached data once, then idle
                    await asyncio.sleep(30)
                    continue
                else:
                    await asyncio.sleep(2)
                    continue

                await asyncio.sleep(self.poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._consecutive_errors += 1
                backoff = min(30, self.poll_interval * self._consecutive_errors)
                logger.error(f"MarketFeed error ({self._consecutive_errors}): {e}")
                await asyncio.sleep(backoff)

    async def _fetch_and_broadcast(self, codes: set[str]):
        """Fetch quotes from TWSE MIS API and push to subscribers."""
        if not self._client:
            return

        # Build ex_ch parameter: tse_2330.tw|otc_6547.tw
        ex_ch_parts = []
        for code in codes:
            exchange = self._get_exchange(code)
            ex_ch_parts.append(f"{exchange}_{code}.tw")

        # TWSE API supports batching ~20 stocks per request
        batch_size = 20
        parts_list = list(ex_ch_parts)
        for i in range(0, len(parts_list), batch_size):
            batch = parts_list[i:i + batch_size]
            ex_ch = "|".join(batch)

            try:
                resp = await self._client.get(
                    TWSE_MIS_URL,
                    params={"ex_ch": ex_ch, "json": "1", "delay": "0"},
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://mis.twse.com.tw/",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning(f"TWSE MIS fetch error: {e}")
                continue

            msg_array = data.get("msgArray", [])
            for raw in msg_array:
                try:
                    quote = QuoteData(raw)
                    if quote.code and quote.last_price is not None:
                        quote_dict = quote.to_dict()
                        self._quote_cache[quote.code] = quote_dict
                        await self.manager.send_to_subscribers(
                            quote.code,
                            {"type": "price_update", "data": quote_dict},
                        )
                except Exception as e:
                    logger.debug(f"Quote parse error: {e}")

        self._last_poll_time = time.time()

    def get_status(self) -> dict:
        """Get feed status for monitoring."""
        return {
            "running": self._running,
            "is_market_hours": self.is_market_hours(),
            "connections": self.manager.connection_count,
            "subscribed_codes": len(self.manager.all_subscribed_codes),
            "cached_quotes": len(self._quote_cache),
            "poll_interval": self.poll_interval,
            "consecutive_errors": self._consecutive_errors,
            "last_poll_time": self._last_poll_time,
        }

    def get_cached_quote(self, code: str) -> dict | None:
        """Get last known quote for a stock."""
        return self._quote_cache.get(code)


class FugleMarketFeed:
    """R57: Fugle WebSocket API market feed (<1s latency).

    Uses Fugle MarketData WebSocket API (aggregates channel) for real-time quotes.
    Requires: FUGLE_API_KEY env var or config setting.

    R58: Refactored to event-driven subscription via ConnectionManager callbacks
    with debounce to avoid rapid subscribe/unsubscribe bursts.
    """

    FUGLE_WS_URL = "wss://api.fugle.tw/marketdata/v1.0/stock/streaming"
    DEBOUNCE_SECONDS = 0.5  # Debounce subscription changes

    def __init__(self, manager: ConnectionManager):
        self.manager = manager
        self._running = False
        self._task: asyncio.Task | None = None
        self._ws = None
        self._quote_cache: dict[str, dict] = {}
        self._subscribed_codes: set[str] = set()
        self._consecutive_errors = 0
        self._last_message_time: float = 0
        self._api_key: str = os.environ.get("FUGLE_API_KEY", "")
        # R58: Pending subscription changes (debounced)
        self._pending_add: set[str] = set()
        self._pending_remove: set[str] = set()
        self._debounce_task: asyncio.Task | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None

    def _get_api_key(self) -> str:
        """Get Fugle API key from env or config file."""
        if self._api_key:
            return self._api_key
        try:
            from pathlib import Path
            config_path = Path(__file__).resolve().parent.parent / "data" / "fugle_config.json"
            if config_path.exists():
                data = _json.loads(config_path.read_text(encoding="utf-8"))
                self._api_key = data.get("api_key", "")
        except Exception as e:
            logger.debug(f"Failed to load Fugle config: {e}")
        return self._api_key

    def _on_codes_changed(self, added: set[str], removed: set[str]):
        """R58: Event callback from ConnectionManager — debounced."""
        self._pending_add.update(added)
        self._pending_remove.update(removed)
        # Remove contradictions (added then removed, or vice versa)
        self._pending_add -= self._pending_remove & self._pending_add
        self._pending_remove -= self._pending_add & self._pending_remove

        # Schedule debounced flush
        if self._event_loop and self._running:
            if self._debounce_task and not self._debounce_task.done():
                self._debounce_task.cancel()
            self._debounce_task = self._event_loop.create_task(self._flush_pending())

    async def _flush_pending(self):
        """R58: Flush pending subscription changes after debounce delay."""
        await asyncio.sleep(self.DEBOUNCE_SECONDS)
        if not self._ws or not self._running:
            return

        add_codes = self._pending_add.copy()
        remove_codes = self._pending_remove.copy()
        self._pending_add.clear()
        self._pending_remove.clear()

        for code in add_codes:
            await self._subscribe_code(self._ws, code)
        for code in remove_codes:
            await self._unsubscribe_code(self._ws, code)
        self._subscribed_codes = (self._subscribed_codes | add_codes) - remove_codes

        if add_codes or remove_codes:
            logger.debug(f"Fugle subscription sync: +{len(add_codes)} -{len(remove_codes)}")

    async def start(self):
        """Start the Fugle WebSocket connection."""
        if self._running:
            return
        api_key = self._get_api_key()
        if not api_key:
            logger.warning("Fugle API key not configured. Set FUGLE_API_KEY env var or data/fugle_config.json")
            return
        self._running = True
        self._event_loop = asyncio.get_event_loop()
        # R58: Register event-driven subscription callback
        self.manager.on_codes_changed(self._on_codes_changed)
        self._task = asyncio.create_task(self._ws_loop())
        logger.info("FugleMarketFeed started")

    async def stop(self):
        """Stop the Fugle WebSocket connection."""
        self._running = False
        # R58: Unregister event callback
        self.manager.off_codes_changed(self._on_codes_changed)
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                logger.debug(f"WS close error: {e}")
            self._ws = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("FugleMarketFeed stopped")

    def is_market_hours(self) -> bool:
        """Check if Taiwan market is open (Mon-Fri 09:00-13:30 UTC+8)."""
        now = datetime.now(TW_TZ)
        if now.weekday() >= 5:
            return False
        t = now.time()
        from datetime import time as dtime
        return dtime(8, 55) <= t <= dtime(13, 35)

    async def _ws_loop(self):
        """Main WebSocket connection loop with auto-reconnect."""
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not installed. Run: pip install websockets")
            self._running = False
            return

        api_key = self._get_api_key()
        while self._running:
            try:
                url = f"{self.FUGLE_WS_URL}?apikey={api_key}"
                async with websockets.connect(url) as ws:
                    self._ws = ws
                    self._consecutive_errors = 0
                    logger.info("Fugle WebSocket connected")

                    # Re-subscribe existing codes
                    if self._subscribed_codes:
                        for code in self._subscribed_codes:
                            await self._subscribe_code(ws, code)

                    # R58: Initial sync — subscribe to all currently watched codes
                    initial_codes = self.manager.all_subscribed_codes
                    for code in initial_codes:
                        await self._subscribe_code(ws, code)
                    self._subscribed_codes = initial_codes.copy()

                    # Event-driven updates handled by _on_codes_changed callback
                    async for message in ws:
                        if not self._running:
                            break
                        try:
                            data = _json.loads(message)
                            await self._handle_message(data)
                        except Exception as e:
                            logger.debug(f"Fugle message parse error: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._consecutive_errors += 1
                backoff = min(30, 2 ** self._consecutive_errors)
                logger.warning(f"Fugle WS error ({self._consecutive_errors}): {e}, reconnecting in {backoff}s")
                self._ws = None
                await asyncio.sleep(backoff)

    # R58: _sync_subscriptions removed — replaced by event-driven _on_codes_changed

    async def _subscribe_code(self, ws, code: str):
        """Subscribe to a stock's aggregates channel."""
        try:
            msg = _json.dumps({"event": "subscribe", "data": {"channel": "aggregates", "symbol": code}})
            await ws.send(msg)
            logger.debug(f"Fugle subscribed: {code}")
        except Exception as e:
            logger.debug(f"Fugle subscribe error for {code}: {e}")

    async def _unsubscribe_code(self, ws, code: str):
        """Unsubscribe from a stock's aggregates channel."""
        try:
            msg = _json.dumps({"event": "unsubscribe", "data": {"channel": "aggregates", "symbol": code}})
            await ws.send(msg)
        except Exception as e:
            logger.debug(f"Fugle unsubscribe failed for {code}: {e}")

    async def _handle_message(self, data: dict):
        """Handle incoming Fugle WebSocket message."""
        event = data.get("event")
        if event != "data":
            return

        channel = data.get("channel")
        payload = data.get("data", {})
        symbol = payload.get("symbol")

        if not symbol:
            return

        if channel == "aggregates":
            quote_dict = self._parse_aggregates(payload)
            if quote_dict:
                self._quote_cache[symbol] = quote_dict
                self._last_message_time = time.time()
                await self.manager.send_to_subscribers(
                    symbol,
                    {"type": "price_update", "data": quote_dict},
                )
        elif channel == "trades":
            # Trades channel: update last price + volume
            existing = self._quote_cache.get(symbol, {})
            if payload.get("price") is not None:
                existing["last_price"] = payload["price"]
                existing["volume"] = payload.get("volume", existing.get("volume"))
                existing["timestamp"] = int(time.time())
                self._quote_cache[symbol] = existing
                self._last_message_time = time.time()
                await self.manager.send_to_subscribers(
                    symbol,
                    {"type": "price_update", "data": existing},
                )

    def _parse_aggregates(self, data: dict) -> dict | None:
        """Parse Fugle aggregates data to our QuoteData format."""
        symbol = data.get("symbol")
        if not symbol:
            return None

        last_price = data.get("lastPrice") or data.get("closePrice")
        prev_close = data.get("previousClose") or data.get("referencePrice")

        # Extract bid/ask from bids/asks arrays
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        bid_prices = [b.get("price") for b in bids[:5]] if bids else []
        bid_volumes = [b.get("size") for b in bids[:5]] if bids else []
        ask_prices = [a.get("price") for a in asks[:5]] if asks else []
        ask_volumes = [a.get("size") for a in asks[:5]] if asks else []

        total = data.get("total", {})

        return {
            "code": symbol,
            "name": data.get("name", ""),
            "last_price": last_price,
            "change": data.get("change"),
            "change_pct": data.get("changePercent"),
            "open": data.get("openPrice"),
            "high": data.get("highPrice"),
            "low": data.get("lowPrice"),
            "prev_close": prev_close,
            "volume": total.get("tradeVolume"),
            "bid_prices": bid_prices,
            "bid_volumes": bid_volumes,
            "ask_prices": ask_prices,
            "ask_volumes": ask_volumes,
            "timestamp": int(time.time()),
        }

    def get_status(self) -> dict:
        """Get feed status for monitoring."""
        return {
            "running": self._running,
            "provider": "fugle",
            "is_market_hours": self.is_market_hours(),
            "connections": self.manager.connection_count,
            "subscribed_codes": len(self._subscribed_codes),
            "cached_quotes": len(self._quote_cache),
            "consecutive_errors": self._consecutive_errors,
            "last_message_time": self._last_message_time,
            "ws_connected": self._ws is not None,
        }

    def get_cached_quote(self, code: str) -> dict | None:
        """Get last known quote for a stock."""
        return self._quote_cache.get(code)


def create_market_feed(manager: ConnectionManager) -> MarketFeed | FugleMarketFeed:
    """R57: Factory function to create the appropriate market feed based on config.

    Set MARKET_FEED_PROVIDER env var to "fugle" to use Fugle API.
    Default: "twse" (free, ~20s delay).
    """
    provider = os.environ.get("MARKET_FEED_PROVIDER", "twse").lower()
    if provider == "fugle":
        api_key = os.environ.get("FUGLE_API_KEY", "")
        if not api_key:
            try:
                from pathlib import Path
                config_path = Path(__file__).resolve().parent.parent / "data" / "fugle_config.json"
                if config_path.exists():
                    data = _json.loads(config_path.read_text(encoding="utf-8"))
                    api_key = data.get("api_key", "")
            except Exception as e:
                logger.debug(f"Failed to load Fugle config for factory: {e}")
        if api_key:
            logger.info("Using Fugle MarketData WebSocket feed (<1s latency)")
            return FugleMarketFeed(manager)
        else:
            logger.warning("FUGLE_API_KEY not set, falling back to TWSE MIS feed")
            return MarketFeed(manager)
    else:
        logger.info("Using TWSE MIS polling feed (~20s latency)")
        return MarketFeed(manager)


# Singleton instances
ws_manager = ConnectionManager()
market_feed = create_market_feed(ws_manager)

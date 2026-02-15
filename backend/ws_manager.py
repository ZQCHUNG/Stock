"""WebSocket 連線管理器 + TWSE 即時行情推送

R55-1: 即時行情 WebSocket
- ConnectionManager: 管理 WebSocket 連線與訂閱
- MarketFeed: 輪詢 TWSE/TPEX MIS API，推送即時報價
- 支援 tse (上市) + otc (上櫃) 股票
- 交易時段 (09:00-13:30 UTC+8) 每 5 秒輪詢
- 非交易時段停止輪詢，但保持連線
"""

import asyncio
import logging
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
        """Rebuild the union of all subscribed codes."""
        self._all_codes = set()
        for codes in self.subscriptions.values():
            self._all_codes.update(codes)

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
                    except Exception:
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
            except Exception:
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


# Singleton instances
ws_manager = ConnectionManager()
market_feed = MarketFeed(ws_manager)

"""WebSocket 路由 — 即時行情推送

R55-1: /ws/market WebSocket endpoint
- Client 連線後發送 subscribe/unsubscribe 訊息
- Server 推送 price_update 事件
- 支援 snapshot 請求（取得最新快取報價）
"""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.ws_manager import ws_manager, market_feed

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/market")
async def market_data_ws(websocket: WebSocket):
    """WebSocket endpoint for real-time market data.

    Client messages:
        {"type": "subscribe", "codes": ["2330", "2317"]}
        {"type": "unsubscribe", "codes": ["2330"]}
        {"type": "snapshot", "codes": ["2330"]}  # get cached quotes
        {"type": "ping"}

    Server messages:
        {"type": "price_update", "data": {...quote...}}
        {"type": "snapshot", "data": {"2330": {...}, ...}}
        {"type": "status", "data": {...feed status...}}
        {"type": "pong"}
        {"type": "error", "message": "..."}
    """
    conn_id = await ws_manager.connect(websocket)

    # Send initial status
    try:
        await websocket.send_json({
            "type": "status",
            "data": market_feed.get_status(),
        })
    except Exception:
        pass

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = msg.get("type", "")
            codes = msg.get("codes", [])

            if msg_type == "subscribe" and codes:
                await ws_manager.subscribe(conn_id, codes)
                # Send cached quotes immediately
                snapshots = {}
                for code in codes:
                    cached = market_feed.get_cached_quote(code)
                    if cached:
                        snapshots[code] = cached
                if snapshots:
                    await websocket.send_json({"type": "snapshot", "data": snapshots})

            elif msg_type == "unsubscribe" and codes:
                await ws_manager.unsubscribe(conn_id, codes)

            elif msg_type == "snapshot":
                snapshots = {}
                for code in codes:
                    cached = market_feed.get_cached_quote(code)
                    if cached:
                        snapshots[code] = cached
                await websocket.send_json({"type": "snapshot", "data": snapshots})

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "status":
                await websocket.send_json({
                    "type": "status",
                    "data": market_feed.get_status(),
                })

            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WS error for {conn_id}: {e}")
    finally:
        await ws_manager.disconnect(conn_id)


@router.get("/api/market/status")
def get_market_feed_status():
    """REST endpoint for market feed status monitoring."""
    return market_feed.get_status()


@router.get("/api/market/quote/{code}")
def get_cached_quote(code: str):
    """REST fallback: get last cached quote for a stock."""
    cached = market_feed.get_cached_quote(code)
    if cached:
        return cached
    return {"error": f"No cached quote for {code}"}

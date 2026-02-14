"""系統路由 — 快取狀態、最近股票"""

import json
from pathlib import Path
from fastapi import APIRouter

router = APIRouter()

RECENT_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "recent_stocks.json"


@router.get("/cache-stats")
def cache_stats():
    """取得快取統計"""
    from data.cache import get_cache_stats
    return get_cache_stats()


@router.post("/flush-cache")
def flush_cache():
    """清空所有快取"""
    from data.cache import flush_cache as _flush
    _flush()
    return {"ok": True}


@router.get("/recent-stocks")
def get_recent_stocks():
    """取得最近查看的股票"""
    try:
        if RECENT_FILE.exists():
            codes = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
            from data.stock_list import get_stock_name
            return [{"code": c, "name": get_stock_name(c)} for c in codes]
    except Exception:
        pass
    return []


@router.post("/recent-stocks/{code}")
def add_recent_stock(code: str):
    """記錄最近查看的股票"""
    codes = []
    try:
        if RECENT_FILE.exists():
            codes = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
    except Exception:
        codes = []

    if code in codes:
        codes.remove(code)
    codes.insert(0, code)
    codes = codes[:20]  # 最多保留 20 筆

    RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECENT_FILE.write_text(json.dumps(codes, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


@router.get("/worker-heartbeat")
def worker_heartbeat():
    """取得 Worker 心跳"""
    from data.cache import get_worker_heartbeat
    hb = get_worker_heartbeat()
    return hb or {"status": "offline"}


@router.get("/v4-params")
def get_v4_params():
    """取得 v4 策略預設參數"""
    from config import STRATEGY_V4_PARAMS
    return STRATEGY_V4_PARAMS


@router.get("/transition-alerts")
def get_transition_alerts(limit: int = 20):
    """取得 Maturity Transition 事件（Gemini R24 P2）

    Returns list of transition events, most recent first.
    High-value events: Leader stock upgrading maturity while sector is hot.
    """
    from data.cache import get_transition_events
    events = get_transition_events(limit=limit)
    # Return most recent first
    return list(reversed(events))

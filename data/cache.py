"""Redis 快取層

快取策略（市場感知）：
- 股價資料：盤中 15 分鐘，收盤後 60 分鐘
- 技術分析結果：盤中 15 分鐘，收盤後 60 分鐘
- 推薦掃描結果：TTL 10 分鐘
- 法人籌碼資料：TTL 60 分鐘
- 股票清單：TTL 24 小時
"""

import json
import redis
import pandas as pd
import numpy as np
from datetime import datetime


# Redis 連線（lazy init + cooldown）
_redis_client: redis.Redis | None = None
_redis_last_fail: float = 0
_REDIS_COOLDOWN = 30  # 連線失敗後 30 秒內不重試


def get_redis() -> redis.Redis | None:
    """取得 Redis 連線（連不上回傳 None，系統仍可正常運作）"""
    global _redis_client, _redis_last_fail

    # 冷卻期：避免 Redis 不在線時每次呼叫都等 timeout
    import time
    if _redis_client is None and _redis_last_fail > 0:
        if time.time() - _redis_last_fail < _REDIS_COOLDOWN:
            return None

    if _redis_client is not None:
        try:
            _redis_client.ping()
            return _redis_client
        except Exception:
            _redis_client = None

    try:
        _redis_client = redis.Redis(
            host="localhost",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        _redis_client.ping()
        _redis_last_fail = 0
        return _redis_client
    except Exception:
        _redis_client = None
        _redis_last_fail = time.time()
        return None


def _df_to_json(df: pd.DataFrame) -> str:
    """DataFrame 序列化為 JSON"""
    data = {
        "index": df.index.strftime("%Y-%m-%d").tolist(),
        "columns": df.columns.tolist(),
        "values": df.values.tolist(),
    }
    return json.dumps(data)


def _json_to_df(json_str: str) -> pd.DataFrame:
    """JSON 反序列化為 DataFrame"""
    data = json.loads(json_str)
    df = pd.DataFrame(
        data["values"],
        index=pd.to_datetime(data["index"]),
        columns=data["columns"],
    )
    df.index.name = "date"
    return df


def _market_aware_ttl(ttl_open: int = 900, ttl_closed: int = 3600) -> int:
    """根據台股開盤狀態回傳適當 TTL

    台股交易時間：週一至週五 09:00-13:30
    盤中 TTL 較短（預設 15 分鐘），收盤後較長（預設 60 分鐘）
    """
    now = datetime.now()
    weekday = now.weekday()  # 0=Mon, 6=Sun
    hour, minute = now.hour, now.minute
    time_val = hour * 60 + minute

    # 週末或非交易時間
    if weekday >= 5:
        return ttl_closed
    if time_val < 9 * 60 or time_val > 13 * 60 + 30:
        return ttl_closed
    return ttl_open


# ===== 股價資料快取 =====

def get_cached_stock_data(stock_code: str, period_days: int) -> pd.DataFrame | None:
    """從快取讀取股價資料"""
    r = get_redis()
    if r is None:
        return None

    key = f"stock_data:{stock_code}:{period_days}"
    try:
        cached = r.get(key)
        if cached:
            return _json_to_df(cached)
    except Exception:
        pass
    return None


def set_cached_stock_data(stock_code: str, period_days: int, df: pd.DataFrame, ttl: int | None = None) -> None:
    """寫入股價資料快取（預設使用市場感知 TTL）"""
    r = get_redis()
    if r is None:
        return

    if ttl is None:
        ttl = _market_aware_ttl(ttl_open=900, ttl_closed=3600)

    key = f"stock_data:{stock_code}:{period_days}"
    try:
        r.setex(key, ttl, _df_to_json(df))
    except Exception:
        pass


# ===== 分析結果快取 =====

def get_cached_analysis(stock_code: str) -> dict | None:
    """從快取讀取分析結果"""
    r = get_redis()
    if r is None:
        return None

    key = f"analysis:{stock_code}"
    try:
        cached = r.get(key)
        if cached:
            data = json.loads(cached)
            # 還原 date 欄位
            if "date" in data:
                data["date"] = pd.Timestamp(data["date"])
            return data
    except Exception:
        pass
    return None


def set_cached_analysis(stock_code: str, analysis: dict, ttl: int = 300) -> None:
    """寫入分析結果快取"""
    r = get_redis()
    if r is None:
        return

    key = f"analysis:{stock_code}"
    try:
        # 序列化 Timestamp 和 numpy 類型
        serializable = _make_serializable(analysis)
        r.setex(key, ttl, json.dumps(serializable, ensure_ascii=False))
    except Exception:
        pass


# ===== 推薦掃描快取 =====

def get_cached_scan_results() -> list[dict] | None:
    """從快取讀取推薦掃描結果"""
    r = get_redis()
    if r is None:
        return None

    try:
        cached = r.get("scan_results")
        if cached:
            results = json.loads(cached)
            for item in results:
                if "date" in item:
                    item["date"] = pd.Timestamp(item["date"])
            return results
    except Exception:
        pass
    return None


def set_cached_scan_results(results: list[dict], ttl: int = 600) -> None:
    """寫入推薦掃描結果快取"""
    r = get_redis()
    if r is None:
        return

    try:
        serializable = [_make_serializable(item) for item in results]
        r.setex("scan_results", ttl, json.dumps(serializable, ensure_ascii=False))
    except Exception:
        pass


# ===== 條件選股快取 =====

def get_cached_screener_results(conditions_hash: str) -> list[dict] | None:
    """從快取讀取條件選股結果"""
    r = get_redis()
    if r is None:
        return None

    key = f"screener:{conditions_hash}"
    try:
        cached = r.get(key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    return None


def set_cached_screener_results(conditions_hash: str, results: list[dict], ttl: int = 1800) -> None:
    """寫入條件選股結果快取（預設 30 分鐘）"""
    r = get_redis()
    if r is None:
        return

    try:
        serializable = [_make_serializable(item) for item in results]
        r.setex(key=f"screener:{conditions_hash}", time=ttl, value=json.dumps(serializable, ensure_ascii=False))
    except Exception:
        pass


# ===== 股票清單快取 =====

def get_cached_stock_list() -> dict[str, dict] | None:
    """從快取讀取股票清單"""
    r = get_redis()
    if r is None:
        return None

    try:
        cached = r.get("stock_list")
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    return None


def set_cached_stock_list(stocks: dict[str, dict], ttl: int = 86400) -> None:
    """寫入股票清單快取（預設 24 小時）"""
    r = get_redis()
    if r is None:
        return

    try:
        r.setex("stock_list", ttl, json.dumps(stocks, ensure_ascii=False))
    except Exception:
        pass


# ===== 法人籌碼快取 =====

def get_cached_institutional_data(stock_code: str) -> pd.DataFrame | None:
    """從快取讀取法人籌碼資料"""
    r = get_redis()
    if r is None:
        return None

    key = f"institutional:{stock_code}"
    try:
        cached = r.get(key)
        if cached:
            return _json_to_df(cached)
    except Exception:
        pass
    return None


def set_cached_institutional_data(stock_code: str, df: pd.DataFrame, ttl: int = 3600) -> None:
    """寫入法人籌碼資料快取（預設 60 分鐘）"""
    r = get_redis()
    if r is None:
        return

    key = f"institutional:{stock_code}"
    try:
        r.setex(key, ttl, _df_to_json(df))
    except Exception:
        pass


# ===== 工具函式 =====

def _make_serializable(obj):
    """將 numpy/pandas 類型轉為 JSON 可序列化的 Python 原生類型"""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_make_serializable(v) for v in obj]
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    elif isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    elif isinstance(obj, (np.bool_,)):
        return bool(obj)
    elif pd.isna(obj) if isinstance(obj, float) else False:
        return None
    return obj


def get_cache_stats() -> dict:
    """取得快取統計"""
    r = get_redis()
    if r is None:
        return {"status": "disconnected"}

    try:
        info = r.info("memory")
        keys = r.dbsize()
        return {
            "status": "connected",
            "keys": keys,
            "memory_used": info.get("used_memory_human", "N/A"),
            "memory_peak": info.get("used_memory_peak_human", "N/A"),
        }
    except Exception:
        return {"status": "error"}


def flush_cache() -> bool:
    """清空所有快取"""
    r = get_redis()
    if r is None:
        return False
    try:
        r.flushdb()
        return True
    except Exception:
        return False

"""快取層 — Redis（主）+ In-Memory（備援）

快取策略（市場感知）：
- 股價資料：盤中 15 分鐘，收盤後 60 分鐘
- 技術分析結果：盤中 15 分鐘，收盤後 60 分鐘
- 推薦掃描結果：TTL 10 分鐘
- 法人籌碼資料：TTL 60 分鐘
- 股票清單：TTL 24 小時

Redis 不可用時自動降級為 in-memory TTL 快取，
確保即使沒裝 Redis 系統仍有快取效果。
"""

import json
import time as _time
import threading
import redis
import pandas as pd
import numpy as np
from datetime import datetime


# ===== In-Memory TTL Cache (Redis 備援) =====

class _MemoryCache:
    """Thread-safe in-memory TTL cache，Redis 不可用時的備援方案

    - 最多保存 max_entries 筆，超過時淘汰過期 → 最舊
    - TTL 到期自動失效
    - 用於 Redis 無法連線時仍提供快取效果
    """

    def __init__(self, max_entries: int = 200):
        self._store: dict[str, tuple[float, str]] = {}  # key → (expiry_ts, value)
        self._lock = threading.Lock()
        self._max_entries = max_entries

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expiry, value = entry
            if _time.time() > expiry:
                del self._store[key]
                return None
            return value

    def setex(self, key: str, ttl: int, value: str) -> None:
        with self._lock:
            if len(self._store) >= self._max_entries:
                self._evict()
            self._store[key] = (_time.time() + ttl, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def flushdb(self) -> None:
        with self._lock:
            self._store.clear()

    def dbsize(self) -> int:
        with self._lock:
            now = _time.time()
            return sum(1 for exp, _ in self._store.values() if now <= exp)

    def _evict(self) -> None:
        """淘汰：先清過期，仍不足則移除最舊"""
        now = _time.time()
        expired = [k for k, (exp, _) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
        if len(self._store) >= self._max_entries:
            oldest = min(self._store, key=lambda k: self._store[k][0])
            del self._store[oldest]


_memory_cache = _MemoryCache()


# ===== Redis 連線（lazy init + cooldown + fast probe） =====

_redis_client: redis.Redis | None = None
_redis_last_fail: float = 0
_REDIS_COOLDOWN = 60  # 連線失敗後 60 秒內不重試


def _redis_port_open(host: str = "127.0.0.1", port: int = 6379, timeout: float = 0.1) -> bool:
    """快速探測 Redis port 是否可達（避免 Windows TCP 10 秒超時）"""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def get_redis() -> redis.Redis | None:
    """取得 Redis 連線（連不上回傳 None，系統仍可正常運作）"""
    global _redis_client, _redis_last_fail

    # 冷卻期：避免 Redis 不在線時每次呼叫都等 timeout
    if _redis_client is None and _redis_last_fail > 0:
        if _time.time() - _redis_last_fail < _REDIS_COOLDOWN:
            return None

    if _redis_client is not None:
        try:
            _redis_client.ping()
            return _redis_client
        except Exception:
            _redis_client = None

    # 快速探測 port：避免 Windows 上 socket_connect_timeout 無效（10-20 秒）
    if not _redis_port_open():
        _redis_last_fail = _time.time()
        return None

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
        _redis_last_fail = _time.time()
        return None


def _cache_get(key: str) -> str | None:
    """從快取讀取：Redis 優先，memory 備援"""
    r = get_redis()
    if r is not None:
        try:
            val = r.get(key)
            if val is not None:
                return val
        except Exception:
            pass
    return _memory_cache.get(key)


def _cache_set(key: str, value: str, ttl: int) -> None:
    """寫入快取：Redis + memory 雙寫（確保 memory 始終溫暖）"""
    r = get_redis()
    if r is not None:
        try:
            r.setex(key, ttl, value)
        except Exception:
            pass
    _memory_cache.setex(key, ttl, value)


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
    key = f"stock_data:{stock_code}:{period_days}"
    cached = _cache_get(key)
    if cached:
        try:
            return _json_to_df(cached)
        except Exception:
            pass
    return None


def set_cached_stock_data(stock_code: str, period_days: int, df: pd.DataFrame, ttl: int | None = None) -> None:
    """寫入股價資料快取（預設使用市場感知 TTL）"""
    if ttl is None:
        ttl = _market_aware_ttl(ttl_open=900, ttl_closed=3600)
    key = f"stock_data:{stock_code}:{period_days}"
    _cache_set(key, _df_to_json(df), ttl)


# ===== 分析結果快取 =====

def get_cached_analysis(stock_code: str) -> dict | None:
    """從快取讀取分析結果"""
    key = f"analysis:{stock_code}"
    cached = _cache_get(key)
    if cached:
        try:
            data = json.loads(cached)
            if "date" in data:
                data["date"] = pd.Timestamp(data["date"])
            return data
        except Exception:
            pass
    return None


def set_cached_analysis(stock_code: str, analysis: dict, ttl: int = 300) -> None:
    """寫入分析結果快取"""
    key = f"analysis:{stock_code}"
    try:
        serializable = _make_serializable(analysis)
        _cache_set(key, json.dumps(serializable, ensure_ascii=False), ttl)
    except Exception:
        pass


# ===== 推薦掃描快取 =====

def get_cached_scan_results() -> list[dict] | None:
    """從快取讀取推薦掃描結果"""
    cached = _cache_get("scan_results")
    if cached:
        try:
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
    try:
        serializable = [_make_serializable(item) for item in results]
        _cache_set("scan_results", json.dumps(serializable, ensure_ascii=False), ttl)
    except Exception:
        pass


# ===== 條件選股快取 =====

def get_cached_screener_results(conditions_hash: str) -> list[dict] | None:
    """從快取讀取條件選股結果"""
    key = f"screener:{conditions_hash}"
    cached = _cache_get(key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    return None


def set_cached_screener_results(conditions_hash: str, results: list[dict], ttl: int = 1800) -> None:
    """寫入條件選股結果快取（預設 30 分鐘）"""
    try:
        serializable = [_make_serializable(item) for item in results]
        _cache_set(f"screener:{conditions_hash}", json.dumps(serializable, ensure_ascii=False), ttl)
    except Exception:
        pass


# ===== 股票清單快取 =====

def get_cached_stock_list() -> dict[str, dict] | None:
    """從快取讀取股票清單"""
    cached = _cache_get("stock_list")
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    return None


def set_cached_stock_list(stocks: dict[str, dict], ttl: int = 86400) -> None:
    """寫入股票清單快取（預設 24 小時）"""
    try:
        _cache_set("stock_list", json.dumps(stocks, ensure_ascii=False), ttl)
    except Exception:
        pass


# ===== 法人籌碼快取 =====

def get_cached_institutional_data(stock_code: str) -> pd.DataFrame | None:
    """從快取讀取法人籌碼資料"""
    key = f"institutional:{stock_code}"
    cached = _cache_get(key)
    if cached:
        try:
            return _json_to_df(cached)
        except Exception:
            pass
    return None


def set_cached_institutional_data(stock_code: str, df: pd.DataFrame, ttl: int = 3600) -> None:
    """寫入法人籌碼資料快取（預設 60 分鐘）"""
    key = f"institutional:{stock_code}"
    _cache_set(key, _df_to_json(df), ttl)


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


# ===== Worker 心跳 =====

# ===== 產業熱度快取（Worker 專用） =====

def get_cached_sector_heat() -> dict | None:
    """讀取 Worker 計算的產業熱度數據

    Returns dict with keys: data (sector heat JSON), updated_at (ISO str), status (ok/error:...)
    """
    cached = _cache_get("sector_heat:data")
    if cached:
        try:
            data = json.loads(cached)
            # 附加 metadata
            updated_at = _cache_get("sector_heat:updated_at")
            status = _cache_get("sector_heat:status") or "ok"
            data["_updated_at"] = updated_at
            data["_status"] = status
            return data
        except Exception:
            pass
    return None


def set_cached_sector_heat(data: dict, ttl: int = 86400) -> None:
    """寫入產業熱度數據（Worker 呼叫）

    Args:
        data: sector heat result dict (sectors, scanned, total_buy)
        ttl: 預設 24 小時
    """
    try:
        serializable = _make_serializable(data)
        _cache_set("sector_heat:data", json.dumps(serializable, ensure_ascii=False), ttl)
        _cache_set("sector_heat:updated_at", datetime.now().isoformat(), ttl)
        _cache_set("sector_heat:status", "ok", ttl)
    except Exception:
        pass


def set_sector_heat_error(error_msg: str) -> None:
    """標記產業熱度掃描失敗（不清除舊數據）"""
    try:
        _cache_set("sector_heat:status", f"error:{error_msg}", 86400)
    except Exception:
        pass


def get_sector_heat_previous() -> dict | None:
    """讀取前次掃描的熱度數據（用於 Momentum 計算）"""
    cached = _cache_get("sector_heat:previous")
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    return None


def set_sector_heat_previous(heat_map: dict, ttl: int = 86400) -> None:
    """儲存當前熱度作為下次比對的基準

    Args:
        heat_map: {sector_name: weighted_heat_value}
        ttl: 24 小時
    """
    try:
        _cache_set("sector_heat:previous", json.dumps(heat_map, ensure_ascii=False), ttl)
    except Exception:
        pass


def set_worker_heartbeat(scan_count: int, stocks_scanned: int, buy_signals: int = 0) -> None:
    """Worker 更新心跳資訊"""
    try:
        data = {
            "last_scan_time": datetime.now().isoformat(),
            "scan_count": scan_count,
            "stocks_scanned": stocks_scanned,
            "buy_signals": buy_signals,
            "status": "running",
        }
        _cache_set("worker:heartbeat", json.dumps(data), 1800)
    except Exception:
        pass


def get_worker_heartbeat() -> dict | None:
    """讀取 Worker 心跳資訊"""
    cached = _cache_get("worker:heartbeat")
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    return None


# ===== Maturity Transition Events (Gemini R24 P2) =====

def get_stock_maturity_map() -> dict | None:
    """讀取前次掃描的每檔股票 maturity 狀態（用於 Transition 偵測）"""
    cached = _cache_get("sector_heat:stock_maturity")
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    return None


def set_stock_maturity_map(maturity_map: dict, ttl: int = 86400) -> None:
    """儲存當前每檔股票的 maturity（{code: maturity_str}）"""
    try:
        _cache_set("sector_heat:stock_maturity", json.dumps(maturity_map, ensure_ascii=False), ttl)
    except Exception:
        pass


def add_transition_event(event: dict, ttl: int = 86400) -> None:
    """新增 Maturity Transition 事件（單次觸發）

    event keys: code, name, from_maturity, to_maturity, sector, momentum,
                is_leader, leader_score, sector_heat, timestamp
    """
    try:
        # Read existing events
        cached = _cache_get("sector_heat:transitions")
        events = json.loads(cached) if cached else []

        # Single-fire: check if same code+transition already exists today
        event_key = f"{event['code']}:{event['from_maturity']}→{event['to_maturity']}"
        today = datetime.now().strftime("%Y-%m-%d")
        existing_keys = {
            f"{e['code']}:{e['from_maturity']}→{e['to_maturity']}"
            for e in events if e.get("date") == today
        }
        if event_key in existing_keys:
            return  # Already fired today

        event["date"] = today
        events.append(event)

        # Keep only last 50 events
        if len(events) > 50:
            events = events[-50:]

        _cache_set("sector_heat:transitions", json.dumps(events, ensure_ascii=False), ttl)
    except Exception:
        pass


def get_transition_events(limit: int = 20) -> list:
    """讀取最近的 Maturity Transition 事件"""
    cached = _cache_get("sector_heat:transitions")
    if cached:
        try:
            events = json.loads(cached)
            return events[-limit:]
        except Exception:
            pass
    return []


def clear_transition_events() -> None:
    """清除過期 Transition 事件（新交易日重置）

    高價值事件（is_high_value=True）保留 3 天，一般事件只保留當天。
    """
    try:
        cached = _cache_get("sector_heat:transitions")
        if not cached:
            return

        events = json.loads(cached)
        today = datetime.now().strftime("%Y-%m-%d")

        # Keep high-value events from last 3 days
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")

        retained = [
            e for e in events
            if e.get("is_high_value") and e.get("date", "") >= cutoff
        ]

        _cache_set("sector_heat:transitions", json.dumps(retained, ensure_ascii=False), 86400)
    except Exception:
        pass


# ===== Portfolio Exit Alerts (Gemini R25) =====

def get_portfolio_exit_alerts() -> list:
    """讀取倉位出場警報"""
    cached = _cache_get("portfolio:exit_alerts")
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    return []


def set_portfolio_exit_alerts(alerts: list, ttl: int = 86400) -> None:
    """儲存倉位出場警報"""
    try:
        _cache_set("portfolio:exit_alerts", json.dumps(alerts, ensure_ascii=False), ttl)
    except Exception:
        pass


# ===== Equity Ledger (Gemini R25: Daily Snapshot) =====

def get_equity_ledger() -> list:
    """讀取每日資產快照歷史"""
    cached = _cache_get("portfolio:equity_ledger")
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    return []


def append_equity_snapshot(snapshot: dict, ttl: int = 86400 * 365) -> None:
    """新增每日資產快照（去重：同日只保留最新）"""
    try:
        ledger = get_equity_ledger()
        today = snapshot.get("date", datetime.now().strftime("%Y-%m-%d"))

        # Replace if same date exists
        ledger = [s for s in ledger if s.get("date") != today]
        ledger.append(snapshot)

        # Keep last 365 days
        if len(ledger) > 365:
            ledger = ledger[-365:]

        _cache_set("portfolio:equity_ledger", json.dumps(ledger, ensure_ascii=False), ttl)
    except Exception:
        pass


def get_cache_stats() -> dict:
    """取得快取統計"""
    r = get_redis()
    if r is not None:
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
            pass

    # Memory cache fallback stats
    mem_keys = _memory_cache.dbsize()
    return {
        "status": "memory_fallback",
        "keys": mem_keys,
        "memory_used": "in-process",
        "memory_peak": "N/A",
    }


def flush_cache() -> bool:
    """清空所有快取（Redis + memory）"""
    _memory_cache.flushdb()
    r = get_redis()
    if r is not None:
        try:
            r.flushdb()
        except Exception:
            pass
    return True

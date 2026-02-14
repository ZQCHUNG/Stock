"""快取層測試 — In-Memory TTL Cache"""

import time
import json
import pandas as pd
import numpy as np
import pytest
from unittest.mock import patch

from data.cache import (
    _MemoryCache,
    _cache_get, _cache_set,
    _df_to_json, _json_to_df,
    _market_aware_ttl,
    get_cached_stock_data, set_cached_stock_data,
    get_cached_analysis, set_cached_analysis,
    get_cached_scan_results, set_cached_scan_results,
    get_cached_stock_list, set_cached_stock_list,
    get_cached_screener_results, set_cached_screener_results,
    get_cached_institutional_data, set_cached_institutional_data,
    get_cache_stats, flush_cache,
    set_worker_heartbeat, get_worker_heartbeat,
)


class TestMemoryCache:
    def test_basic_set_get(self):
        cache = _MemoryCache()
        cache.setex("key1", 60, "value1")
        assert cache.get("key1") == "value1"

    def test_missing_key(self):
        cache = _MemoryCache()
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        cache = _MemoryCache()
        cache.setex("key1", 1, "value1")
        assert cache.get("key1") == "value1"
        time.sleep(1.1)
        assert cache.get("key1") is None

    def test_overwrite(self):
        cache = _MemoryCache()
        cache.setex("key1", 60, "old")
        cache.setex("key1", 60, "new")
        assert cache.get("key1") == "new"

    def test_delete(self):
        cache = _MemoryCache()
        cache.setex("key1", 60, "value1")
        cache.delete("key1")
        assert cache.get("key1") is None

    def test_delete_nonexistent(self):
        cache = _MemoryCache()
        cache.delete("nonexistent")  # should not raise

    def test_flushdb(self):
        cache = _MemoryCache()
        cache.setex("a", 60, "1")
        cache.setex("b", 60, "2")
        cache.flushdb()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_dbsize(self):
        cache = _MemoryCache()
        assert cache.dbsize() == 0
        cache.setex("a", 60, "1")
        cache.setex("b", 60, "2")
        assert cache.dbsize() == 2

    def test_dbsize_excludes_expired(self):
        cache = _MemoryCache()
        cache.setex("live", 60, "1")
        cache.setex("dead", 1, "2")
        time.sleep(1.1)
        assert cache.dbsize() == 1

    def test_max_entries_eviction(self):
        cache = _MemoryCache(max_entries=3)
        cache.setex("a", 60, "1")
        cache.setex("b", 60, "2")
        cache.setex("c", 60, "3")
        # Adding 4th should evict oldest
        cache.setex("d", 60, "4")
        assert cache.dbsize() <= 3
        assert cache.get("d") == "4"

    def test_evicts_expired_first(self):
        cache = _MemoryCache(max_entries=3)
        cache.setex("expired", 1, "x")
        cache.setex("live1", 60, "1")
        cache.setex("live2", 60, "2")
        time.sleep(1.1)
        # Should evict expired entry, not live ones
        cache.setex("new", 60, "3")
        assert cache.get("live1") == "1"
        assert cache.get("live2") == "2"
        assert cache.get("new") == "3"


class TestDfSerialization:
    def _make_df(self):
        dates = pd.bdate_range("2024-01-01", periods=5)
        return pd.DataFrame({
            "open": [100.0, 101, 102, 103, 104],
            "close": [101.0, 102, 103, 104, 105],
            "volume": [1000.0, 2000, 3000, 4000, 5000],
        }, index=dates)

    def test_roundtrip(self):
        df = self._make_df()
        df.index.name = "date"
        json_str = _df_to_json(df)
        restored = _json_to_df(json_str)
        assert list(restored.columns) == list(df.columns)
        assert len(restored) == len(df)
        assert restored.index.name == "date"
        np.testing.assert_allclose(restored["close"].values, df["close"].values)


class TestMarketAwareTtl:
    def test_weekend_returns_closed(self):
        from unittest.mock import patch
        from datetime import datetime
        # Saturday
        with patch("data.cache.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 6, 10, 0)  # Saturday
            assert _market_aware_ttl(900, 3600) == 3600

    def test_market_hours_returns_open(self):
        from datetime import datetime
        with patch("data.cache.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 3, 10, 0)  # Wednesday 10:00
            assert _market_aware_ttl(900, 3600) == 900

    def test_after_market_returns_closed(self):
        from datetime import datetime
        with patch("data.cache.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 3, 15, 0)  # Wednesday 15:00
            assert _market_aware_ttl(900, 3600) == 3600


class TestCacheIntegrationNoRedis:
    """在 Redis 不可用時，透過 memory cache 仍可正常操作"""

    @pytest.fixture(autouse=True)
    def mock_no_redis(self):
        """模擬 Redis 不可用"""
        with patch("data.cache.get_redis", return_value=None):
            yield

    def test_stock_data_roundtrip(self):
        dates = pd.bdate_range("2024-01-01", periods=10)
        df = pd.DataFrame({
            "open": np.random.uniform(100, 110, 10),
            "high": np.random.uniform(110, 120, 10),
            "low": np.random.uniform(90, 100, 10),
            "close": np.random.uniform(100, 110, 10),
            "volume": np.random.randint(1000, 10000, 10).astype(float),
        }, index=dates)
        df.index.name = "date"

        set_cached_stock_data("2330", 365, df, ttl=60)
        result = get_cached_stock_data("2330", 365)
        assert result is not None
        assert len(result) == 10
        np.testing.assert_allclose(result["close"].values, df["close"].values)

    def test_analysis_roundtrip(self):
        analysis = {
            "signal": "BUY",
            "close": 150.5,
            "date": pd.Timestamp("2024-06-01"),
        }
        set_cached_analysis("2330", analysis, ttl=60)
        result = get_cached_analysis("2330")
        assert result is not None
        assert result["signal"] == "BUY"
        assert result["close"] == 150.5
        assert result["date"] == pd.Timestamp("2024-06-01")

    def test_scan_results_roundtrip(self):
        results = [
            {"code": "2330", "signal": "BUY", "close": 600.0, "date": pd.Timestamp("2024-06-01")},
            {"code": "2317", "signal": "BUY", "close": 130.0},
        ]
        set_cached_scan_results(results, ttl=60)
        cached = get_cached_scan_results()
        assert cached is not None
        assert len(cached) == 2
        assert cached[0]["code"] == "2330"

    def test_stock_list_roundtrip(self):
        stocks = {"2330": {"name": "台積電"}, "2317": {"name": "鴻海"}}
        set_cached_stock_list(stocks, ttl=60)
        result = get_cached_stock_list()
        assert result is not None
        assert "2330" in result
        assert result["2330"]["name"] == "台積電"

    def test_screener_results_roundtrip(self):
        results = [{"code": "2330", "score": 0.95}]
        set_cached_screener_results("hash123", results, ttl=60)
        cached = get_cached_screener_results("hash123")
        assert cached is not None
        assert cached[0]["code"] == "2330"

    def test_institutional_data_roundtrip(self):
        dates = pd.bdate_range("2024-06-01", periods=5)
        df = pd.DataFrame({
            "foreign_net": [1000, -2000, 3000, 500, -100],
            "trust_net": [200, 300, -100, 400, 500],
            "dealer_net": [-50, 100, 200, -300, 100],
            "total_net": [1150, -1600, 3100, 600, 500],
        }, index=dates)
        df.index.name = "date"

        set_cached_institutional_data("2330", df, ttl=60)
        result = get_cached_institutional_data("2330")
        assert result is not None
        assert len(result) == 5

    def test_worker_heartbeat_roundtrip(self):
        set_worker_heartbeat(scan_count=5, stocks_scanned=100, buy_signals=3)
        result = get_worker_heartbeat()
        assert result is not None
        assert result["scan_count"] == 5
        assert result["stocks_scanned"] == 100
        assert result["buy_signals"] == 3

    def test_cache_stats_memory_fallback(self):
        stats = get_cache_stats()
        assert stats["status"] == "memory_fallback"
        assert "keys" in stats

    def test_flush_cache(self):
        set_cached_stock_list({"test": {"name": "test"}}, ttl=60)
        assert get_cached_stock_list() is not None
        flush_cache()
        assert get_cached_stock_list() is None

    def test_miss_returns_none(self):
        assert get_cached_stock_data("9999", 365) is None
        assert get_cached_analysis("9999") is None
        assert get_cached_scan_results() is None
        assert get_cached_stock_list() is None
        assert get_cached_screener_results("nope") is None
        assert get_cached_institutional_data("9999") is None
        assert get_worker_heartbeat() is None

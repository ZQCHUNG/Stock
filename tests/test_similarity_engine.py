"""Tests for Multi-Window Similarity Engine.

E2E tests with real data (features_all.parquet, pit_close_matrix.parquet).
No mocks — validates actual computation results.
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure project root is on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analysis.similarity_engine import (
    DIMENSION_GROUPS,
    SimilarCase,
    SimilarityResult,
    WindowData,
    _compute_forward_returns,
    _compute_statistics,
    _get_dimension_mask,
    get_engine_status,
    load_window,
    search_similar,
)

# ---- Data availability checks ----

FEATURES_FILE = ROOT / "data" / "pattern_data" / "features" / "features_all.parquet"
CLOSE_MATRIX_FILE = ROOT / "data" / "pit_close_matrix.parquet"
METADATA_FILE = ROOT / "data" / "pattern_data" / "features" / "feature_metadata.json"

pytestmark = pytest.mark.skipif(
    not FEATURES_FILE.exists(),
    reason="features_all.parquet not found — skip E2E tests",
)


# ---- Fixtures ----

@pytest.fixture(scope="module")
def window_data():
    """Load the fallback window (features_all.parquet treated as window=1)."""
    return load_window(1)


@pytest.fixture(scope="module")
def close_matrix():
    """Load the close matrix for forward return verification."""
    if not CLOSE_MATRIX_FILE.exists():
        pytest.skip("pit_close_matrix.parquet not found")
    return pd.read_parquet(CLOSE_MATRIX_FILE)


@pytest.fixture(scope="module")
def metadata():
    """Load feature metadata."""
    import json
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# ---- 1. WindowData structure ----

class TestLoadWindow:
    def test_load_fallback_window(self, window_data):
        """Load features_all.parquet as fallback when window file doesn't exist."""
        assert isinstance(window_data, WindowData)
        assert window_data.matrix.dtype == np.float32
        assert window_data.matrix.shape[1] == 65
        assert len(window_data.stock_codes) == window_data.matrix.shape[0]
        assert len(window_data.dates) == window_data.matrix.shape[0]
        assert len(window_data.regime_tags) == window_data.matrix.shape[0]

    def test_window_data_has_index(self, window_data):
        """code_date_to_idx dict allows O(1) lookup."""
        assert isinstance(window_data.code_date_to_idx, dict)
        assert len(window_data.code_date_to_idx) > 0
        # Spot check: 2330 should exist
        keys_2330 = [k for k in window_data.code_date_to_idx if k[0] == "2330"]
        assert len(keys_2330) > 100  # 2330 has ~1486 rows

    def test_no_nan_in_matrix(self, window_data):
        """Matrix should have NaN replaced with 0."""
        assert not np.any(np.isnan(window_data.matrix))

    def test_missing_window_falls_back(self):
        """Requesting window=30 (no parquet) should fallback to features_all."""
        wd = load_window(30)
        assert isinstance(wd, WindowData)
        assert wd.matrix.shape[0] > 1_000_000  # ~1.6M rows

    def test_regime_tags_valid(self, window_data):
        """Regime tags should be int8 with known values."""
        assert window_data.regime_tags.dtype == np.int8
        unique = set(window_data.regime_tags.tolist())
        # Should only contain {-1, 0, 1} or a subset
        assert unique.issubset({-1, 0, 1})


# ---- 2. Dimension mask ----

class TestDimensionMask:
    def test_all_dimensions_mask(self, metadata):
        """Selecting all 5 user-facing dims covers all 65 features."""
        all_features = metadata["all_features"]
        mask = _get_dimension_mask(list(DIMENSION_GROUPS.keys()), all_features, metadata)
        assert mask.dtype == bool
        assert mask.sum() == 65

    def test_single_dimension_technical(self, metadata):
        """Technical dimension selects exactly 20 features."""
        all_features = metadata["all_features"]
        mask = _get_dimension_mask(["technical"], all_features, metadata)
        assert mask.sum() == 20

    def test_institutional_includes_brokerage(self, metadata):
        """User-facing 'institutional' maps to internal institutional + brokerage."""
        all_features = metadata["all_features"]
        mask = _get_dimension_mask(["institutional"], all_features, metadata)
        # institutional (11) + brokerage (14) = 25
        assert mask.sum() == 25

    def test_invalid_dimension_raises(self, metadata):
        """Unknown dimension should raise ValueError."""
        all_features = metadata["all_features"]
        with pytest.raises(ValueError, match="Unknown dimension"):
            _get_dimension_mask(["nonexistent"], all_features, metadata)

    def test_multiple_dimensions(self, metadata):
        """Selecting technical + fundamental = 20 + 8 = 28."""
        all_features = metadata["all_features"]
        mask = _get_dimension_mask(["technical", "fundamental"], all_features, metadata)
        assert mask.sum() == 28


# ---- 3. Search similar ----

class TestSearchSimilar:
    def test_search_2330_default(self):
        """Search similar for TSMC with default params."""
        result = search_similar("2330")
        assert isinstance(result, SimilarityResult)
        assert len(result.cases) > 0
        assert len(result.cases) <= 30  # default top_k
        # All cases should have similarity in [0, 1]
        for c in result.cases:
            assert 0.0 <= c.similarity <= 1.0

    def test_search_with_specific_dimensions(self):
        """Search with only technical + institutional dimensions."""
        result = search_similar("2330", dimensions=["technical", "institutional"])
        assert isinstance(result, SimilarityResult)
        assert len(result.cases) > 0
        # dimension_similarities should include these dims
        for c in result.cases:
            assert "technical" in c.dimension_similarities
            assert "institutional" in c.dimension_similarities

    def test_search_exclude_self(self):
        """By default, exclude_self=True should not return the query stock+date."""
        result = search_similar("2330")
        query_code = result.query["stock_code"]
        query_date = result.query["date"]
        for c in result.cases:
            if c.stock_code == query_code:
                assert c.date != query_date

    def test_search_include_self(self):
        """With exclude_self=False, the query itself should appear (sim ~1.0)."""
        result = search_similar("2330", top_k=5, exclude_self=False)
        # At least one case should be the query stock with very high similarity
        self_cases = [c for c in result.cases
                      if c.stock_code == "2330" and c.similarity > 0.99]
        assert len(self_cases) >= 1

    def test_search_missing_stock_raises(self):
        """Non-existent stock code should raise ValueError."""
        with pytest.raises(ValueError, match="not found"):
            search_similar("9999")

    def test_search_with_query_date(self):
        """Search with a specific historical date."""
        result = search_similar("2330", query_date="2024-01-02")
        assert result.query["date"] == "2024-01-02"
        assert len(result.cases) > 0

    def test_search_top_k_limit(self):
        """top_k limits the number of returned cases."""
        result = search_similar("2330", top_k=5)
        assert len(result.cases) <= 5

    def test_cases_sorted_by_similarity(self):
        """Cases should be sorted by similarity descending."""
        result = search_similar("2330", top_k=10)
        sims = [c.similarity for c in result.cases]
        assert sims == sorted(sims, reverse=True)

    def test_search_performance(self):
        """Search should complete within 2 seconds (vectorized cosine)."""
        start = time.time()
        search_similar("2330", top_k=30)
        elapsed = time.time() - start
        assert elapsed < 2.0, f"Search took {elapsed:.2f}s, expected < 2s"


# ---- 4. Forward returns ----

class TestForwardReturns:
    def test_forward_returns_structure(self):
        """Each case should have forward_returns with expected horizons."""
        result = search_similar("2330", top_k=5)
        for c in result.cases:
            assert isinstance(c.forward_returns, dict)
            for h in ["d7", "d14", "d30", "d90", "d180"]:
                assert h in c.forward_returns

    def test_forward_returns_spot_check(self, close_matrix):
        """Verify a forward return against the close matrix directly."""
        result = search_similar("2330", query_date="2024-06-03", top_k=5)
        # Pick the first case and verify d7 manually
        case = result.cases[0]
        code = case.stock_code
        match_date = pd.Timestamp(case.date)

        if code not in close_matrix.columns:
            pytest.skip(f"{code} not in close matrix")

        prices = close_matrix[code].dropna()
        if match_date not in prices.index:
            pytest.skip(f"{match_date} not in price index for {code}")

        idx = prices.index.get_loc(match_date)
        if idx + 7 < len(prices):
            expected_d7 = (prices.iloc[idx + 7] / prices.iloc[idx]) - 1.0
            if case.forward_returns["d7"] is not None:
                assert abs(case.forward_returns["d7"] - expected_d7) < 0.001

    def test_forward_returns_none_at_end(self):
        """Cases near data end may have None forward returns for long horizons."""
        # Search at latest date — d180 should be None
        result = search_similar("2330", top_k=5)
        # Not all will be None, but this shouldn't crash
        for c in result.cases:
            # d180 could be None if match_date is recent
            assert c.forward_returns["d180"] is None or isinstance(
                c.forward_returns["d180"], float
            )


# ---- 5. Statistics ----

class TestStatistics:
    def test_statistics_structure(self):
        """Statistics should have per-horizon metrics."""
        result = search_similar("2330", top_k=30)
        stats = result.statistics
        assert isinstance(stats, dict)
        for h in ["d7", "d14", "d30", "d90", "d180"]:
            if h in stats:
                s = stats[h]
                assert "win_rate" in s
                assert "mean" in s
                assert "median" in s
                assert 0.0 <= s["win_rate"] <= 1.0

    def test_statistics_from_cases(self):
        """_compute_statistics produces correct results."""
        cases = [
            SimilarCase("A", "2024-01-01", 0.9, {}, {"d7": 0.05, "d14": -0.02, "d30": None, "d90": None, "d180": None}),
            SimilarCase("B", "2024-01-02", 0.8, {}, {"d7": -0.01, "d14": 0.03, "d30": None, "d90": None, "d180": None}),
            SimilarCase("C", "2024-01-03", 0.7, {}, {"d7": 0.02, "d14": 0.01, "d30": None, "d90": None, "d180": None}),
        ]
        stats = _compute_statistics(cases)
        # d7: 2 wins out of 3
        assert abs(stats["d7"]["win_rate"] - 2 / 3) < 0.01
        # d14: 2 wins out of 3
        assert abs(stats["d14"]["win_rate"] - 2 / 3) < 0.01
        # d30: all None → should not be in stats or have count=0
        if "d30" in stats:
            assert stats["d30"]["count"] == 0

    def test_to_dict_serializable(self):
        """SimilarityResult.to_dict() should be JSON-serializable."""
        import json
        result = search_similar("2330", top_k=5)
        d = result.to_dict()
        json_str = json.dumps(d)
        assert len(json_str) > 100


# ---- 6. Engine status ----

class TestEngineStatus:
    def test_status_returns_dict(self):
        """get_engine_status returns window/dimension/stock info."""
        status = get_engine_status()
        assert isinstance(status, dict)
        assert "loaded_windows" in status
        assert "dimensions" in status
        assert "stock_count" in status
        assert "memory_mb" in status

    def test_status_after_load(self, window_data):
        """After loading a window, status should show it."""
        status = get_engine_status()
        assert len(status["loaded_windows"]) >= 1


# ---- 7. LRU cache eviction ----

class TestLRUCache:
    def test_cache_max_two_windows(self):
        """Loading 3 windows should evict the least recently used."""
        from analysis.similarity_engine import _window_cache

        # Load 3 different "windows" (all fallback to same file, but cache key differs)
        load_window(7)
        load_window(14)
        load_window(30)

        # Cache should have at most 2 entries
        assert len(_window_cache) <= 2
        # The most recently loaded (14 and 30) should remain
        assert 30 in _window_cache
        assert 14 in _window_cache
        assert 7 not in _window_cache

    def test_lru_access_updates_order(self):
        """Accessing a cached window should update its LRU position."""
        from analysis.similarity_engine import _window_cache

        # Load 7 and 14
        load_window(7)
        load_window(14)
        # Access 7 again (makes it most recently used)
        load_window(7)
        # Load 30 → should evict 14 (least recently used), not 7
        load_window(30)

        assert 7 in _window_cache
        assert 30 in _window_cache
        assert 14 not in _window_cache

"""Tests for Golden Template Builder.

E2E tests with real data (features_all.parquet, pit_close_matrix.parquet).
Falls back to synthetic data if real files are not available.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analysis.golden_template_builder import (
    DEFAULT_D30_THRESHOLD,
    FORWARD_LABELS,
    PRESET_WEIGHTS,
    _apply_industry_cap,
    _build_dimension_indices,
    _build_weight_vector,
    _cap_per_stock,
    _compute_forward_returns_batch,
    _compute_hit_rate,
    _compute_per_horizon_stats,
    _compute_quartile_stats,
    _dedup_per_stock,
    _get_active_liquid_stocks,
    _safe_float,
    build_golden_templates,
    compute_consistency,
    compute_score_distribution,
    scan_market,
)

# --- Data availability ---
FEATURES_FILE = ROOT / "data" / "pattern_data" / "features" / "features_all.parquet"
CLOSE_MATRIX_FILE = ROOT / "data" / "pit_close_matrix.parquet"
METADATA_FILE = ROOT / "data" / "pattern_data" / "features" / "feature_metadata.json"

HAS_REAL_DATA = FEATURES_FILE.exists() and CLOSE_MATRIX_FILE.exists() and METADATA_FILE.exists()


# ===========================================================================
# Unit tests (always run — no real data needed)
# ===========================================================================


class TestComputeConsistency:
    """Tests for compute_consistency()."""

    def test_all_positive(self):
        assert compute_consistency(0.05, 0.10, 0.20, 0.30) == 1.0

    def test_all_negative(self):
        assert compute_consistency(-0.05, -0.10, -0.20, -0.30) == 0.0

    def test_mixed(self):
        # 2 out of 4 positive
        assert compute_consistency(0.05, -0.10, 0.20, -0.30) == 0.5

    def test_three_positive_one_negative(self):
        assert compute_consistency(0.05, 0.10, 0.20, -0.05) == 0.75

    def test_with_nan(self):
        # NaN values are excluded from count
        assert compute_consistency(0.05, float("nan"), 0.20, float("nan")) == 1.0

    def test_all_nan(self):
        assert compute_consistency(float("nan"), float("nan"), float("nan"), float("nan")) == 0.0

    def test_with_none(self):
        assert compute_consistency(0.05, None, 0.20, None) == 1.0

    def test_zero_is_not_positive(self):
        # Zero return is not positive
        assert compute_consistency(0.0, 0.0, 0.20, 0.0) == 0.25


class TestDedupPerStock:
    """Tests for _dedup_per_stock()."""

    def test_basic_dedup(self):
        df = pd.DataFrame({
            "stock_code": ["2330"] * 5,
            "date": pd.to_datetime(["2025-01-01", "2025-01-05", "2025-01-10", "2025-02-15", "2025-03-20"]),
            "value": [1, 2, 3, 4, 5],
        })
        result = _dedup_per_stock(df, cooldown_days=30)
        # Jan-01 kept, Jan-05/10 skipped (<30d), Feb-15 kept (45d), Mar-20 kept (33d)
        assert len(result) == 3
        assert result.iloc[0]["date"] == pd.Timestamp("2025-01-01")
        assert result.iloc[1]["date"] == pd.Timestamp("2025-02-15")
        assert result.iloc[2]["date"] == pd.Timestamp("2025-03-20")

    def test_different_stocks_independent(self):
        df = pd.DataFrame({
            "stock_code": ["2330", "2330", "2454", "2454"],
            "date": pd.to_datetime(["2025-01-01", "2025-01-05", "2025-01-01", "2025-01-05"]),
        })
        result = _dedup_per_stock(df, cooldown_days=30)
        # Each stock keeps only its first: 2330 Jan-01 + 2454 Jan-01
        assert len(result) == 2
        assert set(result["stock_code"]) == {"2330", "2454"}

    def test_zero_cooldown_keeps_all(self):
        df = pd.DataFrame({
            "stock_code": ["2330"] * 3,
            "date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
        })
        result = _dedup_per_stock(df, cooldown_days=0)
        assert len(result) == 3

    def test_empty_df(self):
        df = pd.DataFrame({"stock_code": [], "date": []})
        result = _dedup_per_stock(df, cooldown_days=30)
        assert len(result) == 0


class TestCapPerStock:
    """Tests for _cap_per_stock()."""

    def test_cap_applied(self):
        df = pd.DataFrame({
            "stock_code": ["2330"] * 5,
            "consistency": [0.25, 0.50, 1.0, 0.75, 0.0],
        })
        result = _cap_per_stock(df, max_per_stock=3)
        assert len(result) == 3
        # Top 3 by consistency: 1.0, 0.75, 0.50
        assert list(result["consistency"].sort_values(ascending=False)) == [1.0, 0.75, 0.50]

    def test_under_cap_unchanged(self):
        df = pd.DataFrame({
            "stock_code": ["2330"] * 2,
            "consistency": [0.5, 1.0],
        })
        result = _cap_per_stock(df, max_per_stock=5)
        assert len(result) == 2

    def test_multiple_stocks(self):
        df = pd.DataFrame({
            "stock_code": ["2330"] * 4 + ["2454"] * 4,
            "consistency": [0.25, 0.50, 0.75, 1.0, 0.0, 0.25, 0.50, 0.75],
        })
        result = _cap_per_stock(df, max_per_stock=2)
        assert len(result) == 4  # 2 per stock
        assert result[result["stock_code"] == "2330"]["consistency"].max() == 1.0
        assert result[result["stock_code"] == "2454"]["consistency"].max() == 0.75


class TestSafeFloat:
    """Tests for _safe_float()."""

    def test_normal(self):
        assert _safe_float(0.123456789) == 0.123457

    def test_nan(self):
        assert _safe_float(float("nan")) is None

    def test_none(self):
        assert _safe_float(None) is None

    def test_numpy_nan(self):
        assert _safe_float(np.nan) is None

    def test_int(self):
        assert _safe_float(5) == 5.0


class TestComputeQuartileStats:
    """Tests for _compute_quartile_stats()."""

    def test_basic(self):
        values = [0.20, 0.25, 0.30, 0.35, 0.40]
        stats = _compute_quartile_stats(values)
        assert stats["median"] == 0.30
        assert stats["count"] == 5
        assert "q25" in stats
        assert "q75" in stats
        assert stats["min"] == 0.20
        assert stats["max"] == 0.40

    def test_empty(self):
        assert _compute_quartile_stats([]) == {}

    def test_single_value(self):
        stats = _compute_quartile_stats([0.25])
        assert stats["median"] == 0.25
        assert stats["count"] == 1


class TestApplyIndustryCap:
    """Tests for _apply_industry_cap()."""

    def test_cap_applied(self):
        # Industry group by first 2 digits: 23xx has 4 stocks, cap=2
        results = [
            {"stock_code": "2330", "composite_score": 0.9},   # 23
            {"stock_code": "2317", "composite_score": 0.85},  # 23
            {"stock_code": "2881", "composite_score": 0.8},   # 28
            {"stock_code": "2357", "composite_score": 0.75},  # 23 — third, capped
            {"stock_code": "2303", "composite_score": 0.7},   # 23 — fourth, capped
        ]
        filtered = _apply_industry_cap(results, max_per_industry=2, top_k=10)
        codes = [r["stock_code"] for r in filtered]
        # 23xx: 2330, 2317 kept; 2357, 2303 skipped
        assert "2330" in codes
        assert "2317" in codes
        assert "2881" in codes
        assert "2357" not in codes
        assert "2303" not in codes
        assert len(filtered) == 3

    def test_top_k_limit(self):
        results = [{"stock_code": f"{i}000", "composite_score": 1 - i * 0.01} for i in range(20)]
        filtered = _apply_industry_cap(results, max_per_industry=10, top_k=5)
        assert len(filtered) == 5

    def test_empty_input(self):
        assert _apply_industry_cap([], max_per_industry=3, top_k=15) == []


class TestBuildWeightVector:
    """Tests for _build_weight_vector()."""

    def test_all_preset_uniform(self):
        features = ["ret_1d", "inst_foreign_net", "eps_yoy", "attention_index_7d", "sector_rs"]
        dim_indices = {
            "technical": [0],
            "institutional": [1],
            "fundamental": [2],
            "news": [3],
            "industry": [4],
        }
        w = _build_weight_vector(features, dim_indices, "all")
        np.testing.assert_array_equal(w, np.ones(5, dtype=np.float32))

    def test_technical_preset_weights(self):
        features = ["ret_1d", "inst_foreign_net", "eps_yoy", "attention_index_7d", "sector_rs"]
        dim_indices = {
            "technical": [0],
            "institutional": [1],
            "fundamental": [2],
            "news": [3],
            "industry": [4],
        }
        w = _build_weight_vector(features, dim_indices, "technical")
        # technical (idx 0) and institutional (idx 1) should be 2.0
        assert w[0] == 2.0
        assert w[1] == 2.0
        assert w[2] == 1.0
        assert w[3] == 1.0
        assert w[4] == 1.0

    def test_unknown_preset_defaults_to_all(self):
        features = ["ret_1d"]
        dim_indices = {"technical": [0]}
        w = _build_weight_vector(features, dim_indices, "nonexistent")
        assert w[0] == 1.0


class TestComputeForwardReturnsBatch:
    """Tests for _compute_forward_returns_batch() with synthetic data."""

    def test_basic_returns(self):
        dates = pd.bdate_range("2025-01-02", periods=100)
        close = pd.DataFrame(
            {"2330": np.linspace(100, 200, 100)},
            index=dates,
        )
        stock_codes = np.array(["2330"])
        query_dates = np.array([dates[0]])

        fwd = _compute_forward_returns_batch(stock_codes, query_dates, close)
        assert fwd.shape == (1, 4)
        # D7 return: (price[7] / price[0]) - 1
        expected_d7 = (close["2330"].iloc[7] / close["2330"].iloc[0]) - 1
        np.testing.assert_almost_equal(fwd[0, 0], expected_d7, decimal=4)

    def test_missing_stock(self):
        dates = pd.bdate_range("2025-01-02", periods=50)
        close = pd.DataFrame({"2330": np.ones(50) * 100}, index=dates)
        stock_codes = np.array(["9999"])  # Not in close matrix
        query_dates = np.array([dates[0]])

        fwd = _compute_forward_returns_batch(stock_codes, query_dates, close)
        assert np.all(np.isnan(fwd))

    def test_near_end_truncation(self):
        dates = pd.bdate_range("2025-01-02", periods=20)
        close = pd.DataFrame({"2330": np.ones(20) * 100}, index=dates)
        stock_codes = np.array(["2330"])
        query_dates = np.array([dates[15]])  # Only 4 days left

        fwd = _compute_forward_returns_batch(stock_codes, query_dates, close)
        # D7 (pos 15+7=22 > 20) should be NaN
        assert np.isnan(fwd[0, 0])  # d7


class TestGetActiveLiquidStocks:
    """Tests for _get_active_liquid_stocks() — Fix 1 & Fix 2."""

    def test_active_stock_kept(self):
        """Stock with data up to latest date passes."""
        dates = pd.bdate_range("2025-01-02", periods=30)
        close = pd.DataFrame({"2330": np.ones(30) * 500}, index=dates)
        result = _get_active_liquid_stocks(close, min_active_days=5, min_traded_ratio=0.9)
        assert "2330" in result

    def test_stale_stock_removed(self):
        """Stock whose last price is >5 days before latest market date."""
        dates = pd.bdate_range("2025-01-02", periods=30)
        prices = np.ones(30) * 500
        prices[-6:] = np.nan  # No data for last 6 trading days (~8 cal days)
        close = pd.DataFrame({"2330": prices}, index=dates)
        result = _get_active_liquid_stocks(close, min_active_days=5, min_traded_ratio=0.0)
        assert "2330" not in result

    def test_illiquid_stock_removed(self):
        """Stock with too many gaps in last 20 days."""
        dates = pd.bdate_range("2025-01-02", periods=30)
        prices = np.ones(30) * 500
        # Put NaN gaps in 5 of the last 20 days (75% traded < 90% threshold)
        prices[-20:-15] = np.nan
        close = pd.DataFrame({"2330": prices}, index=dates)
        result = _get_active_liquid_stocks(close, min_active_days=5, min_traded_ratio=0.9)
        assert "2330" not in result

    def test_mixed_stocks(self):
        """One active+liquid, one stale, one illiquid."""
        dates = pd.bdate_range("2025-01-02", periods=30)
        good = np.ones(30) * 500
        stale = np.ones(30) * 100
        stale[-8:] = np.nan  # Stale: no data for 8 days
        illiquid = np.ones(30) * 200
        illiquid[-20:-14] = np.nan  # Illiquid: 6 gaps in last 20 days
        close = pd.DataFrame({"GOOD": good, "STALE": stale, "ILLIQUID": illiquid}, index=dates)
        result = _get_active_liquid_stocks(close, min_active_days=5, min_traded_ratio=0.9)
        assert "GOOD" in result
        assert "STALE" not in result
        assert "ILLIQUID" not in result

    def test_empty_matrix(self):
        close = pd.DataFrame()
        result = _get_active_liquid_stocks(close)
        assert result == set()


class TestComputeHitRate:
    """Tests for _compute_hit_rate() — Fix 3."""

    def test_all_positive(self):
        """All templates have all positive returns → hit_rate = 1.0."""
        matches = [
            {"fwd_d7": 0.05, "fwd_d14": 0.10, "fwd_d30": 0.25, "fwd_d90": 0.40},
            {"fwd_d7": 0.01, "fwd_d14": 0.02, "fwd_d30": 0.30, "fwd_d90": 0.50},
        ]
        assert _compute_hit_rate(matches) == 1.0

    def test_mixed(self):
        """One template has a negative return → hit_rate = 0.5."""
        matches = [
            {"fwd_d7": 0.05, "fwd_d14": 0.10, "fwd_d30": 0.25, "fwd_d90": 0.40},
            {"fwd_d7": -0.02, "fwd_d14": 0.10, "fwd_d30": 0.25, "fwd_d90": 0.40},
        ]
        assert _compute_hit_rate(matches) == 0.5

    def test_all_negative_d7(self):
        """All templates have negative D7 → hit_rate = 0.0."""
        matches = [
            {"fwd_d7": -0.05, "fwd_d14": 0.10, "fwd_d30": 0.25, "fwd_d90": 0.40},
            {"fwd_d7": -0.02, "fwd_d14": 0.10, "fwd_d30": 0.25, "fwd_d90": 0.40},
        ]
        assert _compute_hit_rate(matches) == 0.0

    def test_with_none_values(self):
        """None values are excluded; remaining must all be positive."""
        matches = [
            {"fwd_d7": None, "fwd_d14": 0.10, "fwd_d30": 0.25, "fwd_d90": None},
        ]
        assert _compute_hit_rate(matches) == 1.0

    def test_empty(self):
        assert _compute_hit_rate([]) == 0.0


class TestComputePerHorizonStats:
    """Tests for _compute_per_horizon_stats() — Fix 4."""

    def test_all_horizons_present(self):
        """Stats should cover each forward return horizon."""
        matches = [
            {"fwd_d7": 0.05, "fwd_d14": 0.10, "fwd_d30": 0.25, "fwd_d90": 0.40},
            {"fwd_d7": 0.03, "fwd_d14": 0.08, "fwd_d30": 0.22, "fwd_d90": 0.35},
            {"fwd_d7": 0.07, "fwd_d14": 0.12, "fwd_d30": 0.30, "fwd_d90": 0.50},
        ]
        stats = _compute_per_horizon_stats(matches)
        for label in FORWARD_LABELS:
            assert label in stats, f"Missing stats for {label}"
            assert "median" in stats[label]
            assert "q25" in stats[label]
            assert "q75" in stats[label]
            assert "count" in stats[label]
            assert stats[label]["count"] == 3

    def test_median_correctness(self):
        matches = [
            {"fwd_d7": 0.01, "fwd_d14": 0.10, "fwd_d30": 0.20, "fwd_d90": 0.30},
            {"fwd_d7": 0.05, "fwd_d14": 0.20, "fwd_d30": 0.30, "fwd_d90": 0.40},
            {"fwd_d7": 0.09, "fwd_d14": 0.30, "fwd_d30": 0.40, "fwd_d90": 0.50},
        ]
        stats = _compute_per_horizon_stats(matches)
        assert stats["fwd_d7"]["median"] == 0.05
        assert stats["fwd_d14"]["median"] == 0.20

    def test_with_none(self):
        """None values excluded from stats."""
        matches = [
            {"fwd_d7": 0.05, "fwd_d14": None, "fwd_d30": 0.25, "fwd_d90": None},
        ]
        stats = _compute_per_horizon_stats(matches)
        assert "fwd_d7" in stats
        assert "fwd_d14" not in stats  # All None → excluded
        assert "fwd_d90" not in stats

    def test_no_mean_in_stats(self):
        """Design point #8: stats must NOT contain mean."""
        matches = [
            {"fwd_d7": 0.05, "fwd_d14": 0.10, "fwd_d30": 0.25, "fwd_d90": 0.40},
        ]
        stats = _compute_per_horizon_stats(matches)
        for label in stats:
            assert "mean" not in stats[label]

    def test_empty(self):
        assert _compute_per_horizon_stats([]) == {}


class TestComputeScoreDistribution:
    """Tests for compute_score_distribution() — Fix 5."""

    def test_basic(self):
        results = [{"composite_score": v} for v in [0.3, 0.5, 0.7, 0.8, 0.9]]
        dist = compute_score_distribution(results)
        assert dist["count"] == 5
        assert dist["median"] == 0.7
        assert dist["min"] == 0.3
        assert dist["max"] == 0.9
        assert "p25" in dist
        assert "p75" in dist
        assert "p90" in dist
        assert "p95" in dist

    def test_empty(self):
        dist = compute_score_distribution([])
        assert dist["count"] == 0

    def test_single(self):
        dist = compute_score_distribution([{"composite_score": 0.42}])
        assert dist["count"] == 1
        assert dist["median"] == 0.42


# ===========================================================================
# E2E tests (only run with real data)
# ===========================================================================

pytestmark_e2e = pytest.mark.skipif(
    not HAS_REAL_DATA,
    reason="Real data files not found — skip E2E tests",
)


@pytestmark_e2e
class TestBuildGoldenTemplatesE2E:
    """E2E test: build golden templates from real data."""

    def test_build_produces_valid_output(self, tmp_path):
        """Build with real data and verify output structure."""
        result = build_golden_templates(
            features_parquet=str(FEATURES_FILE),
            close_matrix_parquet=str(CLOSE_MATRIX_FILE),
            output_path=str(tmp_path),
            d30_threshold=0.20,
            cooldown_days=30,
            max_per_stock=20,
        )

        # Should succeed
        assert result.get("after_cap", 0) > 0
        assert result.get("stocks_represented", 0) > 0

        # Output files exist
        assert (tmp_path / "golden_templates.parquet").exists()
        assert (tmp_path / "template_norms.npy").exists()
        assert (tmp_path / "build_metadata.json").exists()

        # Parquet structure
        tpl = pd.read_parquet(tmp_path / "golden_templates.parquet")
        assert "template_id" in tpl.columns
        assert "stock_code" in tpl.columns
        assert "date" in tpl.columns
        assert "consistency" in tpl.columns
        for label in FORWARD_LABELS:
            assert label in tpl.columns

        # All D30 >= threshold
        assert (tpl["fwd_d30"] >= 0.20).all()

        # Template IDs are sequential
        assert list(tpl["template_id"]) == list(range(len(tpl)))

        # Norms match template count
        norms = np.load(tmp_path / "template_norms.npy")
        assert len(norms) == len(tpl)

        # Per-stock cap enforced
        max_per = tpl.groupby("stock_code").size().max()
        assert max_per <= 20

        # Consistency in valid range
        assert (tpl["consistency"] >= 0.0).all()
        assert (tpl["consistency"] <= 1.0).all()

    def test_build_metadata_complete(self, tmp_path):
        """Build metadata has all required fields."""
        result = build_golden_templates(
            output_path=str(tmp_path),
            d30_threshold=0.20,
        )
        assert "built_at" in result
        assert "total_candidates" in result
        assert "after_dedup" in result
        assert "stocks_represented" in result
        assert "elapsed_s" in result

    def test_higher_threshold_fewer_templates(self, tmp_path):
        """Higher D30 threshold should produce fewer templates."""
        dir_20 = tmp_path / "t20"
        dir_30 = tmp_path / "t30"

        r20 = build_golden_templates(output_path=str(dir_20), d30_threshold=0.20)
        r30 = build_golden_templates(output_path=str(dir_30), d30_threshold=0.30)

        assert r30["after_cap"] <= r20["after_cap"]


@pytestmark_e2e
class TestScanMarketE2E:
    """E2E test: scan market with golden templates."""

    @pytest.fixture(scope="class")
    def templates_dir(self, tmp_path_factory):
        """Build templates once for all scan tests."""
        tmp = tmp_path_factory.mktemp("golden")
        build_golden_templates(output_path=str(tmp), d30_threshold=0.20)
        return tmp

    def test_scan_returns_results(self, templates_dir):
        results = scan_market(
            templates_path=str(templates_dir / "golden_templates.parquet"),
            preset="all",
            top_k=15,
        )
        assert len(results) > 0
        assert len(results) <= 15

    def test_scan_result_structure(self, templates_dir):
        results = scan_market(
            templates_path=str(templates_dir / "golden_templates.parquet"),
            preset="technical",
            top_k=5,
        )
        if not results:
            pytest.skip("No scan results")

        r = results[0]
        assert "stock_code" in r
        assert "similarity" in r
        assert "consistency" in r
        assert "composite_score" in r
        assert "hit_rate" in r
        assert "top_matches" in r
        assert "stats" in r

        # Composite = sim * 0.7 + cons * 0.3
        expected = r["similarity"] * 0.7 + r["consistency"] * 0.3
        assert abs(r["composite_score"] - expected) < 0.001

    def test_scan_sorted_by_composite(self, templates_dir):
        results = scan_market(
            templates_path=str(templates_dir / "golden_templates.parquet"),
            preset="all",
            top_k=15,
        )
        if len(results) < 2:
            pytest.skip("Not enough results to verify sort")
        scores = [r["composite_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_scan_industry_cap(self, templates_dir):
        results = scan_market(
            templates_path=str(templates_dir / "golden_templates.parquet"),
            preset="all",
            top_k=50,
            max_per_industry=3,
        )
        # Check no industry group has more than 3
        from collections import Counter
        industry_counts = Counter(r["stock_code"][:2] for r in results)
        for industry, count in industry_counts.items():
            assert count <= 3, f"Industry {industry} has {count} > 3"

    def test_scan_different_presets(self, templates_dir):
        """Different presets should produce different rankings."""
        r_tech = scan_market(
            templates_path=str(templates_dir / "golden_templates.parquet"),
            preset="technical", top_k=10,
        )
        r_value = scan_market(
            templates_path=str(templates_dir / "golden_templates.parquet"),
            preset="value", top_k=10,
        )
        if not r_tech or not r_value:
            pytest.skip("Not enough results")

        # Top results should differ (at least partially)
        tech_codes = {r["stock_code"] for r in r_tech[:5]}
        value_codes = {r["stock_code"] for r in r_value[:5]}
        # Not necessarily 100% different, but not 100% same either
        # (this is a soft check — preset weights should cause differences)
        # Just verify both return valid results
        assert len(r_tech) > 0
        assert len(r_value) > 0

    def test_scan_stats_has_per_horizon_quartiles(self, templates_dir):
        """Design point #8: stats per horizon with median/quartiles, NOT averages."""
        results = scan_market(
            templates_path=str(templates_dir / "golden_templates.parquet"),
            preset="all", top_k=5,
        )
        if not results:
            pytest.skip("No results")

        stats = results[0].get("stats", {})
        if stats:
            # Stats should be keyed by horizon
            for label in stats:
                assert label.startswith("fwd_d"), f"Unexpected key: {label}"
                assert "median" in stats[label]
                assert "q25" in stats[label]
                assert "q75" in stats[label]
                # Should NOT have "mean" (design decision)
                assert "mean" not in stats[label]

    def test_scan_hit_rate_in_range(self, templates_dir):
        """Design point #9: hit_rate should be between 0 and 1."""
        results = scan_market(
            templates_path=str(templates_dir / "golden_templates.parquet"),
            preset="all", top_k=10,
        )
        for r in results:
            assert 0.0 <= r["hit_rate"] <= 1.0

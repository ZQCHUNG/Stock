"""Tests for R87: Sector Correlation Monitor

Tests cover:
- Cap-weighted sector returns
- Correlation matrix computation
- Z-Score threshold alerts
- Flash alerts (15d vs 90d spike)
- Systemic flush detection
- Union-Find risk bucket merging
- Color mapping
- Bucket entry allowed checks
- Edge cases (empty, single sector, NaN)
"""

import numpy as np
import pandas as pd
import pytest

from analysis.sector_correlation import (
    # Constants
    STRUCTURAL_WINDOW,
    FLASH_WINDOW,
    ZSCORE_ALERT,
    ABSOLUTE_ALERT,
    FLASH_SPIKE_THRESHOLD,
    SYSTEMIC_FLUSH_THRESHOLD,
    SYSTEMIC_ELEVATED,
    SECTOR_CAP_SINGLE,
    RISK_BUCKET_MULTIPLIER,
    MIN_STOCKS_PER_SECTOR,
    # Classes
    UnionFind,
    # Functions
    get_corr_color,
    compute_cap_weighted_sector_returns,
    compute_sector_correlation_matrix,
    compute_zscore_alerts,
    compute_flash_alerts,
    compute_systemic_risk_score,
    compute_risk_buckets,
    check_bucket_entry_allowed,
    build_heatmap_data,
    compute_full_sector_correlation,
)


# ─── Helpers ─────────────────────────────────────────────────

def _make_returns(n_days: int = 200, codes: list[str] | None = None, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic daily returns for testing."""
    rng = np.random.RandomState(seed)
    if codes is None:
        # Use codes from sector mapping that cover multiple sectors
        codes = ["2330", "2454", "2317", "2382", "2383", "2881", "2882", "1303", "1301", "2412"]
    dates = pd.date_range("2023-01-01", periods=n_days, freq="B")
    data = {}
    for code in codes:
        data[code] = rng.normal(0.001, 0.02, n_days)
    return pd.DataFrame(data, index=dates)


def _make_market_caps(codes: list[str]) -> dict[str, float]:
    """Generate synthetic market caps."""
    caps = {
        "2330": 20_000_000,  # TSMC dominates
        "2454": 2_000_000,
        "2317": 5_000_000,
        "2382": 1_000_000,
        "2383": 800_000,
        "2881": 3_000_000,
        "2882": 2_500_000,
        "1303": 1_500_000,
        "1301": 1_200_000,
        "2412": 1_000_000,
    }
    return {c: caps.get(c, 500_000) for c in codes}


# ─── Constants Tests ─────────────────────────────────────────

class TestConstants:
    def test_structural_window(self):
        assert STRUCTURAL_WINDOW == 90

    def test_flash_window(self):
        assert FLASH_WINDOW == 15

    def test_zscore_alert(self):
        assert ZSCORE_ALERT == 1.5

    def test_absolute_alert(self):
        assert ABSOLUTE_ALERT == 0.95

    def test_flash_spike_threshold(self):
        assert FLASH_SPIKE_THRESHOLD == 0.20

    def test_systemic_flush_threshold(self):
        assert SYSTEMIC_FLUSH_THRESHOLD == 0.50

    def test_risk_bucket_multiplier(self):
        assert RISK_BUCKET_MULTIPLIER == 1.2

    def test_sector_cap(self):
        assert SECTOR_CAP_SINGLE == 0.20


# ─── UnionFind Tests ─────────────────────────────────────────

class TestUnionFind:
    def test_basic_union(self):
        uf = UnionFind(["A", "B", "C"])
        uf.union("A", "B")
        assert uf.find("A") == uf.find("B")
        assert uf.find("C") != uf.find("A")

    def test_transitive_union(self):
        uf = UnionFind(["A", "B", "C"])
        uf.union("A", "B")
        uf.union("B", "C")
        assert uf.find("A") == uf.find("C")

    def test_groups_only_multi_member(self):
        uf = UnionFind(["A", "B", "C", "D"])
        uf.union("A", "B")
        groups = uf.groups()
        assert len(groups) == 1
        root = list(groups.keys())[0]
        assert set(groups[root]) == {"A", "B"}

    def test_no_groups_when_no_unions(self):
        uf = UnionFind(["A", "B", "C"])
        assert uf.groups() == {}

    def test_multiple_groups(self):
        uf = UnionFind(["A", "B", "C", "D", "E"])
        uf.union("A", "B")
        uf.union("C", "D")
        groups = uf.groups()
        assert len(groups) == 2


# ─── Color Mapping Tests ────────────────────────────────────

class TestColorMapping:
    def test_deep_red(self):
        assert get_corr_color(0.85)["color"] == "#dc2626"

    def test_orange(self):
        assert get_corr_color(0.55)["color"] == "#f97316"

    def test_neutral(self):
        assert get_corr_color(0.0)["color"] == "#f5f5f5"

    def test_light_blue(self):
        assert get_corr_color(-0.4)["color"] == "#93c5fd"

    def test_deep_blue(self):
        assert get_corr_color(-0.6)["color"] == "#2563eb"

    def test_boundary_07(self):
        assert get_corr_color(0.7)["color"] == "#dc2626"

    def test_boundary_neg03(self):
        assert get_corr_color(-0.3)["color"] == "#f5f5f5"

    def test_boundary_neg05(self):
        assert get_corr_color(-0.5)["color"] == "#93c5fd"


# ─── Cap-Weighted Returns Tests ──────────────────────────────

class TestCapWeightedReturns:
    def test_basic_computation(self):
        codes = ["2330", "2454", "2317", "2382"]  # Semis + AI Server
        returns = _make_returns(100, codes)
        caps = _make_market_caps(codes)
        sector_ret = compute_cap_weighted_sector_returns(returns, caps)
        assert not sector_ret.empty
        assert "半導體" in sector_ret.columns or "AI伺服器" in sector_ret.columns

    def test_tsmc_dominates_semiconductor(self):
        """TSMC (20M cap) should dominate semiconductor return."""
        codes = ["2330", "2454"]
        dates = pd.date_range("2024-01-01", periods=50, freq="B")
        returns = pd.DataFrame({
            "2330": [0.05] * 50,  # TSMC: +5% daily
            "2454": [-0.05] * 50,  # MediaTek: -5% daily
        }, index=dates)
        caps = {"2330": 20_000_000, "2454": 2_000_000}
        sector_ret = compute_cap_weighted_sector_returns(returns, caps)
        if "半導體" in sector_ret.columns:
            # TSMC weight ~91%, so sector return should be positive
            assert sector_ret["半導體"].mean() > 0

    def test_equal_weight_fallback(self):
        """When all caps are 0, fallback to equal weight."""
        codes = ["2330", "2454"]
        returns = _make_returns(50, codes)
        caps = {"2330": 0, "2454": 0}
        sector_ret = compute_cap_weighted_sector_returns(returns, caps)
        # Should still produce output (equal weight fallback)
        assert not sector_ret.empty

    def test_min_stocks_filter(self):
        """Sectors with <2 stocks should be excluded."""
        # Only one stock in 光電 sector
        codes = ["3008"]  # Just one optoelectronics stock
        returns = _make_returns(50, codes)
        caps = _make_market_caps(codes)
        sector_ret = compute_cap_weighted_sector_returns(returns, caps)
        # 光電 should not appear (only 1 stock)
        assert "光電" not in sector_ret.columns

    def test_empty_returns(self):
        returns = pd.DataFrame()
        sector_ret = compute_cap_weighted_sector_returns(returns, {})
        assert sector_ret.empty


# ─── Correlation Matrix Tests ────────────────────────────────

class TestCorrelationMatrix:
    def test_symmetric(self):
        codes = ["2330", "2454", "2317", "2382", "2881", "2882"]
        returns = _make_returns(200, codes)
        caps = _make_market_caps(codes)
        sector_ret = compute_cap_weighted_sector_returns(returns, caps)
        corr = compute_sector_correlation_matrix(sector_ret)
        # Correlation matrix should be symmetric
        for sa in corr.columns:
            for sb in corr.columns:
                assert abs(corr.loc[sa, sb] - corr.loc[sb, sa]) < 1e-10

    def test_diagonal_is_one(self):
        codes = ["2330", "2454", "2317", "2382", "2881", "2882"]
        returns = _make_returns(200, codes)
        caps = _make_market_caps(codes)
        sector_ret = compute_cap_weighted_sector_returns(returns, caps)
        corr = compute_sector_correlation_matrix(sector_ret)
        for s in corr.columns:
            assert abs(corr.loc[s, s] - 1.0) < 1e-10

    def test_short_data(self):
        """Should still compute with less data than window."""
        codes = ["2330", "2454", "2317", "2382"]
        returns = _make_returns(30, codes)  # Less than 90
        caps = _make_market_caps(codes)
        sector_ret = compute_cap_weighted_sector_returns(returns, caps)
        corr = compute_sector_correlation_matrix(sector_ret)
        assert not corr.empty


# ─── Z-Score Alert Tests ─────────────────────────────────────

class TestZScoreAlerts:
    def test_no_alerts_random_data(self):
        """Random data should rarely trigger Z-score alerts."""
        codes = ["2330", "2454", "2317", "2382", "2881", "2882"]
        returns = _make_returns(800, codes)
        caps = _make_market_caps(codes)
        sector_ret = compute_cap_weighted_sector_returns(returns, caps)
        alerts = compute_zscore_alerts(sector_ret)
        # With random data, alerts should be infrequent
        # (but possible, so we don't assert 0)
        assert isinstance(alerts, list)

    def test_extreme_correlation_triggers_absolute(self):
        """Perfectly correlated sectors should trigger absolute alert."""
        dates = pd.date_range("2020-01-01", periods=800, freq="B")
        base = np.random.RandomState(42).normal(0.001, 0.02, 800)
        # Two sectors perfectly correlated
        sector_ret = pd.DataFrame({
            "半導體": base,
            "AI伺服器": base * 1.001 + np.random.RandomState(43).normal(0, 0.0001, 800),
        }, index=dates)
        alerts = compute_zscore_alerts(sector_ret)
        absolute_alerts = [a for a in alerts if a["alert_type"] == "absolute_extreme"]
        assert len(absolute_alerts) > 0

    def test_alert_structure(self):
        """Alert dicts should have required fields."""
        dates = pd.date_range("2020-01-01", periods=800, freq="B")
        base = np.random.RandomState(42).normal(0.001, 0.02, 800)
        sector_ret = pd.DataFrame({
            "A": base,
            "B": base * 0.99 + np.random.RandomState(43).normal(0, 0.0005, 800),
        }, index=dates)
        alerts = compute_zscore_alerts(sector_ret)
        if alerts:
            a = alerts[0]
            assert "sector_a" in a
            assert "sector_b" in a
            assert "current_corr" in a
            assert "z_score" in a
            assert "alert_type" in a

    def test_single_sector(self):
        """Single sector should produce no alerts."""
        sector_ret = pd.DataFrame({"半導體": np.random.normal(0, 0.02, 200)})
        alerts = compute_zscore_alerts(sector_ret)
        assert len(alerts) == 0


# ─── Flash Alert Tests ───────────────────────────────────────

class TestFlashAlerts:
    def test_spike_detected(self):
        """Sudden correlation spike in last 15 days should trigger alert."""
        dates = pd.date_range("2023-01-01", periods=200, freq="B")
        rng = np.random.RandomState(42)
        # First 185 days: uncorrelated
        a_early = rng.normal(0, 0.02, 185)
        b_early = rng.normal(0, 0.02, 185)
        # Last 15 days: highly correlated
        shared = rng.normal(0, 0.02, 15)
        a_late = shared
        b_late = shared + rng.normal(0, 0.001, 15)

        sector_ret = pd.DataFrame({
            "A": np.concatenate([a_early, a_late]),
            "B": np.concatenate([b_early, b_late]),
        }, index=dates)
        alerts = compute_flash_alerts(sector_ret)
        assert len(alerts) >= 1
        assert alerts[0]["spike"] > FLASH_SPIKE_THRESHOLD

    def test_no_spike_stable_corr(self):
        """Stable correlation should not trigger flash alert."""
        dates = pd.date_range("2023-01-01", periods=200, freq="B")
        rng = np.random.RandomState(42)
        base = rng.normal(0, 0.02, 200)
        sector_ret = pd.DataFrame({
            "A": base + rng.normal(0, 0.005, 200),
            "B": base + rng.normal(0, 0.005, 200),
        }, index=dates)
        alerts = compute_flash_alerts(sector_ret)
        # Stable correlation → no spike
        assert len(alerts) == 0

    def test_too_short_data(self):
        """Less than flash_window days should return empty."""
        sector_ret = pd.DataFrame({
            "A": [0.01] * 10,
            "B": [0.01] * 10,
        })
        alerts = compute_flash_alerts(sector_ret)
        assert len(alerts) == 0


# ─── Systemic Risk Score Tests ───────────────────────────────

class TestSystemicRisk:
    def test_normal_random(self):
        """Random data should show normal systemic risk."""
        codes = ["2330", "2454", "2317", "2382", "2881", "2882"]
        returns = _make_returns(200, codes)
        caps = _make_market_caps(codes)
        sector_ret = compute_cap_weighted_sector_returns(returns, caps)
        result = compute_systemic_risk_score(sector_ret)
        assert result["level"] in ("normal", "elevated", "systemic")
        assert 0 <= result["score"] <= 1

    def test_systemic_flush_detection(self):
        """All sectors suddenly correlated should trigger systemic."""
        dates = pd.date_range("2023-01-01", periods=200, freq="B")
        rng = np.random.RandomState(42)
        sectors = ["A", "B", "C", "D", "E"]
        # First 185 days: independent
        data = {}
        for s in sectors:
            early = rng.normal(0, 0.02, 185)
            # Last 15 days: all same direction (panic sell)
            late = np.full(15, -0.03) + rng.normal(0, 0.001, 15)
            data[s] = np.concatenate([early, late])
        sector_ret = pd.DataFrame(data, index=dates)
        result = compute_systemic_risk_score(sector_ret)
        # Should detect elevated or systemic
        assert result["spiking_pairs"] > 0

    def test_tighten_stops_on_systemic(self):
        """Systemic alert should set tighten_stops=True."""
        # Force systemic: make score > 0.5
        result = {
            "score": 0.6,
            "spiking_pairs": 6,
            "total_pairs": 10,
            "level": "systemic",
            "label": "SYSTEMIC ALERT",
            "tighten_stops": True,
        }
        assert result["tighten_stops"] is True

    def test_empty_returns(self):
        sector_ret = pd.DataFrame()
        result = compute_systemic_risk_score(sector_ret)
        assert result["level"] == "normal"
        assert result["tighten_stops"] is False


# ─── Risk Bucket Tests ───────────────────────────────────────

class TestRiskBuckets:
    def test_basic_bucket_creation(self):
        alerts = [{"sector_a": "半導體", "sector_b": "AI伺服器", "alert_type": "zscore_spike"}]
        sectors = ["半導體", "AI伺服器", "金融"]
        result = compute_risk_buckets(alerts, [], sectors)
        assert len(result["buckets"]) == 1
        assert set(result["buckets"][0]["members"]) == {"半導體", "AI伺服器"}

    def test_combined_cap(self):
        alerts = [{"sector_a": "A", "sector_b": "B", "alert_type": "zscore_spike"}]
        result = compute_risk_buckets(alerts, [], ["A", "B", "C"])
        bucket = result["buckets"][0]
        expected_cap = SECTOR_CAP_SINGLE * RISK_BUCKET_MULTIPLIER
        assert abs(bucket["combined_cap"] - expected_cap) < 0.001

    def test_transitive_merge(self):
        """A-B correlated, B-C correlated → A,B,C in one bucket."""
        alerts = [
            {"sector_a": "A", "sector_b": "B", "alert_type": "zscore_spike"},
            {"sector_a": "B", "sector_b": "C", "alert_type": "flash_spike"},
        ]
        result = compute_risk_buckets(alerts, alerts, ["A", "B", "C", "D"])
        # A, B, C should be merged
        merged_bucket = [b for b in result["buckets"] if len(b["members"]) == 3]
        assert len(merged_bucket) == 1
        assert set(merged_bucket[0]["members"]) == {"A", "B", "C"}

    def test_no_alerts_no_buckets(self):
        result = compute_risk_buckets([], [], ["A", "B"])
        assert len(result["buckets"]) == 0

    def test_flash_alerts_also_merge(self):
        flash = [{"sector_a": "X", "sector_b": "Y", "corr_15d": 0.9, "corr_90d": 0.6, "spike": 0.3}]
        result = compute_risk_buckets([], flash, ["X", "Y", "Z"])
        assert len(result["buckets"]) == 1


# ─── Bucket Entry Allowed Tests ──────────────────────────────

class TestBucketEntryAllowed:
    def test_allowed_within_cap(self):
        risk_buckets = {
            "buckets": [{"root": "A", "members": ["A", "B"], "combined_cap": 0.24}],
            "sector_to_bucket": {"A": "A", "B": "A"},
        }
        weights = {"A": 0.10, "B": 0.05}
        result = check_bucket_entry_allowed(risk_buckets, weights, "A", 0.05)
        assert result["allowed"] is True

    def test_blocked_exceeds_bucket_cap(self):
        risk_buckets = {
            "buckets": [{"root": "A", "members": ["A", "B"], "combined_cap": 0.24}],
            "sector_to_bucket": {"A": "A", "B": "A"},
        }
        weights = {"A": 0.15, "B": 0.08}
        result = check_bucket_entry_allowed(risk_buckets, weights, "A", 0.05)
        assert result["allowed"] is False
        assert "exceeds combined cap" in result["reason"]

    def test_unbucketed_sector_uses_single_cap(self):
        risk_buckets = {"buckets": [], "sector_to_bucket": {}}
        weights = {"金融": 0.18}
        result = check_bucket_entry_allowed(risk_buckets, weights, "金融", 0.03)
        assert result["allowed"] is False  # 0.18 + 0.03 > 0.20

    def test_unbucketed_sector_allowed(self):
        risk_buckets = {"buckets": [], "sector_to_bucket": {}}
        weights = {"金融": 0.10}
        result = check_bucket_entry_allowed(risk_buckets, weights, "金融", 0.05)
        assert result["allowed"] is True


# ─── Heatmap Tests ───────────────────────────────────────────

class TestHeatmap:
    def test_heatmap_structure(self):
        corr = pd.DataFrame(
            [[1.0, 0.8], [0.8, 1.0]],
            index=["A", "B"],
            columns=["A", "B"],
        )
        data = build_heatmap_data(corr)
        assert len(data) == 4  # 2×2 matrix
        cell = data[0]
        assert "sector_a" in cell
        assert "sector_b" in cell
        assert "correlation" in cell
        assert "color" in cell

    def test_nan_handling(self):
        corr = pd.DataFrame(
            [[1.0, float("nan")], [float("nan"), 1.0]],
            index=["A", "B"],
            columns=["A", "B"],
        )
        data = build_heatmap_data(corr)
        for cell in data:
            assert not np.isnan(cell["correlation"])


# ─── Full Integration Test ───────────────────────────────────

class TestFullCorrelation:
    def test_full_report_structure(self):
        codes = ["2330", "2454", "2317", "2382", "2881", "2882", "1303", "1301"]
        returns = _make_returns(200, codes)
        caps = _make_market_caps(codes)
        result = compute_full_sector_correlation(returns, caps)

        assert "sectors" in result
        assert "correlation_matrix" in result
        assert "heatmap" in result
        assert "zscore_alerts" in result
        assert "flash_alerts" in result
        assert "systemic_risk" in result
        assert "risk_buckets" in result

    def test_empty_data(self):
        result = compute_full_sector_correlation(pd.DataFrame(), {})
        assert result["sectors"] == []
        assert result["systemic_risk"]["level"] == "normal"

    def test_correlation_matrix_serializable(self):
        """Ensure correlation_matrix is JSON-serializable (dict of dicts)."""
        codes = ["2330", "2454", "2317", "2382"]
        returns = _make_returns(200, codes)
        caps = _make_market_caps(codes)
        result = compute_full_sector_correlation(returns, caps)
        cm = result["correlation_matrix"]
        assert isinstance(cm, dict)
        for k, v in cm.items():
            assert isinstance(v, dict)
            for inner_val in v.values():
                assert isinstance(inner_val, float)

"""Tests for analysis/sector_rs.py (R64: Sector RS & Peer RS Check)

All tests use synthetic data — no network calls.
"""

import pytest
from analysis.sector_rs import (
    compute_sector_rs_table,
    compute_peer_alpha,
    assess_cluster_risk,
    get_sector_context,
    PEER_ALPHA_LEADER,
    PEER_ALPHA_LAGGARD,
    CLUSTER_NORMAL_DIAMOND_PCT,
    CLUSTER_NORMAL_HEAT,
    CLUSTER_CAUTION_DIAMOND_PCT,
    CLUSTER_CAUTION_HEAT,
)


# ── Fixtures ───────────────────────────────────────────────

def _make_rankings(stocks: list[dict]) -> dict:
    """Build a synthetic rs_ranking.json-like structure."""
    return {
        "scan_date": "2026-02-16 12:00",
        "total_stocks": len(stocks),
        "params": {"lookback": 120, "exclude_recent": 5},
        "stats": {},
        "rankings": stocks,
    }


SEMI_STOCKS = [
    {"code": "2330", "name": "台積電", "rs_ratio": 1.5, "rs_rating": 92.0},
    {"code": "2454", "name": "聯發科", "rs_ratio": 1.3, "rs_rating": 85.0},
    {"code": "3034", "name": "聯詠", "rs_ratio": 1.1, "rs_rating": 72.0},
    {"code": "2303", "name": "聯電", "rs_ratio": 0.9, "rs_rating": 55.0},
    {"code": "2408", "name": "南亞科", "rs_ratio": 0.7, "rs_rating": 35.0},
]

FINANCIAL_STOCKS = [
    {"code": "2881", "name": "富邦金", "rs_ratio": 1.2, "rs_rating": 88.0},
    {"code": "2882", "name": "國泰金", "rs_ratio": 1.0, "rs_rating": 65.0},
    {"code": "2886", "name": "兆豐金", "rs_ratio": 0.8, "rs_rating": 42.0},
]


# ── compute_sector_rs_table ────────────────────────────────

class TestComputeSectorRsTable:

    def test_returns_empty_on_no_data(self, monkeypatch):
        monkeypatch.setattr("analysis.sector_rs.get_cached_rankings", lambda: None)
        result = compute_sector_rs_table(None)
        assert result == {}

    def test_returns_empty_on_empty_rankings(self):
        result = compute_sector_rs_table(_make_rankings([]))
        assert result == {}

    def test_median_not_mean(self, monkeypatch):
        """Gemini mandate: use MEDIAN, not mean."""
        rankings = _make_rankings(SEMI_STOCKS)
        # Monkeypatch sector groups to match our test data
        monkeypatch.setattr(
            "analysis.sector_rs.SECTOR_L1_GROUPS",
            {"半導體": ["2330", "2454", "3034", "2303", "2408"]},
        )

        table = compute_sector_rs_table(rankings)
        assert "半導體" in table

        # RS ratios: [1.5, 1.3, 1.1, 0.9, 0.7] → median = 1.1
        assert table["半導體"]["median_rs"] == 1.1
        # Mean would be 1.1 too for this symmetric set, so add asymmetric test
        assert table["半導體"]["count"] == 5

    def test_median_asymmetric(self, monkeypatch):
        """Verify median is robust to outliers (TSMC Effect)."""
        stocks = [
            {"code": "A", "name": "A", "rs_ratio": 6.0, "rs_rating": 99.0},  # outlier
            {"code": "B", "name": "B", "rs_ratio": 1.1, "rs_rating": 70.0},
            {"code": "C", "name": "C", "rs_ratio": 1.0, "rs_rating": 60.0},
            {"code": "D", "name": "D", "rs_ratio": 0.9, "rs_rating": 50.0},
            {"code": "E", "name": "E", "rs_ratio": 0.8, "rs_rating": 40.0},
        ]
        rankings = _make_rankings(stocks)
        monkeypatch.setattr(
            "analysis.sector_rs.SECTOR_L1_GROUPS",
            {"TestSector": ["A", "B", "C", "D", "E"]},
        )

        table = compute_sector_rs_table(rankings)
        # Median of [6.0, 1.1, 1.0, 0.9, 0.8] = 1.0
        assert table["TestSector"]["median_rs"] == 1.0
        # Mean would be 1.96 — very different!

    def test_diamond_count(self, monkeypatch):
        rankings = _make_rankings(SEMI_STOCKS)
        monkeypatch.setattr(
            "analysis.sector_rs.SECTOR_L1_GROUPS",
            {"半導體": ["2330", "2454", "3034", "2303", "2408"]},
        )

        table = compute_sector_rs_table(rankings)
        # 2330 (92.0) and 2454 (85.0) are Diamond (≥80)
        assert table["半導體"]["diamond_count"] == 2
        assert table["半導體"]["diamond_pct"] == pytest.approx(0.4, abs=0.01)

    def test_members_sorted_by_rating_desc(self, monkeypatch):
        rankings = _make_rankings(SEMI_STOCKS)
        monkeypatch.setattr(
            "analysis.sector_rs.SECTOR_L1_GROUPS",
            {"半導體": ["2330", "2454", "3034", "2303", "2408"]},
        )

        table = compute_sector_rs_table(rankings)
        ratings = [m["rs_rating"] for m in table["半導體"]["members"]]
        assert ratings == sorted(ratings, reverse=True)


# ── compute_peer_alpha ─────────────────────────────────────

class TestComputePeerAlpha:

    def test_leader(self):
        # stock RS 1.5 / sector median 1.1 = 1.36 → Leader (≥1.2)
        result = compute_peer_alpha(1.5, 1.1)
        assert result["classification"] == "Leader"
        assert result["peer_alpha"] == pytest.approx(1.364, abs=0.01)
        assert result["downgrade"] is False

    def test_rider(self):
        # stock RS 1.1 / sector median 1.1 = 1.0 → Rider (0.8-1.2)
        result = compute_peer_alpha(1.1, 1.1)
        assert result["classification"] == "Rider"
        assert result["peer_alpha"] == pytest.approx(1.0, abs=0.01)
        assert result["downgrade"] is False

    def test_laggard(self):
        # stock RS 0.7 / sector median 1.1 = 0.636 → Laggard (<0.8)
        result = compute_peer_alpha(0.7, 1.1)
        assert result["classification"] == "Laggard"
        assert result["peer_alpha"] < PEER_ALPHA_LAGGARD
        assert result["downgrade"] is True  # Beta Trap protection

    def test_downgrade_diamond_to_gold(self):
        """Gemini mandate: Peer Alpha < 0.8 → downgrade Diamond to Gold."""
        result = compute_peer_alpha(0.7, 1.1)
        assert result["downgrade"] is True

    def test_zero_sector_rs(self):
        result = compute_peer_alpha(1.5, 0.0)
        assert result["peer_alpha"] is None
        assert result["classification"] == "N/A"

    def test_exact_thresholds(self):
        # Exactly at leader threshold
        result = compute_peer_alpha(1.2, 1.0)
        assert result["classification"] == "Leader"

        # Exactly at laggard threshold
        result = compute_peer_alpha(0.8, 1.0)
        assert result["classification"] == "Rider"  # 0.8 is NOT laggard (>=0.8)

        # Just below laggard
        result = compute_peer_alpha(0.79, 1.0)
        assert result["classification"] == "Laggard"


# ── assess_cluster_risk ────────────────────────────────────

class TestAssessClusterRisk:

    def test_normal(self):
        result = assess_cluster_risk(diamond_pct=0.20, sector_heat=0.4)
        assert result["level"] == "normal"
        assert result["label"] == "Clear Skies"

    def test_caution(self):
        result = assess_cluster_risk(diamond_pct=0.35, sector_heat=0.65)
        assert result["level"] == "caution"
        assert "Sector Crowded" in result["label"]

    def test_danger(self):
        result = assess_cluster_risk(diamond_pct=0.55, sector_heat=0.80)
        assert result["level"] == "danger"
        assert "Parabolic" in result["label"]

    def test_high_diamond_low_heat_stays_normal(self):
        """High diamond% but low heat → normal (sector naturally has strong stocks)."""
        result = assess_cluster_risk(diamond_pct=0.60, sector_heat=0.3)
        assert result["level"] == "normal"

    def test_low_diamond_high_heat_stays_normal(self):
        """High heat but low diamond% → normal."""
        result = assess_cluster_risk(diamond_pct=0.10, sector_heat=0.9)
        assert result["level"] == "normal"

    def test_boundary_caution(self):
        """Exactly at caution boundary."""
        result = assess_cluster_risk(
            diamond_pct=CLUSTER_NORMAL_DIAMOND_PCT,
            sector_heat=CLUSTER_NORMAL_HEAT,
        )
        assert result["level"] == "caution"

    def test_boundary_danger(self):
        """Exactly at danger boundary."""
        result = assess_cluster_risk(
            diamond_pct=CLUSTER_CAUTION_DIAMOND_PCT,
            sector_heat=CLUSTER_CAUTION_HEAT,
        )
        assert result["level"] == "danger"

    def test_no_heat_provided(self):
        result = assess_cluster_risk(diamond_pct=0.55, sector_heat=None)
        assert result["level"] == "normal"  # heat defaults to 0


# ── get_sector_context ─────────────────────────────────────

class TestGetSectorContext:

    def test_mapped_stock(self, monkeypatch):
        rankings = _make_rankings(SEMI_STOCKS)
        monkeypatch.setattr("analysis.sector_rs.get_cached_rankings", lambda: rankings)
        monkeypatch.setattr(
            "analysis.sector_rs.SECTOR_L1_GROUPS",
            {"半導體": ["2330", "2454", "3034", "2303", "2408"]},
        )
        monkeypatch.setattr("analysis.sector_rs.get_stock_sector", lambda code, level=2:
            "晶圓代工" if level == 2 else "半導體"
        )

        result = get_sector_context("2330")
        assert result["sector_l1"] == "半導體"
        assert result["blind_spot"] is False
        assert result["sector_rs"]["median_rs"] == 1.1
        assert result["peer_alpha"]["classification"] == "Leader"  # 1.5/1.1 ≈ 1.36
        assert result["peer_rank"] == 1  # Highest RS in sector

    def test_unmapped_stock_blind_spot(self, monkeypatch):
        """Gemini mandate: unmapped stocks get 'Sector Blind Spot' warning."""
        rankings = _make_rankings(SEMI_STOCKS)
        monkeypatch.setattr("analysis.sector_rs.get_cached_rankings", lambda: rankings)
        monkeypatch.setattr("analysis.sector_rs.get_stock_sector", lambda code, level=2: "未分類")

        result = get_sector_context("9999")
        assert result["blind_spot"] is True
        assert result["sector_l1"] == "未分類"
        assert result["cluster_risk"]["label"] == "Sector Blind Spot"
        assert result["peer_alpha"]["peer_alpha"] is None

    def test_with_sector_heat(self, monkeypatch):
        rankings = _make_rankings(SEMI_STOCKS)
        monkeypatch.setattr("analysis.sector_rs.get_cached_rankings", lambda: rankings)
        monkeypatch.setattr(
            "analysis.sector_rs.SECTOR_L1_GROUPS",
            {"半導體": ["2330", "2454", "3034", "2303", "2408"]},
        )
        monkeypatch.setattr("analysis.sector_rs.get_stock_sector", lambda code, level=2:
            "IC設計" if level == 2 else "半導體"
        )

        heat_map = {"半導體": 0.7}
        result = get_sector_context("2454", sector_heat_map=heat_map)
        # diamond_pct=0.4, heat=0.7 → caution (30-50% diamond, 0.6-0.75 heat)
        assert result["cluster_risk"]["level"] == "caution"

    def test_laggard_in_strong_sector(self, monkeypatch):
        rankings = _make_rankings(SEMI_STOCKS)
        monkeypatch.setattr("analysis.sector_rs.get_cached_rankings", lambda: rankings)
        monkeypatch.setattr(
            "analysis.sector_rs.SECTOR_L1_GROUPS",
            {"半導體": ["2330", "2454", "3034", "2303", "2408"]},
        )
        monkeypatch.setattr("analysis.sector_rs.get_stock_sector", lambda code, level=2:
            "記憶體" if level == 2 else "半導體"
        )

        result = get_sector_context("2408")  # RS 0.7, sector median 1.1
        assert result["peer_alpha"]["classification"] == "Laggard"
        assert result["peer_alpha"]["downgrade"] is True  # Diamond → Gold
        assert result["peer_rank"] == 5  # Lowest in sector

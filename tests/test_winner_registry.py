"""Tests for R88.7 Phase 3: Winner Branch Registry."""
import pytest
import json
import numpy as np
from pathlib import Path
from unittest.mock import patch
from analysis.winner_registry import (
    _is_summary_row,
    _parse_lots,
    _parse_month_end_date,
    _get_sector,
    scan_broker_buys,
    compute_winner_scores,
    bootstrap_ci,
    load_registry,
)


# --- Fixtures ---

@pytest.fixture
def sector_map():
    return {
        "2330": "半導體",
        "2454": "半導體",
        "2882": "金融",
        "2891": "金融",
        "1301": "傳產",
        "2317": "AI伺服器",
    }


@pytest.fixture
def chain_map():
    return {
        "3008": "semiconductor",
        "1101": "cement",
        "2002": "steel",
        "5880": "finance",
    }


@pytest.fixture
def sample_records():
    """Simulates extracted buy records from broker files."""
    return [
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "2330", "date": "2024-01-31", "net_lots": 5000, "pct": 0.15},
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "2454", "date": "2024-02-29", "net_lots": 3000, "pct": 0.12},
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "2882", "date": "2024-03-29", "net_lots": 4000, "pct": 0.10},
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "1301", "date": "2024-04-30", "net_lots": 2000, "pct": 0.08},
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "2317", "date": "2024-05-31", "net_lots": 6000, "pct": 0.20},
        # More records for A001 to reach n >= 15
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "2330", "date": "2024-06-28", "net_lots": 4000, "pct": 0.13},
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "2454", "date": "2024-07-31", "net_lots": 3500, "pct": 0.11},
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "2882", "date": "2024-08-30", "net_lots": 2500, "pct": 0.09},
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "1301", "date": "2024-09-30", "net_lots": 3000, "pct": 0.12},
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "2317", "date": "2024-10-31", "net_lots": 5000, "pct": 0.18},
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "2330", "date": "2024-11-29", "net_lots": 4500, "pct": 0.14},
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "2454", "date": "2024-12-31", "net_lots": 3200, "pct": 0.10},
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "2882", "date": "2025-01-31", "net_lots": 2800, "pct": 0.11},
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "1301", "date": "2025-02-28", "net_lots": 3500, "pct": 0.13},
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "2317", "date": "2025-03-31", "net_lots": 4200, "pct": 0.16},
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "2330", "date": "2025-04-30", "net_lots": 5500, "pct": 0.17},
        {"broker_code": "A001", "broker_name": "凱基-台北", "stock_code": "2882", "date": "2025-05-30", "net_lots": 3000, "pct": 0.10},
        # B002: Only trades in semiconductors (ghost bias)
        {"broker_code": "B002", "broker_name": "富邦-台北", "stock_code": "2330", "date": "2024-01-31", "net_lots": 8000, "pct": 0.25},
        {"broker_code": "B002", "broker_name": "富邦-台北", "stock_code": "2330", "date": "2024-02-29", "net_lots": 7000, "pct": 0.22},
        {"broker_code": "B002", "broker_name": "富邦-台北", "stock_code": "2330", "date": "2024-03-29", "net_lots": 6500, "pct": 0.20},
        {"broker_code": "B002", "broker_name": "富邦-台北", "stock_code": "2454", "date": "2024-04-30", "net_lots": 5500, "pct": 0.18},
        {"broker_code": "B002", "broker_name": "富邦-台北", "stock_code": "2330", "date": "2024-05-31", "net_lots": 9000, "pct": 0.28},
        {"broker_code": "B002", "broker_name": "富邦-台北", "stock_code": "2454", "date": "2024-06-28", "net_lots": 6000, "pct": 0.19},
        {"broker_code": "B002", "broker_name": "富邦-台北", "stock_code": "2330", "date": "2024-07-31", "net_lots": 7500, "pct": 0.23},
        {"broker_code": "B002", "broker_name": "富邦-台北", "stock_code": "2454", "date": "2024-08-30", "net_lots": 5000, "pct": 0.16},
        {"broker_code": "B002", "broker_name": "富邦-台北", "stock_code": "2330", "date": "2024-09-30", "net_lots": 8000, "pct": 0.24},
        {"broker_code": "B002", "broker_name": "富邦-台北", "stock_code": "2454", "date": "2024-10-31", "net_lots": 6500, "pct": 0.20},
        {"broker_code": "B002", "broker_name": "富邦-台北", "stock_code": "2330", "date": "2024-11-29", "net_lots": 7000, "pct": 0.22},
        {"broker_code": "B002", "broker_name": "富邦-台北", "stock_code": "2454", "date": "2024-12-31", "net_lots": 5500, "pct": 0.17},
        {"broker_code": "B002", "broker_name": "富邦-台北", "stock_code": "2330", "date": "2025-01-31", "net_lots": 8500, "pct": 0.26},
        {"broker_code": "B002", "broker_name": "富邦-台北", "stock_code": "2454", "date": "2025-02-28", "net_lots": 6000, "pct": 0.19},
        {"broker_code": "B002", "broker_name": "富邦-台北", "stock_code": "2330", "date": "2025-03-31", "net_lots": 7500, "pct": 0.23},
        # C003: Only 5 trades (insufficient n)
        {"broker_code": "C003", "broker_name": "元大-台北", "stock_code": "2330", "date": "2024-01-31", "net_lots": 1000, "pct": 0.05},
        {"broker_code": "C003", "broker_name": "元大-台北", "stock_code": "2882", "date": "2024-02-29", "net_lots": 800, "pct": 0.04},
        {"broker_code": "C003", "broker_name": "元大-台北", "stock_code": "1301", "date": "2024-03-29", "net_lots": 600, "pct": 0.03},
        {"broker_code": "C003", "broker_name": "元大-台北", "stock_code": "2317", "date": "2024-04-30", "net_lots": 900, "pct": 0.04},
        {"broker_code": "C003", "broker_name": "元大-台北", "stock_code": "2454", "date": "2024-05-31", "net_lots": 700, "pct": 0.03},
    ]


@pytest.fixture
def fwd_index_profitable():
    """Forward returns index where most stocks go up (for A001 winner)."""
    idx = {}
    # Profitable returns (60% win rate with good avg profit)
    dates = [
        "2024-01-31", "2024-02-29", "2024-03-29", "2024-04-30", "2024-05-31",
        "2024-06-28", "2024-07-31", "2024-08-30", "2024-09-30", "2024-10-31",
        "2024-11-29", "2024-12-31", "2025-01-31", "2025-02-28", "2025-03-31",
        "2025-04-30", "2025-05-30",
    ]
    stocks = ["2330", "2454", "2882", "1301", "2317"]
    returns = [
        0.05, 0.08, -0.03, 0.04, 0.06,    # Win, Win, Loss, Win, Win
        -0.02, 0.03, -0.04, 0.07, 0.02,    # Loss, Win, Loss, Win, Win
        0.05, -0.01, 0.03, 0.06, -0.02,    # Win, Loss, Win, Win, Loss
        0.04, 0.03,                          # Win, Win
    ]
    i = 0
    for date in dates:
        for stock in stocks:
            ret = returns[i % len(returns)]
            idx[(stock, date)] = {"d7": ret * 0.3, "d21": ret, "d90": ret * 2}
            i += 1
    return idx


@pytest.fixture
def fwd_index_mixed():
    """Forward returns where some are profitable, some are not."""
    idx = {}
    dates = [
        "2024-01-31", "2024-02-29", "2024-03-29", "2024-04-30", "2024-05-31",
        "2024-06-28", "2024-07-31", "2024-08-30", "2024-09-30", "2024-10-31",
        "2024-11-29", "2024-12-31", "2025-01-31", "2025-02-28", "2025-03-31",
        "2025-04-30", "2025-05-30",
    ]
    stocks = ["2330", "2454", "2882", "1301", "2317"]
    np.random.seed(42)
    for date in dates:
        for stock in stocks:
            ret = np.random.normal(0.01, 0.05)
            idx[(stock, date)] = {"d7": ret * 0.3, "d21": ret, "d90": ret * 2}
    return idx


# --- Parse Tests ---

class TestParseHelpers:
    def test_is_summary_row_buy(self):
        assert _is_summary_row({"broker": "合計買超張數"})

    def test_is_summary_row_avg(self):
        assert _is_summary_row({"broker": "平均買超成本"})

    def test_is_summary_row_normal(self):
        assert not _is_summary_row({"broker": "凱基-台北"})

    def test_parse_lots_comma(self):
        assert _parse_lots("17,206") == 17206

    def test_parse_lots_int(self):
        assert _parse_lots(500) == 500

    def test_parse_lots_label(self):
        assert _parse_lots("合計賣超張數") == 0

    def test_parse_month_end_date_standard(self):
        assert _parse_month_end_date("2025-1-31") == "2025-01-31"

    def test_parse_month_end_date_padded(self):
        assert _parse_month_end_date("2025-01-31") == "2025-01-31"

    def test_parse_month_end_date_slash(self):
        assert _parse_month_end_date("2025/1/31") == "2025-01-31"

    def test_parse_month_end_date_invalid(self):
        assert _parse_month_end_date("invalid") is None


class TestGetSector:
    def test_sector_map_priority(self, sector_map, chain_map):
        assert _get_sector("2330", sector_map, chain_map) == "半導體"

    def test_chain_map_fallback(self, sector_map, chain_map):
        assert _get_sector("1101", sector_map, chain_map) == "cement"

    def test_unknown(self, sector_map, chain_map):
        assert _get_sector("9999", sector_map, chain_map) == "unknown"


# --- Winner Score Tests ---

class TestComputeWinnerScores:
    def test_sufficient_n(self, sample_records, fwd_index_profitable, sector_map, chain_map):
        scores = compute_winner_scores(
            sample_records, fwd_index_profitable, sector_map, chain_map,
            horizon="d21", min_n=15,
        )
        # A001 has 17 records, should be included
        assert "A001" in scores
        assert scores["A001"]["n"] >= 15

    def test_insufficient_n_filtered(self, sample_records, fwd_index_profitable, sector_map, chain_map):
        scores = compute_winner_scores(
            sample_records, fwd_index_profitable, sector_map, chain_map,
            horizon="d21", min_n=15,
        )
        # C003 has only 5 records, should be filtered
        assert "C003" not in scores

    def test_ghost_bias_detected(self, sample_records, fwd_index_profitable, sector_map, chain_map):
        scores = compute_winner_scores(
            sample_records, fwd_index_profitable, sector_map, chain_map,
            horizon="d21", min_n=15,
        )
        # B002 only trades semiconductors → ghost bias
        assert "B002" in scores
        assert scores["B002"]["ghost_bias"] is True

    def test_no_ghost_bias_diversified(self, sample_records, fwd_index_profitable, sector_map, chain_map):
        scores = compute_winner_scores(
            sample_records, fwd_index_profitable, sector_map, chain_map,
            horizon="d21", min_n=15,
        )
        # A001 trades across 4+ sectors
        if "A001" in scores:
            assert scores["A001"]["ghost_bias"] is False
            assert scores["A001"]["sector_count"] >= 3

    def test_winner_score_formula(self, sample_records, fwd_index_profitable, sector_map, chain_map):
        scores = compute_winner_scores(
            sample_records, fwd_index_profitable, sector_map, chain_map,
            horizon="d21", min_n=15,
        )
        if "A001" in scores:
            info = scores["A001"]
            # Verify: score = win_rate * (avg_profit / |avg_loss|)
            expected = info["win_rate"] * (info["avg_profit"] / abs(info["avg_loss"]))
            assert abs(info["score"] - expected) < 0.01

    def test_sector_count_correct(self, sample_records, fwd_index_profitable, sector_map, chain_map):
        scores = compute_winner_scores(
            sample_records, fwd_index_profitable, sector_map, chain_map,
            horizon="d21", min_n=15,
        )
        if "B002" in scores:
            # B002 only trades 2330 and 2454, both 半導體
            assert scores["B002"]["sector_count"] == 1

    def test_unique_stocks(self, sample_records, fwd_index_profitable, sector_map, chain_map):
        scores = compute_winner_scores(
            sample_records, fwd_index_profitable, sector_map, chain_map,
            horizon="d21", min_n=15,
        )
        if "A001" in scores:
            assert scores["A001"]["unique_stocks"] >= 4

    def test_min_n_parameter(self, sample_records, fwd_index_profitable, sector_map, chain_map):
        # With min_n=5, C003 should be included
        scores = compute_winner_scores(
            sample_records, fwd_index_profitable, sector_map, chain_map,
            horizon="d21", min_n=5,
        )
        assert "C003" in scores

    def test_empty_records(self, sector_map, chain_map):
        scores = compute_winner_scores(
            [], {}, sector_map, chain_map,
            horizon="d21", min_n=15,
        )
        assert len(scores) == 0


# --- Bootstrap CI Tests ---

class TestBootstrapCI:
    def test_profitable_returns(self):
        # Mostly positive returns → CI lower bound should be positive
        returns = [0.05, 0.08, -0.03, 0.04, 0.06, -0.02, 0.03, -0.04,
                   0.07, 0.02, 0.05, -0.01, 0.03, 0.06, -0.02, 0.04]
        np.random.seed(42)
        ci_lo, ci_hi = bootstrap_ci(returns, n_iterations=500)
        assert ci_lo > 0  # Lower bound should be positive for mostly winners
        assert ci_hi > ci_lo

    def test_losing_returns(self):
        # Mostly negative returns → CI lower bound should be low
        returns = [-0.05, -0.08, 0.01, -0.04, -0.06, 0.02, -0.03, -0.04,
                   -0.07, -0.02, -0.05, 0.01, -0.03, -0.06, 0.02, -0.04]
        np.random.seed(42)
        ci_lo, ci_hi = bootstrap_ci(returns, n_iterations=500)
        assert ci_lo < 1.0  # Should fail the threshold

    def test_insufficient_data(self):
        returns = [0.05, 0.03]
        ci_lo, ci_hi = bootstrap_ci(returns)
        assert ci_lo == 0.0
        assert ci_hi == 0.0

    def test_all_wins(self):
        returns = [0.05, 0.03, 0.08, 0.04, 0.06, 0.02, 0.07, 0.05,
                   0.03, 0.04, 0.06, 0.08, 0.05, 0.03, 0.07, 0.04]
        np.random.seed(42)
        ci_lo, ci_hi = bootstrap_ci(returns, n_iterations=500)
        # All wins → both bounds should be very high
        assert ci_lo > 1.0

    def test_deterministic_with_seed(self):
        returns = [0.05, -0.03, 0.04, -0.02, 0.06, -0.01, 0.03, -0.04,
                   0.05, 0.02, -0.03, 0.04, -0.02, 0.06, -0.01, 0.03]
        r1 = bootstrap_ci(returns, n_iterations=500, seed=42)
        r2 = bootstrap_ci(returns, n_iterations=500, seed=42)
        assert r1 == r2


# --- Ghost Bias Tests ---

class TestGhostBias:
    def test_single_sector_flagged(self, fwd_index_profitable, sector_map, chain_map):
        # All trades in same sector
        records = [
            {"broker_code": "X01", "broker_name": "Test", "stock_code": "2330",
             "date": f"2024-{m:02d}-28", "net_lots": 1000, "pct": 0.10}
            for m in range(1, 13)
        ] + [
            {"broker_code": "X01", "broker_name": "Test", "stock_code": "2454",
             "date": f"2025-{m:02d}-28", "net_lots": 1000, "pct": 0.10}
            for m in range(1, 6)
        ]
        scores = compute_winner_scores(
            records, fwd_index_profitable, sector_map, chain_map,
            horizon="d21", min_n=15,
        )
        if "X01" in scores:
            assert scores["X01"]["ghost_bias"] is True
            assert scores["X01"]["max_sector_share"] > 0.5

    def test_diversified_not_flagged(self, fwd_index_profitable, sector_map, chain_map):
        # Trades across 4 sectors
        stocks = ["2330", "2882", "1301", "2317"]
        records = []
        for i, stock in enumerate(stocks):
            for m in range(1, 5):
                records.append({
                    "broker_code": "Y01", "broker_name": "Diverse",
                    "stock_code": stock,
                    "date": f"2024-{(i*4+m):02d}-28" if (i*4+m) <= 12
                            else f"2025-{(i*4+m-12):02d}-28",
                    "net_lots": 1000, "pct": 0.10,
                })
        scores = compute_winner_scores(
            records, fwd_index_profitable, sector_map, chain_map,
            horizon="d21", min_n=15,
        )
        if "Y01" in scores:
            assert scores["Y01"]["ghost_bias"] is False
            assert scores["Y01"]["sector_count"] >= 3


# --- Load Registry Tests ---

class TestLoadRegistry:
    def test_load_nonexistent(self, tmp_path):
        result = load_registry(tmp_path / "nonexistent.json")
        assert result == {}

    def test_load_valid(self, tmp_path):
        registry = {
            "winners": {"A001": {"score": 1.5, "n": 25}},
            "metadata": {"built_at": "2026-02-18"},
        }
        path = tmp_path / "test_registry.json"
        with open(path, "w") as f:
            json.dump(registry, f)
        result = load_registry(path)
        assert "A001" in result
        assert result["A001"]["score"] == 1.5


# --- Scan Tests with Mocked Files ---

class TestScanBrokerBuys:
    def test_scan_with_mock_dir(self, tmp_path):
        # Create mock broker files
        for i, stock in enumerate(["1101", "2330", "2882"]):
            data = {
                "start_date": "2024-1-1",
                "end_date": "2024-1-31",
                "stock": stock,
                "buy_top": [
                    {"broker": "凱基-台北", "buy": "5,000", "sell": "1,000",
                     "net": "4,000", "pct": "15.00%"},
                    {"broker": "富邦", "buy": "3,000", "sell": "500",
                     "net": "2,500", "pct": "10.00%"},
                    {"broker": "合計買超張數", "buy": "8,000", "sell": "合計",
                     "net": "6,500", "pct": "平均買超成本"},
                ],
                "sell_top": [],
                "broker_codes": ["6010", "9600"],
            }
            with open(tmp_path / f"{stock}_202401.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)

        records = scan_broker_buys(tmp_path, top_k=5)
        assert len(records) == 6  # 3 files × 2 non-summary brokers
        assert all(r["net_lots"] > 0 for r in records)
        assert all(r["broker_code"] in ("6010", "9600") for r in records)

    def test_scan_summary_row_excluded(self, tmp_path):
        data = {
            "start_date": "2024-1-1",
            "end_date": "2024-1-31",
            "stock": "2330",
            "buy_top": [
                {"broker": "凱基-台北", "buy": "5,000", "sell": "1,000",
                 "net": "4,000", "pct": "15.00%"},
                {"broker": "合計買超張數", "buy": "5,000", "sell": "合計",
                 "net": "4,000", "pct": "平均買超成本"},
            ],
            "sell_top": [],
            "broker_codes": ["6010"],
        }
        with open(tmp_path / "2330_202401.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        records = scan_broker_buys(tmp_path, top_k=5)
        assert len(records) == 1
        assert records[0]["broker_name"] == "凱基-台北"


# --- Integration-like Tests ---

class TestEndToEnd:
    def test_full_pipeline_synthetic(self, sample_records, fwd_index_profitable, sector_map, chain_map):
        """Test the full pipeline with synthetic data."""
        scores = compute_winner_scores(
            sample_records, fwd_index_profitable, sector_map, chain_map,
            horizon="d21", min_n=15,
        )

        # A001 should be a winner (diversified, profitable)
        assert "A001" in scores
        a001 = scores["A001"]
        assert a001["score"] > 0
        assert a001["win_rate"] > 0
        assert a001["n"] >= 15
        assert a001["ghost_bias"] is False

        # B002 should be ghost-biased
        assert "B002" in scores
        b002 = scores["B002"]
        assert b002["ghost_bias"] is True

        # C003 should not be present (n < 15)
        assert "C003" not in scores

    def test_pipeline_with_mixed_returns(self, sample_records, fwd_index_mixed, sector_map, chain_map):
        """With random returns, winner score should be modest."""
        scores = compute_winner_scores(
            sample_records, fwd_index_mixed, sector_map, chain_map,
            horizon="d21", min_n=15,
        )
        # Scores should exist but be reasonable (not extreme)
        for code, info in scores.items():
            assert 0 <= info["win_rate"] <= 1
            assert info["n"] >= 15

"""Tests for R88.7 Daily Brokerage Feature Engine."""
import pytest
import numpy as np
from analysis.broker_features import (
    parse_daily_brokers,
    compute_broker_features,
    compute_data_quality,
    BROKER_FEATURE_NAMES,
    _parse_lots,
    _parse_pct,
    _is_summary_row,
    _is_foreign_broker,
)


# --- Fixtures ---

@pytest.fixture
def sample_raw_data():
    """Simulates raw Fubon DJhtm parsed output."""
    return {
        "start_date": "2026-2-10",
        "end_date": "2026-2-10",
        "buy_top": [
            {"broker": "凱基-台北", "buy": "5,000", "sell": "1,000", "net": "4,000", "pct": "15.00%"},
            {"broker": "富邦證券", "buy": "4,000", "sell": "2,000", "net": "2,000", "pct": "12.00%"},
            {"broker": "元大-台北", "buy": "3,500", "sell": "1,500", "net": "2,000", "pct": "10.00%"},
            {"broker": "群益金鼎", "buy": "2,000", "sell": "1,000", "net": "1,000", "pct": "6.00%"},
            {"broker": "永豐金-匯立", "buy": "1,500", "sell": "500", "net": "1,000", "pct": "4.00%"},
            {"broker": "合計買超張數", "buy": "16,000", "sell": "合計賣超張數", "net": "10,000", "pct": "平均買超成本"},
        ],
        "sell_top": [
            {"broker": "新加坡商瑞銀", "buy": "500", "sell": "6,000", "net": "5,500", "pct": "18.00%"},
            {"broker": "美林", "buy": "300", "sell": "4,000", "net": "3,700", "pct": "12.00%"},
            {"broker": "日盛-台北", "buy": "1,000", "sell": "3,000", "net": "2,000", "pct": "9.00%"},
            {"broker": "統一-台北", "buy": "800", "sell": "2,500", "net": "1,700", "pct": "7.00%"},
            {"broker": "國泰-台北", "buy": "600", "sell": "2,000", "net": "1,400", "pct": "6.00%"},
        ],
        "broker_codes": ["6010", "9600", "0039", "8150", "1020",
                         "7001", "7002", "7003", "7004", "7005"],
    }


@pytest.fixture
def parsed_data(sample_raw_data):
    return parse_daily_brokers(sample_raw_data)


# --- Parse Tests ---

class TestParseLots:
    def test_normal(self):
        assert _parse_lots("17,206") == 17206

    def test_no_comma(self):
        assert _parse_lots("500") == 500

    def test_empty(self):
        assert _parse_lots("") == 0

    def test_label(self):
        assert _parse_lots("合計賣超張數") == 0


class TestParsePct:
    def test_normal(self):
        assert abs(_parse_pct("3.16%") - 0.0316) < 1e-6

    def test_large(self):
        assert abs(_parse_pct("15.00%") - 0.15) < 1e-6

    def test_label(self):
        assert _parse_pct("平均買超成本") == 0.0


class TestIsSummaryRow:
    def test_buy_summary(self):
        assert _is_summary_row({"broker": "合計買超張數"})

    def test_avg_cost(self):
        assert _is_summary_row({"broker": "平均買超成本"})

    def test_normal_broker(self):
        assert not _is_summary_row({"broker": "凱基-台北"})


class TestIsForeignBroker:
    def test_ubs(self):
        assert _is_foreign_broker("新加坡商瑞銀")

    def test_merrill(self):
        assert _is_foreign_broker("美林")

    def test_domestic(self):
        assert not _is_foreign_broker("凱基-台北")

    def test_morgan(self):
        assert _is_foreign_broker("摩根大通")


class TestParseDailyBrokers:
    def test_summary_row_removed(self, parsed_data):
        # Summary row should be filtered out
        assert len(parsed_data["buy_brokers"]) == 5
        for b in parsed_data["buy_brokers"]:
            assert "合計" not in b["broker"]

    def test_sell_brokers_count(self, parsed_data):
        assert len(parsed_data["sell_brokers"]) == 5

    def test_lots_parsed(self, parsed_data):
        first_buy = parsed_data["buy_brokers"][0]
        assert first_buy["buy"] == 5000
        assert first_buy["net"] == 4000

    def test_pct_parsed(self, parsed_data):
        first_buy = parsed_data["buy_brokers"][0]
        assert abs(first_buy["pct"] - 0.15) < 1e-6


# --- Feature Computation Tests ---

class TestComputeBrokerFeatures:
    def test_returns_14_features(self, parsed_data):
        features = compute_broker_features(parsed_data)
        assert len(features) == 14

    def test_all_feature_names(self, parsed_data):
        features = compute_broker_features(parsed_data)
        for name in BROKER_FEATURE_NAMES:
            assert name in features, f"Missing feature: {name}"

    def test_hhi_daily(self, parsed_data):
        features = compute_broker_features(parsed_data)
        hhi = features["broker_hhi_daily"]
        assert 0 < hhi < 1  # Should be a valid HHI

    def test_top3_pct(self, parsed_data):
        features = compute_broker_features(parsed_data)
        # Top 3 buy: 15% + 12% + 10% = 37%
        assert abs(features["broker_top3_pct"] - 0.37) < 0.01

    def test_hhi_delta_without_prev(self, parsed_data):
        features = compute_broker_features(parsed_data)
        assert np.isnan(features["broker_hhi_delta"])

    def test_hhi_delta_with_prev(self, parsed_data):
        features = compute_broker_features(parsed_data, prev_hhi=0.05)
        assert not np.isnan(features["broker_hhi_delta"])

    def test_net_buy_ratio(self, parsed_data):
        features = compute_broker_features(parsed_data)
        ratio = features["broker_net_buy_ratio"]
        assert 0 <= ratio <= 1

    def test_spread(self, parsed_data):
        features = compute_broker_features(parsed_data)
        spread = features["broker_spread"]
        assert spread > 0

    def test_purity_score_below_cutoff(self):
        """Low concentration = zero purity."""
        low_conc = {
            "buy_brokers": [
                {"broker": "A", "buy": 100, "sell": 50, "net": 50, "pct": 0.05},
                {"broker": "B", "buy": 100, "sell": 50, "net": 50, "pct": 0.05},
                {"broker": "C", "buy": 100, "sell": 50, "net": 50, "pct": 0.05},
            ],
            "sell_brokers": [],
            "broker_codes": [],
        }
        features = compute_broker_features(low_conc)
        assert features["broker_purity_score"] == 0.0

    def test_purity_score_high_concentration(self, parsed_data):
        """Top3 > 40% should produce nonzero purity."""
        # Modify to have high concentration
        parsed_data["buy_brokers"][0]["pct"] = 0.30
        parsed_data["buy_brokers"][1]["pct"] = 0.20
        parsed_data["buy_brokers"][2]["pct"] = 0.15
        features = compute_broker_features(parsed_data)
        # 65% > 40% cutoff → nonzero (no winner registry → halved)
        assert features["broker_purity_score"] > 0

    def test_foreign_pct(self, parsed_data):
        features = compute_broker_features(parsed_data)
        # No foreign brokers in buy_top → 0
        assert features["broker_foreign_pct"] == 0.0

    def test_foreign_pct_with_foreign_buyer(self):
        """Foreign broker in buy list."""
        data = {
            "buy_brokers": [
                {"broker": "新加坡商瑞銀", "buy": 1000, "sell": 0, "net": 1000, "pct": 0.50},
                {"broker": "凱基", "buy": 1000, "sell": 500, "net": 500, "pct": 0.30},
            ],
            "sell_brokers": [],
            "broker_codes": [],
        }
        features = compute_broker_features(data)
        assert features["broker_foreign_pct"] == 0.5

    def test_consistency_streak_positive(self, parsed_data):
        features = compute_broker_features(parsed_data, lookback_streak=3)
        # Net buy ratio > 0.5 + prev streak positive → +4
        if features["broker_net_buy_ratio"] > 0.5:
            assert features["broker_consistency_streak"] == 4

    def test_consistency_streak_reset(self, parsed_data):
        """Streak resets on direction change."""
        # Force selling
        for b in parsed_data["buy_brokers"]:
            b["net"] = -abs(b["net"])
        features = compute_broker_features(parsed_data, lookback_streak=5)
        # Was positive, now selling → reset to -1
        assert features["broker_consistency_streak"] == -1

    def test_price_divergence(self, parsed_data):
        ohlc = {"high": 1050, "low": 1000, "close": 1020, "atr_14": 25}
        features = compute_broker_features(parsed_data, ohlc=ohlc)
        # VWAP = (1050+1000+1020)/3 = 1023.33
        # Divergence = (1020 - 1023.33) / 25 ≈ -0.133
        assert abs(features["broker_price_divergence"] - (-0.133)) < 0.01

    def test_price_divergence_without_ohlc(self, parsed_data):
        features = compute_broker_features(parsed_data)
        assert np.isnan(features["broker_price_divergence"])

    def test_volatility_with_lookback(self, parsed_data):
        lookback = [0.6, 0.55, 0.58, 0.62, 0.59, 0.61, 0.57,
                    0.63, 0.56, 0.60, 0.58, 0.62, 0.59, 0.61,
                    0.57, 0.63, 0.56, 0.60, 0.58]
        features = compute_broker_features(parsed_data,
                                           lookback_net_ratios=lookback)
        assert not np.isnan(features["daily_net_buy_volatility"])
        assert features["daily_net_buy_volatility"] > 0

    def test_momentum_5d(self, parsed_data):
        lookback = [0.6, 0.55, 0.58, 0.62]
        features = compute_broker_features(parsed_data,
                                           lookback_net_ratios=lookback)
        assert not np.isnan(features["broker_net_momentum_5d"])


# --- Data Quality Tests ---

class TestComputeDataQuality:
    def test_full_quality(self, parsed_data):
        features = compute_broker_features(parsed_data, prev_hhi=0.05,
                                           prev_turnover=10000,
                                           lookback_net_ratios=[0.5]*20,
                                           ohlc={"high": 100, "low": 90, "close": 95, "atr_14": 5},
                                           tier1_codes={"6010"})
        quality = compute_data_quality(features)
        assert quality["quality"] == "good"
        assert quality["discount"] == 1.0

    def test_partial_quality(self, parsed_data):
        features = compute_broker_features(parsed_data)
        # Without prev_hhi, prev_turnover, lookback, ohlc → several NaN
        quality = compute_data_quality(features)
        missing = quality["missing"]
        assert missing > 0

    def test_insufficient_quality(self):
        """All NaN features → insufficient."""
        features = {name: np.nan for name in BROKER_FEATURE_NAMES}
        quality = compute_data_quality(features)
        assert quality["quality"] == "insufficient"
        assert quality["discount"] == 0.0

    def test_degraded_quality(self):
        """4 missing features → degraded."""
        features = {name: 0.5 for name in BROKER_FEATURE_NAMES}
        # Set 4 to NaN
        for name in BROKER_FEATURE_NAMES[:4]:
            features[name] = np.nan
        quality = compute_data_quality(features)
        assert quality["quality"] == "degraded"
        assert quality["discount"] == 0.5


# --- Winner Registry Tests ---

class TestWinnerRegistry:
    def test_purity_with_winner_registry(self):
        data = {
            "buy_brokers": [
                {"broker": "凱基-台北", "buy": 5000, "sell": 500, "net": 4500, "pct": 0.50},
                {"broker": "富邦", "buy": 3000, "sell": 500, "net": 2500, "pct": 0.30},
                {"broker": "元大", "buy": 1000, "sell": 200, "net": 800, "pct": 0.10},
            ],
            "sell_brokers": [],
            "broker_codes": ["6010", "9600", "0039"],
        }
        # Winner registry: only "6010" is a winner
        registry = {"6010": {"score": 1.5, "n": 25}}
        features = compute_broker_features(data, winner_registry=registry)
        # Top3 = 90% > 40%, 1 of 3 winners → purity = 0.90 * (1/3) * 100 = 30
        assert abs(features["broker_purity_score"] - 30.0) < 0.5

    def test_purity_all_winners(self):
        data = {
            "buy_brokers": [
                {"broker": "A", "buy": 5000, "sell": 0, "net": 5000, "pct": 0.50},
                {"broker": "B", "buy": 3000, "sell": 0, "net": 3000, "pct": 0.30},
                {"broker": "C", "buy": 1000, "sell": 0, "net": 1000, "pct": 0.10},
            ],
            "sell_brokers": [],
            "broker_codes": ["W1", "W2", "W3"],
        }
        registry = {"W1": {}, "W2": {}, "W3": {}}
        features = compute_broker_features(data, winner_registry=registry)
        # Top3 = 90% > 40%, 3/3 winners → purity = 0.90 * 1.0 * 100 = 90
        assert abs(features["broker_purity_score"] - 90.0) < 0.5


# --- Feature Names Constant ---

class TestWinnerMomentum:
    def test_no_tier1_codes(self, parsed_data):
        features = compute_broker_features(parsed_data)
        assert features["broker_winner_momentum"] == 0

    def test_one_tier1_match(self, parsed_data):
        # "6010" is first broker code in fixture
        features = compute_broker_features(parsed_data, tier1_codes={"6010"})
        assert features["broker_winner_momentum"] == 50

    def test_two_tier1_matches(self, parsed_data):
        features = compute_broker_features(parsed_data, tier1_codes={"6010", "9600"})
        assert features["broker_winner_momentum"] == 100

    def test_three_tier1_matches_caps_at_100(self, parsed_data):
        features = compute_broker_features(parsed_data, tier1_codes={"6010", "9600", "0039"})
        assert features["broker_winner_momentum"] == 100

    def test_no_match(self, parsed_data):
        features = compute_broker_features(parsed_data, tier1_codes={"XXXX"})
        assert features["broker_winner_momentum"] == 0


class TestFeatureNames:
    def test_count(self):
        assert len(BROKER_FEATURE_NAMES) == 14

    def test_all_start_with_broker_or_branch_or_daily(self):
        for name in BROKER_FEATURE_NAMES:
            assert (name.startswith("broker_") or
                    name.startswith("branch_") or
                    name.startswith("daily_")), f"Unexpected name: {name}"

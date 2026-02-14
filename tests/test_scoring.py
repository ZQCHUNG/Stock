"""Tests for SQS scoring module (Gemini R42-R45)."""

import pytest

from analysis.scoring import (
    TRANSACTION_COST,
    MCAP_LARGE,
    MCAP_MID,
    INST_WEIGHTS_LARGE,
    INST_WEIGHTS_MID,
    INST_WEIGHTS_SMALL,
    _score_fitness,
    _score_regime,
    _score_net_ev,
    _score_heat,
    _score_maturity,
    _score_institutional,
    _score_institutional_weighted,
    _get_inst_weights,
    _ratio_to_score,
    calculate_sqs,
    compute_sqs_distribution,
)


class TestScoreFitness:
    def test_perfect_match_v4(self):
        assert _score_fitness("Trend Preferred (V4)", "V4") == 100.0

    def test_perfect_match_v5(self):
        assert _score_fitness("Volatility Preferred (V5)", "V5") == 100.0

    def test_balanced_accepts_all(self):
        # Balanced includes V4, V5, Adaptive → perfect match (100)
        assert _score_fitness("Balanced", "V4") == 100.0
        assert _score_fitness("Balanced", "V5") == 100.0

    def test_mismatch(self):
        assert _score_fitness("Trend Only (V4)", "V5") == 20.0
        assert _score_fitness("Volatility Preferred (V5)", "V4") == 20.0

    def test_no_data(self):
        assert _score_fitness("", "V4") == 50.0
        assert _score_fitness("Insufficient Data", "V4") == 50.0


class TestScoreRegime:
    def test_bull_v4_optimal(self):
        assert _score_regime("bull", "V4") == 95

    def test_bear_v4_worst(self):
        assert _score_regime("bear", "V4") == 20

    def test_sideways_v5_good(self):
        assert _score_regime("sideways", "V5") == 85

    def test_unknown_regime(self):
        assert _score_regime("unknown", "V4") == 50.0


class TestScoreNetEv:
    def test_insufficient_data(self):
        assert _score_net_ev(None, 0) == 40.0
        assert _score_net_ev(0.01, 2) == 40.0  # < 3 samples

    def test_zero_ev(self):
        # raw_ev=0.00785 → net_ev=0 → score ~50 (with confidence)
        score = _score_net_ev(TRANSACTION_COST, 20)
        assert 45 < score < 55

    def test_positive_ev(self):
        score = _score_net_ev(0.03 + TRANSACTION_COST, 20)
        assert score >= 90

    def test_negative_ev(self):
        score = _score_net_ev(-0.01, 20)
        assert score < 30

    def test_confidence_discount(self):
        # Same EV, different sample sizes
        score_small = _score_net_ev(0.02, 5)
        score_large = _score_net_ev(0.02, 20)
        assert score_large > score_small


class TestScoreHeat:
    def test_no_data(self):
        assert _score_heat(None, "stable") == 50.0

    def test_high_heat_surge(self):
        score = _score_heat(0.5, "surge")
        assert score >= 70

    def test_low_heat_cooling(self):
        score = _score_heat(0.05, "cooling")
        assert score < 20


class TestScoreMaturity:
    def test_structural_shift(self):
        assert _score_maturity("Structural Shift") == 95.0

    def test_trend_formation(self):
        assert _score_maturity("Trend Formation") == 70.0

    def test_speculative_spike(self):
        assert _score_maturity("Speculative Spike") == 30.0

    def test_unknown(self):
        assert _score_maturity("Unknown") == 40.0


class TestScoreInstitutional:
    def test_no_data(self):
        assert _score_institutional(None) == 50.0

    def test_strong_buy(self):
        score = _score_institutional(0.2)
        assert score >= 90

    def test_strong_sell(self):
        score = _score_institutional(-0.2)
        assert score <= 15

    def test_neutral(self):
        score = _score_institutional(0.0)
        assert 45 < score < 55

    def test_moderate_buy(self):
        score = _score_institutional(0.1)
        assert 65 < score < 80


class TestMarketCapWeighting:
    """R45-3: Market cap weighted institutional scoring."""

    def test_get_inst_weights_large(self):
        w = _get_inst_weights(100e9)  # 1000億
        assert w == INST_WEIGHTS_LARGE

    def test_get_inst_weights_mid(self):
        w = _get_inst_weights(20e9)  # 200億
        assert w == INST_WEIGHTS_MID

    def test_get_inst_weights_small(self):
        w = _get_inst_weights(5e9)  # 50億
        assert w == INST_WEIGHTS_SMALL

    def test_get_inst_weights_none(self):
        w = _get_inst_weights(None)
        assert w == INST_WEIGHTS_MID  # Default fallback

    def test_ratio_to_score_matches_original(self):
        # _ratio_to_score should give same results as _score_institutional
        for ratio in [None, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3]:
            assert _ratio_to_score(ratio) == _score_institutional(ratio)

    def test_weighted_large_cap_foreign_dominated(self):
        # Large cap: foreign 70%. If foreign buys heavily, score high.
        score = _score_institutional_weighted(
            foreign_ratio=0.2, trust_ratio=0.0, dealer_ratio=0.0,
            market_cap=100e9,
        )
        # Foreign 95 * 0.7 + Trust 50 * 0.2 + Dealer 50 * 0.1 = 66.5 + 10 + 5 = 81.5
        assert score > 75

    def test_weighted_small_cap_trust_dominated(self):
        # Small cap: trust 50%. If trust buys heavily, score high.
        score = _score_institutional_weighted(
            foreign_ratio=0.0, trust_ratio=0.2, dealer_ratio=0.0,
            market_cap=5e9,
        )
        # Foreign 50 * 0.25 + Trust 95 * 0.5 + Dealer 50 * 0.25 = 12.5 + 47.5 + 12.5 = 72.5
        assert score > 70

    def test_weighted_vs_unweighted_large_cap_foreign_sell(self):
        # Large cap: foreign sell, trust buy
        # Weighted should weigh foreign sell more heavily
        weighted = _score_institutional_weighted(
            foreign_ratio=-0.15, trust_ratio=0.15, dealer_ratio=0.0,
            market_cap=100e9,
        )
        # Combined ratio: roughly 0, so unweighted = 50
        unweighted = _score_institutional(0.0)
        # Weighted should be lower because foreign (70%) is selling
        assert weighted < unweighted

    def test_weighted_all_none(self):
        # All None should return 50 (neutral)
        score = _score_institutional_weighted(None, None, None, None)
        assert score == 50.0

    def test_calculate_sqs_with_breakdown(self):
        # When breakdown ratios provided, should use weighted scoring
        r1 = calculate_sqs(
            foreign_ratio=0.2, trust_ratio=0.0, dealer_ratio=0.0,
            market_cap=100e9,
        )
        r2 = calculate_sqs(inst_net_ratio=0.05)
        # Both should have valid SQS
        assert 0 <= r1["sqs"] <= 100
        assert 0 <= r2["sqs"] <= 100

    def test_mcap_tier_label(self):
        r = calculate_sqs(market_cap=100e9)
        assert r["mcap_tier"] == "large"
        r = calculate_sqs(market_cap=20e9)
        assert r["mcap_tier"] == "mid"
        r = calculate_sqs(market_cap=5e9)
        assert r["mcap_tier"] == "small"
        r = calculate_sqs()
        assert r["mcap_tier"] is None


class TestCalculateSqs:
    def test_default_returns_dict(self):
        result = calculate_sqs()
        assert "sqs" in result
        assert "grade" in result
        assert "breakdown" in result
        assert 0 <= result["sqs"] <= 100

    def test_perfect_score(self):
        result = calculate_sqs(
            fitness_tag="Trend Only (V4)",
            signal_strategy="V4",
            regime="bull",
            raw_ev_20d=0.05,
            ev_sample_count=30,
            sector_weighted_heat=0.5,
            sector_momentum="surge",
            signal_maturity="Structural Shift",
            inst_net_ratio=0.3,
        )
        assert result["sqs"] >= 80
        assert result["grade"] == "diamond"

    def test_worst_score(self):
        result = calculate_sqs(
            fitness_tag="Volatility Preferred (V5)",
            signal_strategy="V4",
            regime="bear",
            raw_ev_20d=-0.03,
            ev_sample_count=30,
            sector_weighted_heat=0.01,
            sector_momentum="cooling",
            signal_maturity="Speculative Spike",
            inst_net_ratio=-0.3,
        )
        assert result["sqs"] < 30
        assert result["grade"] == "noise"

    def test_cost_trap_detection(self):
        result = calculate_sqs(raw_ev_20d=0.005, ev_sample_count=20)
        assert result["cost_trap"] is True
        assert result["net_ev"] < 0

    def test_no_cost_trap(self):
        result = calculate_sqs(raw_ev_20d=0.02, ev_sample_count=20)
        assert result["cost_trap"] is False

    def test_breakdown_has_6_dimensions(self):
        result = calculate_sqs()
        assert len(result["breakdown"]) == 6
        assert "institutional" in result["breakdown"]

    def test_grade_labels(self):
        r = calculate_sqs(fitness_tag="Trend Only (V4)", signal_strategy="V4", regime="bull",
                          inst_net_ratio=0.3, signal_maturity="Structural Shift")
        assert r["grade"] in ("diamond", "gold", "silver", "noise")


class TestSqsDistribution:
    def test_empty(self):
        result = compute_sqs_distribution([])
        assert result["count"] == 0

    def test_basic_distribution(self):
        scores = [
            {"code": "2330", "sqs": 85, "grade": "diamond"},
            {"code": "2317", "sqs": 70, "grade": "gold"},
            {"code": "2454", "sqs": 55, "grade": "silver"},
            {"code": "3008", "sqs": 40, "grade": "silver"},
            {"code": "1301", "sqs": 30, "grade": "noise"},
        ]
        result = compute_sqs_distribution(scores)
        assert result["count"] == 5
        assert "percentiles" in result
        assert "histogram" in result
        assert "adaptive_grades" in result

    def test_adaptive_grading(self):
        # 10 stocks — top 2 should be diamond, next 3 gold, etc.
        scores = [{"code": str(i), "sqs": 90 - i * 5, "grade": "x"} for i in range(10)]
        result = compute_sqs_distribution(scores)
        grades = result["adaptive_grades"]
        # Top 20% (2 stocks) = diamond
        assert grades["0"]["adaptive_grade"] == "diamond"
        assert grades["1"]["adaptive_grade"] == "diamond"
        # 20-50% (3 stocks) = gold
        assert grades["2"]["adaptive_grade"] == "gold"
        # Bottom 20% (2 stocks) = noise
        assert grades["8"]["adaptive_grade"] == "noise"
        assert grades["9"]["adaptive_grade"] == "noise"

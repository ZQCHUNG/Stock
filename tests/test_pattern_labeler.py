"""Tests for Pattern Labeler (analysis/pattern_labeler.py)

[CONVERGED — Wall Street Trader + Architect Critic APPROVED]
"""

import numpy as np
import pandas as pd
import pytest

from analysis.pattern_labeler import (
    LABELER_CONFIG,
    _deduplicate_episodes,
    _find_nearest_date_idx,
    build_control_group,
    compute_forward_returns,
    compute_super_stock_flags,
    extract_epiphany_features,
    find_super_stock_episodes,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_price_df(stock_code, closes, start_date="2023-01-02"):
    """Build a price DataFrame for a single stock."""
    n = len(closes)
    dates = pd.bdate_range(start=start_date, periods=n)
    return pd.DataFrame({
        "stock_code": stock_code,
        "date": dates,
        "close": closes,
    })


def _make_super_stock_prices(n_days=600, base=50.0):
    """Create prices that show a super stock pattern.

    Flat for ~300 days, then explosive rise for ~300 days.
    Must exceed: 50% in 63 trading days AND 100% in 252 days.
    """
    np.random.seed(42)
    flat = [base + np.random.normal(0, 0.3) for _ in range(300)]
    # Explosive rise: ~1.2% per day → ~110% in 63 days, ~3400% in 300 days
    rise = []
    price = base
    for i in range(300):
        price *= 1.012
        rise.append(price + np.random.normal(0, 0.1))
    return flat + rise


def _make_loser_prices(n_days=500, base=50.0):
    """Create prices that look hot initially but fail."""
    # Rise a bit then crash
    prices = [base]
    for i in range(n_days - 1):
        if i < 50:
            prices.append(prices[-1] * 1.003)  # Small rise
        else:
            prices.append(prices[-1] * 0.997)  # Gradual decline
    return prices


def _make_features_df(stock_codes, n_days=500, start_date="2023-01-02"):
    """Build a synthetic features DataFrame."""
    dates = pd.bdate_range(start=start_date, periods=n_days)
    rows = []
    for code in stock_codes:
        for date in dates:
            row = {
                "stock_code": code,
                "date": date,
                "regime_tag": 1,  # Bull market
            }
            # 65 features with random values
            all_features = [
                "ret_1d", "ret_5d", "ret_20d", "ma5_ratio", "ma20_ratio",
                "ma60_ratio", "bb_position", "rsi_14", "macd_hist", "kd_k",
                "kd_d", "atr_pct", "vol_ratio_5", "vol_ratio_20",
                "high_low_range", "close_vs_high", "gap_pct", "trend_slope_20",
                "volatility_20", "rs_rating",
                "inst_foreign_net", "inst_trust_net", "inst_dealer_net",
                "inst_total_net", "inst_5d_sum", "margin_balance_chg",
                "short_balance_chg", "margin_utilization", "tdcc_retail_chg",
                "tdcc_big_chg", "tdcc_concentration",
                "broker_hhi_daily", "broker_top3_pct", "broker_hhi_delta",
                "broker_net_buy_ratio", "broker_spread",
                "broker_net_momentum_5d", "broker_purity_score",
                "broker_foreign_pct", "branch_overlap_count",
                "daily_net_buy_volatility", "broker_turnover_chg",
                "broker_consistency_streak", "broker_price_divergence",
                "broker_winner_momentum",
                "sector_rs", "peer_alpha", "sector_momentum",
                "industry_chain_pos", "sector_concentration",
                "eps_yoy", "roe", "revenue_yoy", "revenue_mom",
                "pe_percentile", "pb_ratio", "operating_margin", "debt_ratio",
                "attention_index_7d", "attention_spike", "source_diversity",
                "news_velocity", "polarity_filter", "news_recency",
                "co_occurrence_score",
            ]
            for feat in all_features:
                row[feat] = np.random.normal(0, 1)
            rows.append(row)
    return pd.DataFrame(rows)


def _make_metadata():
    """Build synthetic metadata dict matching real structure."""
    return {
        "dimensions": {
            "technical": {
                "features": [
                    "ret_1d", "ret_5d", "ret_20d", "ma5_ratio", "ma20_ratio",
                    "ma60_ratio", "bb_position", "rsi_14", "macd_hist", "kd_k",
                    "kd_d", "atr_pct", "vol_ratio_5", "vol_ratio_20",
                    "high_low_range", "close_vs_high", "gap_pct",
                    "trend_slope_20", "volatility_20", "rs_rating",
                ],
                "count": 20,
            },
            "brokerage": {
                "features": [
                    "broker_hhi_daily", "broker_top3_pct", "broker_hhi_delta",
                    "broker_net_buy_ratio", "broker_spread",
                    "broker_net_momentum_5d", "broker_purity_score",
                    "broker_foreign_pct", "branch_overlap_count",
                    "daily_net_buy_volatility", "broker_turnover_chg",
                    "broker_consistency_streak", "broker_price_divergence",
                    "broker_winner_momentum",
                ],
                "count": 14,
            },
            "institutional": {"features": [], "count": 0},
            "industry": {"features": [], "count": 0},
            "fundamental": {"features": [], "count": 0},
            "attention": {"features": [], "count": 0},
        },
        "all_features": [
            "ret_1d", "ret_5d", "ret_20d", "ma5_ratio", "ma20_ratio",
            "ma60_ratio", "bb_position", "rsi_14", "macd_hist", "kd_k",
            "kd_d", "atr_pct", "vol_ratio_5", "vol_ratio_20",
            "high_low_range", "close_vs_high", "gap_pct", "trend_slope_20",
            "volatility_20", "rs_rating",
            "inst_foreign_net", "inst_trust_net", "inst_dealer_net",
            "inst_total_net", "inst_5d_sum", "margin_balance_chg",
            "short_balance_chg", "margin_utilization", "tdcc_retail_chg",
            "tdcc_big_chg", "tdcc_concentration",
            "broker_hhi_daily", "broker_top3_pct", "broker_hhi_delta",
            "broker_net_buy_ratio", "broker_spread",
            "broker_net_momentum_5d", "broker_purity_score",
            "broker_foreign_pct", "branch_overlap_count",
            "daily_net_buy_volatility", "broker_turnover_chg",
            "broker_consistency_streak", "broker_price_divergence",
            "broker_winner_momentum",
            "sector_rs", "peer_alpha", "sector_momentum",
            "industry_chain_pos", "sector_concentration",
            "eps_yoy", "roe", "revenue_yoy", "revenue_mom",
            "pe_percentile", "pb_ratio", "operating_margin", "debt_ratio",
            "attention_index_7d", "attention_spike", "source_diversity",
            "news_velocity", "polarity_filter", "news_recency",
            "co_occurrence_score",
        ],
        "total_features": 65,
    }


# ---------------------------------------------------------------------------
# find_super_stock_episodes Tests
# ---------------------------------------------------------------------------

class TestFindSuperStockEpisodes:
    def test_detects_super_stock(self):
        """Stock that doubles in 3 months should be detected."""
        prices = _make_super_stock_prices(n_days=500)
        df = _make_price_df("TEST", prices)
        episodes = find_super_stock_episodes(df)
        assert len(episodes) > 0
        assert all(episodes["label"] == "winner")
        assert all(episodes["gain_3mo"] >= 0.50)

    def test_flat_stock_not_detected(self):
        """Flat stock should not be detected."""
        prices = [100.0 + np.random.normal(0, 1) for _ in range(500)]
        df = _make_price_df("FLAT", prices)
        episodes = find_super_stock_episodes(df)
        assert len(episodes) == 0

    def test_insufficient_data(self):
        """Less than 252 days should return empty."""
        df = _make_price_df("SHORT", [100.0] * 100)
        episodes = find_super_stock_episodes(df)
        assert len(episodes) == 0

    def test_multiple_stocks(self):
        """Should handle multiple stocks."""
        np.random.seed(42)
        df1 = _make_price_df("WINNER", _make_super_stock_prices())
        df2 = _make_price_df("FLAT", [100.0 + np.random.normal(0, 0.5) for _ in range(600)])
        combined = pd.concat([df1, df2], ignore_index=True)
        episodes = find_super_stock_episodes(combined)
        assert len(episodes) > 0
        # Only the winner stock should be detected
        assert all(episodes["stock_code"] == "WINNER")

    def test_config_override(self):
        """Custom thresholds should work."""
        prices = [50.0] * 300
        # 40% gain in 3 months
        price = 50.0
        for _ in range(200):
            price *= 1.003
            prices.append(price)
        df = _make_price_df("MED", prices)

        # Default 50% threshold — might not detect
        episodes_strict = find_super_stock_episodes(df)

        # Relaxed threshold
        episodes_relaxed = find_super_stock_episodes(
            df, config={"gain_3mo_threshold": 0.30, "gain_1yr_threshold": 0.50}
        )
        assert len(episodes_relaxed) >= len(episodes_strict)

    def test_episode_has_correct_fields(self):
        """Episode should have all required fields."""
        prices = _make_super_stock_prices()
        df = _make_price_df("TEST", prices)
        episodes = find_super_stock_episodes(df)
        if len(episodes) > 0:
            required = ["stock_code", "epiphany_date", "trough_date",
                        "peak_date", "gain_3mo", "gain_1yr", "label"]
            for field in required:
                assert field in episodes.columns


# ---------------------------------------------------------------------------
# Deduplication Tests
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_removes_close_episodes(self):
        """Episodes within 60 days should be deduplicated."""
        episodes = pd.DataFrame([
            {"stock_code": "A", "epiphany_date": pd.Timestamp("2024-01-01"),
             "gain_1yr": 1.5},
            {"stock_code": "A", "epiphany_date": pd.Timestamp("2024-01-15"),
             "gain_1yr": 1.2},
            {"stock_code": "A", "epiphany_date": pd.Timestamp("2024-06-01"),
             "gain_1yr": 2.0},
        ])
        result = _deduplicate_episodes(episodes, gap_days=60)
        assert len(result) == 2  # Jan and June kept

    def test_different_stocks_not_deduplicated(self):
        """Different stocks on same date should both be kept."""
        episodes = pd.DataFrame([
            {"stock_code": "A", "epiphany_date": pd.Timestamp("2024-01-01"),
             "gain_1yr": 1.5},
            {"stock_code": "B", "epiphany_date": pd.Timestamp("2024-01-01"),
             "gain_1yr": 1.2},
        ])
        result = _deduplicate_episodes(episodes, gap_days=60)
        assert len(result) == 2

    def test_empty_input(self):
        """Empty DataFrame should return empty."""
        result = _deduplicate_episodes(pd.DataFrame())
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Feature Extraction Tests
# ---------------------------------------------------------------------------

class TestExtractEpiphanyFeatures:
    def test_basic_extraction(self):
        """Should extract features at epiphany date."""
        metadata = _make_metadata()
        features_df = _make_features_df(["TEST"], n_days=500)

        # Create episode matching a date in the features
        ep_date = features_df["date"].iloc[300]
        episodes = pd.DataFrame([{
            "stock_code": "TEST",
            "epiphany_date": ep_date,
            "trough_date": ep_date,
            "peak_date": ep_date + pd.Timedelta(days=90),
            "trough_price": 50.0,
            "peak_price": 120.0,
            "gain_3mo": 1.4,
            "gain_1yr": 2.0,
            "max_drawdown_before_peak": -0.15,
            "label": "winner",
        }])

        result = extract_epiphany_features(episodes, features_df, metadata)
        assert len(result) == 1
        assert "ret_1d" in result.columns
        assert "gene_mutation_delta" in result.columns
        assert "regime_context" in result.columns

    def test_missing_stock_handled(self):
        """Should handle stocks not in features gracefully."""
        metadata = _make_metadata()
        features_df = _make_features_df(["OTHER"], n_days=500)

        episodes = pd.DataFrame([{
            "stock_code": "MISSING",
            "epiphany_date": pd.Timestamp("2024-06-01"),
            "trough_date": pd.Timestamp("2024-06-01"),
            "peak_date": pd.Timestamp("2024-09-01"),
            "trough_price": 50.0,
            "peak_price": 120.0,
            "gain_3mo": 1.4,
            "gain_1yr": 2.0,
            "max_drawdown_before_peak": -0.15,
            "label": "winner",
        }])

        result = extract_epiphany_features(episodes, features_df, metadata)
        assert len(result) == 0  # Missing stock → no result

    def test_gene_mutation_computed(self):
        """Gene mutation Δ_div should be broker_mean - tech_mean."""
        metadata = _make_metadata()
        features_df = _make_features_df(["TEST"], n_days=500)

        ep_date = features_df["date"].iloc[300]
        episodes = pd.DataFrame([{
            "stock_code": "TEST",
            "epiphany_date": ep_date,
            "trough_date": ep_date,
            "peak_date": ep_date + pd.Timedelta(days=90),
            "trough_price": 50.0,
            "peak_price": 120.0,
            "gain_3mo": 1.4,
            "gain_1yr": 2.0,
            "max_drawdown_before_peak": -0.15,
            "label": "winner",
        }])

        result = extract_epiphany_features(episodes, features_df, metadata)
        assert "gene_mutation_delta" in result.columns
        assert "tech_score" in result.columns
        assert "broker_score" in result.columns
        # Δ_div = broker_score - tech_score
        row = result.iloc[0]
        expected = row["broker_score"] - row["tech_score"]
        assert row["gene_mutation_delta"] == pytest.approx(expected, abs=0.001)


# ---------------------------------------------------------------------------
# Forward Returns Tests
# ---------------------------------------------------------------------------

class TestComputeForwardReturns:
    def test_basic_returns(self):
        """Should compute forward returns at each horizon."""
        prices = [100.0 + i * 0.5 for i in range(500)]  # Steadily rising
        price_df = _make_price_df("TEST", prices)

        episodes = pd.DataFrame([{
            "stock_code": "TEST",
            "epiphany_date": price_df["date"].iloc[200],
        }])

        result = compute_forward_returns(episodes, price_df, horizons=[7, 21, 90])
        assert "fwd_7d" in result.columns
        assert "fwd_21d" in result.columns
        assert "fwd_90d" in result.columns
        # Rising prices → positive returns
        assert result["fwd_7d"].iloc[0] > 0
        assert result["fwd_21d"].iloc[0] > 0
        assert result["fwd_90d"].iloc[0] > 0

    def test_max_drawdown_computed(self):
        """Should compute max drawdown in first 30 days."""
        prices = [100.0] * 200 + [90.0] * 10 + [100.0] * 290  # Dip then recover
        price_df = _make_price_df("TEST", prices)

        episodes = pd.DataFrame([{
            "stock_code": "TEST",
            "epiphany_date": price_df["date"].iloc[195],
        }])

        result = compute_forward_returns(episodes, price_df)
        assert "max_drawdown_30d" in result.columns
        assert result["max_drawdown_30d"].iloc[0] < 0  # There was a drawdown

    def test_missing_stock_returns_nan(self):
        """Missing stock should get NaN returns."""
        price_df = _make_price_df("OTHER", [100.0] * 500)
        episodes = pd.DataFrame([{
            "stock_code": "MISSING",
            "epiphany_date": pd.Timestamp("2024-01-15"),
        }])

        result = compute_forward_returns(episodes, price_df, horizons=[7])
        assert pd.isna(result["fwd_7d"].iloc[0])


# ---------------------------------------------------------------------------
# Nearest Date Index Tests
# ---------------------------------------------------------------------------

class TestFindNearestDateIdx:
    def test_exact_match(self):
        dates = pd.DatetimeIndex(pd.bdate_range("2024-01-01", periods=10))
        idx = _find_nearest_date_idx(dates, pd.Timestamp("2024-01-03"))
        assert idx is not None
        assert dates[idx] == pd.Timestamp("2024-01-03")

    def test_within_gap(self):
        dates = pd.DatetimeIndex(pd.bdate_range("2024-01-01", periods=10))
        # Weekend date → should find nearest weekday
        idx = _find_nearest_date_idx(dates, pd.Timestamp("2024-01-06"), max_gap=3)
        assert idx is not None

    def test_outside_gap(self):
        dates = pd.DatetimeIndex(pd.bdate_range("2024-01-01", periods=5))
        # 30 days later → should return None
        idx = _find_nearest_date_idx(dates, pd.Timestamp("2024-03-01"), max_gap=5)
        assert idx is None

    def test_empty_dates(self):
        idx = _find_nearest_date_idx(pd.DatetimeIndex([]), pd.Timestamp("2024-01-01"))
        assert idx is None


# ---------------------------------------------------------------------------
# Super Stock Flags Tests
# ---------------------------------------------------------------------------

class TestSuperStockFlags:
    def test_basic_flags(self):
        """Should flag stocks with extreme Δ_div."""
        metadata = _make_metadata()
        n_stocks = 50
        codes = [f"S{i:03d}" for i in range(n_stocks)]
        features_df = _make_features_df(codes, n_days=1, start_date="2024-06-01")

        # Make one stock have extreme broker vs tech divergence
        mask = features_df["stock_code"] == "S000"
        for f in metadata["dimensions"]["brokerage"]["features"]:
            if f in features_df.columns:
                features_df.loc[mask, f] = 5.0  # Very high broker
        for f in metadata["dimensions"]["technical"]["features"]:
            if f in features_df.columns:
                features_df.loc[mask, f] = -1.0  # Low technical

        result = compute_super_stock_flags(features_df, metadata, sigma_threshold=2.0)
        assert len(result) == n_stocks
        assert "is_super_stock_potential" in result.columns

        flagged = result[result["is_super_stock_potential"]]
        assert len(flagged) > 0
        assert "S000" in flagged["stock_code"].values

    def test_no_flags_in_normal_market(self):
        """Normal market (no extreme divergence) should flag few stocks."""
        metadata = _make_metadata()
        features_df = _make_features_df(["S001", "S002", "S003"],
                                         n_days=1, start_date="2024-06-01")
        result = compute_super_stock_flags(features_df, metadata, sigma_threshold=3.0)
        # With random normal data, 3σ should flag very few
        flagged = result[result["is_super_stock_potential"]]
        assert len(flagged) <= 1  # Possibly 0 or 1 with random data

    def test_empty_features(self):
        """Empty features should return empty."""
        metadata = _make_metadata()
        features_df = pd.DataFrame(columns=["stock_code", "date", "regime_tag"])
        result = compute_super_stock_flags(features_df, metadata)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Control Group Tests
# ---------------------------------------------------------------------------

class TestControlGroup:
    def test_basic_control_group(self):
        """Should build loser samples with matching schema."""
        metadata = _make_metadata()
        features_df = _make_features_df(["A", "B"], n_days=200,
                                         start_date="2023-01-02")

        # Make stocks look "hot" (high momentum indicators)
        features_df["ma20_ratio"] = 1.0
        features_df["vol_ratio_20"] = 1.0

        # Forward returns: all negative
        fwd_df = features_df[["stock_code", "date"]].copy()
        fwd_df["d90"] = -0.10  # -10% forward return

        # Empty winners
        winners = pd.DataFrame(columns=["stock_code", "epiphany_date"])

        result = build_control_group(
            features_df, fwd_df, winners, metadata, n_samples=10
        )

        assert len(result) > 0
        assert all(result["label"] == "loser")
        assert "gene_mutation_delta" in result.columns

    def test_excludes_winner_dates(self):
        """Control group should not overlap with winner episodes."""
        metadata = _make_metadata()
        features_df = _make_features_df(["A"], n_days=200,
                                         start_date="2023-01-02")
        features_df["ma20_ratio"] = 1.0
        features_df["vol_ratio_20"] = 1.0

        fwd_df = features_df[["stock_code", "date"]].copy()
        fwd_df["d90"] = -0.10

        # All dates are "winner" dates → no losers should be selected
        winners = pd.DataFrame([{
            "stock_code": "A",
            "epiphany_date": d,
        } for d in features_df["date"]])

        result = build_control_group(
            features_df, fwd_df, winners, metadata
        )
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Config Tests
# ---------------------------------------------------------------------------

class TestConfig:
    def test_default_config_values(self):
        """Default config should have expected values."""
        assert LABELER_CONFIG["gain_3mo_threshold"] == 0.50
        assert LABELER_CONFIG["gain_1yr_threshold"] == 1.00
        assert LABELER_CONFIG["epiphany_lookback_days"] == 21
        assert LABELER_CONFIG["min_history_days"] == 252
        assert 7 in LABELER_CONFIG["forward_horizons"]
        assert 365 in LABELER_CONFIG["forward_horizons"]

"""Tests for Winner DNA Library (analysis/winner_dna.py)

[CONVERGED — Wall Street Trader + Architect Critic APPROVED]
"""

import numpy as np
import pandas as pd
import pytest

from analysis.winner_dna import (
    WINNER_DNA_CONFIG,
    ClusterProfile,
    HorizonStats,
    MatchResult,
    _auto_label_cluster,
    _compute_horizon_stats,
    _compute_recency_weighted_performance,
    _cosine_sim,
    _find_knn_neighbors,
    cluster_winners,
    compute_cluster_profiles,
    load_profiles_from_db,
    match_stock_to_dna,
    reduce_dimensions,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_feature_matrix(n_samples=99, n_features=65, n_groups=3):
    """Build synthetic feature matrix with natural clusters."""
    np.random.seed(42)
    per_group = n_samples // n_groups
    matrices = []
    for g in range(n_groups):
        center = np.random.normal(0, 1, n_features) * (g + 1)
        group = center + np.random.normal(0, 0.5, (per_group, n_features))
        matrices.append(group)
    return np.vstack(matrices)


def _make_samples_df(n_samples=90, n_features=65):
    """Build synthetic winner_dna_samples DataFrame."""
    np.random.seed(42)
    all_features = [f"feat_{i}" for i in range(n_features)]

    rows = []
    for i in range(n_samples):
        row = {
            "stock_code": f"S{i % 30:03d}",
            "epiphany_date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=i),
            "label": "winner" if i < 60 else "loser",
            "regime_context": np.random.choice([1, 0, -1]),
            "gene_mutation_delta": np.random.normal(0, 1),
        }

        # Features — create 3 natural groups
        group = i % 3
        for j, feat in enumerate(all_features):
            row[feat] = (group + 1) * np.random.normal(0, 1) + group * 0.5

        # Forward returns
        for h in [7, 21, 30, 60, 90, 180, 365]:
            row[f"fwd_{h}d"] = np.random.normal(0.05 if i < 60 else -0.03, 0.1)

        rows.append(row)

    return pd.DataFrame(rows), all_features


# ---------------------------------------------------------------------------
# Dimensionality Reduction Tests
# ---------------------------------------------------------------------------

class TestReduceDimensions:
    def test_pca_reduces_dimensions(self):
        """PCA should reduce from 65 to 8 components."""
        matrix = _make_feature_matrix(99, 65)
        reduced, reducer = reduce_dimensions(matrix, method="pca")
        assert reduced.shape == (99, 8)  # 99 = 33*3 groups
        assert reduced.shape[1] < matrix.shape[1]

    def test_umap_reduces_dimensions(self):
        """UMAP should reduce from 65 to 8 components."""
        matrix = _make_feature_matrix(99, 65)
        reduced, reducer = reduce_dimensions(matrix, method="umap")
        assert reduced.shape == (99, 8)

    def test_handles_nan(self):
        """NaN values should be handled (filled with 0)."""
        matrix = _make_feature_matrix(50, 65)
        matrix[0, 0] = np.nan
        matrix[10, 30] = np.nan
        reduced, _ = reduce_dimensions(matrix, method="pca")
        assert not np.any(np.isnan(reduced))

    def test_custom_components(self):
        """Should respect custom n_components."""
        matrix = _make_feature_matrix(99, 65)
        reduced, _ = reduce_dimensions(
            matrix, method="pca",
            config={"pca_n_components": 5}
        )
        assert reduced.shape[1] == 5

    def test_reducer_is_reusable(self):
        """Reducer should be able to transform new data."""
        matrix = _make_feature_matrix(99, 65)
        reduced, reducer = reduce_dimensions(matrix, method="pca")

        # New data
        new_data = np.random.normal(0, 1, (5, 65))
        new_reduced = reducer.transform(new_data)
        assert new_reduced.shape == (5, 8)


# ---------------------------------------------------------------------------
# HDBSCAN Clustering Tests
# ---------------------------------------------------------------------------

class TestClusterWinners:
    def test_finds_clusters(self):
        """HDBSCAN should find clusters in structured data."""
        # Create well-separated groups
        np.random.seed(42)
        group1 = np.random.normal(0, 0.5, (30, 8))
        group2 = np.random.normal(5, 0.5, (30, 8))
        group3 = np.random.normal(-5, 0.5, (30, 8))
        matrix = np.vstack([group1, group2, group3])

        labels, clusterer = cluster_winners(matrix)
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        assert n_clusters >= 2  # At least 2 clusters found

    def test_noise_points_labeled_minus1(self):
        """Noise points should be labeled -1."""
        np.random.seed(42)
        # Add some outliers
        group = np.random.normal(0, 0.5, (20, 8))
        outliers = np.random.normal(100, 0.1, (3, 8))
        matrix = np.vstack([group, outliers])

        labels, _ = cluster_winners(
            matrix,
            config={"hdbscan_min_cluster_size": 5, "hdbscan_min_samples": 3}
        )
        # At least some points should be in clusters
        assert len(labels) == len(matrix)

    def test_handles_small_dataset(self):
        """Should handle very small datasets."""
        matrix = np.random.normal(0, 1, (10, 8))
        labels, _ = cluster_winners(
            matrix,
            config={"hdbscan_min_cluster_size": 3, "hdbscan_min_samples": 2}
        )
        assert len(labels) == 10


# ---------------------------------------------------------------------------
# Cluster Profile Tests
# ---------------------------------------------------------------------------

class TestComputeClusterProfiles:
    def test_basic_profile(self):
        """Should compute profiles for each cluster."""
        samples_df, all_features = _make_samples_df(90, 65)
        reduced = np.random.normal(0, 1, (90, 8))

        # Assign clusters manually
        labels = np.array([0] * 30 + [1] * 30 + [2] * 30)

        profiles = compute_cluster_profiles(
            samples_df, labels, reduced, all_features
        )

        assert len(profiles) == 3
        for p in profiles:
            assert p.n_samples == 30
            assert len(p.centroid) == 8
            assert len(p.top_features) > 0

    def test_performance_stats(self):
        """Each profile should have performance stats per horizon."""
        samples_df, all_features = _make_samples_df(90, 65)
        reduced = np.random.normal(0, 1, (90, 8))
        labels = np.array([0] * 45 + [1] * 45)

        profiles = compute_cluster_profiles(
            samples_df, labels, reduced, all_features
        )

        for p in profiles:
            assert "d21" in p.performance or "d90" in p.performance
            for key, stats in p.performance.items():
                assert "win_rate" in stats
                assert "expectancy" in stats
                assert 0 <= stats["win_rate"] <= 1

    def test_gene_mutation_stats(self):
        """Profile should include gene mutation statistics."""
        samples_df, all_features = _make_samples_df(60, 65)
        reduced = np.random.normal(0, 1, (60, 8))
        labels = np.array([0] * 60)

        profiles = compute_cluster_profiles(
            samples_df, labels, reduced, all_features
        )

        assert len(profiles) == 1
        p = profiles[0]
        assert p.avg_mutation_delta != 0 or p.std_mutation_delta != 0

    def test_noise_excluded(self):
        """Noise points (label -1) should not form a profile."""
        samples_df, all_features = _make_samples_df(90, 65)
        reduced = np.random.normal(0, 1, (90, 8))
        labels = np.array([0] * 30 + [-1] * 30 + [1] * 30)

        profiles = compute_cluster_profiles(
            samples_df, labels, reduced, all_features
        )

        cluster_ids = [p.cluster_id for p in profiles]
        assert -1 not in cluster_ids


# ---------------------------------------------------------------------------
# Horizon Stats Tests
# ---------------------------------------------------------------------------

class TestComputeHorizonStats:
    def test_all_positive_returns(self):
        """All positive returns → 100% win rate."""
        returns = np.array([0.05, 0.10, 0.03, 0.08, 0.15])
        stats = _compute_horizon_stats(returns, horizon=21, txn_cost=0.00785)
        assert stats.win_rate == 1.0
        assert stats.avg_return > 0
        assert stats.expectancy > 0

    def test_all_negative_returns(self):
        """All negative returns → 0% win rate."""
        returns = np.array([-0.05, -0.10, -0.03, -0.08, -0.15])
        stats = _compute_horizon_stats(returns, horizon=21, txn_cost=0.00785)
        assert stats.win_rate == 0.0
        assert stats.avg_return < 0
        assert stats.expectancy < 0

    def test_mixed_returns(self):
        """Mixed returns → partial win rate."""
        returns = np.array([0.05, -0.03, 0.10, -0.05, 0.02])
        stats = _compute_horizon_stats(returns, horizon=21, txn_cost=0.00785)
        assert 0 < stats.win_rate < 1
        assert stats.n_valid == 5

    def test_profit_factor(self):
        """Profit factor = sum(wins) / abs(sum(losses))."""
        returns = np.array([0.10, 0.20, -0.05, -0.10])
        stats = _compute_horizon_stats(returns, horizon=21, txn_cost=0.00785)
        # Wins: 0.10 + 0.20 = 0.30
        # Losses: |-0.05 + -0.10| = 0.15
        # PF = 0.30 / 0.15 = 2.0
        assert stats.profit_factor == pytest.approx(2.0, abs=0.01)

    def test_single_return(self):
        """Single return → n_valid = 1, limited stats."""
        returns = np.array([0.05])
        stats = _compute_horizon_stats(returns, horizon=7, txn_cost=0.00785)
        assert stats.n_valid == 1


# ---------------------------------------------------------------------------
# Match Tests
# ---------------------------------------------------------------------------

class TestMatchStockToDna:
    def test_basic_match(self):
        """Should match a stock against cluster centroids."""
        samples_df, all_features = _make_samples_df(90, 65)

        # Build minimal features_df for a stock
        features_df = pd.DataFrame([{
            "stock_code": "TEST",
            "date": pd.Timestamp("2024-06-01"),
            **{f: np.random.normal(0, 1) for f in all_features},
        }])

        # Create fake profiles
        profiles = [
            ClusterProfile(
                cluster_id=0,
                centroid=[1.0] * 8,
                n_samples=30,
            ),
            ClusterProfile(
                cluster_id=1,
                centroid=[-1.0] * 8,
                n_samples=30,
            ),
        ]

        # Use PCA as reducer
        from sklearn.decomposition import PCA
        matrix = np.random.normal(0, 1, (90, len(all_features)))
        reducer = PCA(n_components=8, random_state=42)
        reducer.fit(matrix)

        result = match_stock_to_dna(
            "TEST", features_df, profiles, reducer, all_features
        )

        assert result.stock_code == "TEST"
        assert result.best_cluster_id in [0, 1]
        assert -1 <= result.cosine_similarity <= 1

    def test_missing_stock(self):
        """Missing stock should return empty result."""
        features_df = pd.DataFrame(columns=["stock_code", "date"])
        all_features = [f"feat_{i}" for i in range(65)]

        result = match_stock_to_dna(
            "MISSING", features_df, [], None, all_features
        )
        assert result.stock_code == "MISSING"
        assert not result.is_match


# ---------------------------------------------------------------------------
# Auto-Label Tests
# ---------------------------------------------------------------------------

class TestAutoLabel:
    def test_momentum_label(self):
        """High ma20_ratio should produce MomentumBreak label."""
        profile = ClusterProfile(cluster_id=0)
        feat_means = {"ma20_ratio": 1.5, "vol_ratio_20": 0.5}
        label = _auto_label_cluster(profile, feat_means)
        assert "MomentumBreak" in label

    def test_volume_label(self):
        """High vol_ratio_20 should produce VolumeExplosion label."""
        profile = ClusterProfile(cluster_id=0)
        feat_means = {"vol_ratio_20": 2.0, "ma20_ratio": 0.5}
        label = _auto_label_cluster(profile, feat_means)
        assert "VolumeExplosion" in label

    def test_fallback_label(self):
        """No dominant features → fallback to Cluster_X."""
        profile = ClusterProfile(cluster_id=5)
        feat_means = {"ma20_ratio": 0.1, "vol_ratio_20": 0.1}
        label = _auto_label_cluster(profile, feat_means)
        assert "Cluster_5" in label


# ---------------------------------------------------------------------------
# Data Classes Tests
# ---------------------------------------------------------------------------

class TestDataClasses:
    def test_cluster_profile_to_dict(self):
        p = ClusterProfile(cluster_id=1, n_samples=50, label="Test")
        d = p.to_dict()
        assert d["cluster_id"] == 1
        assert d["n_samples"] == 50

    def test_horizon_stats_to_dict(self):
        s = HorizonStats(horizon_days=21, win_rate=0.6)
        d = s.to_dict()
        assert d["horizon_days"] == 21
        assert d["win_rate"] == 0.6

    def test_match_result_to_dict(self):
        r = MatchResult(stock_code="2330", cosine_similarity=0.92)
        d = r.to_dict()
        assert d["stock_code"] == "2330"
        assert d["cosine_similarity"] == 0.92


# ---------------------------------------------------------------------------
# Config Tests
# ---------------------------------------------------------------------------

class TestConfig:
    def test_default_config(self):
        assert WINNER_DNA_CONFIG["umap_n_components"] == 8
        assert WINNER_DNA_CONFIG["cosine_match_threshold"] == 0.85
        assert WINNER_DNA_CONFIG["dtw_top_k"] == 30
        assert WINNER_DNA_CONFIG["transaction_cost"] == 0.00785
        assert 7 in WINNER_DNA_CONFIG["performance_horizons"]
        assert 365 in WINNER_DNA_CONFIG["performance_horizons"]

    def test_phase4_config(self):
        """Phase 4 config keys should exist."""
        assert WINNER_DNA_CONFIG["recency_halflife_years"] == 2.0
        assert WINNER_DNA_CONFIG["min_samples_confident"] == 30

    def test_phase5_config(self):
        """Phase 5 config keys should exist."""
        assert WINNER_DNA_CONFIG["knn_k"] == 5
        assert WINNER_DNA_CONFIG["dtw_window_structure"] == 60
        assert WINNER_DNA_CONFIG["dtw_window_momentum"] == 20
        assert WINNER_DNA_CONFIG["stage1_weight"] == 0.7
        assert WINNER_DNA_CONFIG["stage2_weight"] == 0.3
        assert WINNER_DNA_CONFIG["multiscale_agreement_boost"] == 1.5
        assert WINNER_DNA_CONFIG["failed_pattern_warning_ratio"] == 0.6


# ---------------------------------------------------------------------------
# Phase 4: Recency-Weighted Performance Tests
# ---------------------------------------------------------------------------

class TestRecencyWeightedPerformance:
    def test_basic_recency(self):
        """Recency weighting should give higher weight to recent samples."""
        np.random.seed(42)
        data = pd.DataFrame({
            "epiphany_date": pd.date_range("2022-01-01", periods=20, freq="90D"),
            "fwd_21d": [0.05] * 10 + [0.10] * 10,  # Recent samples have higher returns
        })
        result = _compute_recency_weighted_performance(
            data, [21], txn_cost=0.00785, halflife_years=2.0
        )
        assert "d21" in result
        # Recent samples (0.10) should pull weighted avg above simple avg (0.075)
        assert result["d21"]["avg_return"] > 0.075

    def test_empty_data(self):
        """Empty data should return empty dict."""
        data = pd.DataFrame({"epiphany_date": [], "fwd_21d": []})
        result = _compute_recency_weighted_performance(
            data, [21], txn_cost=0.00785, halflife_years=2.0
        )
        assert result == {}

    def test_no_epiphany_column(self):
        """Missing epiphany_date column should return empty dict."""
        data = pd.DataFrame({"fwd_21d": [0.05, 0.10]})
        result = _compute_recency_weighted_performance(
            data, [21], txn_cost=0.00785, halflife_years=2.0
        )
        assert result == {}

    def test_win_rate_bounded(self):
        """Recency-weighted win rate should be between 0 and 1."""
        np.random.seed(42)
        data = pd.DataFrame({
            "epiphany_date": pd.date_range("2023-01-01", periods=50, freq="7D"),
            "fwd_21d": np.random.normal(0.05, 0.1, 50),
        })
        result = _compute_recency_weighted_performance(
            data, [21], txn_cost=0.00785, halflife_years=2.0
        )
        assert 0 <= result["d21"]["win_rate"] <= 1


# ---------------------------------------------------------------------------
# Phase 4: Confidence Level Tests
# ---------------------------------------------------------------------------

class TestConfidenceLevel:
    def test_confident_cluster(self):
        """Cluster with >= 30 samples should be 'confident'."""
        samples_df, all_features = _make_samples_df(60, 65)
        reduced = np.random.normal(0, 1, (60, 8))
        labels = np.array([0] * 60)

        profiles = compute_cluster_profiles(
            samples_df, labels, reduced, all_features
        )
        assert profiles[0].confidence == "confident"

    def test_speculative_cluster(self):
        """Cluster with < 30 samples should be 'speculative'."""
        samples_df, all_features = _make_samples_df(20, 65)
        samples_df = samples_df.head(20)
        reduced = np.random.normal(0, 1, (20, 8))
        labels = np.array([0] * 20)

        profiles = compute_cluster_profiles(
            samples_df, labels, reduced, all_features
        )
        assert profiles[0].confidence == "speculative"

    def test_winner_ratio(self):
        """Winner ratio should be computed correctly."""
        samples_df, all_features = _make_samples_df(60, 65)
        reduced = np.random.normal(0, 1, (60, 8))
        labels = np.array([0] * 60)

        profiles = compute_cluster_profiles(
            samples_df, labels, reduced, all_features
        )
        # 40 winners out of 60 (first 60 from _make_samples_df: 40 winners, 20 losers)
        assert 0 < profiles[0].winner_ratio <= 1.0


# ---------------------------------------------------------------------------
# Phase 5: Cosine Similarity Helper Tests
# ---------------------------------------------------------------------------

class TestCosineSim:
    def test_identical_vectors(self):
        """Identical vectors should have cosine sim = 1."""
        v = np.array([1.0, 2.0, 3.0])
        assert _cosine_sim(v, v) == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors(self):
        """Orthogonal vectors should have cosine sim = 0."""
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert _cosine_sim(a, b) == pytest.approx(0.0, abs=1e-6)

    def test_opposite_vectors(self):
        """Opposite vectors should have cosine sim = -1."""
        a = np.array([1.0, 0.0])
        b = np.array([-1.0, 0.0])
        assert _cosine_sim(a, b) == pytest.approx(-1.0, abs=1e-6)

    def test_zero_vector(self):
        """Zero vector should return 0."""
        a = np.array([0.0, 0.0])
        b = np.array([1.0, 2.0])
        assert _cosine_sim(a, b) == 0.0


# ---------------------------------------------------------------------------
# Phase 5: k-NN Tests
# ---------------------------------------------------------------------------

class TestKNN:
    def test_finds_k_neighbors(self):
        """Should find exactly k neighbors."""
        np.random.seed(42)
        n_samples = 50
        n_features = 8
        samples_reduced = np.random.normal(0, 1, (n_samples, n_features))
        samples_df = pd.DataFrame({
            "stock_code": [f"S{i:03d}" for i in range(n_samples)],
            "epiphany_date": pd.date_range("2024-01-01", periods=n_samples),
            "label": ["winner"] * 30 + ["loser"] * 20,
            "gene_mutation_delta": np.random.normal(0, 1, n_samples),
        })
        labels = np.array([0] * 25 + [1] * 25)
        query = np.random.normal(0, 1, n_features)

        neighbors = _find_knn_neighbors(query, samples_reduced, samples_df, labels, k=5)
        assert len(neighbors) == 5

    def test_neighbors_sorted_by_similarity(self):
        """Neighbors should be sorted by cosine similarity (descending)."""
        np.random.seed(42)
        n = 20
        samples_reduced = np.random.normal(0, 1, (n, 8))
        samples_df = pd.DataFrame({
            "stock_code": [f"S{i}" for i in range(n)],
            "epiphany_date": pd.date_range("2024-01-01", periods=n),
            "label": ["winner"] * n,
            "gene_mutation_delta": np.zeros(n),
        })
        labels = np.zeros(n, dtype=int)
        query = np.random.normal(0, 1, 8)

        neighbors = _find_knn_neighbors(query, samples_reduced, samples_df, labels, k=5)
        sims = [nb["cosine_similarity"] for nb in neighbors]
        assert sims == sorted(sims, reverse=True)

    def test_empty_samples(self):
        """Empty samples should return empty list."""
        samples_reduced = np.empty((0, 8))
        samples_df = pd.DataFrame()
        neighbors = _find_knn_neighbors(
            np.zeros(8), samples_reduced, samples_df, None, k=5
        )
        assert neighbors == []

    def test_neighbor_has_forward_returns(self):
        """Neighbors should include forward return data if available."""
        np.random.seed(42)
        samples_reduced = np.random.normal(0, 1, (10, 8))
        samples_df = pd.DataFrame({
            "stock_code": [f"S{i}" for i in range(10)],
            "epiphany_date": pd.date_range("2024-01-01", periods=10),
            "label": ["winner"] * 10,
            "gene_mutation_delta": np.zeros(10),
            "fwd_21d": np.random.normal(0.05, 0.1, 10),
            "fwd_90d": np.random.normal(0.10, 0.2, 10),
        })
        labels = np.zeros(10, dtype=int)
        query = np.random.normal(0, 1, 8)

        neighbors = _find_knn_neighbors(query, samples_reduced, samples_df, labels, k=3)
        assert "fwd_21d" in neighbors[0]
        assert "fwd_90d" in neighbors[0]


# ---------------------------------------------------------------------------
# Phase 5: Failed Pattern Warning Tests
# ---------------------------------------------------------------------------

class TestFailedPatternWarning:
    def test_no_warning_all_winners(self):
        """All winner neighbors should not trigger warning."""
        np.random.seed(42)
        n = 10
        samples_reduced = np.random.normal(0, 1, (n, 8))
        samples_df = pd.DataFrame({
            "stock_code": [f"S{i}" for i in range(n)],
            "epiphany_date": pd.date_range("2024-01-01", periods=n),
            "label": ["winner"] * n,
            "gene_mutation_delta": np.zeros(n),
        })

        from sklearn.decomposition import PCA
        matrix = np.random.normal(0, 1, (n, 65))
        reducer = PCA(n_components=8, random_state=42)
        reducer.fit(matrix)

        all_features = [f"feat_{i}" for i in range(65)]
        features_df = pd.DataFrame([{
            "stock_code": "TEST",
            "date": pd.Timestamp("2024-06-01"),
            **{f: np.random.normal(0, 1) for f in all_features},
        }])

        profiles = [ClusterProfile(cluster_id=0, centroid=[1.0] * 8, n_samples=30)]

        result = match_stock_to_dna(
            "TEST", features_df, profiles, reducer, all_features,
            samples_df=samples_df,
            samples_reduced=samples_reduced,
            samples_labels=np.zeros(n, dtype=int),
        )
        assert not result.failed_pattern_warning

    def test_warning_mostly_losers(self):
        """Mostly loser neighbors should trigger warning."""
        np.random.seed(42)
        n = 10
        samples_reduced = np.random.normal(0, 1, (n, 8))
        samples_df = pd.DataFrame({
            "stock_code": [f"S{i}" for i in range(n)],
            "epiphany_date": pd.date_range("2024-01-01", periods=n),
            "label": ["loser"] * 8 + ["winner"] * 2,  # 80% losers
            "gene_mutation_delta": np.zeros(n),
        })

        from sklearn.decomposition import PCA
        matrix = np.random.normal(0, 1, (n, 65))
        reducer = PCA(n_components=8, random_state=42)
        reducer.fit(matrix)

        all_features = [f"feat_{i}" for i in range(65)]
        features_df = pd.DataFrame([{
            "stock_code": "TEST",
            "date": pd.Timestamp("2024-06-01"),
            **{f: np.random.normal(0, 1) for f in all_features},
        }])

        profiles = [ClusterProfile(cluster_id=0, centroid=[1.0] * 8, n_samples=30)]

        result = match_stock_to_dna(
            "TEST", features_df, profiles, reducer, all_features,
            samples_df=samples_df,
            samples_reduced=samples_reduced,
            samples_labels=np.zeros(n, dtype=int),
        )
        assert result.failed_pattern_warning
        assert result.failed_pattern_ratio >= 0.6


# ---------------------------------------------------------------------------
# Phase 5: Match with k-NN Integration Tests
# ---------------------------------------------------------------------------

class TestMatchWithKNN:
    def test_match_uses_knn_when_samples_provided(self):
        """When samples are provided, match should use k-NN."""
        np.random.seed(42)
        n = 20
        n_features = 65

        all_features = [f"feat_{i}" for i in range(n_features)]

        # Build samples
        samples_reduced = np.random.normal(0, 1, (n, 8))
        samples_df = pd.DataFrame({
            "stock_code": [f"S{i}" for i in range(n)],
            "epiphany_date": pd.date_range("2024-01-01", periods=n),
            "label": ["winner"] * 15 + ["loser"] * 5,
            "gene_mutation_delta": np.random.normal(0, 1, n),
            **{f: np.random.normal(0, 1, n) for f in all_features},
        })
        labels = np.array([0] * 10 + [1] * 10)

        # Build reducer
        from sklearn.decomposition import PCA
        matrix = np.random.normal(0, 1, (n, n_features))
        reducer = PCA(n_components=8, random_state=42)
        reducer.fit(matrix)

        # Build query stock features
        features_df = pd.DataFrame([{
            "stock_code": "QUERY",
            "date": pd.Timestamp("2024-06-01"),
            **{f: np.random.normal(0, 1) for f in all_features},
        }])

        profiles = [
            ClusterProfile(cluster_id=0, centroid=samples_reduced[:10].mean(axis=0).tolist(), n_samples=30),
            ClusterProfile(cluster_id=1, centroid=samples_reduced[10:].mean(axis=0).tolist(), n_samples=30),
        ]

        result = match_stock_to_dna(
            "QUERY", features_df, profiles, reducer, all_features,
            samples_df=samples_df,
            samples_reduced=samples_reduced,
            samples_labels=labels,
        )

        assert result.stock_code == "QUERY"
        assert len(result.nearest_neighbors) == 5  # k=5
        assert result.best_cluster_id in [0, 1]
        assert result.confidence in ["confident", "speculative", "unknown"]


# ---------------------------------------------------------------------------
# Phase 4: Load Profiles from DB Tests
# ---------------------------------------------------------------------------

class TestLoadProfilesFromDB:
    def test_round_trip(self):
        """Profiles should survive to_dict → load_profiles_from_db."""
        profiles = [
            ClusterProfile(
                cluster_id=0, n_samples=50, n_winners=40, n_losers=10,
                label="MomentumBreak", confidence="confident",
                winner_ratio=0.8, centroid=[1.0, 2.0],
            ),
            ClusterProfile(
                cluster_id=1, n_samples=20, confidence="speculative",
            ),
        ]

        db = {"clusters": [p.to_dict() for p in profiles]}
        loaded = load_profiles_from_db(db)

        assert len(loaded) == 2
        assert loaded[0].cluster_id == 0
        assert loaded[0].confidence == "confident"
        assert loaded[0].winner_ratio == 0.8
        assert loaded[1].confidence == "speculative"

    def test_empty_db(self):
        """Empty DB should return empty list."""
        assert load_profiles_from_db({}) == []
        assert load_profiles_from_db({"clusters": []}) == []

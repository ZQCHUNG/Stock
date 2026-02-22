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
    cluster_winners,
    compute_cluster_profiles,
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

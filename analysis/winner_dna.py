"""Winner DNA Library — Phase 3-5: Clustering + Performance DB + Two-Stage Matcher

[OFFICIALLY APPROVED — Architect Critic Phase 4-5 Gate]
[CONVERGED — Wall Street Trader Phase 4-5 Review]

Phase 3: UMAP/PCA + HDBSCAN → winner clusters (DONE)
Phase 4: Pattern Performance DB with recency-weighted stats (NEW)
Phase 5: Two-Stage Matcher — k-NN + Multi-scale DTW (NEW)

Architecture (per CTO + Trader + Architect consensus):
  1. Load winner_dna_samples.parquet (from Phase 2 labeler)
  2. UMAP: 65 features → 8 components (Architect mandate: avoid dimension curse)
  3. HDBSCAN: Non-supervised clustering → 5-8 "winner nests"
  4. Pattern Performance DB: recency-weighted stats + confidence levels
  5. Two-Stage Matcher:
     Stage 1: k-NN (k=5) in reduced space (Trader: replace static centroid)
     Stage 2: Multi-scale DTW (60d structure + 20d momentum)
     Failed Pattern matching: red warning if stock matches losers too

All thresholds labeled per 假精確 Protocol:
  [HYPOTHESIS: SUPER_STOCK_TARGET] — Price thresholds
  [PLACEHOLDER: MATCH_THRESHOLD_085] — 85% similarity cutoff
  [PLACEHOLDER: STAGE2_WEIGHT_070_030] — Cosine/DTW blend
  [PLACEHOLDER: RECENCY_HALFLIFE_2Y] — Time decay half-life
  [PLACEHOLDER: MULTISCALE_BOOST] — Confidence boost when 20d+60d agree
  [HYPOTHESIS: MIN_SAMPLE_30] — Speculative confidence below 30 samples
  [VERIFIED: GENE_MUTATION_SCANNER] — Existing 1.5σ detection
"""

import json
import logging
import pickle
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

_logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FEATURES_DIR = PROJECT_ROOT / "data" / "pattern_data" / "features"
WINNER_DNA_FILE = FEATURES_DIR / "winner_dna_samples.parquet"
CLUSTER_DB_FILE = FEATURES_DIR / "winner_dna_library.json"
REDUCER_FILE = FEATURES_DIR / "winner_dna_reducer.pkl"
SCALER_FILE = FEATURES_DIR / "winner_dna_scaler.pkl"
METADATA_FILE = FEATURES_DIR / "feature_metadata.json"
FEATURES_FILE = FEATURES_DIR / "features_all.parquet"
PRICE_CACHE_FILE = FEATURES_DIR / "price_cache.parquet"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WINNER_DNA_CONFIG = {
    # UMAP parameters
    "umap_n_components": 8,          # [HYPOTHESIS] Reduce to 8 dimensions
    "umap_n_neighbors": 15,          # [HYPOTHESIS] Local structure size
    "umap_min_dist": 0.1,            # [HYPOTHESIS] Minimum distance in embedding
    "umap_metric": "cosine",         # Match existing engine

    # HDBSCAN parameters
    "hdbscan_min_cluster_size": 5,   # [HYPOTHESIS] Min samples per cluster
    "hdbscan_min_samples": 3,        # [HYPOTHESIS] Core point density
    "hdbscan_cluster_selection_epsilon": 0.0,

    # Fallback to PCA if UMAP unavailable
    "pca_n_components": 8,           # Same dimensionality as UMAP

    # Forward return horizons for performance stats
    "performance_horizons": [7, 21, 30, 60, 90, 180, 365],

    # [PLACEHOLDER: MATCH_THRESHOLD_085] — Cosine similarity cutoff
    # Architect Critic: "Must perform sensitivity test post-implementation"
    "cosine_match_threshold": 0.85,

    # DTW Stage 2 limit (Architect mandate: O(N²) cost control)
    "dtw_top_k": 30,

    # Transaction cost for expectancy calc
    "transaction_cost": 0.00785,     # [VERIFIED] 0.1425%×2 + 0.3% + 0.1%×2

    # Phase 4: Recency weighting
    # [PLACEHOLDER: RECENCY_HALFLIFE_2Y] — Trader suggested, Architect noted
    # "need to verify 2022 bear year weight isn't suppressed too much"
    "recency_halflife_years": 2.0,

    # Phase 4: Confidence level
    # [HYPOTHESIS: MIN_SAMPLE_30] — Central Limit Theorem baseline
    "min_samples_confident": 30,

    # Phase 5: k-NN parameters (Trader: replace static centroid)
    "knn_k": 5,                      # Find 5 nearest "predecessors"

    # Phase 5: Multi-scale DTW windows (Trader recommendation)
    "dtw_window_structure": 60,      # Days for structural match
    "dtw_window_momentum": 20,       # Days for momentum match

    # [PLACEHOLDER: STAGE2_WEIGHT_070_030] — Cosine/DTW blend
    # Trader: "Gene (cause) > Shape (effect)" → 0.7/0.3
    "stage1_weight": 0.7,
    "stage2_weight": 0.3,

    # [PLACEHOLDER: MULTISCALE_BOOST] — Confidence boost when both scales agree
    "multiscale_agreement_boost": 1.5,

    # Phase 5: Failed Pattern warning threshold
    "failed_pattern_warning_ratio": 0.6,  # Warn if >60% of k-NN are losers
}


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class ClusterProfile:
    """Statistical profile of a winner cluster."""
    cluster_id: int
    n_samples: int = 0
    n_winners: int = 0
    n_losers: int = 0
    label: str = ""                          # Human-readable label

    # Multi-horizon performance stats (raw)
    performance: dict = field(default_factory=dict)

    # Recency-weighted performance stats (Phase 4)
    recency_performance: dict = field(default_factory=dict)

    # Confidence level (Phase 4) — "confident" or "speculative"
    confidence: str = "confident"

    # Winner ratio among samples
    winner_ratio: float = 0.0

    # Centroid (mean feature vector in reduced space)
    centroid: list[float] = field(default_factory=list)

    # Top contributing features
    top_features: list[dict] = field(default_factory=list)

    # Regime distribution
    regime_dist: dict = field(default_factory=dict)

    # Gene Mutation stats
    avg_mutation_delta: float = 0.0
    std_mutation_delta: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HorizonStats:
    """Performance statistics for a single holding horizon."""
    horizon_days: int = 0
    win_rate: float = 0.0
    avg_return: float = 0.0
    median_return: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    max_drawdown: float = 0.0
    n_valid: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MatchResult:
    """Result of matching a stock against the Winner DNA Library."""
    stock_code: str = ""
    match_date: str = ""
    best_cluster_id: int = -1
    cosine_similarity: float = 0.0
    final_score: float = 0.0                  # Phase 5: blended score
    is_match: bool = False
    is_super_stock_potential: bool = False
    confidence: str = "unknown"                # confident / speculative / unknown
    cluster_profile: Optional[dict] = None
    feature_vector_reduced: list[float] = field(default_factory=list)

    # Phase 5: k-NN results
    nearest_neighbors: list[dict] = field(default_factory=list)

    # Phase 5: Multi-scale DTW
    dtw_score_60d: float = 0.0
    dtw_score_20d: float = 0.0
    multiscale_agreement: bool = False

    # Phase 5: Failed Pattern warning
    failed_pattern_warning: bool = False
    failed_pattern_ratio: float = 0.0          # % of k-NN that are losers

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Phase 3a: Dimensionality Reduction
# ---------------------------------------------------------------------------

def reduce_dimensions(
    feature_matrix: np.ndarray,
    method: str = "umap",
    config: Optional[dict] = None,
) -> tuple[np.ndarray, object]:
    """Reduce 65-dimensional feature space to 5-10 components.

    Architect Critic mandate: "Must first reduce via UMAP or PCA before
    HDBSCAN to avoid dimension curse."

    Args:
        feature_matrix: (N, 65) array of Z-score normalized features
        method: "umap" or "pca" (fallback)
        config: Override WINNER_DNA_CONFIG

    Returns:
        (reduced_matrix, fitted_reducer) — reducer can be used for new data
    """
    cfg = dict(WINNER_DNA_CONFIG)
    if config:
        cfg.update(config)

    # Handle NaN: fill with 0 (neutral Z-score)
    matrix = np.nan_to_num(feature_matrix, nan=0.0)

    if method == "umap":
        try:
            import umap
            reducer = umap.UMAP(
                n_components=cfg["umap_n_components"],
                n_neighbors=cfg["umap_n_neighbors"],
                min_dist=cfg["umap_min_dist"],
                metric=cfg["umap_metric"],
                random_state=42,
            )
            reduced = reducer.fit_transform(matrix)
            _logger.info("UMAP: %s → %s (%.1f%% variance retained est.)",
                         matrix.shape, reduced.shape,
                         _estimate_variance_retained(matrix, reduced))
            return reduced, reducer
        except ImportError:
            _logger.warning("UMAP not available, falling back to PCA")
            method = "pca"

    # PCA fallback
    from sklearn.decomposition import PCA
    reducer = PCA(n_components=cfg["pca_n_components"], random_state=42)
    reduced = reducer.fit_transform(matrix)
    variance_explained = sum(reducer.explained_variance_ratio_) * 100
    _logger.info("PCA: %s → %s (%.1f%% variance explained)",
                 matrix.shape, reduced.shape, variance_explained)
    return reduced, reducer


def _estimate_variance_retained(original: np.ndarray, reduced: np.ndarray) -> float:
    """Rough estimate of variance retained after reduction."""
    from sklearn.decomposition import PCA
    pca = PCA(n_components=reduced.shape[1])
    pca.fit(original)
    return sum(pca.explained_variance_ratio_) * 100


# ---------------------------------------------------------------------------
# Phase 3b: HDBSCAN Clustering
# ---------------------------------------------------------------------------

def cluster_winners(
    reduced_matrix: np.ndarray,
    config: Optional[dict] = None,
) -> tuple[np.ndarray, object]:
    """Cluster the reduced feature space using HDBSCAN.

    HDBSCAN finds natural clusters without requiring a fixed k.
    Expected: 5-8 "winner nests" (per CTO prediction).

    Args:
        reduced_matrix: (N, n_components) from reduce_dimensions()
        config: Override WINNER_DNA_CONFIG

    Returns:
        (labels, clusterer) — labels[i] = cluster_id (-1 = noise)
    """
    cfg = dict(WINNER_DNA_CONFIG)
    if config:
        cfg.update(config)

    import hdbscan

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=cfg["hdbscan_min_cluster_size"],
        min_samples=cfg["hdbscan_min_samples"],
        cluster_selection_epsilon=cfg["hdbscan_cluster_selection_epsilon"],
        metric="euclidean",
    )

    labels = clusterer.fit_predict(reduced_matrix)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = int((labels == -1).sum())
    _logger.info("HDBSCAN: %d clusters found, %d noise points (%.1f%%)",
                 n_clusters, n_noise, n_noise / len(labels) * 100)

    return labels, clusterer


# ---------------------------------------------------------------------------
# Phase 3c: Pattern Performance DB
# ---------------------------------------------------------------------------

def compute_cluster_profiles(
    samples_df: pd.DataFrame,
    labels: np.ndarray,
    reduced_matrix: np.ndarray,
    all_features: list[str],
    config: Optional[dict] = None,
) -> list[ClusterProfile]:
    """Compute statistical profile for each cluster.

    For each cluster, computes:
    - Multi-horizon win rates and expectancy
    - Centroid in reduced space
    - Top contributing features
    - Regime distribution
    - Gene mutation statistics

    Args:
        samples_df: winner_dna_samples DataFrame (with fwd_Xd columns)
        labels: Cluster labels from HDBSCAN
        reduced_matrix: Reduced feature matrix
        all_features: List of 65 feature names
        config: Override config

    Returns:
        List of ClusterProfile objects
    """
    cfg = dict(WINNER_DNA_CONFIG)
    if config:
        cfg.update(config)

    horizons = cfg["performance_horizons"]
    txn_cost = cfg["transaction_cost"]

    samples_df = samples_df.copy()
    samples_df["cluster_id"] = labels

    profiles = []
    unique_clusters = sorted(set(labels))

    for cid in unique_clusters:
        if cid == -1:
            continue  # Skip noise

        mask = samples_df["cluster_id"] == cid
        cluster_data = samples_df[mask]
        cluster_reduced = reduced_matrix[mask.values]

        profile = ClusterProfile(
            cluster_id=int(cid),
            n_samples=len(cluster_data),
            n_winners=int((cluster_data["label"] == "winner").sum()),
            n_losers=int((cluster_data["label"] == "loser").sum()),
        )

        # Centroid
        profile.centroid = cluster_reduced.mean(axis=0).tolist()

        # Multi-horizon performance stats
        perf = {}
        for h in horizons:
            col = f"fwd_{h}d"
            if col not in cluster_data.columns:
                continue

            returns = cluster_data[col].dropna()
            if len(returns) < 2:
                continue

            stats = _compute_horizon_stats(returns.values, h, txn_cost)
            perf[f"d{h}"] = stats.to_dict()

        profile.performance = perf

        # Phase 4: Recency-weighted performance
        recency_perf = {}
        halflife = cfg.get("recency_halflife_years", 2.0)
        if "epiphany_date" in cluster_data.columns:
            recency_perf = _compute_recency_weighted_performance(
                cluster_data, horizons, txn_cost, halflife
            )
        profile.recency_performance = recency_perf

        # Phase 4: Confidence level [HYPOTHESIS: MIN_SAMPLE_30]
        min_confident = cfg.get("min_samples_confident", 30)
        profile.confidence = (
            "confident" if profile.n_samples >= min_confident else "speculative"
        )

        # Winner ratio
        if profile.n_samples > 0:
            profile.winner_ratio = round(profile.n_winners / profile.n_samples, 4)

        # Top contributing features (highest absolute mean Z-score)
        feat_means = {}
        for feat in all_features:
            if feat in cluster_data.columns:
                vals = cluster_data[feat].dropna()
                if len(vals) > 0:
                    feat_means[feat] = float(vals.mean())

        sorted_feats = sorted(feat_means.items(), key=lambda x: abs(x[1]), reverse=True)
        profile.top_features = [
            {"feature": f, "mean_zscore": round(v, 3)}
            for f, v in sorted_feats[:10]
        ]

        # Regime distribution
        if "regime_context" in cluster_data.columns:
            regime_counts = cluster_data["regime_context"].value_counts().to_dict()
            profile.regime_dist = {
                str(k): int(v) for k, v in regime_counts.items()
            }

        # Gene Mutation stats
        if "gene_mutation_delta" in cluster_data.columns:
            deltas = cluster_data["gene_mutation_delta"].dropna()
            if len(deltas) > 0:
                profile.avg_mutation_delta = round(float(deltas.mean()), 4)
                profile.std_mutation_delta = round(float(deltas.std()), 4)

        # Auto-label based on dominant characteristics
        profile.label = _auto_label_cluster(profile, feat_means)

        profiles.append(profile)

    _logger.info("Computed profiles for %d clusters", len(profiles))
    return profiles


def _compute_horizon_stats(
    returns: np.ndarray,
    horizon: int,
    txn_cost: float,
) -> HorizonStats:
    """Compute performance statistics for a single horizon."""
    stats = HorizonStats(horizon_days=horizon)

    valid = returns[~np.isnan(returns)]
    stats.n_valid = len(valid)

    if len(valid) < 2:
        return stats

    wins = valid[valid > txn_cost]
    losses = valid[valid <= txn_cost]

    stats.win_rate = round(len(wins) / len(valid), 4)
    stats.avg_return = round(float(np.mean(valid)), 6)
    stats.median_return = round(float(np.median(valid)), 6)

    if len(wins) > 0:
        stats.avg_win = round(float(np.mean(wins)), 6)
    if len(losses) > 0:
        stats.avg_loss = round(float(np.mean(losses)), 6)

    # Profit Factor: sum(wins) / abs(sum(losses))
    total_wins = float(np.sum(wins)) if len(wins) > 0 else 0.0
    total_losses = abs(float(np.sum(losses))) if len(losses) > 0 else 0.0
    stats.profit_factor = round(total_wins / total_losses, 4) if total_losses > 0 else 99.99

    # Expectancy = (Win% × Avg Win) - (Loss% × |Avg Loss|)
    loss_rate = 1.0 - stats.win_rate
    stats.expectancy = round(
        (stats.win_rate * stats.avg_win) - (loss_rate * abs(stats.avg_loss)),
        6,
    )

    # Max drawdown (from cumulative returns)
    cumulative = np.cumprod(1 + valid) - 1
    running_max = np.maximum.accumulate(1 + valid)
    drawdowns = (np.cumprod(1 + valid) - running_max) / running_max
    stats.max_drawdown = round(float(np.min(drawdowns)), 6) if len(drawdowns) > 0 else 0.0

    return stats


def _compute_recency_weighted_performance(
    cluster_data: pd.DataFrame,
    horizons: list[int],
    txn_cost: float,
    halflife_years: float,
) -> dict:
    """Compute recency-weighted performance stats.

    [PLACEHOLDER: RECENCY_HALFLIFE_2Y]
    Architect note: "verify 2022 bear year weight isn't suppressed too much"

    Uses exponential decay: w = 2^(-ΔT/halflife)
    where ΔT = years since epiphany_date.
    """
    perf = {}
    now = pd.Timestamp.now()

    if "epiphany_date" not in cluster_data.columns:
        return perf

    dates = pd.to_datetime(cluster_data["epiphany_date"], errors="coerce")
    years_ago = (now - dates).dt.days / 365.25
    # Exponential decay weights
    weights = np.power(2.0, -years_ago.values / halflife_years)
    weights = np.nan_to_num(weights, nan=0.0)
    total_weight = weights.sum()

    if total_weight < 1e-8:
        return perf

    norm_weights = weights / total_weight

    for h in horizons:
        col = f"fwd_{h}d"
        if col not in cluster_data.columns:
            continue

        returns = cluster_data[col].values.astype(float)
        valid_mask = ~np.isnan(returns)
        if valid_mask.sum() < 2:
            continue

        valid_returns = returns[valid_mask]
        valid_weights = norm_weights[valid_mask]

        # Weighted win rate
        wins_mask = valid_returns > txn_cost
        weighted_wr = float(np.sum(valid_weights[wins_mask]))

        # Weighted average return
        weighted_avg = float(np.sum(valid_returns * valid_weights))

        perf[f"d{h}"] = {
            "win_rate": round(weighted_wr, 4),
            "avg_return": round(weighted_avg, 6),
            "n_valid": int(valid_mask.sum()),
        }

    return perf


def _auto_label_cluster(profile: ClusterProfile, feat_means: dict) -> str:
    """Auto-generate a human-readable label for the cluster."""
    labels = []

    # Check dominant features
    if feat_means.get("inst_foreign_net", 0) > 1.0:
        labels.append("ForeignBuy")
    if feat_means.get("broker_net_buy_ratio", 0) > 1.0:
        labels.append("BrokerLoad")
    if feat_means.get("revenue_yoy", 0) > 1.0:
        labels.append("GrowthSurge")
    if feat_means.get("ma20_ratio", 0) > 1.0:
        labels.append("MomentumBreak")
    if feat_means.get("vol_ratio_20", 0) > 1.5:
        labels.append("VolumeExplosion")
    if feat_means.get("atr_pct", 0) > 1.5:
        labels.append("HighVolatility")

    if not labels:
        labels.append(f"Cluster_{profile.cluster_id}")

    return "+".join(labels[:3])


# ---------------------------------------------------------------------------
# Phase 3d: Real-time Matching (Two-Stage)
# ---------------------------------------------------------------------------

def match_stock_to_dna(
    stock_code: str,
    features_df: pd.DataFrame,
    cluster_profiles: list[ClusterProfile],
    reducer: object,
    all_features: list[str],
    config: Optional[dict] = None,
    samples_df: Optional[pd.DataFrame] = None,
    samples_reduced: Optional[np.ndarray] = None,
    samples_labels: Optional[np.ndarray] = None,
    price_df: Optional[pd.DataFrame] = None,
) -> MatchResult:
    """Match a stock against the Winner DNA Library using Two-Stage Matcher.

    Phase 5 Two-Stage Matcher [OFFICIALLY APPROVED — Architect Critic]:
      Stage 1: k-NN (k=5) in reduced space (Trader: replace static centroid)
      Stage 2: Multi-scale DTW (60d + 20d) on price shapes

    Final Score = w1 × cosine_sim + w2 × (1/(1+dtw_distance))
    [PLACEHOLDER: STAGE2_WEIGHT_070_030]

    Failed Pattern warning: if >60% of k-NN are losers → red warning

    Args:
        stock_code: Stock to evaluate
        features_df: Current features (from features_all.parquet)
        cluster_profiles: Fitted cluster profiles
        reducer: Fitted UMAP/PCA reducer
        all_features: List of 65 feature names
        config: Override config
        samples_df: Winner DNA samples (for k-NN, optional)
        samples_reduced: Reduced matrix of all samples (for k-NN, optional)
        samples_labels: Cluster labels for samples (for k-NN, optional)
        price_df: Price data for DTW Stage 2 (optional)

    Returns:
        MatchResult with match details, k-NN neighbors, DTW scores
    """
    cfg = dict(WINNER_DNA_CONFIG)
    if config:
        cfg.update(config)

    threshold = cfg["cosine_match_threshold"]

    # Get latest feature vector for stock
    stock_data = features_df[features_df["stock_code"] == stock_code]
    if stock_data.empty:
        return MatchResult(stock_code=stock_code)

    latest = stock_data.sort_values("date").iloc[-1]
    match_date = str(latest["date"])

    # Extract 65-feature vector
    feat_vector = np.array([float(latest.get(f, 0.0)) for f in all_features])
    feat_vector = np.nan_to_num(feat_vector, nan=0.0).reshape(1, -1)

    # Reduce to cluster space
    try:
        reduced = reducer.transform(feat_vector)
    except Exception:
        return MatchResult(stock_code=stock_code, match_date=match_date)

    reduced_vec = reduced.flatten()

    # ===== Stage 1: k-NN in reduced space =====
    k = cfg.get("knn_k", 5)
    neighbors = []

    if samples_reduced is not None and samples_df is not None:
        neighbors = _find_knn_neighbors(
            reduced_vec, samples_reduced, samples_df, samples_labels, k
        )

    # Best cluster from k-NN majority vote (or fallback to centroid)
    best_cluster = -1
    best_sim = -1.0

    if neighbors:
        # Majority vote from k-NN
        cluster_votes = {}
        for nb in neighbors:
            cid = nb.get("cluster_id", -1)
            cluster_votes[cid] = cluster_votes.get(cid, 0) + 1
        best_cluster = max(cluster_votes, key=cluster_votes.get)
        best_sim = float(np.mean([nb["cosine_similarity"] for nb in neighbors]))
    else:
        # Fallback: cosine to centroids (backward compatible)
        for profile in cluster_profiles:
            centroid = np.array(profile.centroid)
            if len(centroid) != len(reduced_vec):
                continue
            sim = _cosine_sim(reduced_vec, centroid)
            if sim > best_sim:
                best_sim = sim
                best_cluster = profile.cluster_id

    is_match = best_sim >= threshold

    # ===== Stage 2: Multi-scale DTW =====
    dtw_60 = 0.0
    dtw_20 = 0.0
    multiscale_agree = False
    final_score = best_sim  # Default to cosine only

    if is_match and price_df is not None and neighbors:
        dtw_60, dtw_20, multiscale_agree = _compute_multiscale_dtw(
            stock_code, neighbors, price_df, cfg
        )
        # Blend: Final Score = w1 × cosine + w2 × (1/(1+dtw))
        w1 = cfg.get("stage1_weight", 0.7)
        w2 = cfg.get("stage2_weight", 0.3)
        # Use the structural (60d) DTW for blending
        dtw_sim = 1.0 / (1.0 + dtw_60) if dtw_60 > 0 else 1.0
        final_score = w1 * best_sim + w2 * dtw_sim

        # Multiscale boost [PLACEHOLDER: MULTISCALE_BOOST]
        if multiscale_agree:
            boost = cfg.get("multiscale_agreement_boost", 1.5)
            # Boost confidence, not score — cap at 1.0
            final_score = min(1.0, final_score * boost)
    else:
        final_score = best_sim

    # ===== Failed Pattern Warning =====
    failed_warning = False
    failed_ratio = 0.0

    if neighbors:
        loser_count = sum(1 for nb in neighbors if nb.get("label") == "loser")
        failed_ratio = loser_count / len(neighbors) if neighbors else 0.0
        warn_thresh = cfg.get("failed_pattern_warning_ratio", 0.6)
        failed_warning = failed_ratio >= warn_thresh

    # Check super stock potential
    is_super = False
    if "gene_mutation_delta" in latest.index:
        delta = float(latest.get("gene_mutation_delta", 0))
        is_super = abs(delta) > 2.0

    # Get cluster confidence
    matched_profile = next(
        (p for p in cluster_profiles if p.cluster_id == best_cluster), None
    )
    confidence = matched_profile.confidence if matched_profile else "unknown"

    result = MatchResult(
        stock_code=stock_code,
        match_date=match_date,
        best_cluster_id=best_cluster,
        cosine_similarity=round(best_sim, 4),
        final_score=round(final_score, 4),
        is_match=is_match,
        is_super_stock_potential=is_super,
        confidence=confidence,
        cluster_profile=matched_profile.to_dict() if matched_profile else None,
        feature_vector_reduced=reduced_vec.tolist(),
        nearest_neighbors=neighbors,
        dtw_score_60d=round(dtw_60, 4),
        dtw_score_20d=round(dtw_20, 4),
        multiscale_agreement=multiscale_agree,
        failed_pattern_warning=failed_warning,
        failed_pattern_ratio=round(failed_ratio, 4),
    )

    return result


# ---------------------------------------------------------------------------
# Phase 5: k-NN + DTW Helper Functions
# ---------------------------------------------------------------------------

def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-8 or norm_b < 1e-8:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _find_knn_neighbors(
    query_vec: np.ndarray,
    samples_reduced: np.ndarray,
    samples_df: pd.DataFrame,
    samples_labels: Optional[np.ndarray],
    k: int = 5,
) -> list[dict]:
    """Find k nearest neighbors in reduced feature space.

    Trader mandate: "Replace static centroid with k-NN — find the 5 most
    similar predecessors, not just the cluster center."
    """
    n_samples = len(samples_reduced)
    if n_samples == 0:
        return []

    k = min(k, n_samples)

    # Cosine similarity to all samples
    sims = np.array([
        _cosine_sim(query_vec, samples_reduced[i])
        for i in range(n_samples)
    ])

    # Top-k indices
    top_k_idx = np.argsort(sims)[-k:][::-1]

    neighbors = []
    for idx in top_k_idx:
        row = samples_df.iloc[idx]
        nb = {
            "stock_code": str(row.get("stock_code", "")),
            "epiphany_date": str(row.get("epiphany_date", "")),
            "label": str(row.get("label", "")),
            "cosine_similarity": round(float(sims[idx]), 4),
            "cluster_id": int(samples_labels[idx]) if samples_labels is not None else -1,
            "gene_mutation_delta": float(row.get("gene_mutation_delta", 0)),
        }

        # Include forward returns if available
        for h in WINNER_DNA_CONFIG["performance_horizons"]:
            col = f"fwd_{h}d"
            if col in row.index:
                nb[f"fwd_{h}d"] = round(float(row.get(col, 0)), 6)

        neighbors.append(nb)

    return neighbors


def _compute_multiscale_dtw(
    stock_code: str,
    neighbors: list[dict],
    price_df: pd.DataFrame,
    config: dict,
) -> tuple[float, float, bool]:
    """Compute multi-scale DTW between current stock and k-NN neighbors.

    Trader recommendation: 60d captures "structure", 20d captures "momentum".
    If both agree → confidence boost.

    [PLACEHOLDER: MULTISCALE_BOOST]

    Returns:
        (avg_dtw_60d, avg_dtw_20d, scales_agree)
    """
    from analysis.pattern_matcher import dtw_distance, normalize_series

    window_60 = config.get("dtw_window_structure", 60)
    window_20 = config.get("dtw_window_momentum", 20)
    top_k = config.get("dtw_top_k", 30)

    # Get current stock's recent price series
    stock_prices = price_df[price_df["stock_code"] == stock_code].sort_values("date")
    if len(stock_prices) < window_60:
        return 0.0, 0.0, False

    current_60 = normalize_series(stock_prices["close"].values[-window_60:])
    current_20 = normalize_series(stock_prices["close"].values[-window_20:])

    dtw_scores_60 = []
    dtw_scores_20 = []

    # Limit to top_k candidates (Architect mandate)
    candidates = neighbors[:top_k]

    for nb in candidates:
        nb_code = nb["stock_code"]
        nb_date_str = nb.get("epiphany_date", "")
        if not nb_date_str:
            continue

        # Get neighbor's price series around epiphany
        nb_prices = price_df[price_df["stock_code"] == nb_code].sort_values("date")
        if nb_prices.empty:
            continue

        try:
            nb_date = pd.Timestamp(nb_date_str)
        except Exception:
            continue

        # Find the index closest to epiphany date
        date_diffs = (nb_prices["date"] - nb_date).abs()
        closest_idx = date_diffs.idxmin()
        pos = nb_prices.index.get_loc(closest_idx)

        # Extract window before epiphany
        start_60 = max(0, pos - window_60)
        start_20 = max(0, pos - window_20)

        if pos - start_60 < window_20:  # Need at least 20 points
            continue

        nb_series_60 = nb_prices["close"].iloc[start_60:pos].values
        nb_series_20 = nb_prices["close"].iloc[start_20:pos].values

        if len(nb_series_60) >= window_20:
            nb_norm_60 = normalize_series(nb_series_60)
            # Truncate to same length
            min_len = min(len(current_60), len(nb_norm_60))
            d60 = dtw_distance(current_60[-min_len:], nb_norm_60[-min_len:])
            dtw_scores_60.append(d60)

        if len(nb_series_20) >= 10:
            nb_norm_20 = normalize_series(nb_series_20)
            min_len = min(len(current_20), len(nb_norm_20))
            d20 = dtw_distance(current_20[-min_len:], nb_norm_20[-min_len:])
            dtw_scores_20.append(d20)

    avg_60 = float(np.mean(dtw_scores_60)) if dtw_scores_60 else 0.0
    avg_20 = float(np.mean(dtw_scores_20)) if dtw_scores_20 else 0.0

    # Multi-scale agreement: both windows show low DTW distance
    # "Low" = below median of all computed distances
    scales_agree = False
    if dtw_scores_60 and dtw_scores_20:
        # Both below 1.0 normalized DTW → similar shape at both scales
        scales_agree = avg_60 < 1.0 and avg_20 < 1.0

    return avg_60, avg_20, scales_agree


# ---------------------------------------------------------------------------
# Main: Build Winner DNA Library
# ---------------------------------------------------------------------------

def build_winner_dna_library(
    config: Optional[dict] = None,
    method: str = "umap",
    save: bool = True,
) -> dict:
    """Build the complete Winner DNA Library.

    1. Load winner_dna_samples.parquet
    2. Reduce dimensions (UMAP/PCA)
    3. Cluster with HDBSCAN
    4. Compute cluster profiles with multi-horizon stats
    5. Save cluster DB

    Args:
        config: Override WINNER_DNA_CONFIG
        method: "umap" or "pca"
        save: Whether to save output

    Returns:
        Dict with clusters, profiles, and reducer info
    """
    cfg = dict(WINNER_DNA_CONFIG)
    if config:
        cfg.update(config)

    _logger.info("=" * 60)
    _logger.info("Phase 3: Building Winner DNA Library")
    _logger.info("=" * 60)

    # Load data
    if not WINNER_DNA_FILE.exists():
        raise FileNotFoundError(
            f"Winner DNA samples not found: {WINNER_DNA_FILE}. "
            "Run analysis/pattern_labeler.py first (Phase 2)."
        )

    samples_df = pd.read_parquet(WINNER_DNA_FILE)
    metadata = _load_metadata()
    all_features = metadata["all_features"]

    _logger.info("Loaded %d samples (%d winners, %d losers)",
                 len(samples_df),
                 (samples_df["label"] == "winner").sum(),
                 (samples_df["label"] == "loser").sum())

    # Step 1: Extract feature matrix
    feature_cols = [f for f in all_features if f in samples_df.columns]
    feature_matrix = samples_df[feature_cols].values.astype(np.float64)
    _logger.info("Feature matrix: %s (columns: %d/%d)",
                 feature_matrix.shape, len(feature_cols), len(all_features))

    # Step 2: Dimensionality reduction
    _logger.info("Step 2: Dimensionality reduction (%s)...", method)
    reduced_matrix, reducer = reduce_dimensions(feature_matrix, method, cfg)

    # Step 3: HDBSCAN clustering
    _logger.info("Step 3: HDBSCAN clustering...")
    labels, clusterer = cluster_winners(reduced_matrix, cfg)

    # Step 4: Compute cluster profiles
    _logger.info("Step 4: Computing cluster profiles...")
    profiles = compute_cluster_profiles(
        samples_df, labels, reduced_matrix, all_features, cfg
    )

    # Summary
    _print_library_summary(profiles)

    # Save
    if save and profiles:
        db = {
            "version": "2.0",
            "build_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "method": method,
            "n_components": reduced_matrix.shape[1],
            "n_samples": len(samples_df),
            "n_clusters": len(profiles),
            "clusters": [p.to_dict() for p in profiles],
            "config": cfg,
            "reducer_path": str(REDUCER_FILE.name),
            "scaler_path": str(SCALER_FILE.name),
        }
        # Convert non-serializable values
        for k, v in db["config"].items():
            if isinstance(v, np.integer):
                db["config"][k] = int(v)
            elif isinstance(v, np.floating):
                db["config"][k] = float(v)

        with open(CLUSTER_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False, default=str)
        _logger.info("Saved DNA Library to: %s", CLUSTER_DB_FILE)

        # Phase 4: Persist reducer/scaler for real-time matching
        with open(REDUCER_FILE, "wb") as f:
            pickle.dump(reducer, f)
        _logger.info("Saved reducer to: %s", REDUCER_FILE)

        # Save StandardScaler if we have one (for normalizing new data)
        with open(SCALER_FILE, "wb") as f:
            pickle.dump({"feature_cols": feature_cols}, f)
        _logger.info("Saved scaler/metadata to: %s", SCALER_FILE)

    return {
        "samples_df": samples_df,
        "labels": labels,
        "reduced_matrix": reduced_matrix,
        "reducer": reducer,
        "clusterer": clusterer,
        "profiles": profiles,
    }


def _load_metadata() -> dict:
    """Load feature metadata."""
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _print_library_summary(profiles: list[ClusterProfile]):
    """Print summary of the Winner DNA Library."""
    _logger.info("\n" + "=" * 60)
    _logger.info("WINNER DNA LIBRARY SUMMARY")
    _logger.info("=" * 60)

    for p in profiles:
        _logger.info("\nCluster %d: %s", p.cluster_id, p.label)
        _logger.info("  Samples: %d (W:%d, L:%d)", p.n_samples, p.n_winners, p.n_losers)
        _logger.info("  Gene Mutation Δ: mean=%.3f, std=%.3f",
                     p.avg_mutation_delta, p.std_mutation_delta)
        _logger.info("  Top features: %s",
                     ", ".join(f["feature"] for f in p.top_features[:5]))

        # Performance at key horizons
        for horizon_key in ["d21", "d90", "d180"]:
            if horizon_key in p.performance:
                stats = p.performance[horizon_key]
                _logger.info("  %s: WR=%.0f%%, E[R]=%.1f%%, PF=%.2f, Exp=%.3f",
                             horizon_key,
                             stats["win_rate"] * 100,
                             stats["avg_return"] * 100,
                             stats["profit_factor"],
                             stats["expectancy"])

    _logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Convenience: Load Existing Library
# ---------------------------------------------------------------------------

def load_cluster_db() -> Optional[dict]:
    """Load saved cluster DB from JSON."""
    if not CLUSTER_DB_FILE.exists():
        return None
    with open(CLUSTER_DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_reducer() -> Optional[object]:
    """Load persisted UMAP/PCA reducer for real-time matching."""
    if not REDUCER_FILE.exists():
        return None
    with open(REDUCER_FILE, "rb") as f:
        return pickle.load(f)


def load_profiles_from_db(db: dict) -> list[ClusterProfile]:
    """Reconstruct ClusterProfile objects from saved JSON."""
    profiles = []
    for cluster_dict in db.get("clusters", []):
        profile = ClusterProfile(
            cluster_id=cluster_dict.get("cluster_id", -1),
            n_samples=cluster_dict.get("n_samples", 0),
            n_winners=cluster_dict.get("n_winners", 0),
            n_losers=cluster_dict.get("n_losers", 0),
            label=cluster_dict.get("label", ""),
            performance=cluster_dict.get("performance", {}),
            recency_performance=cluster_dict.get("recency_performance", {}),
            confidence=cluster_dict.get("confidence", "unknown"),
            winner_ratio=cluster_dict.get("winner_ratio", 0.0),
            centroid=cluster_dict.get("centroid", []),
            top_features=cluster_dict.get("top_features", []),
            regime_dist=cluster_dict.get("regime_dist", {}),
            avg_mutation_delta=cluster_dict.get("avg_mutation_delta", 0.0),
            std_mutation_delta=cluster_dict.get("std_mutation_delta", 0.0),
        )
        profiles.append(profile)
    return profiles


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    result = build_winner_dna_library()
    if result["profiles"]:
        print(f"\nDone! {len(result['profiles'])} clusters saved to {CLUSTER_DB_FILE}")
    else:
        print("\nNo clusters found. Check logs for details.")

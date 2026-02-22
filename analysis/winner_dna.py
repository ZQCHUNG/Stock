"""Winner DNA Library — Phase 3: UMAP + HDBSCAN Clustering

[CONVERGED — Wall Street Trader + Architect Critic APPROVED]

Uses dimensionality reduction (UMAP/PCA) + HDBSCAN to discover natural
"winner clusters" in the 65-feature space. These clusters represent the
DNA blueprints of historically explosive stocks.

Architecture (per CTO design):
  1. Load winner_dna_samples.parquet (from Phase 2 labeler)
  2. UMAP: 65 features → 5-10 components (Architect mandate: avoid dimension curse)
  3. HDBSCAN: Non-supervised clustering → 5-8 "winner nests"
  4. Pattern Performance DB: For each cluster × holding period → stats
  5. Real-time matching: Cosine Similarity (Stage 1) + DTW (Stage 2)

All thresholds labeled per 假精確 Protocol:
  [HYPOTHESIS: SUPER_STOCK_TARGET] — Price thresholds
  [PLACEHOLDER: MATCH_THRESHOLD_085] — 85% similarity cutoff
  [VERIFIED: GENE_MUTATION_SCANNER] — Existing 1.5σ detection
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

_logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FEATURES_DIR = PROJECT_ROOT / "data" / "pattern_data" / "features"
WINNER_DNA_FILE = FEATURES_DIR / "winner_dna_samples.parquet"
CLUSTER_DB_FILE = FEATURES_DIR / "winner_clusters.json"
METADATA_FILE = FEATURES_DIR / "feature_metadata.json"
FEATURES_FILE = FEATURES_DIR / "features_all.parquet"


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

    # Multi-horizon performance stats
    performance: dict = field(default_factory=dict)

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
    is_match: bool = False
    is_super_stock_potential: bool = False
    cluster_profile: Optional[dict] = None
    feature_vector_reduced: list[float] = field(default_factory=list)

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
    stats.profit_factor = round(total_wins / total_losses, 4) if total_losses > 0 else float("inf")

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
) -> MatchResult:
    """Match a stock's current features against the Winner DNA Library.

    Two-Stage Matcher (per CTO design):
      Stage 1: Cosine Similarity in reduced space → >85% match to any centroid
      Stage 2: (Deferred to Task #9 — DTW shape match)

    [PLACEHOLDER: MATCH_THRESHOLD_085] — 85% needs sensitivity test

    Args:
        stock_code: Stock to evaluate
        features_df: Current features (from features_all.parquet)
        cluster_profiles: Fitted cluster profiles
        reducer: Fitted UMAP/PCA reducer
        all_features: List of 65 feature names
        config: Override config

    Returns:
        MatchResult with best matching cluster and similarity score
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
        # PCA/UMAP transform failure
        return MatchResult(stock_code=stock_code, match_date=match_date)

    reduced_vec = reduced.flatten()

    # Stage 1: Cosine Similarity to each cluster centroid
    best_sim = -1.0
    best_cluster = -1

    for profile in cluster_profiles:
        centroid = np.array(profile.centroid)
        if len(centroid) != len(reduced_vec):
            continue

        # Cosine similarity
        dot = np.dot(reduced_vec, centroid)
        norm_q = np.linalg.norm(reduced_vec)
        norm_c = np.linalg.norm(centroid)

        if norm_q > 1e-8 and norm_c > 1e-8:
            sim = dot / (norm_q * norm_c)
        else:
            sim = 0.0

        if sim > best_sim:
            best_sim = sim
            best_cluster = profile.cluster_id

    is_match = best_sim >= threshold

    # Check super stock potential (Δ_div > 2σ)
    is_super = False
    if "gene_mutation_delta" in latest.index:
        delta = float(latest.get("gene_mutation_delta", 0))
        # Need std from the full dataset — simplified check here
        is_super = abs(delta) > 2.0  # Z-score already normalized

    result = MatchResult(
        stock_code=stock_code,
        match_date=match_date,
        best_cluster_id=best_cluster,
        cosine_similarity=round(best_sim, 4),
        is_match=is_match,
        is_super_stock_potential=is_super,
        cluster_profile=(
            next((p.to_dict() for p in cluster_profiles
                  if p.cluster_id == best_cluster), None)
        ),
        feature_vector_reduced=reduced_vec.tolist(),
    )

    return result


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
            "version": "1.0",
            "method": method,
            "n_components": reduced_matrix.shape[1],
            "n_samples": len(samples_df),
            "n_clusters": len(profiles),
            "clusters": [p.to_dict() for p in profiles],
            "config": cfg,
        }
        # Convert non-serializable values
        for k, v in db["config"].items():
            if isinstance(v, np.integer):
                db["config"][k] = int(v)
            elif isinstance(v, np.floating):
                db["config"][k] = float(v)

        with open(CLUSTER_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False, default=str)
        _logger.info("Saved cluster DB to: %s", CLUSTER_DB_FILE)

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

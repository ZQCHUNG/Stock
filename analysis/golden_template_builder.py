"""Golden Template Library Builder.

Builds a library of "golden" stock templates from historical data —
stocks that achieved D30 forward return >= +20%. These templates are
used for daily market scanning to find current stocks that resemble
past winners.

9-point design (confirmed by trading advisor):
  1. D30 threshold >= +20%
  2. Per-stock cooldown 30 days (keep earliest per wave)
  3. Top-K = 15, same industry max 3
  4. Ranking: composite = similarity * 0.7 + consistency * 0.3
  5. Per-stock template cap: max 20 (keep top by consistency)
  6. Presets use weight multiplication (not dimension filtering)
  7. Scanning: post-market only (once per day)
  8. UI stats: median and quartiles (NOT averages)
  9. Hit rate: Top-5 templates, how many have ALL fwd returns positive

All parameters marked [PLACEHOLDER] pending validation.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# --- Paths ---
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
FEATURES_DIR = _PROJECT_ROOT / "data" / "pattern_data" / "features"
FEATURES_FILE = FEATURES_DIR / "features_all.parquet"
METADATA_FILE = FEATURES_DIR / "feature_metadata.json"
CLOSE_MATRIX_FILE = _PROJECT_ROOT / "data" / "pit_close_matrix.parquet"
GOLDEN_DIR = _PROJECT_ROOT / "data" / "golden_templates"

# --- Constants [PLACEHOLDER] ---
# [PLACEHOLDER: D30_THRESHOLD_001] 20% forward return threshold
DEFAULT_D30_THRESHOLD = 0.20

# [PLACEHOLDER: COOLDOWN_DAYS_001] Per-stock dedup cooldown
DEFAULT_COOLDOWN_DAYS = 30

# [PLACEHOLDER: MAX_PER_STOCK_001] Max templates per stock
DEFAULT_MAX_PER_STOCK = 20

# [PLACEHOLDER: TOP_K_001] Default number of scan results
DEFAULT_TOP_K = 15

# [PLACEHOLDER: MAX_PER_INDUSTRY_001] Same industry cap in top-K
DEFAULT_MAX_PER_INDUSTRY = 3

# [PLACEHOLDER: COMPOSITE_WEIGHTS_001] similarity * 0.7 + consistency * 0.3
SIMILARITY_WEIGHT = 0.7
CONSISTENCY_WEIGHT = 0.3

# Forward return horizons (trading days) matching pit_close_matrix
FORWARD_DAYS = [7, 14, 30, 90]
FORWARD_LABELS = ["fwd_d7", "fwd_d14", "fwd_d30", "fwd_d90"]

# 5 user-facing dimensions → internal dimension mapping
# (reused from similarity_engine.py)
DIMENSION_GROUPS = {
    "technical": ["technical"],
    "institutional": ["institutional", "brokerage"],
    "fundamental": ["fundamental"],
    "news": ["attention"],
    "industry": ["industry"],
}

# Preset weight multipliers — multiply (not filter) selected dimensions
# [PLACEHOLDER: PRESET_WEIGHTS_001]
PRESET_WEIGHTS = {
    "technical": {"technical": 2.0, "institutional": 2.0, "fundamental": 1.0, "news": 1.0, "industry": 1.0},
    "value": {"technical": 1.0, "institutional": 1.0, "fundamental": 2.0, "news": 1.0, "industry": 2.0},
    "event": {"technical": 1.0, "institutional": 2.0, "fundamental": 1.0, "news": 2.0, "industry": 1.0},
    "all": {"technical": 1.0, "institutional": 1.0, "fundamental": 1.0, "news": 1.0, "industry": 1.0},
}


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def compute_consistency(fwd_d7: float, fwd_d14: float, fwd_d30: float, fwd_d90: float) -> float:
    """Fraction of forward returns that are positive.

    Args:
        fwd_d7: D7 forward return (may be NaN).
        fwd_d14: D14 forward return (may be NaN).
        fwd_d30: D30 forward return (may be NaN).
        fwd_d90: D90 forward return (may be NaN).

    Returns:
        Float 0.0 to 1.0: fraction of non-NaN returns that are positive.
        Returns 0.0 if all are NaN.
    """
    values = [fwd_d7, fwd_d14, fwd_d30, fwd_d90]
    valid = [v for v in values if v is not None and not (isinstance(v, float) and np.isnan(v))]
    if not valid:
        return 0.0
    positive_count = sum(1 for v in valid if v > 0)
    return positive_count / len(valid)


def _load_metadata() -> dict:
    """Load feature_metadata.json."""
    if not METADATA_FILE.exists():
        raise FileNotFoundError(f"Feature metadata not found: {METADATA_FILE}")
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_dimension_indices(all_features: list, metadata: dict) -> dict:
    """Map each user-facing dimension to its feature column indices.

    Returns:
        dict: dimension_name -> list of int indices into all_features.
    """
    dim_indices = {}
    for dim_name, internal_dims in DIMENSION_GROUPS.items():
        indices = []
        for internal in internal_dims:
            if internal in metadata.get("dimensions", {}):
                for feat in metadata["dimensions"][internal]["features"]:
                    if feat in all_features:
                        indices.append(all_features.index(feat))
        dim_indices[dim_name] = indices
    return dim_indices


def _build_weight_vector(
    all_features: list,
    dim_indices: dict,
    preset: str,
) -> np.ndarray:
    """Build per-feature weight vector based on preset.

    Uses weight multiplication: selected dimensions get 2x, others get 1x.

    Returns:
        np.ndarray of shape (n_features,), float32.
    """
    weights = np.ones(len(all_features), dtype=np.float32)
    preset_config = PRESET_WEIGHTS.get(preset, PRESET_WEIGHTS["all"])

    for dim_name, indices in dim_indices.items():
        w = preset_config.get(dim_name, 1.0)
        for idx in indices:
            weights[idx] = w

    return weights


def _compute_forward_returns_batch(
    stock_codes: np.ndarray,
    dates: np.ndarray,
    close_matrix: pd.DataFrame,
) -> np.ndarray:
    """Compute forward returns for multiple (stock, date) pairs.

    Args:
        stock_codes: (N,) array of stock codes.
        dates: (N,) array of datetime64.
        close_matrix: Close price matrix (dates x stocks).

    Returns:
        (N, 4) float32 array: columns = [d7, d14, d30, d90].
        NaN where data is unavailable.
    """
    n = len(stock_codes)
    result = np.full((n, len(FORWARD_DAYS)), np.nan, dtype=np.float32)

    # Build date -> position lookup
    cm_index = close_matrix.index
    date_to_pos = {d: i for i, d in enumerate(cm_index)}

    for i in range(n):
        code = stock_codes[i]
        if code not in close_matrix.columns:
            continue

        dt = pd.Timestamp(dates[i])
        if dt not in date_to_pos:
            # Find nearest within 5 calendar days
            idx_pos = cm_index.searchsorted(dt)
            if idx_pos >= len(cm_index):
                continue
            actual = cm_index[idx_pos]
            if abs((actual - dt).days) > 5:
                continue
            dt = actual

        pos = date_to_pos[dt]
        prices = close_matrix[code].values
        base_price = prices[pos]

        if np.isnan(base_price) or base_price <= 0:
            continue

        for j, horizon in enumerate(FORWARD_DAYS):
            future_pos = pos + horizon
            if future_pos < len(prices):
                future_price = prices[future_pos]
                if not np.isnan(future_price) and future_price > 0:
                    result[i, j] = (future_price / base_price) - 1.0

    return result


def _dedup_per_stock(
    df: pd.DataFrame,
    cooldown_days: int,
) -> pd.DataFrame:
    """Per-stock cooldown deduplication.

    For each stock, sort by date ascending. Keep the first occurrence,
    then skip all within cooldown_days. Repeat.

    Args:
        df: DataFrame with at least 'stock_code' and 'date' columns.
        cooldown_days: Minimum days between templates for the same stock.

    Returns:
        Filtered DataFrame.
    """
    keep_indices = []
    for _, group in df.groupby("stock_code"):
        group = group.sort_values("date")
        last_kept = None
        for idx, row in group.iterrows():
            if last_kept is None or (row["date"] - last_kept).days >= cooldown_days:
                keep_indices.append(idx)
                last_kept = row["date"]
    return df.loc[keep_indices].reset_index(drop=True)


def _cap_per_stock(
    df: pd.DataFrame,
    max_per_stock: int,
) -> pd.DataFrame:
    """Cap templates per stock, keeping top by consistency.

    Args:
        df: DataFrame with 'stock_code' and 'consistency' columns.
        max_per_stock: Maximum templates per stock.

    Returns:
        Filtered DataFrame.
    """
    parts = []
    for _, group in df.groupby("stock_code"):
        if len(group) > max_per_stock:
            group = group.nlargest(max_per_stock, "consistency")
        parts.append(group)
    if not parts:
        return df.iloc[:0]
    return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------------------
# Build Golden Templates
# ---------------------------------------------------------------------------


def build_golden_templates(
    features_parquet: str = None,
    close_matrix_parquet: str = None,
    output_path: str = None,
    d30_threshold: float = DEFAULT_D30_THRESHOLD,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
    max_per_stock: int = DEFAULT_MAX_PER_STOCK,
) -> dict:
    """Build the golden template library from historical data.

    Pipeline:
      1. Load features + close matrix
      2. Compute forward returns for all (stock, date) pairs
      3. Filter D30 >= threshold
      4. Remove zero-feature rows
      5. Per-stock cooldown dedup
      6. Per-stock cap (top by consistency)
      7. Save golden_templates.parquet + template_norms.npy + build_metadata.json

    Args:
        features_parquet: Path to features_all.parquet. Default: standard path.
        close_matrix_parquet: Path to pit_close_matrix.parquet. Default: standard path.
        output_path: Directory to save results. Default: data/golden_templates/.
        d30_threshold: [PLACEHOLDER: D30_THRESHOLD_001] Minimum D30 return.
        cooldown_days: [PLACEHOLDER: COOLDOWN_DAYS_001] Per-stock dedup window.
        max_per_stock: [PLACEHOLDER: MAX_PER_STOCK_001] Max templates per stock.

    Returns:
        dict with build metadata (counts, timing, paths).
    """
    t0 = time.time()

    features_path = Path(features_parquet) if features_parquet else FEATURES_FILE
    close_path = Path(close_matrix_parquet) if close_matrix_parquet else CLOSE_MATRIX_FILE
    out_dir = Path(output_path) if output_path else GOLDEN_DIR

    if not features_path.exists():
        raise FileNotFoundError(f"Features file not found: {features_path}")
    if not close_path.exists():
        raise FileNotFoundError(f"Close matrix not found: {close_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    # Load metadata
    meta = _load_metadata()
    feature_cols = meta["all_features"]

    # Load features
    logger.info("Loading features from %s", features_path)
    df = pd.read_parquet(features_path)
    df["date"] = pd.to_datetime(df["date"])
    total_rows = len(df)
    logger.info("Features loaded: %d rows, %d features", total_rows, len(feature_cols))

    # Load close matrix
    logger.info("Loading close matrix from %s", close_path)
    close_matrix = pd.read_parquet(close_path)
    close_matrix.index = pd.to_datetime(close_matrix.index)

    # Compute forward returns for all rows
    logger.info("Computing forward returns for %d rows...", len(df))
    fwd = _compute_forward_returns_batch(
        df["stock_code"].values,
        df["date"].values,
        close_matrix,
    )
    for i, label in enumerate(FORWARD_LABELS):
        df[label] = fwd[:, i]

    # Filter: D30 >= threshold
    d30_col = "fwd_d30"
    candidates = df[df[d30_col] >= d30_threshold].copy()
    n_candidates = len(candidates)
    logger.info(
        "D30 >= %.0f%%: %d candidates (%.2f%% of %d)",
        d30_threshold * 100, n_candidates, 100 * n_candidates / max(total_rows, 1), total_rows,
    )

    if n_candidates == 0:
        logger.warning("No candidates found with D30 >= %.0f%%", d30_threshold * 100)
        return {"status": "empty", "total_candidates": 0}

    # Remove zero-feature rows
    feature_matrix = candidates[feature_cols].values
    row_sums = np.abs(feature_matrix).sum(axis=1)
    nonzero_mask = row_sums > 1e-6
    n_zero = (~nonzero_mask).sum()
    candidates = candidates[nonzero_mask].copy()
    logger.info("Removed %d zero-feature rows, remaining: %d", n_zero, len(candidates))

    # Per-stock cooldown dedup
    candidates = _dedup_per_stock(candidates, cooldown_days)
    n_after_dedup = len(candidates)
    logger.info("After %d-day cooldown dedup: %d templates", cooldown_days, n_after_dedup)

    # Compute consistency
    candidates["consistency"] = candidates.apply(
        lambda r: compute_consistency(r["fwd_d7"], r["fwd_d14"], r["fwd_d30"], r["fwd_d90"]),
        axis=1,
    )

    # Per-stock cap
    candidates = _cap_per_stock(candidates, max_per_stock)
    n_after_cap = len(candidates)
    logger.info("After per-stock cap (%d): %d templates", max_per_stock, n_after_cap)

    # Build template_id
    candidates = candidates.sort_values(["stock_code", "date"]).reset_index(drop=True)
    candidates["template_id"] = np.arange(len(candidates), dtype=np.uint32)

    # Extract feature matrix and compute norms
    template_matrix = candidates[feature_cols].values.astype(np.float32)
    np.nan_to_num(template_matrix, copy=False, nan=0.0)
    norms = np.linalg.norm(template_matrix, axis=1).astype(np.float32)
    norms[norms < 1e-10] = 1.0

    # Regime distribution
    regime_col = "regime_tag" if "regime_tag" in candidates.columns else None
    if regime_col:
        regime_dist = candidates[regime_col].value_counts().to_dict()
        regime_dist = {int(k): int(v) for k, v in regime_dist.items()}
    else:
        regime_dist = {}

    # Save outputs
    save_cols = (
        ["template_id", "stock_code", "date"]
        + ([regime_col] if regime_col else [])
        + FORWARD_LABELS
        + ["consistency"]
        + feature_cols
    )
    out_parquet = out_dir / "golden_templates.parquet"
    candidates[save_cols].to_parquet(out_parquet, index=False)
    logger.info("Saved: %s (%d templates)", out_parquet, len(candidates))

    out_norms = out_dir / "template_norms.npy"
    np.save(out_norms, norms)
    logger.info("Saved: %s", out_norms)

    # Build metadata
    elapsed = time.time() - t0
    stocks_represented = candidates["stock_code"].nunique()
    build_meta = {
        "built_at": pd.Timestamp.now().isoformat(),
        "d30_threshold": d30_threshold,
        "cooldown_days": cooldown_days,
        "max_per_stock": max_per_stock,
        "total_rows_in_features": total_rows,
        "total_candidates": n_candidates,
        "after_zero_filter": n_candidates - n_zero,
        "after_dedup": n_after_dedup,
        "after_cap": n_after_cap,
        "regime_distribution": regime_dist,
        "feature_count": len(feature_cols),
        "stocks_represented": stocks_represented,
        "avg_templates_per_stock": round(n_after_cap / max(stocks_represented, 1), 1),
        "elapsed_s": round(elapsed, 1),
    }

    out_meta = out_dir / "build_metadata.json"
    with open(out_meta, "w", encoding="utf-8") as f:
        json.dump(build_meta, f, indent=2, default=str)
    logger.info("Saved: %s", out_meta)

    logger.info(
        "Golden template build complete: %d templates, %d stocks, %.1fs",
        n_after_cap, stocks_represented, elapsed,
    )
    return build_meta


# ---------------------------------------------------------------------------
# Scan Market
# ---------------------------------------------------------------------------


def scan_market(
    templates_path: str = None,
    current_features_parquet: str = None,
    close_matrix_parquet: str = None,
    regime: int = None,
    preset: str = "technical",
    top_k: int = DEFAULT_TOP_K,
    max_per_industry: int = DEFAULT_MAX_PER_INDUSTRY,
    min_active_days: int = 5,
    min_traded_ratio: float = 0.9,
) -> list:
    """Daily scan: compare current market against golden templates.

    For each stock in today's features, compute weighted cosine similarity
    against all templates (optionally filtered by regime). Rank by
    composite = similarity * 0.7 + consistency * 0.3.

    Filters applied before ranking:
      - Active stock filter: last trade within min_active_days of latest market date
      - Liquidity filter: must have traded >= min_traded_ratio of last 20 days

    Apply industry cap: max_per_industry stocks from the same industry
    in the final top-K list.

    Args:
        templates_path: Path to golden_templates.parquet. Default: standard.
        current_features_parquet: Path to features for today. Default: standard.
        close_matrix_parquet: Path to close matrix. Default: standard.
        regime: 1=bull, -1=bear, None=all templates.
        preset: "technical" | "value" | "event" | "all".
            [PLACEHOLDER: PRESET_WEIGHTS_001]
        top_k: [PLACEHOLDER: TOP_K_001] Number of results to return.
        max_per_industry: [PLACEHOLDER: MAX_PER_INDUSTRY_001] Industry cap.
        min_active_days: Max calendar days gap from latest market date to
            consider a stock as active. Default 5 (~5 trading days ~ 7 cal days).
        min_traded_ratio: Minimum fraction of last 20 trading days with valid
            close prices. Stocks below this are considered illiquid. Default 0.9.

    Returns:
        list of dicts, each containing:
            stock_code, similarity, consistency, composite_score,
            hit_rate (fraction of top-5 templates with ALL fwd returns positive),
            top_template_matches (top 5), stats (median/quartiles per horizon).
    """
    t0 = time.time()

    tpl_path = Path(templates_path) if templates_path else GOLDEN_DIR / "golden_templates.parquet"
    feat_path = Path(current_features_parquet) if current_features_parquet else FEATURES_FILE
    norms_path = tpl_path.parent / "template_norms.npy"

    if not tpl_path.exists():
        raise FileNotFoundError(f"Golden templates not found: {tpl_path}")
    if not feat_path.exists():
        raise FileNotFoundError(f"Features not found: {feat_path}")

    # Load metadata
    meta = _load_metadata()
    feature_cols = meta["all_features"]
    dim_indices = _build_dimension_indices(feature_cols, meta)

    # Load templates
    tpl_df = pd.read_parquet(tpl_path)
    tpl_df["date"] = pd.to_datetime(tpl_df["date"])

    # Regime filter
    if regime is not None and "regime_tag" in tpl_df.columns:
        tpl_df = tpl_df[tpl_df["regime_tag"] == regime].reset_index(drop=True)
        logger.info("Regime filter=%d: %d templates", regime, len(tpl_df))

    if len(tpl_df) == 0:
        logger.warning("No templates after regime filter")
        return []

    # Template feature matrix
    tpl_matrix = tpl_df[feature_cols].values.astype(np.float32)
    np.nan_to_num(tpl_matrix, copy=False, nan=0.0)

    # Template norms (precomputed or recalculate)
    if norms_path.exists():
        tpl_norms = np.load(norms_path)
        # If regime-filtered, we need to recompute for the subset
        if regime is not None and len(tpl_norms) != len(tpl_matrix):
            tpl_norms = np.linalg.norm(tpl_matrix, axis=1).astype(np.float32)
            tpl_norms[tpl_norms < 1e-10] = 1.0
    else:
        tpl_norms = np.linalg.norm(tpl_matrix, axis=1).astype(np.float32)
        tpl_norms[tpl_norms < 1e-10] = 1.0

    # Template consistency
    tpl_consistency = tpl_df["consistency"].values.astype(np.float32)

    # Load current features (latest date per stock)
    feat_df = pd.read_parquet(feat_path)
    feat_df["date"] = pd.to_datetime(feat_df["date"])
    latest_df = feat_df.sort_values("date").groupby("stock_code").tail(1).reset_index(drop=True)
    n_before_filter = len(latest_df)
    logger.info("Current features: %d stocks (latest dates)", n_before_filter)

    if len(latest_df) == 0:
        return []

    # --- Fix 1: Filter delisted/inactive stocks ---
    # --- Fix 2: Filter illiquid stocks (no volume data → use close matrix gaps) ---
    close_path = Path(close_matrix_parquet) if close_matrix_parquet else CLOSE_MATRIX_FILE
    if close_path.exists():
        close_matrix = pd.read_parquet(close_path)
        close_matrix.index = pd.to_datetime(close_matrix.index)
        active_liquid = _get_active_liquid_stocks(
            close_matrix, min_active_days, min_traded_ratio,
        )
        pre_count = len(latest_df)
        latest_df = latest_df[latest_df["stock_code"].isin(active_liquid)].reset_index(drop=True)
        n_filtered = pre_count - len(latest_df)
        logger.info(
            "Active/liquid filter: kept %d, removed %d (inactive=%d-day gap or <%.0f%% traded)",
            len(latest_df), n_filtered, min_active_days, min_traded_ratio * 100,
        )
    else:
        logger.warning("Close matrix not found at %s — skipping active/liquid filter", close_path)

    if len(latest_df) == 0:
        return []

    # Build weight vector for preset
    weight_vec = _build_weight_vector(feature_cols, dim_indices, preset)

    # Current feature matrix (weighted)
    cur_matrix = latest_df[feature_cols].values.astype(np.float32)
    np.nan_to_num(cur_matrix, copy=False, nan=0.0)

    # Apply weights
    cur_weighted = cur_matrix * weight_vec[np.newaxis, :]  # (N_cur, F)
    tpl_weighted = tpl_matrix * weight_vec[np.newaxis, :]  # (N_tpl, F)

    # Weighted norms
    cur_norms = np.linalg.norm(cur_weighted, axis=1).astype(np.float32)
    cur_norms[cur_norms < 1e-10] = 1.0
    tpl_w_norms = np.linalg.norm(tpl_weighted, axis=1).astype(np.float32)
    tpl_w_norms[tpl_w_norms < 1e-10] = 1.0

    # Vectorized cosine similarity: (N_cur, N_tpl)
    # sim_matrix[i, j] = dot(cur_weighted[i], tpl_weighted[j]) / (cur_norms[i] * tpl_w_norms[j])
    sim_matrix = (cur_weighted @ tpl_weighted.T) / (cur_norms[:, np.newaxis] * tpl_w_norms[np.newaxis, :])
    np.clip(sim_matrix, 0.0, 1.0, out=sim_matrix)

    # For each stock: get top-5 template matches, compute composite score
    # [PLACEHOLDER: TOP_MATCH_K_001] Top-5 matches per stock
    match_k = 5
    results = []

    for i in range(len(latest_df)):
        sims = sim_matrix[i]  # (N_tpl,)

        # Skip if all zero
        if sims.max() < 1e-6:
            continue

        # Top-match_k indices
        if len(sims) <= match_k:
            top_idx = np.argsort(sims)[::-1]
        else:
            top_idx = np.argpartition(sims, -match_k)[-match_k:]
            top_idx = top_idx[np.argsort(sims[top_idx])[::-1]]

        top_sims = sims[top_idx]
        top_consistencies = tpl_consistency[top_idx]

        avg_sim = float(np.mean(top_sims))
        avg_consistency = float(np.mean(top_consistencies))

        # Composite score: similarity * 0.7 + consistency * 0.3
        composite = avg_sim * SIMILARITY_WEIGHT + avg_consistency * CONSISTENCY_WEIGHT

        # Build top match details
        top_matches = []
        for j, tidx in enumerate(top_idx):
            trow = tpl_df.iloc[tidx]
            top_matches.append({
                "template_id": int(trow.get("template_id", tidx)),
                "stock_code": str(trow["stock_code"]),
                "date": str(trow["date"].date()),
                "similarity": round(float(top_sims[j]), 6),
                "fwd_d7": _safe_float(trow.get("fwd_d7")),
                "fwd_d14": _safe_float(trow.get("fwd_d14")),
                "fwd_d30": _safe_float(trow.get("fwd_d30")),
                "fwd_d90": _safe_float(trow.get("fwd_d90")),
                "consistency": round(float(top_consistencies[j]), 4),
            })

        # Stats: median and quartiles per horizon (NOT averages) — design point #8
        stats = _compute_per_horizon_stats(top_matches)

        # Hit rate (Fix 3): fraction of top-5 templates where ALL forward
        # returns are positive (the "consistency at match level" concept).
        # Old definition was "D30 > 20%" which was always 5/5 by construction.
        hit_rate = _compute_hit_rate(top_matches)

        stock_code = str(latest_df.iloc[i]["stock_code"])
        results.append({
            "stock_code": stock_code,
            "similarity": round(avg_sim, 6),
            "consistency": round(avg_consistency, 4),
            "composite_score": round(composite, 6),
            "hit_rate": round(hit_rate, 4),
            "top_matches": top_matches,
            "stats": stats,
        })

    # Sort by composite score descending
    results.sort(key=lambda x: x["composite_score"], reverse=True)

    # Apply industry cap
    results = _apply_industry_cap(results, max_per_industry, top_k)

    elapsed = time.time() - t0
    logger.info(
        "Market scan complete: %d results (preset=%s, regime=%s, %.1fms)",
        len(results), preset, regime, elapsed * 1000,
    )
    return results


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _get_active_liquid_stocks(
    close_matrix: pd.DataFrame,
    min_active_days: int = 5,
    min_traded_ratio: float = 0.9,
) -> set:
    """Identify active and liquid stocks from close matrix.

    Fix 1 — Active filter: stock's last valid close must be within
    `min_active_days` calendar days of the latest market date.

    Fix 2 — Liquidity filter: stock must have valid close prices for
    at least `min_traded_ratio` fraction of the last 20 trading days.
    This catches illiquid/suspended stocks without needing volume data.

    Args:
        close_matrix: Close price DataFrame (dates x stocks).
        min_active_days: Max calendar days gap to latest market date.
        min_traded_ratio: Min fraction of last-20 days with valid prices.

    Returns:
        Set of stock codes passing both filters.
    """
    if close_matrix.empty:
        return set()

    latest_market_date = close_matrix.index[-1]
    # Use last 20 trading days for liquidity check
    lookback = min(20, len(close_matrix))
    recent = close_matrix.iloc[-lookback:]

    active_stocks = set()
    for col in close_matrix.columns:
        # Fix 1: Check if stock has recent data
        last_valid = close_matrix[col].last_valid_index()
        if last_valid is None:
            continue
        days_gap = (latest_market_date - last_valid).days
        if days_gap > min_active_days:
            continue

        # Fix 2: Check trading frequency in last 20 days
        valid_count = recent[col].notna().sum()
        traded_ratio = valid_count / lookback
        if traded_ratio < min_traded_ratio:
            continue

        active_stocks.add(col)

    return active_stocks


def _compute_hit_rate(top_matches: list) -> float:
    """Compute hit rate: fraction of top-5 templates with ALL forward returns positive.

    Fix 3 — Old definition was "D30 > 20%" which was always 5/5 since
    golden templates are filtered by D30 >= 20% by construction.
    New definition: a template "hits" when every available forward return
    (D7, D14, D30, D90) is positive. This captures true consistency.

    Args:
        top_matches: List of match dicts with fwd_d7/d14/d30/d90 keys.

    Returns:
        Float 0.0 to 1.0.
    """
    if not top_matches:
        return 0.0

    hit_count = 0
    for m in top_matches:
        fwd_values = [m.get(k) for k in ("fwd_d7", "fwd_d14", "fwd_d30", "fwd_d90")]
        valid = [v for v in fwd_values if v is not None]
        if valid and all(v > 0 for v in valid):
            hit_count += 1

    return hit_count / len(top_matches)


def _compute_per_horizon_stats(top_matches: list) -> dict:
    """Compute median and quartiles for each forward return horizon.

    Fix 4 — Old stats only covered D30. New version covers all horizons
    with median, Q1 (25th percentile), Q3 (75th percentile).

    Args:
        top_matches: List of match dicts with fwd_d7/d14/d30/d90 keys.

    Returns:
        dict keyed by horizon label, each containing median/q25/q75/count.
        Empty dict if no valid data.
    """
    if not top_matches:
        return {}

    stats = {}
    for label in FORWARD_LABELS:
        values = [m[label] for m in top_matches if m.get(label) is not None]
        if values:
            arr = np.array(values, dtype=np.float64)
            stats[label] = {
                "median": round(float(np.median(arr)), 6),
                "q25": round(float(np.percentile(arr, 25)), 6),
                "q75": round(float(np.percentile(arr, 75)), 6),
                "min": round(float(np.min(arr)), 6),
                "max": round(float(np.max(arr)), 6),
                "count": len(arr),
            }
    return stats


def compute_score_distribution(results: list) -> dict:
    """Compute composite score distribution from scan results.

    Fix 5 — Run this after scan_market(..., top_k=9999) to understand
    whether scores are compressed or well-spread.

    Args:
        results: Full list of scan_market results (use large top_k).

    Returns:
        dict with mean, median, p25, p75, p90, p95, max, count.
    """
    if not results:
        return {"count": 0}

    scores = np.array([r["composite_score"] for r in results], dtype=np.float64)
    return {
        "count": len(scores),
        "mean": round(float(np.mean(scores)), 6),
        "median": round(float(np.median(scores)), 6),
        "p25": round(float(np.percentile(scores, 25)), 6),
        "p75": round(float(np.percentile(scores, 75)), 6),
        "p90": round(float(np.percentile(scores, 90)), 6),
        "p95": round(float(np.percentile(scores, 95)), 6),
        "max": round(float(np.max(scores)), 6),
        "min": round(float(np.min(scores)), 6),
    }


def _safe_float(val) -> Optional[float]:
    """Convert value to float, returning None for NaN/None."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else round(f, 6)
    except (ValueError, TypeError):
        return None


def _compute_quartile_stats(values: list) -> dict:
    """Compute median and quartiles (design point #8: NOT averages).

    Returns:
        dict with median, q25, q75, min, max.
    """
    if not values:
        return {}
    arr = np.array(values, dtype=np.float64)
    return {
        "median": round(float(np.median(arr)), 6),
        "q25": round(float(np.percentile(arr, 25)), 6),
        "q75": round(float(np.percentile(arr, 75)), 6),
        "min": round(float(np.min(arr)), 6),
        "max": round(float(np.max(arr)), 6),
        "count": len(arr),
    }


def _apply_industry_cap(
    results: list,
    max_per_industry: int,
    top_k: int,
) -> list:
    """Apply industry cap to scan results.

    Since we may not have industry mapping readily available, we use the
    first 2 digits of stock_code as a rough industry proxy (TWSE convention:
    e.g., 23xx = Electronics, 28xx = Finance).

    For a proper implementation, this should use the actual industry mapping.
    [PLACEHOLDER: INDUSTRY_MAPPING_001]

    Args:
        results: Sorted list of scan results (by composite_score desc).
        max_per_industry: Maximum stocks from same industry group.
        top_k: Total results to return.

    Returns:
        Filtered list, length <= top_k.
    """
    filtered = []
    industry_count = {}

    for r in results:
        # Rough industry proxy: first 2 digits of stock code
        code = r["stock_code"]
        industry = code[:2] if len(code) >= 2 else code

        count = industry_count.get(industry, 0)
        if count >= max_per_industry:
            continue

        filtered.append(r)
        industry_count[industry] = count + 1

        if len(filtered) >= top_k:
            break

    return filtered


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    print("Building golden templates...")
    result = build_golden_templates()
    print(json.dumps(result, indent=2, default=str))

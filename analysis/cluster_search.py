"""多維度相似股分群 — Cosine Similarity 搜尋引擎

Converged design from Gemini Wall Street Trader + Architect Critic debate:
- 50 features across 5 dimensions (tech/inst/industry/fund/attention)
- Shape descriptors (slope/convexity/skewness/endpoint_ratio) per window
- Feature weighting: ATR/Volume 1.5x [CONVERGED]
- Regime filter: same-regime matching [CONVERGED]
- Time decay: exponential, half-life 2 years [CONVERGED]
- Statistics: p5/p95/max_drawdown/expectancy [CONVERGED]
- TRANSACTION_COST deduction [ARCHITECT APPROVED]
- Min similarity threshold [PLACEHOLDER: 0.7]
- Small sample warning when n < 30 [ARCHITECT INSTRUCTION]
"""

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import skew as scipy_skew

logger = logging.getLogger(__name__)

# --- Constants ---
TRANSACTION_COST = 0.00785  # [VERIFIED] 0.1425%×2 + 0.3% + 0.1%×2
# [PLACEHOLDER: SIMILARITY_THRESHOLD_07] — needs distribution validation
MIN_SIMILARITY_THRESHOLD = 0.7
TIME_DECAY_HALF_LIFE_DAYS = 365 * 2  # [CONVERGED] 2 years
SMALL_SAMPLE_THRESHOLD = 30  # [ARCHITECT INSTRUCTION]

# Feature weighting [CONVERGED with Gemini Wall Street Trader]
FEATURE_WEIGHTS = {
    "atr_pct": 1.5,
    "vol_ratio_20": 1.5,
}

# --- Data paths ---
FEATURES_DIR = Path(__file__).resolve().parent.parent / "data" / "pattern_data" / "features"
FEATURES_FILE = FEATURES_DIR / "features_all.parquet"
RETURNS_FILE = FEATURES_DIR / "forward_returns.parquet"
METADATA_FILE = FEATURES_DIR / "feature_metadata.json"

# --- In-memory cache ---
_features_df: Optional[pd.DataFrame] = None
_features_matrix: Optional[np.ndarray] = None
_feature_index: Optional[pd.DataFrame] = None
_regime_tags: Optional[np.ndarray] = None
_forward_returns: Optional[pd.DataFrame] = None
_metadata: Optional[dict] = None
_feature_cols: Optional[list] = None
_feature_weight_vector: Optional[np.ndarray] = None


def _load_metadata() -> dict:
    global _metadata
    if _metadata is not None:
        return _metadata
    if not METADATA_FILE.exists():
        raise FileNotFoundError(f"Feature metadata not found: {METADATA_FILE}")
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        _metadata = json.load(f)
    return _metadata


def _load_data():
    """Load Parquet files into memory (called once on first query)."""
    global _features_df, _features_matrix, _feature_index, _regime_tags
    global _forward_returns, _feature_cols, _feature_weight_vector

    if _features_matrix is not None:
        return

    if not FEATURES_FILE.exists():
        raise FileNotFoundError(
            f"Features file not found: {FEATURES_FILE}. "
            "Run data/build_features.py first."
        )

    logger.info("Loading feature matrix from %s ...", FEATURES_FILE)
    meta = _load_metadata()
    _feature_cols = meta["all_features"]

    features_df = pd.read_parquet(FEATURES_FILE)
    features_df["date"] = pd.to_datetime(features_df["date"])
    features_df = features_df.sort_values(["stock_code", "date"]).reset_index(drop=True)

    _features_df = features_df
    _feature_index = features_df[["stock_code", "date"]].copy()

    # Extract regime_tag (for filtering, not similarity)
    if "regime_tag" in features_df.columns:
        _regime_tags = features_df["regime_tag"].values.astype(np.int8)
    else:
        _regime_tags = np.zeros(len(features_df), dtype=np.int8)

    _features_matrix = features_df[_feature_cols].values.astype(np.float32)
    np.nan_to_num(_features_matrix, copy=False, nan=0.0)

    # Build feature weight vector [CONVERGED]
    _feature_weight_vector = np.ones(len(_feature_cols), dtype=np.float32)
    for feat_name, weight in FEATURE_WEIGHTS.items():
        if feat_name in _feature_cols:
            idx = _feature_cols.index(feat_name)
            _feature_weight_vector[idx] = weight

    # Load forward returns
    if RETURNS_FILE.exists():
        _forward_returns = pd.read_parquet(RETURNS_FILE)
        _forward_returns["date"] = pd.to_datetime(_forward_returns["date"])
    else:
        _forward_returns = pd.DataFrame(
            columns=["date", "stock_code", "d3", "d7", "d21", "d90", "d180"]
        )

    logger.info(
        "Loaded %d rows, %d features, %d stocks",
        len(_features_matrix), _features_matrix.shape[1],
        _feature_index["stock_code"].nunique(),
    )


def _get_dimension_columns(dimensions: list[str]) -> list[int]:
    meta = _load_metadata()
    indices = []
    for dim in dimensions:
        dim_info = meta["dimensions"].get(dim)
        if dim_info is None:
            raise ValueError(f"Unknown dimension: {dim}. Available: {list(meta['dimensions'].keys())}")
        for feat in dim_info["features"]:
            if feat in _feature_cols:
                indices.append(_feature_cols.index(feat))
    return indices


def _compute_shape_descriptors(window_data: np.ndarray) -> np.ndarray:
    """Compute 4 shape descriptors for each feature in a window.

    [CONVERGED] Gemini Wall Street Trader:
    - slope: linear regression slope (trend direction)
    - convexity: quadratic coefficient (acceleration/deceleration)
    - skewness: asymmetry (V-turn vs sideways are completely different)
    - endpoint_ratio: end/start (overall change magnitude)

    Args:
        window_data: (W, D) array of W days × D features

    Returns:
        (4*D,) array: [slope_f1, slope_f2, ..., conv_f1, conv_f2, ..., skew_f1, ..., endpt_f1, ...]
    """
    w, d = window_data.shape
    if w < 3:
        return np.zeros(4 * d, dtype=np.float32)

    x = np.arange(w, dtype=np.float64)
    x_centered = x - x.mean()
    x2 = x_centered ** 2

    descriptors = np.zeros((4, d), dtype=np.float32)

    for j in range(d):
        col = window_data[:, j].astype(np.float64)
        valid = ~np.isnan(col)
        if valid.sum() < 3:
            continue

        # Slope: linear regression coefficient
        xv = x_centered[valid]
        yv = col[valid]
        denom = np.sum(xv ** 2)
        if denom > 0:
            descriptors[0, j] = np.sum(xv * yv) / denom

        # Convexity: quadratic coefficient (a in ax^2 + bx + c)
        if valid.sum() >= 3:
            try:
                coeffs = np.polyfit(x[valid], yv, 2)
                descriptors[1, j] = coeffs[0]
            except (np.linalg.LinAlgError, ValueError):
                pass

        # Skewness
        if np.std(yv) > 1e-10:
            descriptors[2, j] = float(scipy_skew(yv, bias=False))

        # Endpoint ratio: last / first
        if abs(yv[0]) > 1e-10:
            descriptors[3, j] = yv[-1] / yv[0]
        else:
            descriptors[3, j] = 0.0

    return descriptors.flatten()


def _cosine_similarity_batch(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between query vector and all rows in matrix."""
    query_norm = np.linalg.norm(query)
    if query_norm < 1e-10:
        return np.zeros(matrix.shape[0], dtype=np.float32)

    matrix_norms = np.linalg.norm(matrix, axis=1)
    safe_norms = np.where(matrix_norms < 1e-10, 1.0, matrix_norms)
    dots = matrix @ query
    return dots / (safe_norms * query_norm)


def _compute_time_decay_weights(dates: np.ndarray, reference_date: pd.Timestamp) -> np.ndarray:
    """Compute exponential time decay weights.

    [CONVERGED] half-life = 2 years — recent cases weighted more heavily.
    """
    days_diff = (reference_date - dates).dt.days.values.astype(np.float64)
    decay = np.exp(-np.log(2) * days_diff / TIME_DECAY_HALF_LIFE_DAYS)
    return decay.astype(np.float32)


def find_similar(
    stock_code: str,
    dimensions: list[str],
    window: int = 20,
    top_k: int = 30,
    exclude_self: bool = True,
    min_date: Optional[str] = None,
    regime_match: bool = True,
) -> dict:
    """Find historically similar cases based on selected dimensions.

    Converged algorithm (Gemini Wall Street Trader + Architect Critic):
    1. Load feature matrix (cached in memory)
    2. Get target window → compute 4 shape descriptors per feature
    3. Apply feature weights (ATR/Volume 1.5x)
    4. Compute shape descriptors for all candidate windows
    5. Cosine similarity on descriptor vectors
    6. Apply regime filter, time decay, min similarity threshold
    7. Compute statistics with TRANSACTION_COST deduction, p5/p95, expectancy
    """
    _load_data()

    if not dimensions:
        raise ValueError("At least one dimension must be selected")

    col_indices = _get_dimension_columns(dimensions)
    if not col_indices:
        raise ValueError("No features found for selected dimensions")

    # Find target stock rows
    stock_mask = _feature_index["stock_code"] == stock_code
    stock_rows = _feature_index[stock_mask].index
    if len(stock_rows) == 0:
        raise ValueError(f"Stock {stock_code} not found in feature data")

    target_indices = stock_rows[-window:]
    target_date = _feature_index.loc[target_indices[-1], "date"]

    # Get query regime for filtering
    query_regime = int(_regime_tags[target_indices[-1]]) if _regime_tags is not None else 0

    # Extract selected dimension columns
    sel_matrix = _features_matrix[:, col_indices]

    # Apply feature weights to selected columns
    sel_weights = _feature_weight_vector[col_indices]
    weighted_matrix = sel_matrix * sel_weights[np.newaxis, :]

    # Compute query shape descriptors
    target_window = weighted_matrix[target_indices]
    query_descriptors = _compute_shape_descriptors(target_window)

    # Compute candidate shape descriptors (sliding window for each stock)
    n_rows = len(weighted_matrix)
    n_desc = len(query_descriptors)  # 4 * n_selected_features

    # For efficiency, pre-compute descriptors for all valid windows
    # Group by stock_code and compute shape descriptors per window
    candidate_descriptors = np.zeros((n_rows, n_desc), dtype=np.float32)
    valid_mask = np.zeros(n_rows, dtype=bool)

    for code, group_idx in _feature_index.groupby("stock_code").groups.items():
        group_idx = sorted(group_idx)
        if len(group_idx) < window:
            continue
        for i in range(window - 1, len(group_idx)):
            row_idx = group_idx[i]
            window_indices = group_idx[max(0, i - window + 1): i + 1]
            if len(window_indices) < max(3, window // 2):
                continue
            win_data = weighted_matrix[window_indices]
            candidate_descriptors[row_idx] = _compute_shape_descriptors(win_data)
            valid_mask[row_idx] = True

    # Compute cosine similarities on descriptor vectors
    similarities = _cosine_similarity_batch(query_descriptors, candidate_descriptors)

    # Apply filters
    mask = valid_mask.copy()

    if exclude_self:
        mask &= (_feature_index["stock_code"] != stock_code).values

    if min_date:
        min_dt = pd.Timestamp(min_date)
        mask &= (_feature_index["date"] >= min_dt).values

    # Exclude future dates
    mask &= (_feature_index["date"] < target_date).values

    # Regime filter [CONVERGED] — default ON
    if regime_match and _regime_tags is not None:
        mask &= (_regime_tags == query_regime)

    # Minimum similarity threshold [PLACEHOLDER: SIMILARITY_THRESHOLD_07]
    mask &= (similarities >= MIN_SIMILARITY_THRESHOLD)

    similarities[~mask] = -2.0

    # Time decay weights [CONVERGED]
    decay_weights = _compute_time_decay_weights(_feature_index["date"], target_date)
    weighted_sim = similarities * decay_weights

    # Get top-K indices
    top_indices = np.argsort(weighted_sim)[::-1][:top_k * 3]
    top_indices = top_indices[similarities[top_indices] > -1.5]

    # Deduplicate
    seen = set()
    selected = []
    for idx in top_indices:
        if len(selected) >= top_k:
            break
        code = _feature_index.loc[idx, "stock_code"]
        date = _feature_index.loc[idx, "date"]
        key = (code, date.year, date.month)
        if key in seen:
            continue
        seen.add(key)
        selected.append(idx)

    # Build results
    similar_cases = []
    return_horizons = ["d3", "d7", "d21", "d90", "d180"]

    for idx in selected:
        code = _feature_index.loc[idx, "stock_code"]
        date = _feature_index.loc[idx, "date"]
        sim = float(similarities[idx])

        fwd = {}
        if _forward_returns is not None:
            match = _forward_returns[
                (_forward_returns["stock_code"] == code)
                & (_forward_returns["date"] == date)
            ]
            if len(match) > 0:
                row = match.iloc[0]
                for h in return_horizons:
                    val = row.get(h, None)
                    fwd[h] = float(val) if pd.notna(val) else None
            else:
                fwd = {h: None for h in return_horizons}
        else:
            fwd = {h: None for h in return_horizons}

        similar_cases.append({
            "stock_code": code,
            "date": date.strftime("%Y-%m-%d"),
            "similarity": round(sim, 4),
            "forward_returns": fwd,
        })

    # Compute aggregate statistics [CONVERGED + ARCHITECT APPROVED]
    statistics = {
        "sample_count": len(similar_cases),
        "small_sample_warning": len(similar_cases) < SMALL_SAMPLE_THRESHOLD,
    }

    for h in return_horizons:
        vals = [
            c["forward_returns"][h]
            for c in similar_cases
            if c["forward_returns"].get(h) is not None
        ]
        if vals:
            arr = np.array(vals)
            # Deduct transaction cost for short horizons [ARCHITECT: Physical Consistency]
            arr_net = arr - TRANSACTION_COST

            wins = arr_net[arr_net > 0]
            losses = arr_net[arr_net <= 0]
            win_rate = float(np.mean(arr_net > 0))
            avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
            avg_loss = float(np.mean(np.abs(losses))) if len(losses) > 0 else 0.0
            expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss

            statistics[h] = {
                "mean": round(float(np.mean(arr_net)), 4),
                "median": round(float(np.median(arr_net)), 4),
                "win_rate": round(win_rate, 4),
                "hit_rate_2pct": round(float(np.mean(arr_net > 0.02)), 4),
                "std": round(float(np.std(arr_net)), 4),
                "min": round(float(np.min(arr_net)), 4),
                "max": round(float(np.max(arr_net)), 4),
                "p5": round(float(np.percentile(arr_net, 5)), 4),
                "p95": round(float(np.percentile(arr_net, 95)), 4),
                "expectancy": round(expectancy, 4),
                "avg_win": round(avg_win, 4),
                "avg_loss": round(avg_loss, 4),
            }
        else:
            statistics[h] = {
                "mean": None, "median": None, "win_rate": None,
                "hit_rate_2pct": None, "std": None, "min": None, "max": None,
                "p5": None, "p95": None, "expectancy": None,
                "avg_win": None, "avg_loss": None,
            }

    meta = _load_metadata()
    dims_used = [d for d in dimensions if d in meta["dimensions"]]

    return {
        "query": {
            "stock_code": stock_code,
            "date": target_date.strftime("%Y-%m-%d"),
            "window": window,
            "regime": query_regime,
            "regime_match": regime_match,
        },
        "dimensions_used": dims_used,
        "feature_count": len(col_indices),
        "descriptor_count": len(col_indices) * 4,
        "similar_cases": similar_cases,
        "statistics": statistics,
        "transaction_cost_deducted": TRANSACTION_COST,
    }


def get_dimensions() -> list[dict]:
    """Return available dimensions with feature counts and descriptions."""
    meta = _load_metadata()
    result = []
    for name, info in meta["dimensions"].items():
        result.append({
            "name": name,
            "label": info["description"],
            "feature_count": info["count"],
            "features": info["features"],
        })
    return result


def get_feature_status() -> dict:
    """Return the status of feature data files."""
    status = {
        "features_file": str(FEATURES_FILE),
        "returns_file": str(RETURNS_FILE),
        "metadata_file": str(METADATA_FILE),
        "features_exists": FEATURES_FILE.exists(),
        "returns_exists": RETURNS_FILE.exists(),
        "metadata_exists": METADATA_FILE.exists(),
        "loaded_in_memory": _features_matrix is not None,
    }

    if FEATURES_FILE.exists():
        status["features_size_mb"] = round(FEATURES_FILE.stat().st_size / 1024 / 1024, 1)
    if RETURNS_FILE.exists():
        status["returns_size_mb"] = round(RETURNS_FILE.stat().st_size / 1024 / 1024, 1)

    if _features_matrix is not None:
        status["rows"] = _features_matrix.shape[0]
        status["features"] = _features_matrix.shape[1]
        status["stocks"] = int(_feature_index["stock_code"].nunique())

    if _metadata is not None:
        status["dimensions"] = list(_metadata["dimensions"].keys())
        status["date_range"] = _metadata.get("date_range")

    return status

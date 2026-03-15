"""Multi-Window Multi-Dimension Similarity Engine.

NEW module — independent from cluster_search.py.
Supports multi-window parquet files (features_wN.parquet) with fallback
to features_all.parquet (treated as window=1, point-in-time).

Architecture:
  - 5 user-facing dimensions mapped from 6 internal dimensions
  - Vectorized cosine similarity (~50-100ms for 1.6M rows)
  - On-the-fly forward returns from pit_close_matrix.parquet
  - LRU cache (max 2 windows in memory)

All parameters marked [PLACEHOLDER] pending validation.
"""

import json
import logging
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# --- Paths ---
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
FEATURES_DIR = _PROJECT_ROOT / "data" / "pattern_data" / "features"
METADATA_FILE = FEATURES_DIR / "feature_metadata.json"
CLOSE_MATRIX_FILE = _PROJECT_ROOT / "data" / "pit_close_matrix.parquet"

# --- Constants [PLACEHOLDER] ---
MAX_CACHED_WINDOWS = 2  # [PLACEHOLDER] LRU cache size
DEFAULT_TOP_K = 30  # [PLACEHOLDER] default number of similar cases
VALID_WINDOWS = (7, 14, 30, 90, 180)  # [PLACEHOLDER] supported window sizes
FORWARD_HORIZONS = [1, 3, 7, 30, 180]  # [PLACEHOLDER] trading days
HORIZON_LABELS = ["d1", "d3", "d7", "d30", "d180"]

# 5 user-facing dimensions → 6 internal dimensions
# "institutional" merges internal "institutional" + "brokerage"
DIMENSION_GROUPS = {
    "technical": ["technical"],  # 20 features
    "institutional": ["institutional", "brokerage"],  # 11 + 14 = 25 features
    "fundamental": ["fundamental"],  # 8 features
    "news": ["attention"],  # 7 features
    "industry": ["industry"],  # 5 features
}

ALL_USER_DIMENSIONS = list(DIMENSION_GROUPS.keys())


# --- Data Classes ---


@dataclass
class WindowData:
    """Feature matrix for a single time window."""

    matrix: np.ndarray  # (N, 65) float32
    stock_codes: np.ndarray  # (N,) strings
    dates: np.ndarray  # (N,) datetime64
    regime_tags: np.ndarray  # (N,) int8
    code_date_to_idx: dict  # (stock_code, date) -> row_idx
    feature_cols: list  # ordered feature column names
    norms: np.ndarray  # (N,) precomputed L2 norms


@dataclass
class SimilarCase:
    """A single similar case found by the engine."""

    stock_code: str
    date: str  # ISO format string
    similarity: float
    dimension_similarities: dict  # dim_name -> float
    forward_returns: dict  # "d1", "d3", ... -> float | None


@dataclass
class SimilarityResult:
    """Full result of a similarity search."""

    query: dict  # stock_code, date, window, dimensions, feature_count
    cases: list  # list[SimilarCase]
    statistics: dict  # per-horizon stats

    def to_dict(self) -> dict:
        """JSON-serializable dict."""
        return {
            "query": self.query,
            "cases": [
                {
                    "stock_code": c.stock_code,
                    "date": c.date,
                    "similarity": round(c.similarity, 6),
                    "dimension_similarities": {
                        k: round(v, 6) for k, v in c.dimension_similarities.items()
                    },
                    "forward_returns": {
                        k: round(v, 6) if v is not None else None
                        for k, v in c.forward_returns.items()
                    },
                }
                for c in self.cases
            ],
            "statistics": self.statistics,
        }


# --- LRU Cache ---
# OrderedDict-based: most recently used at the end.
_window_cache: OrderedDict = OrderedDict()  # window_int -> WindowData

# Close matrix cache (loaded once)
_close_matrix: Optional[pd.DataFrame] = None
_metadata_cache: Optional[dict] = None


def _load_metadata() -> dict:
    """Load and cache feature_metadata.json."""
    global _metadata_cache
    if _metadata_cache is not None:
        return _metadata_cache
    if not METADATA_FILE.exists():
        raise FileNotFoundError(f"Feature metadata not found: {METADATA_FILE}")
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        _metadata_cache = json.load(f)
    return _metadata_cache


def _load_close_matrix() -> pd.DataFrame:
    """Load and cache pit_close_matrix.parquet."""
    global _close_matrix
    if _close_matrix is not None:
        return _close_matrix
    if not CLOSE_MATRIX_FILE.exists():
        raise FileNotFoundError(f"Close matrix not found: {CLOSE_MATRIX_FILE}")
    _close_matrix = pd.read_parquet(CLOSE_MATRIX_FILE)
    _close_matrix.index = pd.to_datetime(_close_matrix.index)
    logger.info(
        "Close matrix loaded: %d dates x %d stocks",
        len(_close_matrix),
        len(_close_matrix.columns),
    )
    return _close_matrix


def load_window(window: int) -> WindowData:
    """Load feature parquet for a given window. LRU cache max 2 windows.

    If features_wN.parquet exists, use it.
    Otherwise, fallback to features_all.parquet (point-in-time).
    """
    # Check cache — move to end if found (mark as recently used)
    if window in _window_cache:
        _window_cache.move_to_end(window)
        return _window_cache[window]

    # Evict LRU if cache is full
    while len(_window_cache) >= MAX_CACHED_WINDOWS:
        evicted_key, _ = _window_cache.popitem(last=False)
        logger.info("LRU evicted window=%d", evicted_key)

    # Try window-specific file first
    window_file = FEATURES_DIR / f"features_w{window}.parquet"
    if window_file.exists():
        parquet_path = window_file
        logger.info("Loading window-specific file: %s", window_file.name)
    else:
        parquet_path = FEATURES_DIR / "features_all.parquet"
        if not parquet_path.exists():
            raise FileNotFoundError(
                f"No feature file found: tried {window_file} and {parquet_path}"
            )
        logger.info(
            "Window file %s not found, falling back to features_all.parquet",
            window_file.name,
        )

    meta = _load_metadata()
    feature_cols = meta["all_features"]

    t0 = time.time()
    df = pd.read_parquet(parquet_path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["stock_code", "date"]).reset_index(drop=True)

    # Build matrix
    matrix = df[feature_cols].values.astype(np.float32)
    np.nan_to_num(matrix, copy=False, nan=0.0)

    stock_codes = df["stock_code"].values
    dates = df["date"].values
    regime_tags = (
        df["regime_tag"].values.astype(np.int8)
        if "regime_tag" in df.columns
        else np.zeros(len(df), dtype=np.int8)
    )

    # Build O(1) lookup
    code_date_to_idx = {}
    for i in range(len(df)):
        code_date_to_idx[(stock_codes[i], dates[i])] = i

    # Precompute norms
    norms = np.linalg.norm(matrix, axis=1).astype(np.float32)
    norms[norms < 1e-10] = 1.0

    wd = WindowData(
        matrix=matrix,
        stock_codes=stock_codes,
        dates=dates,
        regime_tags=regime_tags,
        code_date_to_idx=code_date_to_idx,
        feature_cols=feature_cols,
        norms=norms,
    )

    _window_cache[window] = wd
    elapsed = time.time() - t0
    logger.info(
        "Window=%d loaded: %d rows, %d features, %.1fs",
        window,
        matrix.shape[0],
        matrix.shape[1],
        elapsed,
    )
    return wd


def _get_dimension_mask(
    dimensions: list, all_features: list, metadata: dict
) -> np.ndarray:
    """Boolean mask for selected user-facing dimensions' features.

    Args:
        dimensions: list of user-facing dimension names (keys of DIMENSION_GROUPS)
        all_features: ordered list of all feature column names
        metadata: the loaded feature_metadata.json dict

    Returns:
        np.ndarray of bool, shape (len(all_features),)
    """
    # Validate dimensions
    for d in dimensions:
        if d not in DIMENSION_GROUPS:
            raise ValueError(
                f"Unknown dimension: '{d}'. Valid: {list(DIMENSION_GROUPS.keys())}"
            )

    # Collect internal dimension names
    internal_dims = set()
    for d in dimensions:
        internal_dims.update(DIMENSION_GROUPS[d])

    # Build mask
    selected_features = set()
    for dim_name in internal_dims:
        if dim_name in metadata["dimensions"]:
            selected_features.update(metadata["dimensions"][dim_name]["features"])

    mask = np.array([f in selected_features for f in all_features], dtype=bool)
    return mask


def _compute_forward_returns(
    stock_code: str,
    match_date,
    close_matrix: pd.DataFrame,
    horizons: list = None,
) -> dict:
    """Compute forward returns from pit_close_matrix.parquet.

    Uses trading days (the actual index of close_matrix), not calendar days.

    Returns:
        dict like {"d1": 0.012, "d3": -0.005, "d7": None, ...}
    """
    if horizons is None:
        horizons = FORWARD_HORIZONS

    result = {}
    match_ts = pd.Timestamp(match_date)

    if stock_code not in close_matrix.columns:
        for h, label in zip(horizons, HORIZON_LABELS):
            result[label] = None
        return result

    prices = close_matrix[stock_code]

    # Find the position of match_date in the index
    if match_ts not in close_matrix.index:
        # Try nearest date within 3 trading days
        idx_pos = close_matrix.index.searchsorted(match_ts)
        if idx_pos >= len(close_matrix.index):
            for h, label in zip(horizons, HORIZON_LABELS):
                result[label] = None
            return result
        actual_date = close_matrix.index[idx_pos]
        if abs((actual_date - match_ts).days) > 5:
            for h, label in zip(horizons, HORIZON_LABELS):
                result[label] = None
            return result
        match_ts = actual_date

    idx_pos = close_matrix.index.get_loc(match_ts)
    base_price = prices.iloc[idx_pos]

    if pd.isna(base_price) or base_price <= 0:
        for h, label in zip(horizons, HORIZON_LABELS):
            result[label] = None
        return result

    for h, label in zip(horizons, HORIZON_LABELS):
        future_pos = idx_pos + h
        if future_pos < len(prices):
            future_price = prices.iloc[future_pos]
            if pd.notna(future_price) and future_price > 0:
                result[label] = float((future_price / base_price) - 1.0)
            else:
                result[label] = None
        else:
            result[label] = None

    return result


def _compute_statistics(cases: list) -> dict:
    """Per-horizon statistics from a list of SimilarCase.

    Returns dict: {horizon_label: {win_rate, mean, median, std, p5, p95, avg_win, avg_loss, count}}
    """
    stats = {}
    for label in HORIZON_LABELS:
        values = [
            c.forward_returns[label]
            for c in cases
            if c.forward_returns.get(label) is not None
        ]
        if not values:
            stats[label] = {"count": 0}
            continue

        arr = np.array(values, dtype=np.float64)
        wins = arr[arr > 0]
        losses = arr[arr <= 0]

        stats[label] = {
            "count": len(arr),
            "win_rate": round(float(len(wins) / len(arr)), 4),
            "mean": round(float(np.mean(arr)), 6),
            "median": round(float(np.median(arr)), 6),
            "std": round(float(np.std(arr)), 6),
            "p5": round(float(np.percentile(arr, 5)), 6),
            "p95": round(float(np.percentile(arr, 95)), 6),
            "avg_win": round(float(np.mean(wins)), 6) if len(wins) > 0 else 0.0,
            "avg_loss": round(float(np.mean(losses)), 6) if len(losses) > 0 else 0.0,
        }
    return stats


def _compute_per_dimension_similarity(
    query_vec: np.ndarray,
    candidate_vec: np.ndarray,
    feature_cols: list,
    metadata: dict,
    selected_dimensions: list,
) -> dict:
    """Cosine similarity breakdown per user-facing dimension."""
    result = {}
    for dim_name in selected_dimensions:
        mask = _get_dimension_mask([dim_name], feature_cols, metadata)
        q = query_vec[mask]
        c = candidate_vec[mask]
        q_norm = np.linalg.norm(q)
        c_norm = np.linalg.norm(c)
        if q_norm < 1e-10 or c_norm < 1e-10:
            result[dim_name] = 0.0
        else:
            result[dim_name] = float(np.dot(q, c) / (q_norm * c_norm))
    return result


def search_similar(
    stock_code: str,
    window: int = 30,
    dimensions: list = None,
    query_date: str = None,
    top_k: int = DEFAULT_TOP_K,
    exclude_self: bool = True,
) -> SimilarityResult:
    """Main entry point. Cosine similarity on selected dimension features.

    Args:
        stock_code: Target stock code (e.g. "2330")
        window: Window size (7|14|30|90|180). Falls back if file doesn't exist.
        dimensions: List of user-facing dimension names. Default: all 5.
        query_date: ISO date string. Default: latest available date for the stock.
        top_k: Number of similar cases to return.
        exclude_self: If True, exclude the query stock+date from results.

    Returns:
        SimilarityResult with cases sorted by similarity descending.
    """
    if dimensions is None:
        dimensions = ALL_USER_DIMENSIONS

    # Load data
    wd = load_window(window)
    meta = _load_metadata()

    # Find query row
    if query_date is not None:
        query_ts = pd.Timestamp(query_date)
        key = (stock_code, query_ts)
        if key not in wd.code_date_to_idx:
            # Try to find nearest date for this stock
            stock_mask = wd.stock_codes == stock_code
            if not np.any(stock_mask):
                raise ValueError(
                    f"Stock '{stock_code}' not found in window={window} data"
                )
            stock_dates = wd.dates[stock_mask]
            # Find closest date
            diffs = np.abs(stock_dates - query_ts)
            nearest_idx = np.argmin(diffs)
            nearest_date = stock_dates[nearest_idx]
            if abs((pd.Timestamp(nearest_date) - query_ts).days) > 5:
                raise ValueError(
                    f"Date '{query_date}' not found for stock '{stock_code}' "
                    f"(nearest: {nearest_date})"
                )
            query_ts = nearest_date
            key = (stock_code, query_ts)
    else:
        # Use latest date for this stock
        stock_mask = wd.stock_codes == stock_code
        if not np.any(stock_mask):
            raise ValueError(
                f"Stock '{stock_code}' not found in window={window} data"
            )
        stock_dates = wd.dates[stock_mask]
        query_ts = stock_dates.max()
        key = (stock_code, query_ts)

    query_idx = wd.code_date_to_idx[key]
    query_date_str = str(pd.Timestamp(query_ts).date())

    # Build dimension mask
    dim_mask = _get_dimension_mask(dimensions, wd.feature_cols, meta)
    feature_count = int(dim_mask.sum())

    # Vectorized cosine similarity
    query_vec = wd.matrix[query_idx]
    masked_query = query_vec[dim_mask]
    q_norm = np.linalg.norm(masked_query)

    if q_norm < 1e-10:
        # Query vector is all zeros in selected dimensions
        return SimilarityResult(
            query={
                "stock_code": stock_code,
                "date": query_date_str,
                "window": window,
                "dimensions": dimensions,
                "feature_count": feature_count,
            },
            cases=[],
            statistics={},
        )

    # Slice masked columns from full matrix
    masked_matrix = wd.matrix[:, dim_mask]  # (N, D_selected)

    # Compute all cosine similarities at once
    # dot products: (N,) = masked_matrix @ masked_query
    dots = masked_matrix @ masked_query  # (N,)
    candidate_norms = np.linalg.norm(masked_matrix, axis=1)
    candidate_norms[candidate_norms < 1e-10] = 1.0
    similarities = dots / (candidate_norms * q_norm)

    # Clip to [0, 1] (negative cosine = dissimilar, we clamp)
    np.clip(similarities, 0.0, 1.0, out=similarities)

    # Exclude self if needed
    if exclude_self:
        similarities[query_idx] = -1.0

    # Get top-k indices
    if top_k >= len(similarities):
        top_indices = np.argsort(similarities)[::-1][:top_k]
    else:
        # Partial sort for efficiency
        top_indices = np.argpartition(similarities, -top_k)[-top_k:]
        top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]

    # Filter out zero/negative similarity
    top_indices = top_indices[similarities[top_indices] > 0.0]

    # Load close matrix for forward returns
    try:
        cm = _load_close_matrix()
    except FileNotFoundError:
        cm = None

    # Build SimilarCase list
    cases = []
    for idx in top_indices:
        case_code = str(wd.stock_codes[idx])
        case_date_ts = wd.dates[idx]
        case_date_str = str(pd.Timestamp(case_date_ts).date())
        sim = float(similarities[idx])

        # Per-dimension similarity breakdown
        dim_sims = _compute_per_dimension_similarity(
            query_vec, wd.matrix[idx], wd.feature_cols, meta, dimensions
        )

        # Forward returns
        if cm is not None:
            fwd = _compute_forward_returns(case_code, case_date_ts, cm)
        else:
            fwd = {label: None for label in HORIZON_LABELS}

        cases.append(
            SimilarCase(
                stock_code=case_code,
                date=case_date_str,
                similarity=sim,
                dimension_similarities=dim_sims,
                forward_returns=fwd,
            )
        )

    # Statistics
    statistics = _compute_statistics(cases)

    return SimilarityResult(
        query={
            "stock_code": stock_code,
            "date": query_date_str,
            "window": window,
            "dimensions": dimensions,
            "feature_count": feature_count,
        },
        cases=cases,
        statistics=statistics,
    )


def get_engine_status() -> dict:
    """Return engine status: loaded windows, dimensions, memory usage."""
    meta = _load_metadata() if METADATA_FILE.exists() else {}
    loaded = {}
    total_memory = 0.0

    for w, wd in _window_cache.items():
        mem_mb = wd.matrix.nbytes / (1024 * 1024)
        total_memory += mem_mb
        loaded[w] = {
            "rows": wd.matrix.shape[0],
            "features": wd.matrix.shape[1],
            "stocks": len(set(wd.stock_codes.tolist())),
            "memory_mb": round(mem_mb, 1),
        }

    return {
        "loaded_windows": loaded,
        "max_cached_windows": MAX_CACHED_WINDOWS,
        "dimensions": ALL_USER_DIMENSIONS,
        "dimension_groups": {
            k: {"internal": v, "feature_count": sum(
                meta.get("dimensions", {}).get(d, {}).get("count", 0) for d in v
            )}
            for k, v in DIMENSION_GROUPS.items()
        },
        "stock_count": meta.get("stock_count", 0),
        "total_features": meta.get("total_features", 0),
        "memory_mb": round(total_memory, 1),
        "close_matrix_loaded": _close_matrix is not None,
    }

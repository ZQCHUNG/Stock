"""多維度相似股分群 — 雙軌引擎 (Facts vs Opinion)

R88.2 CONVERGED (Gemini Wall Street Trader + Architect Critic + Joe):
  Block 1 (Raw/Facts): User-selected dimensions, equal-weight cosine similarity
  Block 2 (Augmented/Opinion): Dynamic feature selection, regime-aware, weighted
  Spaghetti Chart: Forward price paths for visual comparison
  Divergence Warning: When D21 win rate differs >15% between blocks [ARCHITECT]

R88.3 APPROVED (Joe Feedback + Wall Street + Architect):
  Feedback 1: Block 1 gets dimension Checkable Tags (user controls which dims)
  Feedback 2: Per-dimension similarity breakdown ("Gene Map" / Attribution Analysis)
  Trap Guard: Unselected dims with <40% similarity show [!] warning

R88.5 CONVERGED (Wall Street Trader — 6-year stress test approved):
  Sniper Confidence Tiering: Sim>=88%+Fund>=50% = Sniper, Fund>=40% = Tactical
  [VERIFIED] rho=0.2553 (p<0.000001) across 2020-2025
  [VERIFIED] PF=1.65 (n=45) at Sniper tier, 6-year cross-environment
  [EXPERIMENTAL] n=45 < 50 — not yet [VERIFIED], pending more data

Protocol v3 labels:
  [VERIFIED] TRANSACTION_COST = 0.00785
  [CONVERGED] Dual-block architecture, time decay, regime filter
  [CONVERGED] Sniper Sim >= 88%, Fund >= 50% (Trader verdict R88.5)
  [CONVERGED] Tactical Fund >= 40% (Trader verdict R88.5)
  [HEURISTIC: SIMILARITY_DRIVER_V1] Text summary generation
  [PLACEHOLDER] MIN_SIMILARITY_THRESHOLD = 0.5, DIVERGENCE_THRESHOLD = 0.15
"""

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# --- Constants ---
TRANSACTION_COST = 0.00785  # [VERIFIED] 0.1425%×2 + 0.3% + 0.1%×2
MIN_SIMILARITY_THRESHOLD = 0.5  # [PLACEHOLDER: lowered from 0.7 for raw pipeline]
TIME_DECAY_HALF_LIFE_DAYS = 365 * 2  # [CONVERGED] 2 years
SMALL_SAMPLE_THRESHOLD = 30  # [ARCHITECT INSTRUCTION]
DIVERGENCE_THRESHOLD = 0.15  # [PLACEHOLDER] 15% win rate difference triggers warning
SPAGHETTI_DAYS = 90  # Forward price path length for chart

# R88.5 Sniper Confidence Tiering [CONVERGED — Wall Street Trader 2026-02-18]
# Validated: 6-year stress test (2020-2025), 55 stocks, 2970 records
# rho=0.2553 (p<0.000001), PF=1.65 at Sniper tier (n=45)
SNIPER_SIM_THRESHOLD = 0.88  # [CONVERGED] Mean similarity >= 88%
SNIPER_FUND_THRESHOLD = 0.50  # [CONVERGED] Fundamental dim similarity >= 50%
TACTICAL_FUND_THRESHOLD = 0.40  # [CONVERGED] Tactical tier >= 40%
SNIPER_LABEL = "[EXPERIMENTAL]"  # [CONVERGED] n=45 < 50, pending more data

# R88.7 Phase 5: Sparse features that need daily data accumulation
# [CONVERGED — Wall Street Trader 2026-02-18]
# These features are all-zero under monthly-only data. Zero-weight them
# in cosine similarity to avoid diluting the effective features.
WARMUP_FEATURES = frozenset([
    "branch_overlap_count",      # Needs cross-stock daily data
    "daily_net_buy_volatility",  # Needs multiple daily data points
    "broker_price_divergence",   # Needs intra-period OHLC+ATR
    "broker_winner_momentum",    # Only 16 winners, extremely sparse
])

# Augmented pipeline: feature weighting [CONVERGED with Gemini]
AUGMENTED_FEATURE_WEIGHTS = {
    "atr_pct": 1.5,
    "vol_ratio_20": 1.5,
    "rsi_14": 1.3,
    "inst_total_net": 1.3,
    "inst_5d_sum": 1.2,
}

# Dynamic feature selection by regime [CONVERGED]
# In each regime, these dimensions get boosted
REGIME_DIMENSION_BOOST = {
    1: {"technical": 1.5, "institutional": 1.3},  # Bull: tech + flow
    0: {"fundamental": 1.5, "institutional": 1.3},  # Sideways: fundamentals + flow
    -1: {"technical": 1.3, "fundamental": 1.5},  # Bear: tech + fundamentals
}

# --- Data paths ---
FEATURES_DIR = Path(__file__).resolve().parent.parent / "data" / "pattern_data" / "features"
FEATURES_FILE = FEATURES_DIR / "features_all.parquet"
RETURNS_FILE = FEATURES_DIR / "forward_returns.parquet"
METADATA_FILE = FEATURES_DIR / "feature_metadata.json"
PRICE_CACHE_FILE = FEATURES_DIR / "price_cache.parquet"

# --- In-memory cache ---
_features_matrix: Optional[np.ndarray] = None
_feature_index: Optional[pd.DataFrame] = None
_regime_tags: Optional[np.ndarray] = None
_forward_returns: Optional[pd.DataFrame] = None
_fwd_returns_index: Optional[dict] = None  # (stock_code, date) → row index
_metadata: Optional[dict] = None
_feature_cols: Optional[list] = None
_price_cache: Optional[pd.DataFrame] = None
_price_grouped: Optional[dict] = None  # stock_code → DataFrame subset
_norms: Optional[np.ndarray] = None  # Pre-computed row norms
_dim_col_indices: Optional[dict] = None  # dimension name → column indices
_warmup_mask: Optional[np.ndarray] = None  # True = active feature, False = warming up

# Dimension display labels (Chinese)
DIMENSION_LABELS = {
    "technical": "技術面",
    "institutional": "籌碼面",
    "brokerage": "分點面",  # R88.6 [CONVERGED] Split from institutional
    "industry": "產業面",
    "fundamental": "基本面",
    "attention": "關注度",
}

# Similarity gene map thresholds [ARCHITECT: color coding]
SIM_HIGH = 0.90   # Deep green
SIM_MID = 0.70    # Light green
SIM_LOW = 0.50    # Yellow
SIM_DANGER = 0.40  # Red — [ARCHITECT] unselected dim below this triggers [!] warning


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
    """Load Parquet files into memory (called once, then cached)."""
    global _features_matrix, _feature_index, _regime_tags
    global _forward_returns, _fwd_returns_index, _feature_cols
    global _price_cache, _price_grouped, _norms

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

    # Load features — use float16 for memory [CONVERGED: 234MB → 117MB]
    features_df = pd.read_parquet(FEATURES_FILE)
    features_df["date"] = pd.to_datetime(features_df["date"])
    features_df = features_df.sort_values(["stock_code", "date"]).reset_index(drop=True)

    _feature_index = features_df[["stock_code", "date"]].copy()

    if "regime_tag" in features_df.columns:
        _regime_tags = features_df["regime_tag"].values.astype(np.int8)
    else:
        _regime_tags = np.zeros(len(features_df), dtype=np.int8)

    # float32 for computation (float16 loses too much in matrix multiply)
    _features_matrix = features_df[_feature_cols].values.astype(np.float32)
    np.nan_to_num(_features_matrix, copy=False, nan=0.0)

    # Pre-compute row norms for fast cosine similarity
    _norms = np.linalg.norm(_features_matrix, axis=1).astype(np.float32)
    _norms[_norms < 1e-10] = 1.0  # Avoid division by zero

    # Load forward returns + build O(1) lookup index
    if RETURNS_FILE.exists():
        _forward_returns = pd.read_parquet(RETURNS_FILE)
        _forward_returns["date"] = pd.to_datetime(_forward_returns["date"])
        # Build dict index: (stock_code, date) → row integer position
        _fwd_returns_index = {}
        for i, row in enumerate(_forward_returns.itertuples()):
            _fwd_returns_index[(row.stock_code, row.date)] = i
        logger.info("Forward returns index: %d entries", len(_fwd_returns_index))
    else:
        _forward_returns = pd.DataFrame(
            columns=["date", "stock_code", "d3", "d7", "d21", "d90", "d180"]
        )
        _fwd_returns_index = {}

    # Load price cache for Spaghetti Chart + pre-group by stock
    if PRICE_CACHE_FILE.exists():
        _price_cache = pd.read_parquet(PRICE_CACHE_FILE, columns=["stock_code", "date", "close"])
        _price_cache["date"] = pd.to_datetime(_price_cache["date"])
        _price_cache = _price_cache.sort_values(["stock_code", "date"]).reset_index(drop=True)
        # Pre-group: {stock_code → numpy arrays (dates, closes)}
        _price_grouped = {}
        for code, group in _price_cache.groupby("stock_code"):
            _price_grouped[code] = {
                "dates": group["date"].values,
                "closes": group["close"].values.astype(np.float64),
            }
        logger.info("Price cache grouped: %d stocks", len(_price_grouped))

    # R88.7: Build warmup mask — detect features with near-zero coverage
    global _warmup_mask
    _warmup_mask = np.ones(len(_feature_cols), dtype=bool)
    warmup_count = 0
    for feat_name in WARMUP_FEATURES:
        if feat_name in _feature_cols:
            idx = _feature_cols.index(feat_name)
            col_data = _features_matrix[:, idx]
            nonzero_pct = float(np.count_nonzero(col_data) / len(col_data))
            if nonzero_pct < 0.01:  # Less than 1% non-zero → warming up
                _warmup_mask[idx] = False
                warmup_count += 1
                logger.info("Warmup feature: %s (%.1f%% non-zero)", feat_name, nonzero_pct * 100)
    logger.info("Warmup features masked: %d of %d", warmup_count, len(WARMUP_FEATURES))

    logger.info(
        "Loaded %d rows, %d features (%d active), %d stocks",
        len(_features_matrix), _features_matrix.shape[1],
        int(np.sum(_warmup_mask)),
        _feature_index["stock_code"].nunique(),
    )


def _get_dimension_col_indices() -> dict:
    """Cache dimension → column index mapping for fast sub-vector slicing."""
    global _dim_col_indices
    if _dim_col_indices is not None:
        return _dim_col_indices

    meta = _load_metadata()
    _dim_col_indices = {}
    for dim_name, dim_info in meta["dimensions"].items():
        indices = []
        for feat in dim_info["features"]:
            if feat in _feature_cols:
                indices.append(_feature_cols.index(feat))
        _dim_col_indices[dim_name] = np.array(indices, dtype=np.int32)

    return _dim_col_indices


def _get_dimension_mask(dimensions: list[str]) -> np.ndarray:
    """Build a boolean mask for selected dimensions' feature columns."""
    dim_indices = _get_dimension_col_indices()
    mask = np.zeros(len(_feature_cols), dtype=bool)
    for dim in dimensions:
        if dim in dim_indices:
            mask[dim_indices[dim]] = True
    return mask


def _cosine_similarity_by_dimension(
    query_idx: int, case_idx: int
) -> dict[str, float]:
    """Compute per-dimension cosine similarity between query and a single case.

    Returns {technical: 0.95, institutional: 0.42, ...}
    Vectorized per dimension — no loops over features.
    """
    dim_indices = _get_dimension_col_indices()
    result = {}

    q_full = _features_matrix[query_idx]
    c_full = _features_matrix[case_idx]

    for dim_name, col_idx in dim_indices.items():
        if len(col_idx) == 0:
            result[dim_name] = 0.0
            continue

        q_sub = q_full[col_idx]
        c_sub = c_full[col_idx]

        q_norm = np.linalg.norm(q_sub)
        c_norm = np.linalg.norm(c_sub)

        if q_norm < 1e-10 or c_norm < 1e-10:
            result[dim_name] = 0.0
        else:
            result[dim_name] = round(float(np.dot(q_sub, c_sub) / (q_norm * c_norm)), 4)

    return result


def _generate_similarity_summary(
    dim_sims: dict[str, float],
    selected_dims: Optional[list[str]] = None,
) -> str:
    """Generate text explaining WHY this case is similar.

    [HEURISTIC: SIMILARITY_DRIVER_V1]
    Logic: max dim = driver, min dim = risk/divergence, low std = "all-round sync"
    [ARCHITECT] No predictive language. Facts only.
    """
    if not dim_sims:
        return ""

    items = sorted(dim_sims.items(), key=lambda x: x[1], reverse=True)
    best_dim, best_val = items[0]
    worst_dim, worst_val = items[-1]

    best_label = DIMENSION_LABELS.get(best_dim, best_dim)
    worst_label = DIMENSION_LABELS.get(worst_dim, worst_dim)

    vals = np.array(list(dim_sims.values()))
    std = float(np.std(vals))

    parts = []

    # All-round sync check
    if std < 0.08 and np.mean(vals) > 0.7:
        parts.append(f"全方位同步（5 維度均在 {np.min(vals)*100:.0f}%-{np.max(vals)*100:.0f}% 間）")
    else:
        # Driver
        parts.append(f"主要驅動：{best_label}（{best_val*100:.0f}%）")
        # Divergence
        if worst_val < SIM_LOW:
            parts.append(f"背離點：{worst_label}（{worst_val*100:.0f}%）")

    # Unselected dimension warning [ARCHITECT: <40% → [!]]
    if selected_dims:
        all_dims = set(dim_sims.keys())
        unselected = all_dims - set(selected_dims)
        for ud in unselected:
            if dim_sims.get(ud, 1.0) < SIM_DANGER:
                ud_label = DIMENSION_LABELS.get(ud, ud)
                parts.append(f"[!] 未選維度 {ud_label} 僅 {dim_sims[ud]*100:.0f}%")

    return " · ".join(parts)


def _cosine_similarity_weighted(query: np.ndarray, matrix: np.ndarray,
                                 weights: Optional[np.ndarray] = None) -> np.ndarray:
    """Vectorized cosine similarity — single matrix multiply, milliseconds."""
    if weights is not None:
        q = query * weights
        m = matrix * weights[np.newaxis, :]
    else:
        q = query
        m = matrix

    q_norm = np.linalg.norm(q)
    if q_norm < 1e-10:
        return np.zeros(m.shape[0], dtype=np.float32)

    m_norms = np.linalg.norm(m, axis=1)
    m_norms[m_norms < 1e-10] = 1.0

    dots = m @ q
    return (dots / (m_norms * q_norm)).astype(np.float32)


def _build_weight_vector(feature_weights: dict, dimension_boosts: Optional[dict] = None) -> np.ndarray:
    """Build a weight vector for all features."""
    meta = _load_metadata()
    weights = np.ones(len(_feature_cols), dtype=np.float32)

    # Apply per-feature weights
    for feat_name, w in feature_weights.items():
        if feat_name in _feature_cols:
            idx = _feature_cols.index(feat_name)
            weights[idx] = w

    # Apply dimension-level boosts
    if dimension_boosts:
        for dim_name, boost in dimension_boosts.items():
            dim_info = meta["dimensions"].get(dim_name)
            if dim_info:
                for feat in dim_info["features"]:
                    if feat in _feature_cols:
                        idx = _feature_cols.index(feat)
                        weights[idx] *= boost

    return weights


def _get_forward_prices(cases: list[dict], max_days: int = SPAGHETTI_DAYS) -> list[dict]:
    """Get normalized forward price paths for Spaghetti Chart.

    Each path starts at 1.0 (the match date's close price).
    Returns list of {stock_code, date, path: [{day: 0, value: 1.0}, {day: 1, value: 1.02}, ...]}

    Optimized: uses pre-grouped price data + numpy vectorized division.
    """
    if _price_grouped is None:
        return []

    paths = []
    for case in cases:
        code = case["stock_code"]
        match_date = np.datetime64(pd.Timestamp(case["date"]))

        stock_data = _price_grouped.get(code)
        if stock_data is None:
            continue

        dates = stock_data["dates"]
        closes = stock_data["closes"]

        # Binary search for start index (dates are sorted)
        start_idx = np.searchsorted(dates, match_date, side="left")
        if start_idx >= len(dates):
            continue

        end_idx = min(start_idx + max_days + 1, len(dates))
        if end_idx - start_idx < 2:
            continue

        base_price = closes[start_idx]
        if base_price <= 0 or np.isnan(base_price):
            continue

        # Vectorized normalization
        segment = closes[start_idx:end_idx] / base_price
        valid = np.isfinite(segment)

        path = [
            {"day": int(i), "value": round(float(segment[i]), 4)}
            for i in range(len(segment))
            if valid[i]
        ]

        if len(path) < 2:
            continue

        paths.append({
            "stock_code": code,
            "date": case["date"],
            "similarity": case["similarity"],
            "path": path,
        })

    return paths


def _compute_statistics(cases: list[dict]) -> dict:
    """Compute aggregate statistics for a set of similar cases."""
    return_horizons = ["d3", "d7", "d21", "d90", "d180"]

    statistics = {
        "sample_count": len(cases),
        "small_sample_warning": len(cases) < SMALL_SAMPLE_THRESHOLD,
    }

    for h in return_horizons:
        vals = [
            c["forward_returns"][h]
            for c in cases
            if c["forward_returns"].get(h) is not None
        ]
        if vals:
            arr = np.array(vals)
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

    return statistics


def _compute_sniper_assessment(cases: list[dict]) -> dict:
    """Compute Sniper Confidence Tiering for a set of similar cases.

    R88.5 CONVERGED (Wall Street Trader, 6-year stress test):
      - Sniper: mean_sim >= 88% AND mean_fund_sim >= 50%
      - Tactical: mean_fund_sim >= 40%
      - Avoid: everything else

    Returns:
      {
        "tier": "sniper" | "tactical" | "avoid",
        "mean_similarity": 0.91,
        "mean_fund_similarity": 0.55,
        "confidence_label": "高信心" | "極高信心（注意樣本稀疏）",
        "label": "[EXPERIMENTAL]",
        "validation": {"rho": 0.2553, "pf": 1.65, "n": 45, "period": "2020-2025"},
      }
    """
    if not cases:
        return {
            "tier": "avoid",
            "mean_similarity": 0.0,
            "mean_fund_similarity": 0.0,
            "confidence_label": "無資料",
            "label": SNIPER_LABEL,
            "validation": {"rho": 0.2553, "pf": 1.65, "n": 45, "period": "2020-2025"},
        }

    # Mean overall similarity
    mean_sim = float(np.mean([c["similarity"] for c in cases]))

    # Mean fundamental dimension similarity
    fund_sims = []
    for c in cases:
        ds = c.get("dimension_similarities")
        if ds and "fundamental" in ds:
            fund_sims.append(ds["fundamental"])
    mean_fund_sim = float(np.mean(fund_sims)) if fund_sims else 0.0

    # Tier classification
    if mean_sim >= SNIPER_SIM_THRESHOLD and mean_fund_sim >= SNIPER_FUND_THRESHOLD:
        tier = "sniper"
    elif mean_fund_sim >= TACTICAL_FUND_THRESHOLD:
        tier = "tactical"
    else:
        tier = "avoid"

    # Confidence label (Trader instruction)
    if mean_sim >= 0.90:
        confidence_label = "極高信心（注意樣本稀疏）"
    elif mean_sim >= SNIPER_SIM_THRESHOLD:
        confidence_label = "高信心"
    elif mean_sim >= 0.85:
        confidence_label = "中等信心"
    else:
        confidence_label = "低信心"

    return {
        "tier": tier,
        "mean_similarity": round(mean_sim, 4),
        "mean_fund_similarity": round(mean_fund_sim, 4),
        "confidence_label": confidence_label,
        "label": SNIPER_LABEL,
        "validation": {"rho": 0.2553, "pf": 1.65, "n": 45, "period": "2020-2025"},
    }


def _find_cases(
    stock_code: str,
    query_date: Optional[str],
    top_k: int,
    weights: Optional[np.ndarray],
    regime_filter: bool,
    exclude_self: bool = True,
    min_date: Optional[str] = "2020-01-01",
    dimensions: Optional[list[str]] = None,
    compute_dim_breakdown: bool = False,
    selected_dims_for_summary: Optional[list[str]] = None,
) -> tuple[list[dict], dict]:
    """Core similarity search — shared by raw and augmented pipelines.

    Args:
        dimensions: If provided, only use features from these dimensions (Block 1).
        compute_dim_breakdown: If True, compute per-dimension similarity for each case.
        selected_dims_for_summary: Dimensions the user selected (for [!] warnings).
    """
    _load_data()

    # Find query row
    stock_mask = _feature_index["stock_code"] == stock_code
    stock_rows = _feature_index[stock_mask]

    if stock_rows.empty:
        raise ValueError(f"Stock {stock_code} not found in feature data")

    if query_date:
        qd = pd.Timestamp(query_date)
        # Find closest date <= query_date
        valid = stock_rows[stock_rows["date"] <= qd]
        if valid.empty:
            raise ValueError(f"No data for {stock_code} on or before {query_date}")
        query_idx = valid.index[-1]
    else:
        query_idx = stock_rows.index[-1]

    query_row_date = _feature_index.loc[query_idx, "date"]
    query_regime = int(_regime_tags[query_idx])
    query_vector = _features_matrix[query_idx]

    # Dimension filtering: zero out non-selected dimensions [R88.3]
    # R88.7: Also zero-weight warmup features (sparse, data accumulating)
    effective_weights = weights
    if dimensions:
        dim_mask = _get_dimension_mask(dimensions)
        # Apply warmup mask: exclude warming-up features
        dim_mask &= _warmup_mask
        if effective_weights is not None:
            effective_weights = effective_weights * dim_mask.astype(np.float32)
        else:
            effective_weights = dim_mask.astype(np.float32)
    elif _warmup_mask is not None and not np.all(_warmup_mask):
        # No dimension filter, but still apply warmup mask
        warmup_w = _warmup_mask.astype(np.float32)
        if effective_weights is not None:
            effective_weights = effective_weights * warmup_w
        else:
            effective_weights = warmup_w

    # Compute cosine similarity
    similarities = _cosine_similarity_weighted(
        query_vector, _features_matrix, effective_weights
    )

    # Build filter mask
    mask = np.ones(len(similarities), dtype=bool)

    if exclude_self:
        mask &= (_feature_index["stock_code"] != stock_code).values

    if min_date:
        mask &= (_feature_index["date"] >= pd.Timestamp(min_date)).values

    # Exclude future dates
    mask &= (_feature_index["date"] < query_row_date).values

    # Regime filter
    if regime_filter and _regime_tags is not None:
        mask &= (_regime_tags == query_regime)

    # Min similarity
    mask &= (similarities >= MIN_SIMILARITY_THRESHOLD)

    similarities[~mask] = -2.0

    # Time decay
    days_diff = (query_row_date - _feature_index["date"]).dt.days.values.astype(np.float64)
    decay = np.exp(-np.log(2) * days_diff / TIME_DECAY_HALF_LIFE_DAYS).astype(np.float32)
    weighted_sim = similarities * decay

    # Top-K with deduplication (same stock same month → keep best)
    top_indices = np.argsort(weighted_sim)[::-1][:top_k * 3]
    top_indices = top_indices[similarities[top_indices] > -1.5]

    # Use numpy arrays for fast dedup (avoid .loc per iteration)
    all_codes = _feature_index["stock_code"].values
    all_dates = _feature_index["date"].values

    seen = set()
    selected = []
    for idx in top_indices:
        if len(selected) >= top_k:
            break
        code = all_codes[idx]
        date = pd.Timestamp(all_dates[idx])
        key = (code, date.year, date.month)
        if key in seen:
            continue
        seen.add(key)
        selected.append(idx)

    # Build result cases
    return_horizons = ["d3", "d7", "d21", "d90", "d180"]
    cases = []

    # Pre-extract stock_code/date arrays for fast lookup
    idx_codes = _feature_index["stock_code"].values
    idx_dates = _feature_index["date"].values

    # Batch per-dimension breakdown if needed [R88.3 optimized]
    batch_dim_sims = {}
    if compute_dim_breakdown and selected:
        dim_indices = _get_dimension_col_indices()
        q_full = _features_matrix[query_idx]
        for s_idx in selected:
            c_full = _features_matrix[s_idx]
            dim_result = {}
            for dim_name, col_idx in dim_indices.items():
                if len(col_idx) == 0:
                    dim_result[dim_name] = 0.0
                    continue
                q_sub = q_full[col_idx]
                c_sub = c_full[col_idx]
                q_norm = np.linalg.norm(q_sub)
                c_norm = np.linalg.norm(c_sub)
                if q_norm < 1e-10 or c_norm < 1e-10:
                    dim_result[dim_name] = 0.0
                else:
                    dim_result[dim_name] = round(float(np.dot(q_sub, c_sub) / (q_norm * c_norm)), 4)
            batch_dim_sims[s_idx] = dim_result

    for idx in selected:
        code = str(idx_codes[idx])
        date = pd.Timestamp(idx_dates[idx])
        sim = float(similarities[idx])

        # O(1) forward returns lookup via dict index
        fwd = {}
        if _fwd_returns_index is not None:
            fwd_row_idx = _fwd_returns_index.get((code, date))
            if fwd_row_idx is not None:
                row = _forward_returns.iloc[fwd_row_idx]
                for h in return_horizons:
                    val = row.get(h, None)
                    fwd[h] = float(val) if pd.notna(val) else None
            else:
                fwd = {h: None for h in return_horizons}
        else:
            fwd = {h: None for h in return_horizons}

        case = {
            "stock_code": code,
            "date": date.strftime("%Y-%m-%d"),
            "similarity": round(sim, 4),
            "forward_returns": fwd,
        }

        # Per-dimension breakdown [R88.3]
        if compute_dim_breakdown and idx in batch_dim_sims:
            dim_sims = batch_dim_sims[idx]
            case["dimension_similarities"] = dim_sims
            case["similarity_summary"] = _generate_similarity_summary(
                dim_sims, selected_dims_for_summary
            )

        cases.append(case)

    query_info = {
        "stock_code": stock_code,
        "date": query_row_date.strftime("%Y-%m-%d"),
        "regime": query_regime,
    }

    return cases, query_info


def _generate_opinion(
    raw_stats: dict,
    aug_stats: dict,
    query_info: dict,
    aug_cases: list[dict],
) -> dict:
    """Generate text advice for Block 2 (System Analysis).

    [CONVERGED] Architect Critic: must include regime label and quality warnings.
    """
    regime_labels = {1: "多頭", 0: "盤整", -1: "空頭"}
    regime = query_info.get("regime", 0)
    regime_label = regime_labels.get(regime, "未知")

    # Build opinion text
    lines = []
    lines.append(f"目前市場環境判定：{regime_label} [VERIFIED: Regime Filter Applied]")

    # Check sample quality
    n = aug_stats.get("sample_count", 0)
    if n < 10:
        lines.append(f"[!] 相似案例僅 {n} 筆，統計信度極低。建議觀望。")
    elif n < SMALL_SAMPLE_THRESHOLD:
        lines.append(f"[!] 相似案例 {n} 筆，低於 {SMALL_SAMPLE_THRESHOLD} 筆門檻，統計結果可能不穩定。")

    # D21 analysis (medium-term most actionable)
    d21 = aug_stats.get("d21", {})
    d21_wr = d21.get("win_rate")
    d21_exp = d21.get("expectancy")

    if d21_wr is not None:
        if d21_wr >= 0.65:
            lines.append(f"[BULL] 21日勝率 {d21_wr*100:.0f}%，歷史偏多。期望值 {d21_exp*100:+.1f}%。")
        elif d21_wr <= 0.35:
            lines.append(f"[BEAR] 21日勝率 {d21_wr*100:.0f}%，歷史偏空。期望值 {d21_exp*100:+.1f}%。")
        else:
            lines.append(f"[NEUTRAL] 21日勝率 {d21_wr*100:.0f}%，方向不明確。期望值 {d21_exp*100:+.1f}%。")

    # Similarity quality
    if aug_cases:
        avg_sim = np.mean([c["similarity"] for c in aug_cases])
        if avg_sim < 0.6:
            lines.append("[!] 平均相似度偏低，歷史上較難找到高度匹配案例，以下分析僅供參考。")

    # Divergence check with raw
    raw_d21_wr = raw_stats.get("d21", {}).get("win_rate")
    if d21_wr is not None and raw_d21_wr is not None:
        diff = abs(d21_wr - raw_d21_wr)
        if diff > DIVERGENCE_THRESHOLD:
            lines.append(
                f"[DIVERGE] 加工邏輯與原始數據偏離 {diff*100:.0f}% "
                f"原始勝率 {raw_d21_wr*100:.0f}% vs 加工後 {d21_wr*100:.0f}%。"
                f"差異來自 Regime 過濾與特徵加權。"
            )

    return {
        "regime_label": regime_label,
        "advice_text": "\n".join(lines),
        "confidence": "high" if n >= 30 else ("medium" if n >= 15 else "low"),
        "filters_applied": [
            f"Regime: {regime_label}",
            "Dynamic Feature Weighting",
            "Time Decay (2y half-life)",
        ],
    }


def find_similar_dual(
    stock_code: str,
    query_date: Optional[str] = None,
    top_k: int = 30,
    exclude_self: bool = True,
    dimensions: Optional[list[str]] = None,
) -> dict:
    """Main entry point — runs both raw and augmented pipelines.

    [CONVERGED] Joe's two-block design:
      Block 1 (Raw): User-selected dimensions, equal-weight → "The Facts"
      Block 2 (Augmented): Dynamic feature selection + regime filter → "Our Opinion"

    R88.3: dimensions param controls Block 1 feature subset.
    Both blocks always compute per-dimension similarity breakdown.
    """
    _load_data()
    meta = _load_metadata()
    all_dim_names = list(meta["dimensions"].keys())

    # Validate dimensions
    if dimensions:
        dimensions = [d for d in dimensions if d in meta["dimensions"]]
        if not dimensions:
            dimensions = None  # Fallback to all

    selected_dims = dimensions or all_dim_names

    # Determine query regime for augmented pipeline
    stock_mask = _feature_index["stock_code"] == stock_code
    stock_rows = _feature_index[stock_mask]
    if stock_rows.empty:
        raise ValueError(f"Stock {stock_code} not found in feature data")

    if query_date:
        qd = pd.Timestamp(query_date)
        valid = stock_rows[stock_rows["date"] <= qd]
        if valid.empty:
            raise ValueError(f"No data for {stock_code} on or before {query_date}")
        query_idx = valid.index[-1]
    else:
        query_idx = stock_rows.index[-1]

    query_regime = int(_regime_tags[query_idx])

    # Build description for Block 1
    if dimensions:
        dim_labels = [DIMENSION_LABELS.get(d, d) for d in dimensions]
        feat_count = sum(
            meta["dimensions"][d]["count"]
            for d in dimensions if d in meta["dimensions"]
        )
        # R88.7: Subtract warmup features from reported count
        warmup_in_dims = sum(
            1 for d in dimensions if d in meta["dimensions"]
            for f in meta["dimensions"][d]["features"] if f in WARMUP_FEATURES
        )
        active_count = feat_count - warmup_in_dims
        if warmup_in_dims > 0:
            raw_desc = f"{'+'.join(dim_labels)} ({active_count}/{feat_count} 指標)，等權重，無環境過濾"
        else:
            raw_desc = f"{'+'.join(dim_labels)} ({feat_count} 指標)，等權重，無環境過濾"
    else:
        total = len(_feature_cols) if _feature_cols else 60
        active = int(np.sum(_warmup_mask)) if _warmup_mask is not None else total
        raw_desc = f"{active}/{total} 指標等權重，無環境過濾，歷史全量比對"

    # --- Block 1: Raw (The Facts) ---
    raw_cases, query_info = _find_cases(
        stock_code=stock_code,
        query_date=query_date,
        top_k=top_k,
        weights=None,  # Equal weight
        regime_filter=False,  # No regime filter
        exclude_self=exclude_self,
        dimensions=dimensions,  # R88.3: user-selected dims
        compute_dim_breakdown=True,  # R88.3: gene map
        selected_dims_for_summary=selected_dims,
    )
    raw_stats = _compute_statistics(raw_cases)
    raw_paths = _get_forward_prices(raw_cases)

    # --- Block 2: Augmented (Our Opinion) ---
    dim_boost = REGIME_DIMENSION_BOOST.get(query_regime, {})
    aug_weights = _build_weight_vector(AUGMENTED_FEATURE_WEIGHTS, dim_boost)

    aug_cases, _ = _find_cases(
        stock_code=stock_code,
        query_date=query_date,
        top_k=top_k,
        weights=aug_weights,
        regime_filter=True,  # Regime filter ON
        exclude_self=exclude_self,
        compute_dim_breakdown=True,  # R88.3: gene map
    )
    aug_stats = _compute_statistics(aug_cases)
    aug_paths = _get_forward_prices(aug_cases)

    # Generate opinion text
    opinion = _generate_opinion(raw_stats, aug_stats, query_info, aug_cases)

    # Build weight transparency for Block 2 [R88.3 ARCHITECT]
    aug_weight_info = {}
    for dim_name in all_dim_names:
        base = 1.0
        boost = dim_boost.get(dim_name, 1.0)
        aug_weight_info[dim_name] = round(base * boost, 2)
    opinion["weight_transparency"] = aug_weight_info

    # R88.5 Sniper Confidence Assessment (on raw block, per Trader mandate)
    sniper_assessment = _compute_sniper_assessment(raw_cases)

    # Divergence warning [ARCHITECT: >15% D21 win rate diff]
    raw_d21_wr = raw_stats.get("d21", {}).get("win_rate")
    aug_d21_wr = aug_stats.get("d21", {}).get("win_rate")
    divergence_warning = False
    if raw_d21_wr is not None and aug_d21_wr is not None:
        divergence_warning = abs(raw_d21_wr - aug_d21_wr) > DIVERGENCE_THRESHOLD

    return {
        "query": query_info,
        "dimensions_used": selected_dims,
        "sniper_assessment": sniper_assessment,
        "raw": {
            "label": "原始數據",
            "description": raw_desc,
            "similar_cases": raw_cases,
            "statistics": raw_stats,
            "forward_paths": raw_paths,
        },
        "augmented": {
            "label": "系統分析",
            "description": f"動態特徵加權 + {opinion['regime_label']}環境過濾",
            "similar_cases": aug_cases,
            "statistics": aug_stats,
            "forward_paths": aug_paths,
            "opinion": opinion,
        },
        "divergence_warning": divergence_warning,
        "transaction_cost_deducted": TRANSACTION_COST,
    }


# --- Legacy API (keep backward compatible) ---

def find_similar(
    stock_code: str,
    dimensions: list[str],
    window: int = 20,
    top_k: int = 30,
    exclude_self: bool = True,
    min_date: Optional[str] = None,
    regime_match: bool = True,
) -> dict:
    """Legacy API — redirects to raw pipeline with all features."""
    cases, query_info = _find_cases(
        stock_code=stock_code,
        query_date=None,
        top_k=top_k,
        weights=None,
        regime_filter=regime_match,
        exclude_self=exclude_self,
        min_date=min_date,
    )
    stats = _compute_statistics(cases)

    return {
        "query": {**query_info, "window": window, "regime_match": regime_match},
        "dimensions_used": dimensions,
        "feature_count": len(_feature_cols) if _feature_cols else 0,
        "descriptor_count": len(_feature_cols) * 4 if _feature_cols else 0,
        "similar_cases": cases,
        "statistics": stats,
        "transaction_cost_deducted": TRANSACTION_COST,
    }


def get_dimensions() -> list[dict]:
    """Return available dimensions with feature counts and warmup status."""
    meta = _load_metadata()
    result = []
    for name, info in meta["dimensions"].items():
        # R88.7: Mark features that are warming up (data accumulating)
        warmup_features = [f for f in info["features"] if f in WARMUP_FEATURES]
        active_count = info["count"] - len(warmup_features)

        result.append({
            "name": name,
            "label": info["description"],
            "feature_count": info["count"],
            "active_feature_count": active_count,
            "features": info["features"],
            "warmup_features": warmup_features,
            "has_warmup": len(warmup_features) > 0,
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


# ============================================================
# Gene Mutation Scanner (R88.7 Phase 7)
# [CONVERGED — Wall Street Trader 2026-02-18]
# "Δ_div = Score_brokerage - Score_technical"
# ">1.5σ = 匿蹤吸貨, <-1.5σ = 誘多派發"
# ============================================================

# [PLACEHOLDER] Feature weights — equal for now, tune after 2/23 first flight
MUTATION_WEIGHTS_CONFIG = {
    "brokerage": {
        "broker_winner_momentum": 2.5,
        "broker_purity_score": 2.0,
        "broker_net_buy_ratio": 1.5,
        "_default": 1.0,
    },
    "technical": {
        "atr_pct": 1.5,
        "vol_ratio_20": 1.5,
        "_default": 1.0,
    },
}

# [PLACEHOLDER] Liquidity filter — vol_ratio_20 Z-score > -2 as proxy
# (raw volume not in Z-score space, use vol_ratio_20 instead)
MUTATION_VOLUME_FLOOR_ZSCORE = -2.0

# [CONVERGED — Wall Street Trader 2026-02-19] Circuit Breaker
# If >30% of stocks show >2σ mutations simultaneously, it's a data bug, not alpha.
# Abort Atomic Swap and flag the issue.
GLOBAL_SHIFT_THRESHOLD_PCT = 0.30  # 30% of stocks
GLOBAL_SHIFT_SIGMA = 2.0  # Z-score threshold for "shifted"


def scan_gene_mutations(
    threshold_sigma: float = 1.5,
    top_n: int = 10,
    weights_config: dict | None = None,
    use_weights: bool = False,
) -> dict:
    """Scan for Brokerage vs Technical divergence across all stocks.

    [CONVERGED — Wall Street Trader 2026-02-18]
    Detects stocks where brokerage dimension Z-score significantly diverges
    from technical dimension Z-score, indicating hidden accumulation or
    deceptive distribution.

    Args:
        threshold_sigma: Minimum |Δ_div| to qualify as mutation (default 1.5)
        top_n: Return top N mutations by |Δ_div|
        weights_config: Feature weights per dimension (None = equal weights for baseline)
        use_weights: If True, use weighted average; if False, arithmetic mean (baseline)

    Returns:
        Dict with mutations list, histogram data, and metadata.
    """
    _load_data()

    if _features_matrix is None or _feature_index is None:
        return {"error": "Features not loaded", "mutations": []}

    if weights_config is None:
        weights_config = MUTATION_WEIGHTS_CONFIG

    dim_indices = _get_dimension_col_indices()

    # Need both brokerage and technical dimensions
    if "brokerage" not in dim_indices or "technical" not in dim_indices:
        return {"error": "Missing brokerage or technical dimension", "mutations": []}

    brok_cols = dim_indices["brokerage"]
    tech_cols = dim_indices["technical"]

    # Filter out warmup features from brokerage dimension
    if _warmup_mask is not None:
        brok_active = np.array([c for c in brok_cols if _warmup_mask[c]])
    else:
        brok_active = brok_cols
    tech_active = tech_cols  # Technical has no warmup features

    if len(brok_active) == 0 or len(tech_active) == 0:
        return {"error": "No active features after warmup mask", "mutations": []}

    # Get latest date for each stock
    dates = _feature_index["date"].values
    stocks = _feature_index["stock_code"].values
    unique_stocks = np.unique(stocks)

    # Build weights arrays
    if use_weights:
        brok_w = _build_weight_array(brok_active, "brokerage", weights_config)
        tech_w = _build_weight_array(tech_active, "technical", weights_config)
    else:
        brok_w = np.ones(len(brok_active), dtype=np.float32)
        tech_w = np.ones(len(tech_active), dtype=np.float32)

    # Find latest row index for each stock
    latest_indices = {}
    for i in range(len(stocks) - 1, -1, -1):
        s = stocks[i]
        if s not in latest_indices:
            latest_indices[s] = i

    # Compute dimension scores for all stocks at their latest date
    results = []
    all_deltas = []

    # Liquidity filter: vol_ratio_20 column index
    vol_ratio_idx = None
    if "vol_ratio_20" in _feature_cols:
        vol_ratio_idx = _feature_cols.index("vol_ratio_20")

    for stock_code, row_idx in latest_indices.items():
        row = _features_matrix[row_idx]

        # Liquidity filter: skip if vol_ratio_20 Z-score too low
        if vol_ratio_idx is not None:
            if row[vol_ratio_idx] < MUTATION_VOLUME_FLOOR_ZSCORE:
                continue

        # Compute weighted dimension scores
        brok_values = row[brok_active]
        tech_values = row[tech_active]

        score_brok = float(np.sum(brok_values * brok_w) / np.sum(brok_w))
        score_tech = float(np.sum(tech_values * tech_w) / np.sum(tech_w))

        delta_div = score_brok - score_tech
        all_deltas.append(delta_div)

        results.append({
            "stock_code": stock_code,
            "date": str(dates[row_idx])[:10],
            "score_brokerage": round(score_brok, 4),
            "score_technical": round(score_tech, 4),
            "delta_div": round(delta_div, 4),
            "abs_delta": round(abs(delta_div), 4),
        })

    # Compute sigma from the distribution of all deltas
    all_deltas_arr = np.array(all_deltas)
    delta_mean = float(np.mean(all_deltas_arr))
    delta_std = float(np.std(all_deltas_arr))

    if delta_std < 1e-8:
        return {"error": "No variance in delta distribution", "mutations": []}

    # Classify mutations
    mutations = []
    for r in results:
        z_score = (r["delta_div"] - delta_mean) / delta_std
        r["z_score"] = round(z_score, 4)

        if z_score > threshold_sigma:
            r["mutation_type"] = "匿蹤吸貨"
            r["mutation_label"] = "Stealth Accumulation"
            mutations.append(r)
        elif z_score < -threshold_sigma:
            r["mutation_type"] = "誘多派發"
            r["mutation_label"] = "Deceptive Distribution"
            mutations.append(r)

    # --- Circuit Breaker: Global Shift Check ---
    # [CONVERGED — Wall Street Trader 2026-02-19]
    # If >30% of stocks exceed 2σ, it's systemic (data bug), not alpha.
    n_extreme = int(np.sum(np.abs(all_deltas_arr - delta_mean) / delta_std > GLOBAL_SHIFT_SIGMA))
    global_shift_pct = n_extreme / len(results) if len(results) > 0 else 0
    global_shift_triggered = global_shift_pct > GLOBAL_SHIFT_THRESHOLD_PCT

    if global_shift_triggered:
        logger.warning(
            f"CIRCUIT BREAKER: {n_extreme}/{len(results)} stocks ({global_shift_pct:.1%}) "
            f"exceed {GLOBAL_SHIFT_SIGMA}σ — likely data bug, not alpha"
        )

    # Sort by |z_score| descending, take top N
    mutations.sort(key=lambda x: abs(x["z_score"]), reverse=True)
    mutations = mutations[:top_n]

    # Build histogram data (20 bins)
    hist_counts, hist_edges = np.histogram(all_deltas_arr, bins=20)
    histogram = {
        "counts": hist_counts.tolist(),
        "edges": [round(float(e), 4) for e in hist_edges.tolist()],
        "threshold_sigma": threshold_sigma,
        "threshold_value_upper": round(delta_mean + threshold_sigma * delta_std, 4),
        "threshold_value_lower": round(delta_mean - threshold_sigma * delta_std, 4),
    }

    return {
        "mutations": mutations,
        "total_stocks_scanned": len(results),
        "total_mutations": len([r for r in results
                                if abs((r["delta_div"] - delta_mean) / delta_std) > threshold_sigma]),
        "distribution": {
            "mean": round(delta_mean, 4),
            "std": round(delta_std, 4),
            "min": round(float(np.min(all_deltas_arr)), 4),
            "max": round(float(np.max(all_deltas_arr)), 4),
        },
        "histogram": histogram,
        "circuit_breaker": {
            "triggered": global_shift_triggered,
            "extreme_count": n_extreme,
            "extreme_pct": round(global_shift_pct, 4),
            "threshold_pct": GLOBAL_SHIFT_THRESHOLD_PCT,
            "threshold_sigma": GLOBAL_SHIFT_SIGMA,
        },
        "config": {
            "threshold_sigma": threshold_sigma,
            "top_n": top_n,
            "use_weights": use_weights,
            "brokerage_features_active": len(brok_active),
            "brokerage_features_total": len(brok_cols),
            "technical_features_active": len(tech_active),
        },
    }


def generate_daily_summary(threshold_sigma: float = 1.5, top_n: int = 20) -> dict:
    """Generate daily auto-summary after scheduler pipeline completes.

    [CONVERGED — Wall Street Trader 2026-02-19]
    Produces a structured JSON summary covering:
    1. Pipeline health (swap report + night watchman)
    2. Market pulse (mutation statistics + bias direction)
    3. Top mutations (stealth accumulation + distribution traps)
    4. Narrative text for quick reading

    Called by scheduler after: fetch_broker → rebuild parquet → atomic swap → mutation scan.
    Saves to data/daily_summary.json for frontend consumption.
    """
    from datetime import datetime
    from pathlib import Path
    import json as json_mod

    summary = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "generated_at": datetime.now().isoformat(),
        "version": "1.0",
    }

    # --- 1. Pipeline Health (from swap_report.json) ---
    swap_report_path = Path(__file__).parent.parent / "data" / "pattern_data" / "features" / "swap_report.json"
    pipeline_health = {"status": "UNKNOWN"}

    if swap_report_path.exists():
        try:
            with open(swap_report_path, "r", encoding="utf-8") as f:
                swap_report = json_mod.load(f)

            pipeline_health = {
                "status": "OK" if swap_report.get("swap_ok") else "FAILED",
                "swap_result": swap_report.get("result", "unknown"),
                "new_rows": swap_report.get("new_row_count"),
                "row_delta": swap_report.get("row_count_delta"),
                "size_mb": swap_report.get("new_file_size_mb"),
                "timestamp": swap_report.get("timestamp"),
            }

            # Night Watchman health
            health = swap_report.get("health_check", {})
            pipeline_health["night_watchman"] = {
                "status": health.get("status", "UNKNOWN"),
                "latest_date": health.get("latest_date"),
                "brokerage_nonzero_rate": health.get("brokerage_nonzero_rate", 0),
                "brokerage_stocks_with_data": health.get("brokerage_stocks_with_data", 0),
            }
        except Exception as e:
            pipeline_health["error"] = str(e)
    else:
        pipeline_health["status"] = "NO_REPORT"

    summary["pipeline_health"] = pipeline_health

    # --- 2. Mutation Scan ---
    try:
        mutation_data = scan_gene_mutations(
            threshold_sigma=threshold_sigma,
            top_n=top_n,
            use_weights=False,
        )

        if "error" in mutation_data:
            summary["market_pulse"] = {"error": mutation_data["error"]}
            summary["top_mutations"] = {"stealth": [], "distribution": []}
            summary["narrative"] = f"Mutation scan error: {mutation_data['error']}"
            return summary

        total_scanned = mutation_data["total_stocks_scanned"]
        total_mutations = mutation_data["total_mutations"]
        mutations = mutation_data["mutations"]

        # Split by type
        stealth = [m for m in mutations if m.get("z_score", 0) > 0]
        distribution = [m for m in mutations if m.get("z_score", 0) < 0]

        # Count all mutations (not just top_n) from distribution stats
        all_stealth_count = sum(1 for m in mutations if m.get("mutation_label") == "Stealth Accumulation")
        all_distrib_count = sum(1 for m in mutations if m.get("mutation_label") == "Deceptive Distribution")

        # Determine bias
        if total_mutations == 0:
            bias = "neutral"
            bias_ratio = 1.0
        elif all_distrib_count > all_stealth_count * 1.5:
            bias = "distribution_heavy"
            bias_ratio = round(all_distrib_count / max(all_stealth_count, 1), 2)
        elif all_stealth_count > all_distrib_count * 1.5:
            bias = "accumulation_heavy"
            bias_ratio = round(all_stealth_count / max(all_distrib_count, 1), 2)
        else:
            bias = "balanced"
            bias_ratio = round(max(all_stealth_count, all_distrib_count) / max(min(all_stealth_count, all_distrib_count), 1), 2)

        summary["market_pulse"] = {
            "total_stocks_scanned": total_scanned,
            "total_mutations": total_mutations,
            "stealth_count": all_stealth_count,
            "distribution_count": all_distrib_count,
            "mutation_bias": bias,
            "bias_ratio": bias_ratio,
            "circuit_breaker": mutation_data.get("circuit_breaker", {}),
            "distribution_stats": mutation_data.get("distribution", {}),
        }

        summary["top_mutations"] = {
            "stealth": [
                {
                    "stock_code": m["stock_code"],
                    "date": m["date"],
                    "z_score": m["z_score"],
                    "score_brokerage": m["score_brokerage"],
                    "score_technical": m["score_technical"],
                }
                for m in stealth[:5]
            ],
            "distribution": [
                {
                    "stock_code": m["stock_code"],
                    "date": m["date"],
                    "z_score": m["z_score"],
                    "score_brokerage": m["score_brokerage"],
                    "score_technical": m["score_technical"],
                }
                for m in distribution[:5]
            ],
        }

        # --- 3. Generate Narrative ---
        cb = mutation_data.get("circuit_breaker", {})
        if cb.get("triggered"):
            narrative = (
                f"CIRCUIT BREAKER TRIGGERED: {cb['extreme_count']}/{total_scanned} stocks "
                f"({cb['extreme_pct']:.1%}) exceed {cb['threshold_sigma']}σ — "
                f"suspected data anomaly, manual review required."
            )
        else:
            bias_text = {
                "distribution_heavy": "誘多派發為主",
                "accumulation_heavy": "匿蹤吸貨為主",
                "balanced": "多空均衡",
                "neutral": "無顯著突變",
            }.get(bias, "未知")

            top_stealth_text = ""
            if stealth:
                top_s = stealth[0]
                top_stealth_text = f"重點觀察 {top_s['stock_code']}（匿蹤吸貨 z={top_s['z_score']:.2f}σ）"

            top_distrib_text = ""
            if distribution:
                top_d = distribution[0]
                top_distrib_text = f"警惕 {top_d['stock_code']}（誘多派發 z={top_d['z_score']:.2f}σ）"

            parts = [
                f"今日市場分點動向：{bias_text}",
                f"（{all_distrib_count} 誘多 vs {all_stealth_count} 匿蹤）。",
            ]
            if top_stealth_text:
                parts.append(top_stealth_text + "。")
            if top_distrib_text:
                parts.append(top_distrib_text + "。")

            narrative = " ".join(parts)

        summary["narrative"] = narrative

    except Exception as e:
        logger.error(f"Daily summary mutation scan failed: {e}")
        summary["market_pulse"] = {"error": str(e)}
        summary["top_mutations"] = {"stealth": [], "distribution": []}
        summary["narrative"] = f"Scan failed: {e}"

    # --- 4. Save to disk ---
    try:
        summary_path = Path(__file__).parent.parent / "data" / "daily_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json_mod.dump(summary, f, indent=2, ensure_ascii=False)
        logger.info(f"Daily summary saved: {summary_path}")
    except Exception as e:
        logger.error(f"Failed to save daily summary: {e}")

    return summary


def _build_weight_array(
    col_indices: np.ndarray, dim_name: str, weights_config: dict
) -> np.ndarray:
    """Build weight array for a dimension's active features.

    Uses per-feature weights from config, falls back to _default.
    """
    dim_weights = weights_config.get(dim_name, {})
    default_w = dim_weights.get("_default", 1.0)

    weights = []
    for idx in col_indices:
        feat_name = _feature_cols[idx]
        w = dim_weights.get(feat_name, default_w)
        weights.append(w)

    return np.array(weights, dtype=np.float32)

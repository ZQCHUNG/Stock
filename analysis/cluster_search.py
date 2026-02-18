"""多維度相似股分群 — 雙軌引擎 (Facts vs Opinion)

CONVERGED design (Gemini Wall Street Trader + Architect Critic + Joe):
  Block 1 (Raw/Facts): 50 features equal-weight cosine similarity, zero processing
  Block 2 (Augmented/Opinion): Dynamic feature selection, regime-aware, weighted
  Spaghetti Chart: Forward price paths for visual comparison
  Divergence Warning: When D21 win rate differs >15% between blocks [ARCHITECT]

Protocol v3 labels:
  [VERIFIED] TRANSACTION_COST = 0.00785
  [CONVERGED] Dual-block architecture, time decay, regime filter
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
_metadata: Optional[dict] = None
_feature_cols: Optional[list] = None
_price_cache: Optional[pd.DataFrame] = None
_norms: Optional[np.ndarray] = None  # Pre-computed row norms


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
    global _forward_returns, _feature_cols, _price_cache, _norms

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

    # Load forward returns
    if RETURNS_FILE.exists():
        _forward_returns = pd.read_parquet(RETURNS_FILE)
        _forward_returns["date"] = pd.to_datetime(_forward_returns["date"])
    else:
        _forward_returns = pd.DataFrame(
            columns=["date", "stock_code", "d3", "d7", "d21", "d90", "d180"]
        )

    # Load price cache for Spaghetti Chart
    if PRICE_CACHE_FILE.exists():
        _price_cache = pd.read_parquet(PRICE_CACHE_FILE, columns=["stock_code", "date", "close"])
        _price_cache["date"] = pd.to_datetime(_price_cache["date"])
        _price_cache = _price_cache.sort_values(["stock_code", "date"]).reset_index(drop=True)

    logger.info(
        "Loaded %d rows, %d features, %d stocks",
        len(_features_matrix), _features_matrix.shape[1],
        _feature_index["stock_code"].nunique(),
    )


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
    """
    if _price_cache is None:
        return []

    paths = []
    for case in cases:
        code = case["stock_code"]
        match_date = pd.Timestamp(case["date"])

        stock_prices = _price_cache[_price_cache["stock_code"] == code].copy()
        if stock_prices.empty:
            continue

        # Get prices from match_date onward
        future = stock_prices[stock_prices["date"] >= match_date].head(max_days + 1)
        if len(future) < 2:
            continue

        base_price = future.iloc[0]["close"]
        if base_price <= 0:
            continue

        path = []
        for i, (_, row) in enumerate(future.iterrows()):
            path.append({
                "day": i,
                "value": round(float(row["close"] / base_price), 4),
            })

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


def _find_cases(
    stock_code: str,
    query_date: Optional[str],
    top_k: int,
    weights: Optional[np.ndarray],
    regime_filter: bool,
    exclude_self: bool = True,
    min_date: Optional[str] = "2020-01-01",
) -> tuple[list[dict], dict]:
    """Core similarity search — shared by raw and augmented pipelines."""
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

    # Compute cosine similarity
    similarities = _cosine_similarity_weighted(query_vector, _features_matrix, weights)

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

    # Build result cases
    return_horizons = ["d3", "d7", "d21", "d90", "d180"]
    cases = []

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

        cases.append({
            "stock_code": code,
            "date": date.strftime("%Y-%m-%d"),
            "similarity": round(sim, 4),
            "forward_returns": fwd,
        })

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
) -> dict:
    """Main entry point — runs both raw and augmented pipelines.

    [CONVERGED] Joe's two-block design:
      Block 1 (Raw): 50 features equal-weight, no regime filter → "The Facts"
      Block 2 (Augmented): Dynamic feature selection + regime filter → "Our Opinion"
    """
    _load_data()
    meta = _load_metadata()

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

    # --- Block 1: Raw (The Facts) ---
    raw_cases, query_info = _find_cases(
        stock_code=stock_code,
        query_date=query_date,
        top_k=top_k,
        weights=None,  # Equal weight
        regime_filter=False,  # No regime filter
        exclude_self=exclude_self,
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
    )
    aug_stats = _compute_statistics(aug_cases)
    aug_paths = _get_forward_prices(aug_cases)

    # Generate opinion text
    opinion = _generate_opinion(raw_stats, aug_stats, query_info, aug_cases)

    # Divergence warning [ARCHITECT: >15% D21 win rate diff]
    raw_d21_wr = raw_stats.get("d21", {}).get("win_rate")
    aug_d21_wr = aug_stats.get("d21", {}).get("win_rate")
    divergence_warning = False
    if raw_d21_wr is not None and aug_d21_wr is not None:
        divergence_warning = abs(raw_d21_wr - aug_d21_wr) > DIVERGENCE_THRESHOLD

    return {
        "query": query_info,
        "raw": {
            "label": "原始數據",
            "description": "50 指標等權重，無環境過濾，歷史全量比對",
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
    """Return available dimensions with feature counts."""
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

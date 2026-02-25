"""Pattern Simulator — Find similar patterns & compute multi-horizon win rates.

User flow:
  1. Select a stock + query date + dimensions
  2. System finds top-K similar historical cases
  3. Returns win rates at d3/d5/d7/d14/d21/d30/d90/d180

Reuses cluster_search.py for cosine similarity + forward returns,
augments with additional horizons (d5, d14, d30) from close matrix.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TRANSACTION_COST = 0.00785  # [VERIFIED]
RETURN_HORIZONS = [3, 5, 7, 14, 21, 30, 90, 180]

# Cached close matrix for computing additional forward returns
_close_matrix: pd.DataFrame | None = None


def _load_close_matrix() -> pd.DataFrame:
    """Load close price matrix (1943 stocks × 790 days)."""
    global _close_matrix
    if _close_matrix is not None:
        return _close_matrix

    from pathlib import Path
    path = Path(__file__).parent.parent / "data" / "pit_close_matrix.parquet"
    if path.exists():
        _close_matrix = pd.read_parquet(path)
        logger.info("Close matrix loaded: %s", _close_matrix.shape)
    else:
        _close_matrix = pd.DataFrame()
    return _close_matrix


def compute_forward_returns(stock_code: str, date: str, horizons: list[int] = None) -> dict:
    """Compute forward returns for a stock at a given date.

    Uses close matrix for fast vectorized computation.
    Returns: {f"d{h}": return_pct, ...}
    """
    if horizons is None:
        horizons = RETURN_HORIZONS

    cm = _load_close_matrix()
    if cm.empty or stock_code not in cm.columns:
        return {}

    prices = cm[stock_code].dropna()
    target_date = pd.Timestamp(date)

    # Find the closest date on or before target
    valid = prices.index[prices.index <= target_date]
    if len(valid) == 0:
        return {}
    base_idx = prices.index.get_loc(valid[-1])
    base_price = float(prices.iloc[base_idx])

    if base_price <= 0:
        return {}

    result = {}
    for h in horizons:
        fwd_idx = base_idx + h
        if fwd_idx < len(prices):
            fwd_price = float(prices.iloc[fwd_idx])
            if fwd_price > 0:
                result[f"d{h}"] = (fwd_price / base_price) - 1.0
    return result


def compute_forward_paths(cases: list[dict], max_days: int = 90) -> list[dict]:
    """Compute normalized forward price paths for spaghetti chart.

    For each case, returns the price trajectory from T=0 to T+max_days,
    normalized to start at 1.0.

    Returns:
        [{stock_code, date, path: [1.0, 1.02, ...], days: [0, 1, 2, ...]}, ...]
    """
    cm = _load_close_matrix()
    if cm.empty:
        return []

    paths = []
    for case in cases:
        code = case.get("stock_code", "")
        date = case.get("date", "")

        if code not in cm.columns:
            continue

        prices = cm[code].dropna().sort_index()
        target_date = pd.Timestamp(date)

        valid = prices.index[prices.index <= target_date]
        if len(valid) == 0:
            continue

        base_idx = prices.index.get_loc(valid[-1])
        base_price = float(prices.iloc[base_idx])
        if base_price <= 0:
            continue

        # Extract forward prices normalized to 1.0
        end_idx = min(base_idx + max_days + 1, len(prices))
        fwd_prices = prices.iloc[base_idx:end_idx]

        if len(fwd_prices) < 2:
            continue

        normalized = (fwd_prices / base_price).values.tolist()
        days = list(range(len(normalized)))

        paths.append({
            "stock_code": code,
            "date": str(target_date.date()),
            "path": [round(v, 4) for v in normalized],
            "days": days,
        })

    return paths


def compute_path_statistics(paths: list[dict]) -> dict:
    """Compute mean, median, worst case paths from spaghetti data.

    Returns:
        {mean_path, median_path, worst_path, best_path, p25_path, p75_path, days}
    """
    if not paths:
        return {}

    max_len = max(len(p["path"]) for p in paths)
    # Pad shorter paths with NaN
    matrix = np.full((len(paths), max_len), np.nan)
    for i, p in enumerate(paths):
        matrix[i, :len(p["path"])] = p["path"]

    days = list(range(max_len))
    # Compute statistics ignoring NaN
    with np.errstate(all="ignore"):
        mean_path = [round(float(np.nanmean(matrix[:, d])), 4) for d in range(max_len)]
        median_path = [round(float(np.nanmedian(matrix[:, d])), 4) for d in range(max_len)]
        p25_path = [round(float(np.nanpercentile(matrix[:, d], 25)), 4) for d in range(max_len)]
        p75_path = [round(float(np.nanpercentile(matrix[:, d], 75)), 4) for d in range(max_len)]

    # Worst = path with lowest final value
    finals = [p["path"][-1] if p["path"] else 1.0 for p in paths]
    worst_idx = int(np.argmin(finals))
    best_idx = int(np.argmax(finals))

    return {
        "days": days,
        "mean_path": mean_path,
        "median_path": median_path,
        "p25_path": p25_path,
        "p75_path": p75_path,
        "worst_path": paths[worst_idx]["path"],
        "worst_case": {"stock_code": paths[worst_idx]["stock_code"], "date": paths[worst_idx]["date"]},
        "best_path": paths[best_idx]["path"],
        "best_case": {"stock_code": paths[best_idx]["stock_code"], "date": paths[best_idx]["date"]},
        "path_count": len(paths),
    }


def _compute_multi_horizon_stats(cases: list[dict]) -> dict:
    """Compute statistics for all RETURN_HORIZONS.

    Similar to cluster_search._compute_statistics but with more horizons.
    """
    horizons = [f"d{h}" for h in RETURN_HORIZONS]

    stats = {
        "sample_count": len(cases),
        "small_sample": len(cases) < 30,
    }

    for h in horizons:
        vals = [c["returns"].get(h) for c in cases if c["returns"].get(h) is not None]
        if not vals:
            stats[h] = {"count": 0, "win_rate": None, "mean": None, "median": None, "expectancy": None}
            continue

        arr = np.array(vals)
        arr_net = arr - TRANSACTION_COST

        wins = arr_net[arr_net > 0]
        losses = arr_net[arr_net <= 0]
        wr = float(np.mean(arr_net > 0))
        avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
        avg_loss = float(np.mean(np.abs(losses))) if len(losses) > 0 else 0.0
        exp = wr * avg_win - (1 - wr) * avg_loss

        stats[h] = {
            "count": len(vals),
            "win_rate": round(wr, 4),
            "mean": round(float(np.mean(arr_net)), 4),
            "median": round(float(np.median(arr_net)), 4),
            "std": round(float(np.std(arr_net)), 4),
            "min": round(float(np.min(arr_net)), 4),
            "max": round(float(np.max(arr_net)), 4),
            "p25": round(float(np.percentile(arr_net, 25)), 4),
            "p75": round(float(np.percentile(arr_net, 75)), 4),
            "expectancy": round(exp, 4),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
        }

    return stats


def _compute_confidence(cases: list[dict], statistics: dict) -> dict:
    """Compute confidence scoring for pattern simulation results.

    Factors:
      1. Sample Size Factor: more cases = higher confidence (capped at 30)
      2. Consistency Factor: low std/mean ratio = cases agree
      3. Directional Agreement: what % of cases point the same direction

    Returns:
        {score: 0-100, grade: "HIGH"/"MEDIUM"/"LOW", factors: {...},
         expected_return_range: {low, high}}
    """
    n = len(cases)
    if n == 0:
        return {"score": 0, "grade": "LOW", "factors": {}}

    # 1. Sample size (0-30 points): linear scale, caps at 30 cases
    size_score = min(n / 30.0, 1.0) * 30

    # 2. Consistency at d21 horizon (0-40 points): lower CV = more consistent
    d21_stats = statistics.get("d21", {})
    if d21_stats and d21_stats.get("std") is not None and d21_stats.get("mean") is not None:
        std = abs(d21_stats["std"])
        mean = abs(d21_stats["mean"])
        cv = std / mean if mean > 0.001 else 10.0
        # CV < 0.5 = very consistent (40pts), CV > 3 = no consistency (0pts)
        consistency_score = max(0, min(1, (3.0 - cv) / 2.5)) * 40
    else:
        consistency_score = 0

    # 3. Directional agreement at d21 (0-30 points)
    d21_vals = [c["returns"].get("d21") for c in cases if c["returns"].get("d21") is not None]
    if d21_vals:
        positive = sum(1 for v in d21_vals if v > 0)
        agreement = max(positive, len(d21_vals) - positive) / len(d21_vals)
        direction_score = agreement * 30
    else:
        direction_score = 0

    total = round(size_score + consistency_score + direction_score)
    grade = "HIGH" if total >= 65 else "MEDIUM" if total >= 40 else "LOW"

    # Expected return range (95% CI) at d21
    expected_range = {}
    if d21_vals:
        arr = np.array(d21_vals) - TRANSACTION_COST
        se = float(np.std(arr)) / max(np.sqrt(len(arr)), 1)
        mean_net = float(np.mean(arr))
        expected_range = {
            "low": round(mean_net - 1.96 * se, 4),
            "high": round(mean_net + 1.96 * se, 4),
            "horizon": "d21",
        }

    return {
        "score": total,
        "grade": grade,
        "factors": {
            "sample_size": round(size_score, 1),
            "consistency": round(consistency_score, 1),
            "direction": round(direction_score, 1),
        },
        "expected_return_range": expected_range,
    }


def simulate_pattern(
    stock_code: str,
    query_date: Optional[str] = None,
    dimensions: Optional[list[str]] = None,
    top_k: int = 30,
) -> dict:
    """Run pattern simulation: find similar cases & compute multi-horizon win rates.

    Args:
        stock_code: Target stock code
        query_date: Date to query (default: latest available)
        dimensions: Which dimensions to match (default: all 6)
        top_k: Number of similar cases to find

    Returns:
        {
            "query": {stock_code, date, dimensions},
            "cases": [{stock_code, date, similarity, returns: {d3,d5,...,d180}}],
            "statistics": {d3: {win_rate, mean, ...}, d5: {...}, ...},
            "spaghetti": [{stock_code, date, prices: [normalized 90d forward]}],
        }
    """
    from analysis.cluster_search import find_similar_dual

    # Run the existing similarity search
    dual = find_similar_dual(
        stock_code=stock_code,
        query_date=query_date,
        top_k=top_k,
        dimensions=dimensions,
    )

    # Extract raw block cases (Block 1 = "The Facts")
    raw_block = dual.get("raw", {})
    raw_cases = raw_block.get("similar_cases", [])

    query_info = dual.get("query", {})

    if not raw_cases:
        return {
            "query": {
                "stock_code": stock_code,
                "date": query_info.get("date", query_date),
                "dimensions": dimensions,
            },
            "cases": [],
            "statistics": _compute_multi_horizon_stats([]),
            "spaghetti": [],
        }

    # Augment cases with additional forward return horizons
    enriched_cases = []
    for case in raw_cases:
        code = case.get("stock_code", "")
        date = case.get("date", "")

        # Start from existing forward returns (d3, d7, d21, d90, d180)
        existing = case.get("forward_returns", {})

        # Compute ALL horizons from close matrix (fills both missing horizons
        # like d5/d14/d30 AND None values from parquet)
        all_returns = compute_forward_returns(code, date)

        # Merge: prefer parquet data when available, fill gaps from close matrix
        merged = {}
        for h in RETURN_HORIZONS:
            key = f"d{h}"
            if key in existing and existing[key] is not None:
                merged[key] = existing[key]
            elif key in all_returns:
                merged[key] = all_returns[key]

        enriched_cases.append({
            "stock_code": code,
            "date": date,
            "similarity": case.get("similarity", 0),
            "returns": merged,
            "dim_breakdown": case.get("dimension_similarities", {}),
        })

    # Compute multi-horizon statistics
    statistics = _compute_multi_horizon_stats(enriched_cases)

    # Confidence scoring
    statistics["confidence"] = _compute_confidence(enriched_cases, statistics)

    # Spaghetti chart: compute normalized forward price paths
    spaghetti_paths = compute_forward_paths(enriched_cases, max_days=90)
    spaghetti_stats = compute_path_statistics(spaghetti_paths)

    return {
        "query": {
            "stock_code": stock_code,
            "date": query_info.get("date", query_date),
            "dimensions": dimensions or dual.get("dimensions_used", []),
            "total_features": raw_block.get("description", ""),
        },
        "cases": enriched_cases,
        "statistics": statistics,
        "spaghetti": {
            "paths": spaghetti_paths,
            "stats": spaghetti_stats,
        },
        "sniper_assessment": dual.get("sniper_assessment", {}),
    }


def get_available_dimensions() -> list[dict]:
    """Return available dimensions with feature counts."""
    try:
        from analysis.cluster_search import _load_metadata
        meta = _load_metadata()
        dims = []
        for key, info in meta.get("dimensions", {}).items():
            dims.append({
                "key": key,
                "label": info.get("label", key),
                "features": info.get("count", 0),
            })
        return dims
    except Exception:
        return [
            {"key": "technical", "label": "技術面", "features": 20},
            {"key": "institutional", "label": "法人面", "features": 11},
            {"key": "brokerage", "label": "分點面", "features": 14},
            {"key": "industry", "label": "產業面", "features": 5},
            {"key": "fundamental", "label": "基本面", "features": 8},
            {"key": "attention", "label": "輿情面", "features": 7},
        ]

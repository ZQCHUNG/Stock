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

    # Spaghetti chart data (reuse from dual result)
    spaghetti = raw_block.get("forward_paths", [])

    return {
        "query": {
            "stock_code": stock_code,
            "date": query_info.get("date", query_date),
            "dimensions": dimensions or dual.get("dimensions_used", []),
            "total_features": raw_block.get("description", ""),
        },
        "cases": enriched_cases,
        "statistics": statistics,
        "spaghetti": spaghetti,
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

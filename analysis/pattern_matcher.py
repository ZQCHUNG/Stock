"""相似線型匹配器 — DTW (Dynamic Time Warping)

根據 Gemini R30 建議：
- 使用 DTW 而非 Correlation（台股散戶多、節奏不穩定）
- Z-score normalization 降維 → Top N 候選 → DTW 精算
- Window: 20 天（短線）/ 60 天（波段）

Usage:
    from analysis.pattern_matcher import find_similar_stocks
    results = find_similar_stocks("2330", window=20, top_n=10)
"""

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

_logger = logging.getLogger(__name__)


# ============================================================
# DTW Algorithm (pure numpy, no external dependency)
# ============================================================

def dtw_distance(s1: np.ndarray, s2: np.ndarray) -> float:
    """Compute DTW distance between two 1D time series.

    Uses O(n*m) dynamic programming. For our use case (n,m ≤ 60),
    this is fast enough without windowing constraints.
    """
    n, m = len(s1), len(s2)
    if n == 0 or m == 0:
        return float("inf")

    # Cost matrix
    dtw_mat = np.full((n + 1, m + 1), float("inf"))
    dtw_mat[0, 0] = 0.0

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = abs(s1[i - 1] - s2[j - 1])
            dtw_mat[i, j] = cost + min(
                dtw_mat[i - 1, j],      # insertion
                dtw_mat[i, j - 1],      # deletion
                dtw_mat[i - 1, j - 1],  # match
            )

    return dtw_mat[n, m] / max(n, m)  # Normalize by length


def normalize_series(series: np.ndarray) -> np.ndarray:
    """Z-score normalize a price series for shape comparison.

    This removes absolute price level and focuses on relative movement pattern.
    """
    std = np.std(series)
    if std < 1e-8:
        return np.zeros_like(series)
    return (series - np.mean(series)) / std


def return_series(prices: np.ndarray) -> np.ndarray:
    """Convert price series to daily return series.

    Using returns instead of prices makes comparison scale-invariant.
    """
    if len(prices) < 2:
        return np.array([])
    return np.diff(prices) / prices[:-1]


# ============================================================
# Pre-filter: Fast screening before expensive DTW
# ============================================================

def _quick_similarity(target_returns: np.ndarray, candidate_returns: np.ndarray) -> float:
    """Fast pre-filter using Pearson correlation on return series.

    Returns correlation coefficient (-1 to 1). Higher = more similar.
    Used to quickly eliminate obviously dissimilar stocks before DTW.
    """
    if len(target_returns) != len(candidate_returns):
        min_len = min(len(target_returns), len(candidate_returns))
        target_returns = target_returns[-min_len:]
        candidate_returns = candidate_returns[-min_len:]

    if len(target_returns) < 5:
        return -1.0

    std_t = np.std(target_returns)
    std_c = np.std(candidate_returns)
    if std_t < 1e-8 or std_c < 1e-8:
        return -1.0

    corr = np.corrcoef(target_returns, candidate_returns)[0, 1]
    return float(corr) if not np.isnan(corr) else -1.0


# ============================================================
# Main API
# ============================================================

def find_similar_stocks(
    target_code: str,
    window: int = 20,
    top_n: int = 10,
    prefilter_top: int = 50,
    candidate_codes: list[str] | None = None,
    period_days: int = 365,
) -> list[dict]:
    """Find stocks with similar recent price patterns using DTW.

    Algorithm:
    1. Get target stock's last `window` days of normalized returns
    2. Get all candidate stocks' data
    3. Pre-filter: rank by Pearson correlation on returns, keep top `prefilter_top`
    4. DTW: compute exact DTW distance for pre-filtered candidates
    5. Return top `top_n` most similar stocks

    Args:
        target_code: Stock code to find similar patterns for
        window: Number of trading days to compare (20=monthly, 60=quarterly)
        top_n: Number of similar stocks to return
        prefilter_top: How many candidates to pass to DTW stage
        candidate_codes: Specific stock codes to compare against (None = all)
        period_days: How far back to fetch data

    Returns:
        List of dicts: [
            {
                "code": "2317",
                "name": "鴻海",
                "dtw_distance": 1.23,
                "correlation": 0.85,
                "target_return_pct": 5.2,
                "candidate_return_pct": 4.8,
                "similarity_score": 87.5,
            },
            ...
        ]
    """
    from data.fetcher import get_stock_data

    # Step 1: Get target data
    target_df = get_stock_data(target_code, period_days=period_days)
    if target_df is None or len(target_df) < window:
        _logger.warning("Insufficient data for target %s (%d rows needed)",
                        target_code, window)
        return []

    target_prices = target_df["close"].values[-window:]
    target_norm = normalize_series(target_prices)
    target_returns = return_series(target_prices)
    target_return_pct = (target_prices[-1] / target_prices[0] - 1) * 100

    # Step 2: Get candidate list
    if candidate_codes is None:
        try:
            from data.stock_list import get_all_stocks
            all_stocks = get_all_stocks()
            candidate_codes = [c for c in all_stocks.keys() if c != target_code]
        except Exception:
            _logger.error("Cannot load stock list")
            return []

    candidate_codes = [c for c in candidate_codes if c != target_code]
    _logger.info("Pattern matching %s (window=%d): %d candidates",
                 target_code, window, len(candidate_codes))

    # Step 3: Pre-filter with fast correlation
    prefilter_results = []
    for code in candidate_codes:
        try:
            df = get_stock_data(code, period_days=period_days)
            if df is None or len(df) < window:
                continue

            prices = df["close"].values[-window:]
            returns = return_series(prices)
            corr = _quick_similarity(target_returns, returns)

            prefilter_results.append({
                "code": code,
                "prices": prices,
                "returns": returns,
                "correlation": corr,
                "return_pct": (prices[-1] / prices[0] - 1) * 100,
            })
        except Exception as e:
            _logger.debug("Skip %s: %s", code, e)
            continue

    if not prefilter_results:
        return []

    # Sort by correlation, keep top candidates
    prefilter_results.sort(key=lambda x: x["correlation"], reverse=True)
    candidates = prefilter_results[:prefilter_top]

    _logger.info("Pre-filter: %d/%d candidates passed (corr ≥ %.2f)",
                 len(candidates), len(prefilter_results),
                 candidates[-1]["correlation"] if candidates else 0)

    # Step 4: DTW on top candidates
    results = []
    for c in candidates:
        cand_norm = normalize_series(c["prices"])
        dist = dtw_distance(target_norm, cand_norm)

        # Convert DTW distance to similarity score (0-100)
        # Lower distance = higher similarity
        # Typical DTW distances range 0-5 for normalized series
        similarity = max(0, 100 - dist * 20)

        try:
            from data.stock_list import get_all_stocks
            name = get_all_stocks().get(c["code"], {}).get("name", "")
        except Exception as e:
            _logger.debug(f"Stock name lookup failed for {c['code']}: {e}")
            name = ""

        results.append({
            "code": c["code"],
            "name": name,
            "dtw_distance": round(dist, 4),
            "correlation": round(c["correlation"], 4),
            "target_return_pct": round(target_return_pct, 2),
            "candidate_return_pct": round(c["return_pct"], 2),
            "similarity_score": round(similarity, 1),
        })

    # Sort by DTW distance (ascending = most similar first)
    results.sort(key=lambda x: x["dtw_distance"])
    return results[:top_n]


def find_similar_pattern_in_history(
    target_code: str,
    window: int = 20,
    search_code: str | None = None,
    lookback_days: int = 365,
) -> list[dict]:
    """Find similar patterns in a stock's own history (or another stock's history).

    Slides a window across the historical data and finds periods where the
    pattern most closely matches the target's recent `window` days.

    Args:
        target_code: Source stock for the pattern
        window: Pattern window size
        search_code: Stock to search in (None = same stock)
        lookback_days: How far back to search

    Returns:
        List of dicts with start_date, end_date, dtw_distance, similarity_score,
        and what happened AFTER the similar pattern (forward returns).
    """
    from data.fetcher import get_stock_data

    # Get target's recent pattern
    target_df = get_stock_data(target_code, period_days=lookback_days)
    if target_df is None or len(target_df) < window:
        return []

    target_prices = target_df["close"].values[-window:]
    target_norm = normalize_series(target_prices)

    # Get search stock's full history
    search_code = search_code or target_code
    search_df = get_stock_data(search_code, period_days=lookback_days)
    if search_df is None or len(search_df) < window * 2:
        return []

    all_prices = search_df["close"].values
    all_dates = search_df.index

    # Slide window across history (excluding the most recent `window` days if same stock)
    results = []
    end_idx = len(all_prices) - window if search_code == target_code else len(all_prices)

    for i in range(0, end_idx - window + 1):
        hist_prices = all_prices[i:i + window]
        hist_norm = normalize_series(hist_prices)
        dist = dtw_distance(target_norm, hist_norm)
        similarity = max(0, 100 - dist * 20)

        # Forward returns (what happened after this pattern)
        fwd_returns = {}
        for days in [5, 10, 20]:
            fwd_idx = i + window + days - 1
            if fwd_idx < len(all_prices):
                fwd_ret = (all_prices[fwd_idx] / all_prices[i + window - 1] - 1) * 100
                fwd_returns[f"d{days}"] = round(fwd_ret, 2)

        results.append({
            "start_date": str(all_dates[i].date()),
            "end_date": str(all_dates[i + window - 1].date()),
            "dtw_distance": round(dist, 4),
            "similarity_score": round(similarity, 1),
            "forward_returns": fwd_returns,
        })

    # Sort by similarity (lowest DTW distance first)
    results.sort(key=lambda x: x["dtw_distance"])

    # Return top 20 most similar periods
    return results[:20]

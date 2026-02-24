"""Daily Pattern Update Pipeline — incremental close matrix + RS + screener refresh.

Runs at 20:15 Mon-Fri (after the 20:00 features rebuild):
  1. Extend pit_close_matrix with latest trading day(s) from yfinance
  2. Recompute PIT RS matrices from extended close matrix
  3. Refresh screener DB snapshot

Uses the existing price_cache.parquet (built by build_features.py) as the primary
data source, with yfinance incremental download as fallback for new dates.

[VERIFIED: PIPELINE_V1] — designed to run after nightly Parquet rebuild
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PRICE_CACHE_PATH = DATA_DIR / "pattern_data" / "features" / "price_cache.parquet"

# PIT matrix paths (same as analysis/pit_rs.py)
PIT_CLOSE_PATH = DATA_DIR / "pit_close_matrix.parquet"
PIT_RS_PATH = DATA_DIR / "pit_rs_matrix.parquet"
PIT_PCTILE_PATH = DATA_DIR / "pit_rs_percentile.parquet"


def extend_close_matrix() -> dict:
    """Extend pit_close_matrix.parquet with latest dates from price_cache.

    Strategy:
      1. Load existing close matrix (wide: date × stocks)
      2. Load price_cache.parquet (long: date, stock_code, close, ...)
      3. Pivot price_cache to wide format
      4. Find new dates not in existing matrix
      5. Append new dates and save

    Returns:
        {"new_dates": int, "total_dates": int, "total_stocks": int}
    """
    t0 = time.time()

    # Load existing close matrix
    if PIT_CLOSE_PATH.exists():
        existing = pd.read_parquet(PIT_CLOSE_PATH)
        existing.index = pd.to_datetime(existing.index)
        logger.info("Existing close matrix: %d dates × %d stocks", len(existing), len(existing.columns))
    else:
        logger.warning("No existing close matrix found — will build from price_cache only")
        existing = pd.DataFrame()

    # Load price_cache (long format from build_features.py)
    if not PRICE_CACHE_PATH.exists():
        logger.warning("price_cache.parquet not found — trying yfinance incremental")
        return _yf_incremental_update(existing)

    cache = pd.read_parquet(PRICE_CACHE_PATH)
    cache["date"] = pd.to_datetime(cache["date"])

    # Pivot to wide format (date × stock_code → close)
    cache_wide = cache.pivot_table(index="date", columns="stock_code", values="close")
    cache_wide = cache_wide.sort_index()
    logger.info("Price cache: %d dates × %d stocks", len(cache_wide), len(cache_wide.columns))

    if existing.empty:
        # No existing matrix — use the full price cache
        merged = cache_wide
        new_dates = len(merged)
    else:
        # Find new dates
        existing_dates = set(existing.index)
        cache_dates = set(cache_wide.index)
        new_date_set = cache_dates - existing_dates

        if not new_date_set:
            # No new dates — try yfinance for today specifically
            logger.info("Price cache has no new dates — trying yfinance for latest")
            return _yf_incremental_update(existing)

        new_dates = len(new_date_set)
        logger.info("Found %d new dates in price_cache", new_dates)

        # Merge: union of stocks, keep existing data, add new date rows
        all_stocks = sorted(set(existing.columns) | set(cache_wide.columns))
        merged = existing.reindex(columns=all_stocks)

        for date in sorted(new_date_set):
            if date in cache_wide.index:
                row = cache_wide.loc[date]
                for col in row.index:
                    if col in merged.columns:
                        merged.loc[date, col] = row[col]

        merged = merged.sort_index()

    # Save updated matrix
    PIT_CLOSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(PIT_CLOSE_PATH)

    elapsed = time.time() - t0
    result = {
        "new_dates": new_dates,
        "total_dates": len(merged),
        "total_stocks": len(merged.columns),
        "elapsed_s": round(elapsed, 1),
    }
    logger.info("Close matrix updated: +%d dates → %d × %d (%.1fs)",
                new_dates, result["total_dates"], result["total_stocks"], elapsed)
    return result


def _yf_incremental_update(existing: pd.DataFrame) -> dict:
    """Fallback: download only the latest 5 trading days from yfinance.

    This is much faster than a full rebuild — only fetches the latest data.
    """
    if existing.empty:
        logger.error("Cannot do incremental update without existing close matrix")
        return {"new_dates": 0, "error": "no_existing_matrix"}

    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed")
        return {"new_dates": 0, "error": "yfinance_not_installed"}

    t0 = time.time()
    latest_existing = existing.index.max()
    logger.info("Latest date in close matrix: %s", latest_existing.strftime("%Y-%m-%d"))

    # Download last 10 calendar days to ensure we get latest trading days
    start = (latest_existing - timedelta(days=2)).strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    # Use existing stock codes with .TW suffix
    stock_codes = list(existing.columns)
    # Load ticker cache for .TW/.TWO resolution
    from analysis.pit_rs import _build_yf_tickers
    yf_tickers = _build_yf_tickers(stock_codes)
    ticker_to_code = {}
    for code, ticker in zip(stock_codes, yf_tickers):
        ticker_to_code[ticker] = code

    new_dates_added = 0
    BATCH_SIZE = 200

    for batch_idx in range(0, len(yf_tickers), BATCH_SIZE):
        batch = yf_tickers[batch_idx:batch_idx + BATCH_SIZE]
        try:
            data = yf.download(
                batch,
                start=start,
                end=end,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if data.empty:
                continue

            if len(batch) == 1:
                ticker = batch[0]
                code = ticker_to_code.get(ticker, ticker.split(".")[0])
                if "Close" in data.columns:
                    for date, val in data["Close"].dropna().items():
                        date = pd.Timestamp(date)
                        if date not in existing.index and code in existing.columns:
                            existing.loc[date, code] = val
                            new_dates_added = max(new_dates_added, 1)
            else:
                if "Close" in data.columns.get_level_values(0):
                    close_df = data["Close"]
                    for date in close_df.index:
                        date = pd.Timestamp(date)
                        if date not in existing.index:
                            for ticker_col in close_df.columns:
                                code = ticker_to_code.get(ticker_col, ticker_col.split(".")[0])
                                val = close_df.loc[date, ticker_col]
                                if pd.notna(val) and code in existing.columns:
                                    existing.loc[date, code] = val
                            new_dates_added += 1
        except Exception as e:
            logger.warning("yf batch %d failed: %s", batch_idx // BATCH_SIZE + 1, e)

        if batch_idx + BATCH_SIZE < len(yf_tickers):
            time.sleep(0.3)

    if new_dates_added > 0:
        existing = existing.sort_index()
        existing.to_parquet(PIT_CLOSE_PATH)

    elapsed = time.time() - t0
    result = {
        "new_dates": new_dates_added,
        "total_dates": len(existing),
        "total_stocks": len(existing.columns),
        "elapsed_s": round(elapsed, 1),
        "source": "yfinance_incremental",
    }
    logger.info("yfinance incremental: +%d dates (%.1fs)", new_dates_added, elapsed)
    return result


def recompute_rs_matrices() -> dict:
    """Recompute PIT RS matrices from the (freshly extended) close matrix.

    Loads pit_close_matrix.parquet and runs the full RS computation pipeline.
    This is fast (~5-10s) since it's purely vectorized math on the matrix.

    Returns:
        {"rs_dates": int, "rs_stocks": int, "elapsed_s": float}
    """
    from analysis.pit_rs import (
        compute_pit_rs_matrix,
        compute_pit_percentiles,
        PIT_RS_CACHE_PATH,
        PIT_PCTILE_CACHE_PATH,
    )

    t0 = time.time()

    if not PIT_CLOSE_PATH.exists():
        logger.error("No close matrix found — cannot compute RS")
        return {"error": "no_close_matrix"}

    close_matrix = pd.read_parquet(PIT_CLOSE_PATH)
    close_matrix.index = pd.to_datetime(close_matrix.index)

    rs_matrix = compute_pit_rs_matrix(close_matrix)
    pctile_matrix = compute_pit_percentiles(rs_matrix)

    # Save
    PIT_RS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    rs_matrix.astype("float32").to_parquet(PIT_RS_CACHE_PATH)
    pctile_matrix.astype("float32").to_parquet(PIT_PCTILE_CACHE_PATH)

    elapsed = time.time() - t0
    result = {
        "rs_dates": len(rs_matrix),
        "rs_stocks": len(rs_matrix.columns),
        "elapsed_s": round(elapsed, 1),
    }
    logger.info("RS matrices recomputed: %d dates × %d stocks (%.1fs)",
                result["rs_dates"], result["rs_stocks"], elapsed)
    return result


def refresh_screener_db() -> dict:
    """Refresh the screener SQLite snapshot with latest data.

    Uses batch-optimized refresh from analysis/financial_screener.py.

    Returns:
        {"stocks_updated": int, "elapsed_s": float}
    """
    t0 = time.time()

    try:
        from analysis.financial_screener import refresh_screening_data
        result = refresh_screening_data()
        elapsed = time.time() - t0
        return {
            "stocks_updated": result.get("rows", 0),
            "status": result.get("status", "unknown"),
            "elapsed_s": round(elapsed, 1),
        }
    except Exception as e:
        logger.error("Screener refresh failed: %s", e)
        return {"error": str(e), "elapsed_s": round(time.time() - t0, 1)}


def run_daily_update() -> dict:
    """Run the complete daily update pipeline.

    Steps (sequential, each depends on the previous):
      1. Extend close matrix with latest prices
      2. Recompute RS matrices
      3. Refresh screener DB

    Returns:
        Summary dict with results from each step.
    """
    logger.info("=" * 60)
    logger.info("Daily Update Pipeline — starting")
    logger.info("=" * 60)

    t0 = time.time()
    results = {}

    # Step 1: Extend close matrix
    logger.info("[Step 1/3] Extending close matrix...")
    try:
        results["close_matrix"] = extend_close_matrix()
    except Exception as e:
        logger.error("Close matrix update failed: %s", e, exc_info=True)
        results["close_matrix"] = {"error": str(e)}

    # Step 2: Recompute RS matrices
    logger.info("[Step 2/3] Recomputing RS matrices...")
    try:
        results["rs_matrices"] = recompute_rs_matrices()
    except Exception as e:
        logger.error("RS recompute failed: %s", e, exc_info=True)
        results["rs_matrices"] = {"error": str(e)}

    # Step 3: Refresh screener DB
    logger.info("[Step 3/3] Refreshing screener DB...")
    try:
        results["screener"] = refresh_screener_db()
    except Exception as e:
        logger.error("Screener refresh failed: %s", e, exc_info=True)
        results["screener"] = {"error": str(e)}

    total_elapsed = time.time() - t0
    results["total_elapsed_s"] = round(total_elapsed, 1)
    results["timestamp"] = datetime.now().isoformat()

    logger.info("=" * 60)
    logger.info("Daily Update Pipeline — completed in %.1fs", total_elapsed)
    logger.info("Results: %s", results)
    logger.info("=" * 60)

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))

    result = run_daily_update()
    print("\n=== Daily Update Summary ===")
    for key, val in result.items():
        print(f"  {key}: {val}")

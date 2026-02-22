"""Point-in-Time (PIT) RS Engine — eliminates look-ahead bias in RS computation.

Gemini Wall Street Trader R10-R11 + Architect Critic APPROVED 2026-02-22

For each trading day, computes RS using ONLY data available at that point:
- RS Raw Score: (base_return)^0.6 × (recent_return)^0.4 (same as compute_rs_ratio)
- RS Percentile: Ranked against all stocks in the universe AT THAT DATE
- RS ROC 20d: 20-day rate of change of Raw Score (acceleration, not ranking)

IMPORTANT: Uses yfinance (auto_adjust=True) for split/dividend-adjusted prices.
The R88 price cache uses raw TWSE data and is NOT suitable for RS computation.

[VERIFIED: PIT_ENGINE_V1] — backtested RS aligned to physical timeline
[PLACEHOLDER: RS_ROC_ACCEL_20] — acceleration threshold needs sweep data
"""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

_logger = logging.getLogger(__name__)

# Default RS parameters (must match STRATEGY_BOLD_PARAMS)
RS_LOOKBACK = 120
RS_EXCLUDE_RECENT = 5
RS_BASE_WEIGHT = 0.6
RS_RECENT_WEIGHT = 0.4
RS_RECENT_DAYS = 20
RS_ROC_PERIOD = 20  # [PLACEHOLDER: RS_ROC_ACCEL_20] Trader R11: 20d = sweet spot

# Cache paths
PIT_CLOSE_CACHE_PATH = Path("data/pit_close_matrix.parquet")
PIT_RS_CACHE_PATH = Path("data/pit_rs_matrix.parquet")
PIT_PCTILE_CACHE_PATH = Path("data/pit_rs_percentile.parquet")

# Ticker cache for .TW/.TWO resolution
_TICKER_CACHE_FILE = Path(".cache/ticker_cache.json")


def _load_ticker_cache() -> dict[str, str]:
    """Load resolved ticker cache (code → yf ticker)."""
    try:
        if _TICKER_CACHE_FILE.exists():
            return json.loads(_TICKER_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _build_yf_tickers(stock_codes: list[str]) -> list[str]:
    """Convert stock codes to yfinance tickers using cached mappings."""
    cache = _load_ticker_cache()
    tickers = []
    for code in stock_codes:
        if code in cache:
            tickers.append(cache[code])
        else:
            tickers.append(f"{code}.TW")  # Default to .TW
    return tickers


def build_close_matrix(
    stock_codes: list[str] | None = None,
    period_days: int = 1200,
    max_workers: int = 10,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Build adjusted-close price matrix using yf.download() bulk download.

    Uses yfinance bulk download (auto_adjust=True) for split/dividend-adjusted prices.
    Much faster than individual fetches — downloads all tickers in batches.
    Caches the result to parquet for fast subsequent loads.

    Returns:
        DataFrame with index=date, columns=stock_codes, values=adjusted close.
    """
    # Try cache first
    if use_cache and PIT_CLOSE_CACHE_PATH.exists():
        close_matrix = pd.read_parquet(PIT_CLOSE_CACHE_PATH)
        close_matrix.index = pd.to_datetime(close_matrix.index)
        _logger.info(
            "Loaded cached close matrix: %d dates × %d stocks",
            len(close_matrix), len(close_matrix.columns),
        )
        return close_matrix

    # Get stock universe
    if stock_codes is None:
        import sys
        if "." not in sys.path:
            sys.path.insert(0, ".")
        from data.stock_list import get_all_stocks
        stocks = get_all_stocks()
        # Filter: 4-digit codes, no ETFs
        stock_codes = [
            code for code in stocks
            if len(code) == 4 and code[0] != "0"
        ]

    _logger.info("Building close matrix for %d stocks via yf.download()", len(stock_codes))
    t0 = time.time()

    # Convert stock codes to yfinance tickers
    yf_tickers = _build_yf_tickers(stock_codes)
    code_to_ticker = dict(zip(stock_codes, yf_tickers))
    ticker_to_code = {v: k for k, v in code_to_ticker.items()}

    # Compute date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=period_days)

    # Download in batches of 100 (yfinance can handle multi-ticker)
    BATCH_SIZE = 100
    all_close = {}

    for batch_idx in range(0, len(yf_tickers), BATCH_SIZE):
        batch = yf_tickers[batch_idx:batch_idx + BATCH_SIZE]
        batch_num = batch_idx // BATCH_SIZE + 1
        total_batches = (len(yf_tickers) + BATCH_SIZE - 1) // BATCH_SIZE
        _logger.info("  Batch %d/%d: downloading %d tickers...", batch_num, total_batches, len(batch))

        try:
            data = yf.download(
                batch,
                start=start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if data.empty:
                continue

            # yf.download returns MultiIndex columns when multiple tickers
            if len(batch) == 1:
                # Single ticker: columns are just ['Close', 'High', ...]
                ticker = batch[0]
                code = ticker_to_code.get(ticker, ticker.split(".")[0])
                if "Close" in data.columns:
                    series = data["Close"].dropna()
                    if len(series) > 100:
                        all_close[code] = series
            else:
                # Multi ticker: columns are MultiIndex (field, ticker)
                if "Close" in data.columns.get_level_values(0):
                    close_df = data["Close"]
                    for ticker_col in close_df.columns:
                        code = ticker_to_code.get(ticker_col, ticker_col.split(".")[0])
                        series = close_df[ticker_col].dropna()
                        if len(series) > 100:
                            all_close[code] = series
        except Exception as e:
            _logger.warning("  Batch %d failed: %s", batch_num, e)

        # Brief pause between batches to avoid rate limiting
        if batch_idx + BATCH_SIZE < len(yf_tickers):
            time.sleep(0.5)

    elapsed = time.time() - t0
    _logger.info(
        "Downloaded %d stocks in %.0fs (%.1f stocks/sec)",
        len(all_close), elapsed, len(all_close) / max(elapsed, 1),
    )

    # Build matrix
    close_matrix = pd.DataFrame(all_close)
    close_matrix = close_matrix.sort_index()
    close_matrix.index = pd.to_datetime(close_matrix.index)

    # Save cache
    PIT_CLOSE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    close_matrix.to_parquet(PIT_CLOSE_CACHE_PATH)
    _logger.info("Close matrix cached to %s (%d dates × %d stocks)",
                 PIT_CLOSE_CACHE_PATH, len(close_matrix), len(close_matrix.columns))

    return close_matrix


def compute_pit_rs_matrix(
    close_matrix: pd.DataFrame,
    lookback: int = RS_LOOKBACK,
    exclude_recent: int = RS_EXCLUDE_RECENT,
    base_weight: float = RS_BASE_WEIGHT,
    recent_weight: float = RS_RECENT_WEIGHT,
    recent_days: int = RS_RECENT_DAYS,
) -> pd.DataFrame:
    """Compute Point-in-Time RS Raw Score for all stocks at all dates.

    For each date t (shifted by exclude_recent):
        t2 = t - exclude_recent
        t1 = t2 - recent_days
        t0 = t2 - lookback
        base_return = close[t1] / close[t0]
        recent_return = close[t2] / close[t1]
        RS_raw = (base_return)^base_weight × (recent_return)^recent_weight

    Returns:
        DataFrame with index=date, columns=stock_codes, values=RS raw scores.
    """
    # Shift by exclude_recent to avoid contamination
    t2 = close_matrix.shift(exclude_recent)
    t1 = close_matrix.shift(exclude_recent + recent_days)
    t0 = close_matrix.shift(exclude_recent + lookback)

    # Compute returns
    base_return = t1 / t0      # 100-day base return ratio
    recent_return = t2 / t1    # 20-day recent return ratio

    # Weighted RS: (base)^0.6 × (recent)^0.4
    rs_raw = (base_return ** base_weight) * (recent_return ** recent_weight)

    # Remove rows with insufficient data (first lookback + exclude_recent rows)
    min_rows = lookback + exclude_recent + 1
    rs_raw = rs_raw.iloc[min_rows:]

    # Remove stocks that are all NaN
    valid_stocks = rs_raw.columns[rs_raw.notna().any()]
    rs_raw = rs_raw[valid_stocks]

    _logger.info(
        "PIT RS matrix: %d dates × %d stocks",
        len(rs_raw), len(rs_raw.columns),
    )
    return rs_raw


def compute_pit_percentiles(rs_matrix: pd.DataFrame) -> pd.DataFrame:
    """Convert RS raw scores to cross-sectional percentiles at each date.

    For each date, ranks all stocks and converts to percentile (0-100).
    This is the PIT equivalent of the static RS rating.
    """
    pctile = rs_matrix.rank(axis=1, pct=True, na_option="keep") * 100
    _logger.info("PIT percentiles computed: %d dates", len(pctile))
    return pctile


def compute_rs_roc(
    rs_matrix: pd.DataFrame,
    roc_period: int = RS_ROC_PERIOD,
) -> pd.DataFrame:
    """Compute RS ROC (Rate of Change) using raw scores.

    Trader R11: "Use RS Raw Score ROC, not ranking ROC."
    Formula: RS_ROC_20 = (RS_t - RS_{t-20}) / RS_{t-20}

    Positive ROC = stock is accelerating
    Negative ROC = stock is decelerating
    """
    rs_shifted = rs_matrix.shift(roc_period)
    roc = (rs_matrix - rs_shifted) / rs_shifted
    _logger.info("RS ROC computed: period=%d", roc_period)
    return roc


def build_pit_rs_full(
    close_matrix: pd.DataFrame | None = None,
    save_cache: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build full PIT RS dataset: raw scores, percentiles, ROC.

    Returns:
        (rs_matrix, pctile_matrix, roc_matrix)
    """
    if close_matrix is None:
        close_matrix = build_close_matrix()

    _logger.info("Building PIT RS matrices...")
    rs_matrix = compute_pit_rs_matrix(close_matrix)
    pctile_matrix = compute_pit_percentiles(rs_matrix)
    roc_matrix = compute_rs_roc(rs_matrix)

    if save_cache:
        PIT_RS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        rs_matrix.astype("float32").to_parquet(PIT_RS_CACHE_PATH)
        pctile_matrix.astype("float32").to_parquet(PIT_PCTILE_CACHE_PATH)
        _logger.info("PIT RS cached to %s", PIT_RS_CACHE_PATH)

    return rs_matrix, pctile_matrix, roc_matrix


def get_stock_pit_rs(
    code: str,
    rs_matrix: pd.DataFrame | None = None,
    pctile_matrix: pd.DataFrame | None = None,
    roc_matrix: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Get PIT RS data for a single stock.

    Returns:
        DataFrame with columns: rs_raw, rs_pctile, rs_roc
        Indexed by date.
    """
    if rs_matrix is None:
        if PIT_RS_CACHE_PATH.exists():
            rs_matrix = pd.read_parquet(PIT_RS_CACHE_PATH)
        else:
            raise FileNotFoundError("PIT RS cache not found. Run build_pit_rs_full() first.")

    if pctile_matrix is None:
        if PIT_PCTILE_CACHE_PATH.exists():
            pctile_matrix = pd.read_parquet(PIT_PCTILE_CACHE_PATH)
        else:
            pctile_matrix = compute_pit_percentiles(rs_matrix)

    if roc_matrix is None:
        roc_matrix = compute_rs_roc(rs_matrix)

    result = pd.DataFrame(index=rs_matrix.index)

    if code in rs_matrix.columns:
        result["rs_raw"] = rs_matrix[code]
    else:
        result["rs_raw"] = np.nan

    if code in pctile_matrix.columns:
        result["rs_pctile"] = pctile_matrix[code]
    else:
        result["rs_pctile"] = np.nan

    if code in roc_matrix.columns:
        result["rs_roc"] = roc_matrix[code]
    else:
        result["rs_roc"] = np.nan

    return result.dropna(subset=["rs_raw"])


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Quick mode: use cached close matrix or build small universe
    quick = "--quick" in sys.argv

    print("=" * 70)
    print("Building PIT RS Engine...")
    print("=" * 70)

    t0 = time.time()

    if quick:
        # Quick mode: use only our test stocks + top stocks
        test_codes = [
            "2330", "2317", "3037", "6442", "6139", "3481",
            "2634", "1513", "2882", "2890", "6505", "2302", "2328",
            "3673", "2497", "1476", "2038", "5522", "3050",
            "2603", "2409", "2618", "2303", "2412",
            "2454", "3443", "2345", "2308", "3034",
        ]
        close_matrix = build_close_matrix(stock_codes=test_codes, use_cache=False)
    else:
        close_matrix = build_close_matrix()

    rs_matrix, pctile_matrix, roc_matrix = build_pit_rs_full(close_matrix)
    elapsed = time.time() - t0

    print(f"\nDone in {elapsed:.1f}s")
    print(f"RS matrix: {rs_matrix.shape}")
    print(f"Percentile matrix: {pctile_matrix.shape}")
    print(f"ROC matrix: {roc_matrix.shape}")

    # Validate: check key stocks at various dates
    for code in ["6442", "6139", "2634", "2330"]:
        stock_rs = get_stock_pit_rs(code, rs_matrix, pctile_matrix, roc_matrix)
        if len(stock_rs) > 0:
            dates_to_check = ["2024-01-26", "2024-06-01", "2025-01-02", "2025-12-01"]
            print(f"\n{code} PIT RS:")
            for d in dates_to_check:
                row = stock_rs[stock_rs.index >= d].head(1)
                if len(row) > 0:
                    r = row.iloc[0]
                    print(f"  {row.index[0].date()}: raw={r['rs_raw']:.4f} "
                          f"pctile={r['rs_pctile']:.1f} roc={r['rs_roc']:.3f}")
        else:
            print(f"\n{code}: NOT IN MATRIX")

"""Lightweight Daily Technical Feature Builder (Close-Only).

Computes 20 technical features from pit_close_matrix.parquet (close prices only).
No external API calls, no volume/high/low data required.

Features needing volume (vol_ratio_5, vol_ratio_20) are set to NaN.
Features needing high/low are approximated from close-to-close data:
  - atr_pct: |daily return| EMA instead of true ATR
  - kd_k/kd_d: rolling min/max of close instead of true high/low
  - high_low_range: |daily return| instead of (high-low)/close
  - close_vs_high: close/rolling_20d_max instead of close/daily_high
  - gap_pct: daily return instead of open gap

Output: data/pattern_data/features/daily_features.parquet
        data/pattern_data/features/daily_feature_metadata.json

Usage:
    python data/build_daily_features.py
"""

import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

PIT_CLOSE_PATH = PROJECT_ROOT / "data" / "pit_close_matrix.parquet"
OUTPUT_DIR = PROJECT_ROOT / "data" / "pattern_data" / "features"
OUTPUT_FILE = OUTPUT_DIR / "daily_features.parquet"
METADATA_FILE = OUTPUT_DIR / "daily_feature_metadata.json"

# 20 technical feature columns (same order as feature_metadata.json technical dimension)
TECH_FEATURE_COLS = [
    "ret_1d", "ret_5d", "ret_20d",
    "ma5_ratio", "ma20_ratio", "ma60_ratio",
    "bb_position", "rsi_14", "macd_hist",
    "kd_k", "kd_d", "atr_pct",
    "vol_ratio_5", "vol_ratio_20",
    "high_low_range", "close_vs_high",
    "gap_pct", "trend_slope_20", "volatility_20",
    "rs_rating",
]

# Minimum history required for ma60 and rs_rating (60-day lookback)
MIN_HISTORY_DAYS = 60


# ---------------------------------------------------------------------------
# Vectorized feature computation (operates on full close matrix at once)
# ---------------------------------------------------------------------------


def compute_returns(close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Compute 1d, 5d, 20d returns."""
    return {
        "ret_1d": close.pct_change(fill_method=None, periods=1),
        "ret_5d": close.pct_change(fill_method=None, periods=5),
        "ret_20d": close.pct_change(fill_method=None, periods=20),
    }


def compute_ma_ratios(close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Compute close / MA ratios."""
    return {
        "ma5_ratio": close / close.rolling(5).mean(),
        "ma20_ratio": close / close.rolling(20).mean(),
        "ma60_ratio": close / close.rolling(60).mean(),
    }


def compute_bb_position(close: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Bollinger Band position: (close - lower) / (upper - lower)."""
    ma = close.rolling(window).mean()
    std = close.rolling(window).std()
    upper = ma + 2 * std
    lower = ma - 2 * std
    width = upper - lower
    width = width.replace(0, np.nan)
    return (close - lower) / width


def compute_rsi(close: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """RSI-14 from close prices, scaled to [0, 1]."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 1 - 1 / (1 + rs)
    return rsi


def compute_macd_hist(close: pd.DataFrame) -> pd.DataFrame:
    """MACD histogram (12-26-9), normalized by close price."""
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal
    return hist / close.replace(0, np.nan)


def compute_stochastic(close: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> dict[str, pd.DataFrame]:
    """Stochastic K/D approximation using rolling min/max of close.

    Without true high/low, rolling min/max of close serves as proxy.
    Scaled to [0, 1].
    """
    low_proxy = close.rolling(k_period).min()
    high_proxy = close.rolling(k_period).max()
    denom = (high_proxy - low_proxy).replace(0, np.nan)
    k = (close - low_proxy) / denom
    d = k.rolling(d_period).mean()
    return {"kd_k": k, "kd_d": d}


def compute_atr_pct(close: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """ATR% approximation from close-only: EMA of |daily return|."""
    daily_range = close.pct_change(fill_method=None).abs()
    return daily_range.ewm(span=period, adjust=False).mean()


def compute_high_low_range(close: pd.DataFrame) -> pd.DataFrame:
    """Approximate daily high-low range as |daily return|."""
    return close.pct_change(fill_method=None).abs()


def compute_close_vs_high(close: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Close / rolling 20d high (1.0 = at recent high)."""
    rolling_high = close.rolling(window).max()
    return close / rolling_high.replace(0, np.nan)


def compute_gap_pct(close: pd.DataFrame) -> pd.DataFrame:
    """Approximate gap% as daily return (no open price available)."""
    return close.pct_change(fill_method=None, periods=1)


def compute_trend_slope(close: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """20-day linear regression slope, normalized by close.

    Vectorized via rolling cov / var approach.
    """
    x = np.arange(window, dtype=np.float64)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()

    result = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    values = close.values.astype(np.float64)

    for i in range(window - 1, len(values)):
        y = values[i - window + 1: i + 1]  # (window, n_stocks)
        y_mean = np.nanmean(y, axis=0)
        cov = np.nansum((x[:, np.newaxis] - x_mean) * (y - y_mean[np.newaxis, :]), axis=0)
        slope = cov / x_var
        current = values[i]
        with np.errstate(divide="ignore", invalid="ignore"):
            norm_slope = np.where(current != 0, slope / current, np.nan)
        result.iloc[i] = norm_slope

    return result


def compute_volatility(close: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """20-day rolling volatility (std of daily returns)."""
    return close.pct_change(fill_method=None).rolling(window).std()


def compute_rs_rating(close: pd.DataFrame) -> pd.DataFrame:
    """Relative Strength percentile rank using cross-sectional 60d returns.

    No TAIEX data available in close matrix, so we use cross-sectional
    median as the market proxy. Output: percentile rank [0, 1] per date.
    """
    ret_60 = close.pct_change(fill_method=None, periods=60)
    market_ret = ret_60.median(axis=1)
    rs_raw = (1 + ret_60).div((1 + market_ret), axis=0) - 1
    return rs_raw.rank(axis=1, pct=True)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def build_daily_features(
    close_matrix_path: str = None,
    output_path: str = None,
    latest_only: bool = False,
) -> dict:
    """Build 20 technical features from close matrix.

    All computation is vectorized across the full matrix (dates x stocks).
    No per-stock loops except for trend_slope_20.

    Args:
        close_matrix_path: Path to pit_close_matrix.parquet. Default: standard.
        output_path: Path for output parquet. Default: standard.
        latest_only: If True, only keep the latest date per stock.

    Returns:
        dict with build metadata (stock_count, total_rows, elapsed_s, etc.).
    """
    t0 = time.time()

    cm_path = Path(close_matrix_path) if close_matrix_path else PIT_CLOSE_PATH
    out_path = Path(output_path) if output_path else OUTPUT_FILE

    if not cm_path.exists():
        raise FileNotFoundError(f"Close matrix not found: {cm_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Loading close matrix from %s", cm_path)
    close = pd.read_parquet(cm_path)
    close.index = pd.to_datetime(close.index)
    close = close.sort_index()
    n_dates, n_stocks = close.shape
    logger.info("Close matrix: %d dates x %d stocks", n_dates, n_stocks)

    # Compute all features (each returns wide DataFrames: dates x stocks)
    logger.info("Computing 20 technical features...")
    feature_frames = {}

    for k, v in compute_returns(close).items():
        feature_frames[k] = v
    for k, v in compute_ma_ratios(close).items():
        feature_frames[k] = v
    feature_frames["bb_position"] = compute_bb_position(close)
    feature_frames["rsi_14"] = compute_rsi(close)
    feature_frames["macd_hist"] = compute_macd_hist(close)
    for k, v in compute_stochastic(close).items():
        feature_frames[k] = v
    feature_frames["atr_pct"] = compute_atr_pct(close)

    # Volume features: NaN (no volume data in close matrix)
    nan_df = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    feature_frames["vol_ratio_5"] = nan_df.copy()
    feature_frames["vol_ratio_20"] = nan_df.copy()

    feature_frames["high_low_range"] = compute_high_low_range(close)
    feature_frames["close_vs_high"] = compute_close_vs_high(close)
    feature_frames["gap_pct"] = compute_gap_pct(close)
    feature_frames["trend_slope_20"] = compute_trend_slope(close)
    feature_frames["volatility_20"] = compute_volatility(close)
    feature_frames["rs_rating"] = compute_rs_rating(close)

    logger.info("All %d features computed, converting to long format...", len(feature_frames))

    # Convert wide -> long format: (date, stock_code, feature_1, ..., feature_20)
    stock_codes = close.columns.tolist()
    dates = close.index
    close_values = close.values

    # Stack all features into 3D array: (n_dates, n_stocks, n_features)
    feature_arrays = []
    for fname in TECH_FEATURE_COLS:
        feature_arrays.append(feature_frames[fname].values)
    feature_3d = np.stack(feature_arrays, axis=2)  # (n_dates, n_stocks, 20)

    # Build long-format indices
    date_idx = np.repeat(np.arange(n_dates), n_stocks)
    stock_idx = np.tile(np.arange(n_stocks), n_dates)

    # Mask 1: only keep rows where close is not NaN
    mask = ~np.isnan(close_values.ravel())

    # Mask 2: require MIN_HISTORY_DAYS of history for stable features
    date_mask = date_idx >= MIN_HISTORY_DAYS

    combined_mask = mask & date_mask
    date_idx = date_idx[combined_mask]
    stock_idx = stock_idx[combined_mask]

    n_rows = len(date_idx)
    logger.info("Building output DataFrame: %d rows", n_rows)

    result_data = {
        "date": dates[date_idx],
        "stock_code": np.array(stock_codes)[stock_idx],
    }
    for i, fname in enumerate(TECH_FEATURE_COLS):
        result_data[fname] = feature_3d[date_idx, stock_idx, i]

    df_out = pd.DataFrame(result_data)

    if latest_only:
        df_out = df_out.sort_values("date").groupby("stock_code").tail(1).reset_index(drop=True)
        logger.info("Latest-only filter: %d rows", len(df_out))
        n_rows = len(df_out)

    # Save parquet
    df_out.to_parquet(out_path, index=False)

    elapsed = time.time() - t0

    # Save metadata
    meta = {
        "all_features": TECH_FEATURE_COLS,
        "total_features": len(TECH_FEATURE_COLS),
        "dimensions": {
            "technical": {
                "features": TECH_FEATURE_COLS,
                "count": len(TECH_FEATURE_COLS),
                "description": "20 technical features from close-only price matrix",
            }
        },
        "extra_columns": [],
        "normalization": "raw",
        "data_source": "pit_close_matrix.parquet (close-only)",
        "close_only_approximations": [
            "atr_pct: |daily return| EMA instead of true ATR",
            "kd_k/kd_d: rolling min/max of close instead of true high/low",
            "high_low_range: |daily return| instead of (high-low)/close",
            "close_vs_high: close/rolling_max instead of close/daily_high",
            "gap_pct: daily return instead of open gap",
            "vol_ratio_5/vol_ratio_20: NaN (no volume data)",
        ],
        "stock_count": int(df_out["stock_code"].nunique()),
        "date_range": [
            str(df_out["date"].min()),
            str(df_out["date"].max()),
        ],
        "total_rows": n_rows,
        "elapsed_s": round(elapsed, 1),
    }

    meta_path = out_path.parent / "daily_feature_metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, default=str)

    logger.info(
        "Daily features built: %d rows, %d stocks, %d features, %.1fs -> %s",
        n_rows, meta["stock_count"], len(TECH_FEATURE_COLS), elapsed, out_path,
    )
    return meta


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    result = build_daily_features()
    print(f"\nDaily features built: {result['total_rows']:,} rows, "
          f"{result['stock_count']} stocks, {result['elapsed_s']}s")

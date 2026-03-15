"""Broker Reversal Score — Phase 3 F6

Leverages R88.7 broker features from Parquet to detect smart money
accumulation as a reversal confirmation signal.

Two sub-features:
  6A: Broker Feature Score — weighted combination of broker metrics
  6B: Institutional Accumulation Detection — streak + purity Z-score

All thresholds tagged [PLACEHOLDER] per protocol.
"""

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_logger = logging.getLogger(__name__)

# ---------- Paths ----------

FEATURES_PARQUET = Path(__file__).parent.parent / "data" / "pattern_data" / "features" / "features_all.parquet"

# ---------- Parameters ----------

# [PLACEHOLDER: BROKER_REV_STREAK_WEIGHT_001] — weight for consistency streak
WEIGHT_STREAK = 0.30

# [PLACEHOLDER: BROKER_REV_PURITY_WEIGHT_001] — weight for purity score
WEIGHT_PURITY = 0.25

# [PLACEHOLDER: BROKER_REV_MOMENTUM_WEIGHT_001] — weight for net momentum 5d
WEIGHT_MOMENTUM = 0.25

# [PLACEHOLDER: BROKER_REV_BUY_RATIO_WEIGHT_001] — weight for net buy ratio
WEIGHT_BUY_RATIO = 0.20

# [PLACEHOLDER: BROKER_REV_ACCUM_STREAK_MIN_001] — minimum streak for accumulation
ACCUM_STREAK_MIN = 3

# [PLACEHOLDER: BROKER_REV_ACCUM_PURITY_ZSCORE_001] — minimum purity Z-score
ACCUM_PURITY_ZSCORE_MIN = 0.6

# [PLACEHOLDER: BROKER_REV_LOOKBACK_DAYS_001] — days of data to look back
LOOKBACK_DAYS = 20

# Broker feature columns used
BROKER_COLS = [
    "broker_consistency_streak",
    "broker_purity_score",
    "broker_net_momentum_5d",
    "broker_net_buy_ratio",
    "broker_winner_momentum",
]

# ---------- Parquet Loader ----------

_parquet_cache: pd.DataFrame | None = None


def _load_parquet(path: Path | None = None) -> pd.DataFrame | None:
    """Load features Parquet with caching.

    Returns None if file does not exist or is unreadable.
    """
    global _parquet_cache
    if _parquet_cache is not None:
        return _parquet_cache

    parquet_path = path or FEATURES_PARQUET
    if not parquet_path.exists():
        _logger.warning("Features parquet not found: %s", parquet_path)
        return None

    try:
        _parquet_cache = pd.read_parquet(parquet_path)
        return _parquet_cache
    except Exception as e:
        _logger.error("Failed to load parquet: %s", e)
        return None


def clear_cache() -> None:
    """Clear the parquet cache (for testing)."""
    global _parquet_cache
    _parquet_cache = None


def _get_stock_data(
    stock_code: str,
    df: pd.DataFrame | None = None,
    lookback: int = LOOKBACK_DAYS,
) -> pd.DataFrame | None:
    """Get recent broker data for a stock from the Parquet.

    Args:
        stock_code: Stock code (e.g., "2330").
        df: Pre-loaded DataFrame (optional, for testing).
        lookback: Number of recent days to return.

    Returns:
        DataFrame with broker columns for the stock, or None.
    """
    if df is None:
        df = _load_parquet()
    if df is None:
        return None

    mask = df["stock_code"] == stock_code
    stock_df = df.loc[mask].copy()

    if stock_df.empty:
        return None

    stock_df = stock_df.sort_values("date")

    # Take last N days
    if len(stock_df) > lookback:
        stock_df = stock_df.tail(lookback)

    return stock_df


# ---------- F6A: Broker Feature Score ----------

def compute_broker_feature_score(
    stock_code: str,
    df: pd.DataFrame | None = None,
) -> tuple[float | None, dict[str, Any]]:
    """Compute weighted broker feature score (0-100).

    Uses the most recent row from the Parquet for:
    - broker_consistency_streak: positive = accumulation
    - broker_purity_score: high = smart money
    - broker_net_momentum_5d: rising = demand building
    - broker_net_buy_ratio: > 0.5 = net buying

    Args:
        stock_code: Stock code.
        df: Pre-loaded DataFrame (optional).

    Returns:
        (score, details_dict) or (None, {}) if data unavailable.
    """
    stock_df = _get_stock_data(stock_code, df)
    if stock_df is None or stock_df.empty:
        return None, {"reason": "no_data"}

    latest = stock_df.iloc[-1]

    # Extract features, handling NaN
    streak = latest.get("broker_consistency_streak", np.nan)
    purity = latest.get("broker_purity_score", np.nan)
    momentum = latest.get("broker_net_momentum_5d", np.nan)
    buy_ratio = latest.get("broker_net_buy_ratio", np.nan)

    # Check if we have enough non-NaN features
    values = {"streak": streak, "purity": purity, "momentum": momentum, "buy_ratio": buy_ratio}
    nan_count = sum(1 for v in values.values() if pd.isna(v))

    if nan_count >= 3:
        return None, {"reason": "insufficient_features", "nan_count": nan_count}

    # Normalize each feature to 0-100 scale
    # Streak: positive is good, cap at 10 days -> 100
    streak_score = 0.0
    if not pd.isna(streak):
        streak_score = max(0.0, min(100.0, float(streak) * 10.0))

    # Purity: already 0-100 scale (from broker_features.py)
    purity_score = 0.0
    if not pd.isna(purity):
        purity_score = max(0.0, min(100.0, float(purity)))

    # Momentum 5d: typically -1 to 1, scale to 0-100
    momentum_score = 0.0
    if not pd.isna(momentum):
        momentum_score = max(0.0, min(100.0, (float(momentum) + 1.0) * 50.0))

    # Buy ratio: 0-1, >0.5 is buying; scale to 0-100
    buy_ratio_score = 0.0
    if not pd.isna(buy_ratio):
        buy_ratio_score = max(0.0, min(100.0, float(buy_ratio) * 100.0))

    # Weighted combination
    total_weight = 0.0
    weighted_sum = 0.0

    for name, sub_score, weight in [
        ("streak", streak_score, WEIGHT_STREAK),
        ("purity", purity_score, WEIGHT_PURITY),
        ("momentum", momentum_score, WEIGHT_MOMENTUM),
        ("buy_ratio", buy_ratio_score, WEIGHT_BUY_RATIO),
    ]:
        if not pd.isna(values[name]):
            weighted_sum += sub_score * weight
            total_weight += weight

    if total_weight <= 0:
        return None, {"reason": "all_nan"}

    # Normalize by actual weight used
    score = round(weighted_sum / total_weight, 1)
    score = max(0.0, min(100.0, score))

    details = {
        "streak": round(float(streak), 2) if not pd.isna(streak) else None,
        "streak_score": round(streak_score, 1),
        "purity": round(float(purity), 2) if not pd.isna(purity) else None,
        "purity_score": round(purity_score, 1),
        "momentum": round(float(momentum), 4) if not pd.isna(momentum) else None,
        "momentum_score": round(momentum_score, 1),
        "buy_ratio": round(float(buy_ratio), 4) if not pd.isna(buy_ratio) else None,
        "buy_ratio_score": round(buy_ratio_score, 1),
        "nan_count": nan_count,
        "date": str(latest.get("date", "")),
    }

    return score, details


# ---------- F6B: Institutional Accumulation Detection ----------

def detect_institutional_accumulation(
    stock_code: str,
    df: pd.DataFrame | None = None,
    streak_min: int = ACCUM_STREAK_MIN,
    purity_zscore_min: float = ACCUM_PURITY_ZSCORE_MIN,
) -> dict[str, Any]:
    """Detect institutional accumulation from broker persistence patterns.

    Checks:
    - broker_consistency_streak >= streak_min (consecutive net-buy days)
    - broker_purity_score Z-score > purity_zscore_min (relative to recent history)

    Args:
        stock_code: Stock code.
        df: Pre-loaded DataFrame (optional).
        streak_min: Minimum streak for accumulation.
        purity_zscore_min: Minimum purity Z-score.

    Returns:
        Dict with has_accumulation, streak_length, confidence, details.
    """
    stock_df = _get_stock_data(stock_code, df, lookback=LOOKBACK_DAYS)
    if stock_df is None or stock_df.empty:
        return {
            "has_accumulation": False,
            "streak_length": 0,
            "confidence": 0.0,
            "reason": "no_data",
        }

    latest = stock_df.iloc[-1]

    # Check streak
    streak = latest.get("broker_consistency_streak", 0)
    if pd.isna(streak):
        streak = 0
    streak = int(streak)

    streak_ok = streak >= streak_min

    # Check purity Z-score over the lookback window
    purity_series = stock_df["broker_purity_score"].dropna()
    if len(purity_series) < 5:
        # Not enough data for Z-score
        return {
            "has_accumulation": False,
            "streak_length": streak,
            "confidence": 0.0,
            "reason": "insufficient_purity_data",
        }

    purity_mean = purity_series.mean()
    purity_std = purity_series.std(ddof=1)
    current_purity = purity_series.iloc[-1]

    if purity_std > 0:
        purity_zscore = (current_purity - purity_mean) / purity_std
    else:
        purity_zscore = 0.0

    purity_ok = purity_zscore > purity_zscore_min

    has_accumulation = streak_ok and purity_ok

    # Confidence: blend of streak strength and purity Z-score
    streak_conf = min(1.0, streak / (streak_min * 2)) if streak > 0 else 0.0
    purity_conf = min(1.0, max(0.0, purity_zscore / 2.0))
    confidence = round((streak_conf * 0.5 + purity_conf * 0.5) * 100, 1)

    return {
        "has_accumulation": has_accumulation,
        "streak_length": streak,
        "confidence": confidence,
        "purity_zscore": round(float(purity_zscore), 3),
        "purity_current": round(float(current_purity), 2),
        "purity_mean": round(float(purity_mean), 2),
        "streak_ok": streak_ok,
        "purity_ok": purity_ok,
    }


# ---------- Combined Score ----------

def compute_broker_reversal_score(
    stock_code: str,
    df: pd.DataFrame | None = None,
) -> tuple[float | None, dict[str, Any]]:
    """Compute combined broker reversal score.

    Combines F6A (feature score) and F6B (accumulation detection) into
    a single score 0-100.

    Args:
        stock_code: Stock code.
        df: Pre-loaded DataFrame (optional).

    Returns:
        (score, details_dict) or (None, {}) if data unavailable.
    """
    feature_score, feature_details = compute_broker_feature_score(stock_code, df)
    accum_result = detect_institutional_accumulation(stock_code, df)

    if feature_score is None:
        return None, {
            "feature": feature_details,
            "accumulation": accum_result,
        }

    # Base score from features
    score = feature_score

    # Bonus for institutional accumulation
    # [PLACEHOLDER: BROKER_REV_ACCUM_BONUS_001]
    if accum_result["has_accumulation"]:
        accum_bonus = 15.0  # [PLACEHOLDER]
        score = min(100.0, score + accum_bonus)

    score = round(score, 1)

    return score, {
        "feature_score": feature_score,
        "accumulation": accum_result,
        "final_score": score,
    }

"""Reversal Detection System — Phase 1+2+3

Detects potential trend reversal signals using:
- F1: Spring Detection — Wyckoff spring (price pierces support then recovers with volume)
- F2: RSI Divergence — bullish/bearish divergence between price and RSI
- F3: BB Squeeze Alert — Bollinger Band width compression to historical lows
- F4: Volume Exhaustion — consecutive days of abnormally low volume
- F5: Multi-scale Accumulation — rising lows across multiple time windows
- F6: Broker Behavior — smart money accumulation from R88.7 features (bonus)

All thresholds tagged [PLACEHOLDER] per 假精確 Protocol.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from analysis.indicators import calculate_bollinger_bands, calculate_rsi, calculate_volume_analysis

_logger = logging.getLogger(__name__)

# ---------- Parameters ----------

# [PLACEHOLDER: REVERSAL_RSI_LOOKBACK_001] — swing detection window
RSI_DIVERGENCE_LOOKBACK = 60  # days to look back for swing points

# [PLACEHOLDER: REVERSAL_SWING_HALF_WIN_001] — half-window for swing detection
SWING_HALF_WIN = 5  # 5-day window: point must be min/max within +/-5 bars

# [PLACEHOLDER: REVERSAL_RSI_MIN_SPREAD_001] — minimum RSI spread for scoring
RSI_MIN_SPREAD = 2.0  # minimum RSI difference to count as divergence

# [PLACEHOLDER: REVERSAL_VOL_EXHAUST_RATIO_001] — volume exhaustion threshold
VOL_EXHAUST_RATIO = 0.5  # volume < 0.5x MA20

# [PLACEHOLDER: REVERSAL_VOL_EXHAUST_SCORE_PER_DAY_001]
VOL_EXHAUST_SCORE_PER_DAY = 25  # score per consecutive day

# [PLACEHOLDER: REVERSAL_VOL_EXTREME_RATIO_001] — bonus threshold
VOL_EXTREME_RATIO = 0.3  # if min ratio < 0.3x, add bonus

# [PLACEHOLDER: REVERSAL_VOL_EXTREME_BONUS_001]
VOL_EXTREME_BONUS = 20

# --- F1: Spring Detection ---
# [PLACEHOLDER: SPRING_SUPPORT_LOOKBACK_001] — lookback for support level
SPRING_SUPPORT_LOOKBACK = 20

# [PLACEHOLDER: SPRING_PIERCE_MIN_PCT_001] — min pierce depth below support
SPRING_PIERCE_MIN_PCT = 0.02

# [PLACEHOLDER: SPRING_RECOVERY_PCT_001] — min recovery as fraction of pierce
SPRING_RECOVERY_PCT = 0.5

# [PLACEHOLDER: SPRING_VOL_MULTIPLIER_001] — volume vs MA20 threshold
SPRING_VOL_MULTIPLIER = 1.5

# --- F3: BB Squeeze ---
# [PLACEHOLDER: BB_SQUEEZE_PERCENTILE_001] — percentile threshold for squeeze
BB_SQUEEZE_PERCENTILE = 10

# [PLACEHOLDER: BB_SQUEEZE_LOOKBACK_001] — lookback window for percentile calc
BB_SQUEEZE_LOOKBACK = 120

# --- Weights ---
# [PLACEHOLDER: REVERSAL_WEIGHT_SPRING_001]
WEIGHT_SPRING = 0.30

# [PLACEHOLDER: REVERSAL_WEIGHT_RSI_DIV_001]
WEIGHT_RSI_DIV = 0.25

# [PLACEHOLDER: REVERSAL_WEIGHT_BB_SQUEEZE_001]
WEIGHT_BB_SQUEEZE = 0.15

# [PLACEHOLDER: REVERSAL_WEIGHT_VOL_EXHAUST_001]
WEIGHT_VOL_EXHAUST = 0.15

# [PLACEHOLDER: REVERSAL_PHASE_WATCH_001]
PHASE_WATCH_THRESHOLD = 30

# [PLACEHOLDER: REVERSAL_PHASE_ALERT_001]
PHASE_ALERT_THRESHOLD = 50

# [PLACEHOLDER: REVERSAL_PHASE_STRONG_001]
PHASE_STRONG_THRESHOLD = 70

# --- F5: Multi-scale Accumulation ---
# [PLACEHOLDER: MULTISCALE_WINDOWS_001] — time windows for multi-scale check
MULTISCALE_WINDOWS = [20, 40, 60]

# [PLACEHOLDER: MULTISCALE_HIGHER_LOW_TOLERANCE_001] — tolerance for "higher" low
MULTISCALE_HIGHER_LOW_TOLERANCE = 0.005  # 0.5%

# [PLACEHOLDER: REVERSAL_WEIGHT_MULTISCALE_001]
WEIGHT_MULTISCALE = 0.15

# Minimum data requirements
MIN_DATA_RSI = 20  # need at least 20 bars for RSI + swing detection
MIN_DATA_VOL = 21  # need at least 21 bars for MA20 volume
MIN_DATA_SPRING = 21  # need support_lookback + 1
MIN_DATA_BB_SQUEEZE = 40  # need BB period (20) + some history
MIN_DATA_MULTISCALE = 25  # need at least window[0] + some margin


# ---------- Data Classes ----------

@dataclass
class ReversalSignal:
    """A single reversal sub-signal (e.g., RSI divergence, volume exhaustion)."""

    signal_type: str  # "spring" | "rsi_divergence" | "bb_squeeze" | "volume_exhaustion" | "multiscale_accumulation"
    direction: str = ""  # "bullish" | "bearish" | ""
    score: float = 0.0  # 0-100
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_type": self.signal_type,
            "direction": self.direction,
            "score": self.score,
            "details": self.details,
        }


@dataclass
class ReversalResult:
    """Composite result from all reversal detection sub-signals."""

    phase: str = "NONE"  # NONE | WATCH | ALERT | STRONG
    score: float = 0.0  # 0-100 composite score
    signals: list[ReversalSignal] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "score": self.score,
            "signals": [s.to_dict() for s in self.signals],
        }


# ---------- Swing Point Detection ----------

def _find_swing_lows(
    prices: np.ndarray,
    half_win: int = SWING_HALF_WIN,
) -> list[tuple[int, float]]:
    """Find local swing low points.

    A swing low at index i means prices[i] is the minimum
    within the window [i - half_win, i + half_win].

    Returns list of (index, price) sorted by index.
    """
    n = len(prices)
    if n < half_win * 2 + 1:
        return []

    result = []
    for i in range(half_win, n - half_win):
        window = prices[max(0, i - half_win): i + half_win + 1]
        if prices[i] == np.min(window):
            # Dedup: skip if too close to previous
            if result and i - result[-1][0] < half_win:
                if prices[i] < result[-1][1]:
                    result[-1] = (i, float(prices[i]))
            else:
                result.append((i, float(prices[i])))

    return result


def _find_swing_highs(
    prices: np.ndarray,
    half_win: int = SWING_HALF_WIN,
) -> list[tuple[int, float]]:
    """Find local swing high points.

    A swing high at index i means prices[i] is the maximum
    within the window [i - half_win, i + half_win].

    Returns list of (index, price) sorted by index.
    """
    n = len(prices)
    if n < half_win * 2 + 1:
        return []

    result = []
    for i in range(half_win, n - half_win):
        window = prices[max(0, i - half_win): i + half_win + 1]
        if prices[i] == np.max(window):
            if result and i - result[-1][0] < half_win:
                if prices[i] > result[-1][1]:
                    result[-1] = (i, float(prices[i]))
            else:
                result.append((i, float(prices[i])))

    return result


# ---------- F2: RSI Divergence ----------

def detect_rsi_divergence(
    df: pd.DataFrame,
    lookback: int = RSI_DIVERGENCE_LOOKBACK,
    half_win: int = SWING_HALF_WIN,
) -> ReversalSignal | None:
    """Detect RSI divergence (bullish and bearish).

    Bullish divergence: price makes lower low, RSI makes higher low.
    Bearish divergence: price makes higher high, RSI makes lower high.

    Args:
        df: OHLCV DataFrame with 'close' column.
        lookback: Number of bars to look back for swing detection.
        half_win: Half-window size for swing point detection.

    Returns:
        ReversalSignal or None if insufficient data.
    """
    if df is None or len(df) < MIN_DATA_RSI:
        return None

    # Calculate RSI
    df_with_rsi = calculate_rsi(df)
    if "rsi" not in df_with_rsi.columns:
        return None

    rsi = df_with_rsi["rsi"].values
    close = df_with_rsi["close"].values

    # Use only the lookback window
    start = max(0, len(close) - lookback)
    close_window = close[start:]
    rsi_window = rsi[start:]

    # Skip if RSI has too many NaN
    valid_rsi = ~np.isnan(rsi_window)
    if valid_rsi.sum() < MIN_DATA_RSI:
        return None

    # --- Check bullish divergence (swing lows) ---
    bullish_signal = _check_bullish_divergence(close_window, rsi_window, half_win)
    if bullish_signal is not None:
        return bullish_signal

    # --- Check bearish divergence (swing highs) ---
    bearish_signal = _check_bearish_divergence(close_window, rsi_window, half_win)
    if bearish_signal is not None:
        return bearish_signal

    # No divergence found
    return ReversalSignal(signal_type="rsi_divergence", score=0)


def _check_bullish_divergence(
    close: np.ndarray,
    rsi: np.ndarray,
    half_win: int,
) -> ReversalSignal | None:
    """Check for bullish RSI divergence: price lower low, RSI higher low."""
    price_lows = _find_swing_lows(close, half_win)
    if len(price_lows) < 2:
        return None

    # Compare last two swing lows
    idx1, price1 = price_lows[-2]
    idx2, price2 = price_lows[-1]

    # Price makes lower low
    if price2 >= price1:
        return None

    # RSI at those points
    rsi1 = rsi[idx1]
    rsi2 = rsi[idx2]

    if np.isnan(rsi1) or np.isnan(rsi2):
        return None

    # RSI makes higher low (divergence!)
    rsi_spread = rsi2 - rsi1
    if rsi_spread <= RSI_MIN_SPREAD:
        return None

    # Score based on RSI spread magnitude
    # [PLACEHOLDER: REVERSAL_RSI_SCORE_SCALE_001]
    score = min(100.0, rsi_spread * 5.0)  # 2-point spread = 10, 20-point = 100

    return ReversalSignal(
        signal_type="rsi_divergence",
        direction="bullish",
        score=round(score, 1),
        details={
            "swing_low_1": {"index": int(idx1), "price": round(price1, 2), "rsi": round(float(rsi1), 2)},
            "swing_low_2": {"index": int(idx2), "price": round(price2, 2), "rsi": round(float(rsi2), 2)},
            "price_change_pct": round((price2 - price1) / price1 * 100, 2),
            "rsi_spread": round(float(rsi_spread), 2),
        },
    )


def _check_bearish_divergence(
    close: np.ndarray,
    rsi: np.ndarray,
    half_win: int,
) -> ReversalSignal | None:
    """Check for bearish RSI divergence: price higher high, RSI lower high."""
    price_highs = _find_swing_highs(close, half_win)
    if len(price_highs) < 2:
        return None

    # Compare last two swing highs
    idx1, price1 = price_highs[-2]
    idx2, price2 = price_highs[-1]

    # Price makes higher high
    if price2 <= price1:
        return None

    # RSI at those points
    rsi1 = rsi[idx1]
    rsi2 = rsi[idx2]

    if np.isnan(rsi1) or np.isnan(rsi2):
        return None

    # RSI makes lower high (divergence!)
    rsi_spread = rsi1 - rsi2  # positive means rsi2 < rsi1
    if rsi_spread <= RSI_MIN_SPREAD:
        return None

    # Score based on RSI spread magnitude
    score = min(100.0, rsi_spread * 5.0)

    return ReversalSignal(
        signal_type="rsi_divergence",
        direction="bearish",
        score=round(score, 1),
        details={
            "swing_high_1": {"index": int(idx1), "price": round(price1, 2), "rsi": round(float(rsi1), 2)},
            "swing_high_2": {"index": int(idx2), "price": round(price2, 2), "rsi": round(float(rsi2), 2)},
            "price_change_pct": round((price2 - price1) / price1 * 100, 2),
            "rsi_spread": round(float(rsi_spread), 2),
        },
    )


# ---------- F1: Spring Detection ----------

def detect_spring(
    df: pd.DataFrame,
    support_lookback: int = SPRING_SUPPORT_LOOKBACK,
    pierce_min_pct: float = SPRING_PIERCE_MIN_PCT,
    recovery_pct: float = SPRING_RECOVERY_PCT,
    vol_multiplier: float = SPRING_VOL_MULTIPLIER,
) -> ReversalSignal | None:
    """Detect Wyckoff Spring: price pierces below support then recovers with volume.

    Algorithm:
    1. Support = rolling min of lows over support_lookback (excluding today)
    2. Today's low pierces below support by >= pierce_min_pct
    3. Close recovers above support (recovery >= recovery_pct of pierce depth)
    4. Volume >= vol_multiplier x volume_ma20

    Args:
        df: OHLCV DataFrame with 'low', 'close', 'volume' columns.
        support_lookback: Window for support level calculation.
        pierce_min_pct: Minimum pierce depth as fraction of support.
        recovery_pct: Minimum recovery as fraction of pierce depth.
        vol_multiplier: Volume must exceed this multiple of MA20.

    Returns:
        ReversalSignal or None if insufficient data.
    """
    if df is None or len(df) < MIN_DATA_SPRING:
        return None

    low = df["low"].values
    close = df["close"].values
    volume = df["volume"].values

    # Support level: rolling min of lows BEFORE today
    # Use the lookback window ending at yesterday
    if len(low) < support_lookback + 1:
        return None

    support = np.min(low[-(support_lookback + 1):-1])

    today_low = low[-1]
    today_close = close[-1]
    today_volume = volume[-1]

    # Pierce depth: how far below support
    pierce_depth = support - today_low
    pierce_pct = pierce_depth / support if support > 0 else 0

    if pierce_pct < pierce_min_pct:
        return ReversalSignal(
            signal_type="spring",
            score=0,
            details={"pierce_pct": round(float(pierce_pct), 4), "reason": "pierce too shallow"},
        )

    # Recovery: close should recover above support
    recovery = today_close - today_low
    full_range = pierce_depth  # depth of pierce below support
    recovery_ratio = recovery / full_range if full_range > 0 else 0

    if recovery_ratio < recovery_pct:
        return ReversalSignal(
            signal_type="spring",
            score=0,
            details={
                "pierce_pct": round(float(pierce_pct), 4),
                "recovery_ratio": round(float(recovery_ratio), 4),
                "reason": "insufficient recovery",
            },
        )

    # Volume confirmation
    vol_ma20 = np.mean(volume[-21:-1]) if len(volume) >= 21 else np.mean(volume[:-1])
    vol_ratio = today_volume / vol_ma20 if vol_ma20 > 0 else 0

    # Score calculation:
    # Base: pierce depth contribution (deeper = more significant, capped at 10%)
    pierce_score = min(50.0, (pierce_pct / 0.10) * 50.0)  # 10% pierce = 50 pts

    # Recovery contribution
    recovery_score = min(25.0, (recovery_ratio / 1.0) * 25.0)  # full recovery = 25 pts

    # Volume contribution
    if vol_ratio >= vol_multiplier:
        vol_score = min(25.0, (vol_ratio / 3.0) * 25.0)  # 3x volume = 25 pts
    else:
        # Volume below threshold — significant penalty
        vol_score = max(0.0, (vol_ratio / vol_multiplier) * 10.0)  # partial credit up to 10

    score = min(100.0, pierce_score + recovery_score + vol_score)

    direction = "bullish"

    return ReversalSignal(
        signal_type="spring",
        direction=direction,
        score=round(score, 1),
        details={
            "support": round(float(support), 2),
            "today_low": round(float(today_low), 2),
            "today_close": round(float(today_close), 2),
            "pierce_pct": round(float(pierce_pct), 4),
            "recovery_ratio": round(float(recovery_ratio), 4),
            "vol_ratio": round(float(vol_ratio), 2),
            "vol_confirmed": vol_ratio >= vol_multiplier,
        },
    )


# ---------- F3: BB Squeeze Alert ----------

def detect_bb_squeeze(
    df: pd.DataFrame,
    squeeze_lookback: int = BB_SQUEEZE_LOOKBACK,
) -> ReversalSignal | None:
    """Detect Bollinger Band width compression to historical lows.

    Algorithm:
    1. BB Width = (upper - lower) / middle * 100
    2. Percentile of current width vs last squeeze_lookback days
    3. Score: <=5th pctl -> 100, <=10th -> 80, <=20th -> 50, else 0
    4. Track compression rate vs 20 days ago

    Args:
        df: OHLCV DataFrame with 'close' column.
        squeeze_lookback: Window for percentile calculation.

    Returns:
        ReversalSignal or None if insufficient data.
    """
    if df is None or len(df) < MIN_DATA_BB_SQUEEZE:
        return None

    # Calculate Bollinger Bands
    df_bb = calculate_bollinger_bands(df)
    if "bb_upper" not in df_bb.columns or "bb_middle" not in df_bb.columns:
        return None

    upper = df_bb["bb_upper"].values
    lower = df_bb["bb_lower"].values
    middle = df_bb["bb_middle"].values

    # BB Width as percentage
    # Avoid division by zero
    valid_middle = np.where(middle > 0, middle, np.nan)
    bb_width = (upper - lower) / valid_middle * 100

    # Get the lookback window
    lookback_start = max(0, len(bb_width) - squeeze_lookback)
    width_window = bb_width[lookback_start:]

    # Remove NaN
    valid_width = width_window[~np.isnan(width_window)]
    if len(valid_width) < 20:
        return None

    current_width = bb_width[-1]
    if np.isnan(current_width):
        return None

    # Calculate percentile
    percentile = float(np.sum(valid_width <= current_width) / len(valid_width) * 100)

    # Score mapping
    if percentile <= 5:
        score = 100.0
    elif percentile <= 10:
        score = 80.0
    elif percentile <= 20:
        score = 50.0
    else:
        score = 0.0

    # Compression rate: compare to 20 days ago
    compression_rate = None
    if len(bb_width) >= 21 and not np.isnan(bb_width[-21]):
        width_20d_ago = bb_width[-21]
        if width_20d_ago > 0:
            compression_rate = round(float((current_width - width_20d_ago) / width_20d_ago * 100), 2)

    return ReversalSignal(
        signal_type="bb_squeeze",
        direction="",  # Squeeze is directionless — signals volatility expansion coming
        score=round(score, 1),
        details={
            "bb_width": round(float(current_width), 4),
            "percentile": round(percentile, 2),
            "compression_rate_pct": compression_rate,
            "lookback_days": len(valid_width),
        },
    )


# ---------- F4: Volume Exhaustion ----------

def detect_volume_exhaustion(
    df: pd.DataFrame,
    ratio_threshold: float = VOL_EXHAUST_RATIO,
) -> ReversalSignal | None:
    """Detect volume exhaustion: consecutive days where volume < threshold x MA20.

    Args:
        df: OHLCV DataFrame with 'volume' column.
        ratio_threshold: Volume ratio threshold (default 0.5x MA20).

    Returns:
        ReversalSignal or None if insufficient data.
    """
    if df is None or len(df) < MIN_DATA_VOL:
        return None

    # Calculate volume MA20
    df_vol = calculate_volume_analysis(df)
    vol = df_vol["volume"].values
    vol_ma20 = df_vol["volume_ma20"].values

    # Count consecutive days from the end where vol < threshold * MA20
    consecutive = 0
    min_ratio = float("inf")

    for i in range(len(vol) - 1, -1, -1):
        if np.isnan(vol_ma20[i]) or vol_ma20[i] <= 0:
            break
        ratio = vol[i] / vol_ma20[i]
        if ratio < ratio_threshold:
            consecutive += 1
            min_ratio = min(min_ratio, ratio)
        else:
            break

    if consecutive == 0:
        return ReversalSignal(
            signal_type="volume_exhaustion",
            score=0,
            details={"consecutive_days": 0, "min_ratio": None},
        )

    # Score: base + bonus
    score = min(100.0, consecutive * VOL_EXHAUST_SCORE_PER_DAY)

    # Bonus for extreme exhaustion
    if min_ratio < VOL_EXTREME_RATIO:
        score = min(100.0, score + VOL_EXTREME_BONUS)

    return ReversalSignal(
        signal_type="volume_exhaustion",
        direction="bullish",  # Volume exhaustion typically precedes bullish reversal
        score=round(score, 1),
        details={
            "consecutive_days": consecutive,
            "min_ratio": round(float(min_ratio), 3) if min_ratio != float("inf") else None,
        },
    )


# ---------- F5: Multi-scale Accumulation ----------

def detect_multiscale_accumulation(
    df: pd.DataFrame,
    windows: list[int] | None = None,
    tolerance: float = MULTISCALE_HIGHER_LOW_TOLERANCE,
    half_win: int = SWING_HALF_WIN,
) -> ReversalSignal | None:
    """Detect accumulation via rising swing lows at multiple time scales.

    Unlike accumulation_scanner.py (52W high anchor — too coarse), this
    detects local bottoms at multiple scales for finer-grained signals.

    Algorithm:
    1. For each window in [20, 40, 60] days:
       - Find swing lows using _find_swing_lows()
       - Check if the last 2-3 swing lows are rising (higher lows)
       - Rising lows = accumulation at that scale
    2. Score = count of windows with rising lows * 33 (max 100)
    3. Bonus: if ALL windows show rising lows = strong confirmation

    Args:
        df: OHLCV DataFrame with 'close' column.
        windows: List of lookback windows (default [20, 40, 60]).
        tolerance: Fraction tolerance for "higher" low (0.005 = 0.5%).
        half_win: Half-window for swing detection.

    Returns:
        ReversalSignal or None if insufficient data.
    """
    if df is None or len(df) < MIN_DATA_MULTISCALE:
        return None

    if windows is None:
        windows = MULTISCALE_WINDOWS

    close = df["close"].values
    rising_windows = []
    window_details = {}

    for w in windows:
        if len(close) < w:
            window_details[str(w)] = {"status": "insufficient_data"}
            continue

        # Use the last w bars
        segment = close[-w:]
        lows = _find_swing_lows(segment, half_win)

        if len(lows) < 2:
            window_details[str(w)] = {"status": "too_few_swings", "swing_count": len(lows)}
            continue

        # Check last 2-3 swing lows for rising pattern
        check_lows = lows[-3:] if len(lows) >= 3 else lows[-2:]
        is_rising = True
        for i in range(1, len(check_lows)):
            prev_price = check_lows[i - 1][1]
            curr_price = check_lows[i][1]
            # "Higher" with tolerance: curr >= prev * (1 - tolerance)
            if curr_price < prev_price * (1 - tolerance):
                is_rising = False
                break

        window_details[str(w)] = {
            "is_rising": is_rising,
            "swing_lows": [(int(idx), round(price, 2)) for idx, price in check_lows],
        }

        if is_rising:
            rising_windows.append(w)

    # Score: 33 per rising window, max 100
    # [PLACEHOLDER: MULTISCALE_SCORE_PER_WINDOW_001]
    score_per_window = 33.0
    rising_count = len(rising_windows)
    score = min(100.0, rising_count * score_per_window)

    # Bonus: all windows rising = strong multi-scale confirmation
    # [PLACEHOLDER: MULTISCALE_ALL_BONUS_001]
    all_windows_checked = sum(1 for w in windows if len(close) >= w)
    if rising_count > 0 and rising_count == all_windows_checked and all_windows_checked == len(windows):
        score = 100.0  # Full confirmation

    direction = "bullish" if score > 0 else ""

    return ReversalSignal(
        signal_type="multiscale_accumulation",
        direction=direction,
        score=round(score, 1),
        details={
            "rising_windows": rising_windows,
            "rising_count": rising_count,
            "total_windows": len(windows),
            "windows_checked": all_windows_checked,
            "window_details": window_details,
        },
    )


# ---------- Composite Detection ----------

def detect_reversal(
    df: pd.DataFrame,
    broker_score: float | None = None,
) -> ReversalResult:
    """Run all reversal sub-signals and compute composite result.

    Signals: F1 (Spring) + F2 (RSI Divergence) + F3 (BB Squeeze)
           + F4 (Volume Exhaustion) + F5 (Multi-scale Accumulation).

    Broker score (F6) is added as a bonus on top of the weighted composite
    rather than being part of the weight map, so existing signal weights
    are unaffected when broker data is unavailable.

    Args:
        df: OHLCV DataFrame.
        broker_score: Optional broker reversal score (0-100) from
            broker_reversal.compute_broker_reversal_score().

    Returns:
        ReversalResult with phase, score, and sub-signals.
    """
    result = ReversalResult()

    if df is None or len(df) < MIN_DATA_RSI:
        return result

    signals: list[ReversalSignal] = []

    # F1: Spring Detection
    spring_signal = detect_spring(df)
    if spring_signal is not None:
        signals.append(spring_signal)

    # F2: RSI Divergence
    rsi_signal = detect_rsi_divergence(df)
    if rsi_signal is not None:
        signals.append(rsi_signal)

    # F3: BB Squeeze Alert
    bb_signal = detect_bb_squeeze(df)
    if bb_signal is not None:
        signals.append(bb_signal)

    # F4: Volume Exhaustion
    vol_signal = detect_volume_exhaustion(df)
    if vol_signal is not None:
        signals.append(vol_signal)

    # F5: Multi-scale Accumulation
    ms_signal = detect_multiscale_accumulation(df)
    if ms_signal is not None:
        signals.append(ms_signal)

    result.signals = signals

    # Compute weighted composite score
    # Normalize weights to available signals
    weight_map = {
        "spring": WEIGHT_SPRING,
        "rsi_divergence": WEIGHT_RSI_DIV,
        "bb_squeeze": WEIGHT_BB_SQUEEZE,
        "volume_exhaustion": WEIGHT_VOL_EXHAUST,
        "multiscale_accumulation": WEIGHT_MULTISCALE,
    }

    active_signals = [s for s in signals if s.score > 0]
    if not active_signals:
        result.score = 0.0
        result.phase = "NONE"
        return result

    total_weight = sum(weight_map.get(s.signal_type, 0) for s in active_signals)
    if total_weight <= 0:
        result.score = 0.0
        result.phase = "NONE"
        return result

    # Normalize: redistribute weights proportionally among active signals
    weighted_sum = sum(
        weight_map.get(s.signal_type, 0) / total_weight * s.score
        for s in active_signals
    )
    composite = min(100.0, weighted_sum)

    # F6: Broker bonus (additive, not in weight map)
    # [PLACEHOLDER: REVERSAL_BROKER_BONUS_WEIGHT_001]
    broker_bonus_weight = 0.10
    if broker_score is not None and broker_score > 0:
        composite = min(100.0, composite + broker_score * broker_bonus_weight)

    result.score = round(composite, 1)

    # Phase classification
    if result.score >= PHASE_STRONG_THRESHOLD:
        result.phase = "STRONG"
    elif result.score >= PHASE_ALERT_THRESHOLD:
        result.phase = "ALERT"
    elif result.score >= PHASE_WATCH_THRESHOLD:
        result.phase = "WATCH"
    else:
        result.phase = "NONE"

    return result


# ---------- High-Level API ----------

def get_reversal_analysis(
    code: str,
    period_days: int = 400,
    include_broker: bool = False,
) -> dict[str, Any]:
    """High-level API: fetch data and run reversal detection.

    Args:
        code: Stock code (e.g., "2330").
        period_days: How many days of data to fetch.
        include_broker: If True, also compute broker reversal score (F6).

    Returns:
        dict with reversal analysis results.
    """
    from data.fetcher import get_stock_data

    df = get_stock_data(code, period_days=period_days)
    if df is None or len(df) < MIN_DATA_RSI:
        return {
            "code": code,
            "error": "Insufficient data",
            "phase": "NONE",
            "score": 0,
            "signals": [],
        }

    # Optional broker score
    broker_score = None
    broker_details = None
    if include_broker:
        try:
            from analysis.broker_reversal import compute_broker_reversal_score
            broker_score, broker_details = compute_broker_reversal_score(code)
        except Exception as e:
            _logger.warning("Broker score failed for %s: %s", code, e)

    result = detect_reversal(df, broker_score=broker_score)
    output = result.to_dict()
    output["code"] = code
    output["latest_close"] = round(float(df["close"].iloc[-1]), 2)
    output["data_points"] = len(df)

    if broker_details is not None:
        output["broker"] = broker_details

    return output

"""Reversal Detection System — Slim (backtest-validated)

300-stock / 16,372 signal backtest with statistical testing proved:
- BB Squeeze: HARMFUL (WR=46.9%, p=0.00001) — REMOVED
- Volume Exhaustion: No edge (LIFT=-1.1%) — REMOVED
- Spring: Unstable (flipped sign between 100/300 stocks) — REMOVED

Only validated signals remain:
- F2: RSI Divergence — bullish/bearish divergence (WR=55.8% in combo)
- F5: Multi-scale Accumulation — rising lows across time windows (WR=51.6% alone)
- Combo (F2+F5): STRONG phase — the ONLY statistically significant edge

All thresholds tagged [PLACEHOLDER] per jia-jing-que Protocol.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from analysis.indicators import calculate_rsi

_logger = logging.getLogger(__name__)

# ---------- Parameters ----------

# [PLACEHOLDER: REVERSAL_RSI_LOOKBACK_001] — swing detection window
RSI_DIVERGENCE_LOOKBACK = 60  # days to look back for swing points

# [PLACEHOLDER: REVERSAL_SWING_HALF_WIN_001] — half-window for swing detection
SWING_HALF_WIN = 5  # 5-day window: point must be min/max within +/-5 bars

# [PLACEHOLDER: REVERSAL_RSI_MIN_SPREAD_001] — minimum RSI spread for scoring
RSI_MIN_SPREAD = 2.0  # minimum RSI difference to count as divergence

# --- F5: Multi-scale Accumulation ---
# [PLACEHOLDER: MULTISCALE_WINDOWS_001] — time windows for multi-scale check
MULTISCALE_WINDOWS = [20, 40, 60]

# [PLACEHOLDER: MULTISCALE_HIGHER_LOW_TOLERANCE_001] — tolerance for "higher" low
MULTISCALE_HIGHER_LOW_TOLERANCE = 0.005  # 0.5%

# Minimum data requirements
MIN_DATA_RSI = 20  # need at least 20 bars for RSI + swing detection
MIN_DATA_MULTISCALE = 25  # need at least window[0] + some margin

# --- Backward-compat constants (imported by reversal_backtest.py) ---
PHASE_WATCH_THRESHOLD = 50
PHASE_ALERT_THRESHOLD = 50  # kept for import compat; ALERT phase removed
PHASE_STRONG_THRESHOLD = 80


# ---------- Data Classes ----------

@dataclass
class ReversalSignal:
    """A single reversal sub-signal (e.g., RSI divergence, multiscale accumulation)."""

    signal_type: str  # "rsi_divergence" | "multiscale_accumulation"
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
    """Composite result from reversal detection.

    Phases (backtest-validated):
        STRONG: Multi-scale + RSI Divergence BOTH triggered (WR=55.8%, p=0.0067)
        WATCH:  Multi-scale triggered alone (WR=51.6%, p=0.0075)
        NONE:   Neither triggered
    """

    phase: str = "NONE"  # NONE | WATCH | STRONG
    score: float = 0.0  # STRONG=80, WATCH=50, NONE=0
    combo_triggered: bool = False  # True when both Multi+RSI fire
    signals: list[ReversalSignal] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "score": self.score,
            "combo_triggered": self.combo_triggered,
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


# ---------- F5: Multi-scale Accumulation ----------

def detect_multiscale_accumulation(
    df: pd.DataFrame,
    windows: list[int] | None = None,
    tolerance: float = MULTISCALE_HIGHER_LOW_TOLERANCE,
    half_win: int = SWING_HALF_WIN,
) -> ReversalSignal | None:
    """Detect accumulation via rising swing lows at multiple time scales.

    Unlike accumulation_scanner.py (52W high anchor -- too coarse), this
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
    """Run validated reversal sub-signals and determine phase.

    Phase logic (backtest-validated, no weighted scores):
        STRONG: Multi-scale + RSI Divergence BOTH triggered (WR=55.8%, p=0.0067)
        WATCH:  Multi-scale triggered alone (WR=51.6%, p=0.0075)
        NONE:   Neither triggered

    Broker score (F6) is added as a bonus when available.

    Args:
        df: OHLCV DataFrame.
        broker_score: Optional broker reversal score (0-100) from
            broker_reversal.compute_broker_reversal_score().

    Returns:
        ReversalResult with phase, score, combo_triggered, and sub-signals.
    """
    result = ReversalResult()

    if df is None or len(df) < MIN_DATA_RSI:
        return result

    signals: list[ReversalSignal] = []

    # F2: RSI Divergence
    rsi_signal = detect_rsi_divergence(df)
    if rsi_signal is not None:
        signals.append(rsi_signal)

    # F5: Multi-scale Accumulation
    ms_signal = detect_multiscale_accumulation(df)
    if ms_signal is not None:
        signals.append(ms_signal)

    result.signals = signals

    # Determine which signals actually fired (score > 0)
    rsi_fired = rsi_signal is not None and rsi_signal.score > 0
    ms_fired = ms_signal is not None and ms_signal.score > 0

    # Phase classification based on backtest results
    if ms_fired and rsi_fired:
        result.phase = "STRONG"
        result.score = 80.0
        result.combo_triggered = True
    elif ms_fired:
        result.phase = "WATCH"
        result.score = 50.0
    else:
        result.phase = "NONE"
        result.score = 0.0

    # F6: Broker bonus (additive, only when we already have a signal)
    # [PLACEHOLDER: REVERSAL_BROKER_BONUS_WEIGHT_001]
    broker_bonus_weight = 0.10
    if result.score > 0 and broker_score is not None and broker_score > 0:
        result.score = min(100.0, round(result.score + broker_score * broker_bonus_weight, 1))

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

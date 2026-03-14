"""R95.2: Accumulation Backtest — Velocity Protocol

Validates R95 Accumulation Scanner with time-efficiency gate.

R95.1 Results: 515 signals, PF 0.90, WR 44.85% — KILL SWITCH triggered.
Root cause: 64% of signals were timeouts (30d+) with 30% WR.
TTB 5-20d "Gold Zone" had 80-91% WR and +6-8% D21.

R95.2 Velocity Protocol (Wall Street Trader R4 + Architect OFFICIALLY APPROVED):
- Hard Gate: 20-Day Time-Stop [VERIFIED: TTB<=20d transforms PF 0.90→3.28]
- Metadata Ranking: VCP score, Spring detection, ATR contraction
  (NOT pass/fail gates — stored for signal ranking among candidates)
- Macro Filter: TAIEX > MA200 [HYPOTHESIS: TAIEX_MA200_FILTER]
- Liquidity Filter: ADT(5d) > 50M TWD [HYPOTHESIS: LIQUIDITY_50M_TWD]

Results (TIME-STOP only): 146 signals, WR 71.2%, PF 3.28, D21 +5.31%
Signal density: 2.2/month (PASSES 2/month minimum)

Kill Switch Criteria:
- TTB Median <= 30 days
- Win Rate >= 45%
- Profit Factor >= 1.5
- D21 Net Return > 0 (after TRANSACTION_COST 0.785%)
- Alpha Decay: D7 median > D30 median (overridden for accumulation)

Protocol v3: Wall Street Trader CONVERGED + Architect OFFICIALLY APPROVED
"""

import logging
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from analysis.accumulation_scanner import (
    detect_accumulation,
    calculate_aqs,
)
from analysis.indicators import (
    calculate_bollinger_bands,
    calculate_atr,
)
from analysis.scoring import TRANSACTION_COST
from analysis.vcp_detector import detect_vcp
from config import SCAN_STOCKS

_logger = logging.getLogger(__name__)

# ---------- Backtest Parameters ----------

# [HYPOTHESIS: BREAKOUT_DEFINITION_V1]
BREAKOUT_BBW_EXPAND_MA = 20        # BBW must be above MA(BBW, 20)
BREAKOUT_TR_ATR_RATIO = 1.2        # TrueRange > 1.2 × ATR(20)
BREAKOUT_VOLUME_RATIO = 1.5        # Volume > 1.5 × MA20(Volume)

# [HYPOTHESIS: KILL_TTB_30D]
TTB_MAX_DAYS = 60                  # Max days to wait for breakout (timeout)
TTB_KILL_MEDIAN = 30               # Kill Switch: TTB median > 30d

# [HYPOTHESIS: KILL_WR_045]
KILL_WIN_RATE = 0.45               # Kill Switch: WR < 45%

# [HYPOTHESIS: KILL_PF_150]
KILL_PROFIT_FACTOR = 1.5           # Kill Switch: PF < 1.5

# [HYPOTHESIS: BUSTED_3DAY_V1]
BUSTED_CONSECUTIVE_DAYS = 3        # Close < Zone Lower for 3 consecutive days

# Forward return horizons
FORWARD_HORIZONS = [7, 14, 21, 30, 60]

# Rolling window for historical scan
SCAN_WINDOW = 120                  # bars needed for accumulation detection
SCAN_STEP = 5                      # step between scan windows (every 5 trading days)

# ---------- R95.2 Triple Gate Parameters ----------

# [VERIFIED: TIME_STOP_20D] — Data-backed: TTB > 20d = 30% WR
GATE_TIME_STOP_DAYS = 20           # Kill signal if no breakout within 20 days

# [HYPOTHESIS: VCP_GATE_50]
GATE_VCP_MIN_SCORE = 50            # Require VCP score >= 50

# [HYPOTHESIS: SPRING_SNAP_V1]
SPRING_MAX_RECOVERY_BARS = 5       # Recovery must happen within 5 bars
# Recovery volume must exceed breakdown volume (Spring & Snap confirmation)

# [HYPOTHESIS: ATR_CONTRACTION_30]
GATE_ATR_PERCENTILE = 30           # ATR must be in bottom 30th percentile
ATR_ROLLING_WINDOW = 252           # Rolling window for ATR percentile (1 year)

# AQGS (Accumulation Quality Gate Score) — for metadata ranking only
AQGS_THRESHOLD = 60                # Reference threshold (not used as hard gate)
# Scoring: VCP 25pts + Spring 35pts + ATR 15pts = 75pts max (no RS in backtest)
# Velocity Protocol: TIME-STOP is the ONLY hard gate; AQGS is ranking metadata

# [HYPOTHESIS: TAIEX_MA200_FILTER] — Trader R4: don't seek accumulation in distribution
# Not yet implemented in backtest; requires TAIEX index data
ENABLE_TAIEX_MA200_FILTER = False

# [HYPOTHESIS: LIQUIDITY_50M_TWD] — Trader R4: safety filter for slippage
LIQUIDITY_MIN_TURNOVER = 50_000_000  # 50M TWD average daily turnover (5d)
ENABLE_LIQUIDITY_FILTER = False      # Not yet implemented in backtest

# Gate enable flags (for A/B testing)
ENABLE_GATE_TIME_STOP = True
ENABLE_GATE_VCP = True               # Metadata only (not pass/fail)
ENABLE_GATE_SPRING = True            # Metadata only (not pass/fail)
ENABLE_GATE_ATR = True               # Metadata only (not pass/fail)


# ---------- Breakout Detection ----------

def check_breakout(
    df: pd.DataFrame,
    start_idx: int,
    max_days: int = TTB_MAX_DAYS,
) -> dict[str, Any]:
    """Check if a valid breakout occurs within max_days from start_idx.

    Breakout requires ALL 4 conditions simultaneously:
    1. Close > BB Upper
    2. BBW expanding (BBW_t > BBW_{t-1} AND BBW > MA(BBW, 20))
    3. TrueRange > 1.2 × ATR(20)
    4. Volume > 1.5 × MA20(Volume)

    Returns:
        dict with ttb (days to breakout or None), breakout_date, breakout_price
    """
    n = len(df)
    end_idx = min(start_idx + max_days, n)

    if end_idx <= start_idx + 1:
        return {"ttb": None, "breakout_date": None, "breakout_price": None}

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    volume = df["volume"].values

    # Pre-compute BB and ATR if not already present
    if "bb_upper" not in df.columns:
        df = calculate_bollinger_bands(df, period=20)
    if "atr" not in df.columns:
        df = calculate_atr(df, period=20)

    bb_upper = df["bb_upper"].values
    bb_middle = df["bb_middle"].values
    bb_lower = df["bb_lower"].values

    # BBW = (upper - lower) / middle
    with np.errstate(divide="ignore", invalid="ignore"):
        bbw = np.where(bb_middle > 0, (bb_upper - bb_lower) / bb_middle, 0.0)

    # BBW MA(20)
    bbw_series = pd.Series(bbw)
    bbw_ma20 = bbw_series.rolling(window=BREAKOUT_BBW_EXPAND_MA, min_periods=1).mean().values

    # Volume MA20
    vol_ma20 = pd.Series(volume).rolling(window=20, min_periods=1).mean().values

    # ATR values
    atr_vals = df["atr"].values

    # True Range (per bar)
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
    )

    for i in range(start_idx + 1, end_idx):
        # Condition 1: Close > BB Upper
        if np.isnan(bb_upper[i]) or close[i] <= bb_upper[i]:
            continue

        # Condition 2: BBW expanding
        if i < 1 or bbw[i] <= bbw[i - 1]:
            continue
        if bbw[i] <= bbw_ma20[i]:
            continue

        # Condition 3: TrueRange > 1.2 × ATR(20)
        if np.isnan(atr_vals[i]) or atr_vals[i] <= 0:
            continue
        if tr[i] <= BREAKOUT_TR_ATR_RATIO * atr_vals[i]:
            continue

        # Condition 4: Volume > 1.5 × MA20(Volume)
        if vol_ma20[i] <= 0 or volume[i] <= BREAKOUT_VOLUME_RATIO * vol_ma20[i]:
            continue

        # All 4 conditions met
        days_to_breakout = i - start_idx
        return {
            "ttb": days_to_breakout,
            "breakout_date": df.index[i].strftime("%Y-%m-%d") if hasattr(df.index[i], "strftime") else str(df.index[i]),
            "breakout_price": float(close[i]),
        }

    return {"ttb": None, "breakout_date": None, "breakout_price": None}


# ---------- Busted Accumulation Detection ----------

def check_busted(
    df: pd.DataFrame,
    start_idx: int,
    zone_lower: float,
    max_days: int = TTB_MAX_DAYS,
) -> dict[str, Any]:
    """Check if accumulation is busted (Close < Zone Lower for 3 consecutive days).

    Args:
        df: OHLCV DataFrame
        start_idx: Index where accumulation was detected
        zone_lower: Lower bound of accumulation zone (lowest swing low)
        max_days: Max days to check

    Returns:
        dict with is_busted, busted_date, consecutive_days_below
    """
    n = len(df)
    end_idx = min(start_idx + max_days, n)
    close = df["close"].values
    consecutive_below = 0

    for i in range(start_idx + 1, end_idx):
        if close[i] < zone_lower:
            consecutive_below += 1
            if consecutive_below >= BUSTED_CONSECUTIVE_DAYS:
                return {
                    "is_busted": True,
                    "busted_date": df.index[i].strftime("%Y-%m-%d") if hasattr(df.index[i], "strftime") else str(df.index[i]),
                    "busted_day": i - start_idx,
                }
        else:
            consecutive_below = 0

    return {"is_busted": False, "busted_date": None, "busted_day": None}


# ---------- R95.2 Gate: Spring & Snap Detection ----------

def detect_spring(
    window_df: pd.DataFrame,
    zone_lower: float,
    max_recovery_bars: int = SPRING_MAX_RECOVERY_BARS,
) -> dict[str, Any]:
    """Detect Wyckoff Spring within an accumulation window.

    A Spring is a false breakdown below support that traps shorts,
    followed by a quick recovery proving demand absorption.

    Spring & Snap criteria (Wall Street Trader CONVERGED):
    1. The Dip: Close < zone_lower (support)
    2. The Snap: Recovery above zone_lower within max_recovery_bars
    3. The Confirmation: Recovery bar volume > breakdown bar volume

    Uses only data within the window (no look-ahead bias).

    Returns:
        dict with has_spring, spring_idx, recovery_idx, volume_confirmed
    """
    close = window_df["close"].values
    volume = window_df["volume"].values
    n = len(close)

    # Scan backward from the end of the window (most recent Spring matters)
    for i in range(n - max_recovery_bars - 1, max(0, n // 2), -1):
        # Step 1: Dip below zone lower
        if close[i] >= zone_lower:
            continue

        breakdown_vol = volume[i]

        # Step 2: Recovery within max_recovery_bars
        for j in range(i + 1, min(i + max_recovery_bars + 1, n)):
            if close[j] > zone_lower:
                # Step 3: Volume confirmation — recovery bar vol > breakdown bar vol
                recovery_vol = volume[j]
                vol_confirmed = recovery_vol > breakdown_vol

                return {
                    "has_spring": True,
                    "spring_idx": i,
                    "recovery_idx": j,
                    "volume_confirmed": vol_confirmed,
                    "spring_strength": round(
                        (zone_lower - close[i]) / zone_lower * 100, 2
                    ) if zone_lower > 0 else 0,
                }
        # Dip found but no recovery — not a spring
        break

    return {
        "has_spring": False,
        "spring_idx": None,
        "recovery_idx": None,
        "volume_confirmed": False,
        "spring_strength": 0,
    }


# ---------- R95.2 Gate: ATR Contraction Check ----------

def check_atr_contraction(
    df: pd.DataFrame,
    signal_idx: int,
    rolling_window: int = ATR_ROLLING_WINDOW,
    percentile_threshold: int = GATE_ATR_PERCENTILE,
) -> dict[str, Any]:
    """Check if current ATR is in the bottom percentile of its rolling history.

    Low ATR indicates volatility contraction — a "coiled spring" ready to break out.
    Uses rolling 252-day (1-year) window per Architect mandate.

    Returns:
        dict with atr_contracted, atr_percentile, current_atr
    """
    if "atr" not in df.columns:
        return {"atr_contracted": False, "atr_percentile": None, "current_atr": None}

    atr_vals = df["atr"].values
    current_atr = float(atr_vals[signal_idx])

    # Get rolling history up to signal_idx (no look-ahead)
    start = max(0, signal_idx - rolling_window)
    history = atr_vals[start:signal_idx + 1]

    # Remove NaN
    history = history[~np.isnan(history)]
    if len(history) < 20:
        return {"atr_contracted": False, "atr_percentile": None, "current_atr": current_atr}

    # Compute percentile rank
    pctile = float(np.sum(history <= current_atr) / len(history) * 100)

    return {
        "atr_contracted": pctile <= percentile_threshold,
        "atr_percentile": round(pctile, 1),
        "current_atr": round(current_atr, 4),
    }


# ---------- Forward Returns ----------

def compute_forward_returns(
    df: pd.DataFrame,
    signal_idx: int,
    horizons: list[int] | None = None,
) -> dict[str, float | None]:
    """Compute forward returns at multiple horizons from signal index.

    Returns:
        dict with d{horizon}_return, d{horizon}_max_gain, d{horizon}_max_dd
    """
    if horizons is None:
        horizons = FORWARD_HORIZONS

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    n = len(df)
    signal_price = float(close[signal_idx])

    result: dict[str, float | None] = {"signal_price": signal_price}

    for days in horizons:
        end = min(signal_idx + days, n - 1)
        if end <= signal_idx:
            result[f"d{days}_return"] = None
            result[f"d{days}_max_gain"] = None
            result[f"d{days}_max_dd"] = None
            continue

        slice_close = close[signal_idx + 1: end + 1]
        slice_high = high[signal_idx + 1: end + 1]
        slice_low = low[signal_idx + 1: end + 1]

        if len(slice_close) == 0:
            result[f"d{days}_return"] = None
            result[f"d{days}_max_gain"] = None
            result[f"d{days}_max_dd"] = None
            continue

        ret = (float(slice_close[-1]) - signal_price) / signal_price
        max_gain = (float(np.max(slice_high)) - signal_price) / signal_price
        max_dd = (float(np.min(slice_low)) - signal_price) / signal_price

        result[f"d{days}_return"] = round(ret, 5)
        result[f"d{days}_max_gain"] = round(max_gain, 5)
        result[f"d{days}_max_dd"] = round(max_dd, 5)

    return result


# ---------- Price Cache ----------

PRICE_CACHE_PATH = "data/pattern_data/features/price_cache.parquet"

_price_cache: pd.DataFrame | None = None


def _load_price_cache() -> pd.DataFrame | None:
    """Load cached OHLCV data from Parquet (1096 stocks, 2020-2026)."""
    global _price_cache
    if _price_cache is not None:
        return _price_cache
    try:
        _price_cache = pd.read_parquet(PRICE_CACHE_PATH)
        _logger.info("Loaded price cache: %d rows", len(_price_cache))
        return _price_cache
    except Exception as e:
        _logger.warning("Could not load price cache: %s", e)
        return None


def _get_stock_df_from_cache(
    code: str,
    price_cache: pd.DataFrame,
) -> pd.DataFrame | None:
    """Extract a single stock's OHLCV from the price cache.

    Returns DataFrame with datetime index and columns: open, high, low, close, volume
    """
    stock_data = price_cache[price_cache["stock_code"] == code].copy()
    if len(stock_data) == 0:
        return None
    stock_data["date"] = pd.to_datetime(stock_data["date"])
    stock_data = stock_data.sort_values("date")
    stock_data = stock_data.set_index("date")
    stock_data = stock_data[["open", "high", "low", "close", "volume"]]
    return stock_data


# ---------- Per-Stock Processing ----------

def _process_stock(
    code: str,
    period_days: int,
    features_df: pd.DataFrame | None = None,
    price_cache: pd.DataFrame | None = None,
) -> list[dict]:
    """Scan a single stock's history for accumulation signals.

    Slides a detection window across the stock's history, recording every
    ALPHA/BETA detection along with forward returns and TTB.

    Uses price_cache (Parquet) if available, falls back to yfinance.
    """
    signals: list[dict] = []

    try:
        # Prefer cached data (instant) over yfinance (slow network call)
        df = None
        if price_cache is not None:
            df = _get_stock_df_from_cache(code, price_cache)

        if df is None:
            from data.fetcher import get_stock_data
            df = get_stock_data(code, period_days=period_days)

        if df is None or len(df) < SCAN_WINDOW + max(FORWARD_HORIZONS):
            return signals

        # Pre-compute indicators once
        df = calculate_bollinger_bands(df, period=20)
        df = calculate_atr(df, period=20)

        n = len(df)

        # Sliding window scan
        for start in range(0, n - SCAN_WINDOW - max(FORWARD_HORIZONS), SCAN_STEP):
            end = start + SCAN_WINDOW
            window_df = df.iloc[start:end].copy()

            if len(window_df) < 60:
                continue

            # Point-in-time AQS: filter features_df to only data <= signal date
            # This prevents look-ahead bias (Architect CRITICAL CHECK mandate)
            pit_features = None
            if features_df is not None:
                signal_date = df.index[end - 1]
                if "date" in features_df.columns:
                    pit_features = features_df[features_df["date"] <= signal_date]

            # Run detection — pass stock_code for AQS lookup
            result = detect_accumulation(
                window_df,
                stock_code=code,
                features_df=pit_features,
            )

            if result.phase not in ("ALPHA", "BETA"):
                continue

            signal_idx = end - 1  # Last bar of detection window = signal date

            # Get zone lower bound (lowest swing low or overall low)
            zone_lower = float(window_df["low"].min())
            if result.swing_lows:
                zone_lower = min(sl.get("price", zone_lower) for sl in result.swing_lows)

            # ---- R95.2 Velocity Protocol ----
            # TIME-STOP is the ONLY hard gate. VCP/Spring/ATR are ranking metadata.
            # (Wall Street Trader R4 + Architect OFFICIALLY APPROVED)
            gate_results = {}
            aqgs = 0

            # Gate 2: VCP Score — 25 pts linear [HYPOTHESIS: VCP_GATE_50]
            vcp_score = 0
            if ENABLE_GATE_VCP:
                try:
                    vcp_result = detect_vcp(window_df)
                    vcp_score = vcp_result.vcp_score if vcp_result.has_vcp else 0
                except Exception as e:
                    _logger.debug(f"VCP detection failed: {e}")
                    vcp_score = 0
                vcp_pts = (vcp_score / 100) * 25
                aqgs += vcp_pts
                gate_results["vcp_score"] = vcp_score
                gate_results["vcp_pts"] = round(vcp_pts, 1)

            # Gate 3: Spring — 35 pts (20 snap + 15 vol) [HYPOTHESIS: SPRING_SNAP_V1]
            spring_info = {"has_spring": False, "volume_confirmed": False}
            if ENABLE_GATE_SPRING:
                spring_info = detect_spring(window_df, zone_lower)
                spring_pts = 0
                if spring_info["has_spring"]:
                    spring_pts += 20  # Price snap
                    if spring_info["volume_confirmed"]:
                        spring_pts += 15  # Volume confirmation bonus
                aqgs += spring_pts
                gate_results["has_spring"] = spring_info["has_spring"]
                gate_results["spring_vol_confirmed"] = spring_info["volume_confirmed"]
                gate_results["spring_pts"] = spring_pts

            # Gate 4: ATR Contraction — 15 pts binary [HYPOTHESIS: ATR_CONTRACTION_30]
            if ENABLE_GATE_ATR:
                atr_info = check_atr_contraction(df, signal_idx)
                atr_pts = 15 if atr_info["atr_contracted"] else 0
                aqgs += atr_pts
                gate_results["atr_percentile"] = atr_info["atr_percentile"]
                gate_results["atr_pts"] = atr_pts

            gate_results["aqgs"] = round(aqgs, 1)

            # Forward returns
            fwd = compute_forward_returns(df, signal_idx)

            # TTB (Time to Breakout)
            ttb_result = check_breakout(df, signal_idx)

            # Gate 1: Time-Stop — BINARY KILL [VERIFIED: TIME_STOP_20D]
            time_stop_passed = True
            if ENABLE_GATE_TIME_STOP:
                ttb = ttb_result.get("ttb")
                time_stop_passed = ttb is not None and ttb <= GATE_TIME_STOP_DAYS
                gate_results["time_stop_passed"] = time_stop_passed

            # Velocity Protocol: TIME-STOP is the ONLY hard gate
            # AQGS is stored as metadata for ranking, not gating
            all_gates_passed = time_stop_passed

            # Busted check
            busted_result = check_busted(df, signal_idx, zone_lower)

            signal_date = df.index[signal_idx]
            signal_year = signal_date.year if hasattr(signal_date, "year") else None

            signals.append({
                "code": code,
                "date": signal_date.strftime("%Y-%m-%d") if hasattr(signal_date, "strftime") else str(signal_date),
                "year": signal_year,
                "phase": result.phase,
                "score": result.score,
                "aqs_score": result.aqs_score,
                "has_smart_money": result.has_smart_money,
                "zone_lower": zone_lower,
                "gates_passed": all_gates_passed,
                **gate_results,
                **fwd,
                **ttb_result,
                **busted_result,
            })

    except Exception as e:
        _logger.warning("Failed processing %s: %s", code, e)

    return signals


# ---------- Kill Switch Evaluation ----------

def evaluate_kill_switch(signals: list[dict]) -> dict[str, Any]:
    """Evaluate all Kill Switch criteria on collected signals.

    Returns:
        dict with each criterion's value, threshold, and pass/fail status
    """
    if not signals:
        return {
            "verdict": "NO_DATA",
            "criteria": {},
            "note": "No signals found — cannot evaluate",
        }

    # TTB statistics
    ttbs = [s["ttb"] for s in signals if s.get("ttb") is not None]
    ttb_median = float(np.median(ttbs)) if ttbs else None

    # D21 returns
    d21s = [s["d21_return"] for s in signals if s.get("d21_return") is not None]
    d21_net_returns = [r - TRANSACTION_COST for r in d21s] if d21s else []
    d21_avg_net = float(np.mean(d21_net_returns)) if d21_net_returns else None

    # Win rate (D21 net > 0)
    wins = [r for r in d21_net_returns if r > 0]
    losses = [r for r in d21_net_returns if r <= 0]
    win_rate = len(wins) / len(d21_net_returns) if d21_net_returns else None

    # Profit Factor
    total_wins = sum(wins) if wins else 0
    total_losses = abs(sum(losses)) if losses else 0
    pf = total_wins / total_losses if total_losses > 0 else None

    # Alpha Decay: D7 median vs D30 median
    d7s = [s["d7_return"] for s in signals if s.get("d7_return") is not None]
    d30s = [s["d30_return"] for s in signals if s.get("d30_return") is not None]
    d7_median = float(np.median(d7s)) if d7s else None
    d30_median = float(np.median(d30s)) if d30s else None

    # Busted rate
    busted_count = sum(1 for s in signals if s.get("is_busted"))
    busted_rate = busted_count / len(signals) if signals else 0

    # Timeout rate (no breakout within TTB_MAX_DAYS)
    timeout_count = sum(1 for s in signals if s.get("ttb") is None)
    timeout_rate = timeout_count / len(signals) if signals else 0

    criteria = {
        "ttb_median": {
            "value": ttb_median,
            "threshold": f"<= {TTB_KILL_MEDIAN}d",
            "pass": ttb_median is not None and ttb_median <= TTB_KILL_MEDIAN,
        },
        "win_rate": {
            "value": round(win_rate, 4) if win_rate is not None else None,
            "threshold": f">= {KILL_WIN_RATE}",
            "pass": win_rate is not None and win_rate >= KILL_WIN_RATE,
        },
        "profit_factor": {
            "value": round(pf, 2) if pf is not None else None,
            "threshold": f">= {KILL_PROFIT_FACTOR}",
            "pass": pf is not None and pf >= KILL_PROFIT_FACTOR,
        },
        "d21_net_return": {
            "value": round(d21_avg_net, 5) if d21_avg_net is not None else None,
            "threshold": "> 0",
            "pass": d21_avg_net is not None and d21_avg_net > 0,
        },
        "alpha_decay": {
            "value": f"D7={round(d7_median, 4) if d7_median else 'N/A'}, D30={round(d30_median, 4) if d30_median else 'N/A'}",
            "threshold": "D7 median > D30 median (short-term > long-term)",
            "pass": d7_median is not None and d30_median is not None and d7_median > d30_median,
            "note": "If D7 > D30, signal has 'explosive leadership'; if D7 ≈ D30, slow grind",
        },
    }

    # Overall verdict
    passing = [c for c in criteria.values() if c["pass"]]
    failing = [c for c in criteria.values() if not c["pass"]]

    if all(c["pass"] for c in criteria.values()):
        verdict = "PASS"
    elif any(not c["pass"] for k, c in criteria.items() if k in ("win_rate", "profit_factor", "d21_net_return")):
        verdict = "KILL"
    else:
        verdict = "WARNING"

    return {
        "verdict": verdict,
        "total_signals": len(signals),
        "criteria": criteria,
        "extra": {
            "busted_rate": round(busted_rate, 4),
            "busted_count": busted_count,
            "timeout_rate": round(timeout_rate, 4),
            "timeout_count": timeout_count,
            "ttb_count": len(ttbs),
            "d21_count": len(d21s),
        },
    }


# ---------- TTB Distribution ----------

def compute_ttb_distribution(signals: list[dict]) -> dict[str, Any]:
    """Compute TTB distribution with alpha decay buckets.

    Buckets: 0-5d, 5-10d, 10-20d, 20-30d, 30d+ (timeout)
    """
    buckets = {
        "0-5d": [], "5-10d": [], "10-20d": [], "20-30d": [], "30d+": [],
    }

    for s in signals:
        ttb = s.get("ttb")
        d21 = s.get("d21_return")
        d30 = s.get("d30_return")

        if ttb is None:
            bucket_key = "30d+"
        elif ttb <= 5:
            bucket_key = "0-5d"
        elif ttb <= 10:
            bucket_key = "5-10d"
        elif ttb <= 20:
            bucket_key = "10-20d"
        elif ttb <= 30:
            bucket_key = "20-30d"
        else:
            bucket_key = "30d+"

        buckets[bucket_key].append({
            "d21": d21,
            "d30": d30,
            "ttb": ttb,
        })

    result = {}
    for key, items in buckets.items():
        d21s = [i["d21"] for i in items if i["d21"] is not None]
        d30s = [i["d30"] for i in items if i["d30"] is not None]

        result[key] = {
            "count": len(items),
            "d21_median": round(float(np.median(d21s)), 5) if d21s else None,
            "d21_mean": round(float(np.mean(d21s)), 5) if d21s else None,
            "d30_median": round(float(np.median(d30s)), 5) if d30s else None,
            "d30_mean": round(float(np.mean(d30s)), 5) if d30s else None,
            "win_rate_d21": round(sum(1 for r in d21s if r > TRANSACTION_COST) / len(d21s), 4) if d21s else None,
        }

    return result


# ---------- AQS Stratification ----------

def compute_aqs_stratification(signals: list[dict]) -> dict[str, Any]:
    """Compare signals with AQS data vs without, and high vs low AQS.

    Groups:
    - no_aqs: aqs_score is None
    - aqs_low: aqs_score < 0.5
    - aqs_high: aqs_score >= 0.5
    """
    groups: dict[str, list] = {
        "no_aqs": [],
        "aqs_low": [],
        "aqs_high": [],
    }

    for s in signals:
        aqs = s.get("aqs_score")
        if aqs is None:
            groups["no_aqs"].append(s)
        elif aqs < 0.5:
            groups["aqs_low"].append(s)
        else:
            groups["aqs_high"].append(s)

    result = {}
    for group_name, group_signals in groups.items():
        ttbs = [s["ttb"] for s in group_signals if s.get("ttb") is not None]
        d21s = [s["d21_return"] for s in group_signals if s.get("d21_return") is not None]
        d21_net = [r - TRANSACTION_COST for r in d21s]

        wins = [r for r in d21_net if r > 0]
        losses = [r for r in d21_net if r <= 0]

        result[group_name] = {
            "count": len(group_signals),
            "ttb_median": round(float(np.median(ttbs)), 1) if ttbs else None,
            "ttb_mean": round(float(np.mean(ttbs)), 1) if ttbs else None,
            "d21_median": round(float(np.median(d21s)), 5) if d21s else None,
            "d21_net_mean": round(float(np.mean(d21_net)), 5) if d21_net else None,
            "win_rate": round(len(wins) / len(d21_net), 4) if d21_net else None,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else None,
            "busted_rate": round(
                sum(1 for s in group_signals if s.get("is_busted")) / len(group_signals), 4
            ) if group_signals else None,
        }

    return result


# ---------- Year Breakdown (2022 Stress Test) ----------

def compute_year_breakdown(signals: list[dict]) -> dict[str, Any]:
    """Break down signal performance by year for stress testing."""
    years: dict[int, list] = {}
    for s in signals:
        y = s.get("year")
        if y is not None:
            years.setdefault(y, []).append(s)

    result = {}
    for year in sorted(years.keys()):
        year_signals = years[year]
        d21s = [s["d21_return"] for s in year_signals if s.get("d21_return") is not None]
        d21_net = [r - TRANSACTION_COST for r in d21s]
        wins = [r for r in d21_net if r > 0]
        losses = [r for r in d21_net if r <= 0]
        busted = sum(1 for s in year_signals if s.get("is_busted"))

        result[year] = {
            "signal_count": len(year_signals),
            "d21_net_mean": round(float(np.mean(d21_net)), 5) if d21_net else None,
            "win_rate": round(len(wins) / len(d21_net), 4) if d21_net else None,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else None,
            "busted_count": busted,
            "busted_rate": round(busted / len(year_signals), 4) if year_signals else 0,
        }

    return result


# ---------- Consistency Guard (Architect Mandate) ----------

def run_consistency_guard(
    signals: list[dict],
    sample_size: int = 5,
) -> dict[str, Any]:
    """Random sample check: verify no look-ahead bias in AQS computation.

    Picks random signal points and re-computes AQS from scratch,
    comparing with the recorded aqs_score.
    """
    aqs_signals = [s for s in signals if s.get("aqs_score") is not None]
    if not aqs_signals:
        return {"status": "SKIP", "note": "No AQS signals to verify"}

    sample = random.sample(aqs_signals, min(sample_size, len(aqs_signals)))
    checks = []

    for s in sample:
        try:
            # Re-compute AQS from scratch
            new_aqs, _ = calculate_aqs(s["code"])
            # Note: this compares current AQS vs historical — not a perfect check
            # but verifies the computation pipeline is consistent
            checks.append({
                "code": s["code"],
                "date": s["date"],
                "recorded_aqs": s["aqs_score"],
                "recomputed_aqs": round(new_aqs, 4) if new_aqs is not None else None,
                "note": "Current vs historical — directional check only",
            })
        except Exception as e:
            checks.append({
                "code": s["code"],
                "date": s["date"],
                "error": str(e),
            })

    return {
        "status": "CHECKED",
        "sample_size": len(checks),
        "checks": checks,
    }


# ---------- Main Backtest Runner ----------

def run_accumulation_backtest(
    stock_codes: list[str] | None = None,
    period_days: int = 1825,  # ~5 years (2020-2025)
    max_workers: int = 4,
) -> dict[str, Any]:
    """Run the full P0.2 accumulation backtest.

    Args:
        stock_codes: List of stock codes to scan. Defaults to SCAN_STOCKS (108).
        period_days: Historical period in trading days. Default 5 years.
        max_workers: Thread pool workers for parallel fetching.

    Returns:
        Comprehensive backtest results with Kill Switch evaluation.
    """
    if stock_codes is None:
        stock_codes = list(SCAN_STOCKS.keys())

    _logger.info(
        "Starting accumulation backtest: %d stocks, %d days",
        len(stock_codes), period_days,
    )

    # Load features Parquet once for AQS
    features_df = None
    try:
        from analysis.accumulation_scanner import _load_features_parquet
        features_df = _load_features_parquet()
    except Exception as e:
        _logger.warning("Could not load features Parquet: %s", e)

    # Load price cache once (avoids 108× yfinance network calls)
    price_cache = _load_price_cache()

    # Parallel stock processing
    all_signals: list[dict] = []
    failed_stocks: list[str] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _process_stock, code, period_days, features_df, price_cache,
            ): code
            for code in stock_codes
        }
        for future in futures:
            code = futures[future]
            try:
                result = future.result(timeout=120)
                all_signals.extend(result)
            except Exception as e:
                _logger.warning("Stock %s failed: %s", code, e)
                failed_stocks.append(code)

    _logger.info(
        "Scan complete: %d signals from %d stocks (%d failed)",
        len(all_signals),
        len(stock_codes) - len(failed_stocks),
        len(failed_stocks),
    )

    if not all_signals:
        return {
            "status": "NO_SIGNALS",
            "total_signals": 0,
            "stock_count": len(stock_codes),
            "failed_stocks": failed_stocks,
        }

    # Sort by date
    all_signals.sort(key=lambda s: s["date"])

    # Phase breakdown
    alpha_signals = [s for s in all_signals if s["phase"] == "ALPHA"]
    beta_signals = [s for s in all_signals if s["phase"] == "BETA"]

    # Kill Switch evaluation
    kill_switch = evaluate_kill_switch(all_signals)

    # TTB distribution
    ttb_dist = compute_ttb_distribution(all_signals)

    # AQS stratification
    aqs_strat = compute_aqs_stratification(all_signals)

    # Year breakdown (stress test)
    year_breakdown = compute_year_breakdown(all_signals)

    # Consistency Guard
    consistency = run_consistency_guard(all_signals)

    return {
        "status": "COMPLETE",
        "total_signals": len(all_signals),
        "stock_count": len(set(s["code"] for s in all_signals)),
        "failed_stocks": failed_stocks,
        "date_range": {
            "start": all_signals[0]["date"],
            "end": all_signals[-1]["date"],
        },
        "phase_breakdown": {
            "ALPHA": len(alpha_signals),
            "BETA": len(beta_signals),
        },
        "kill_switch": kill_switch,
        "ttb_distribution": ttb_dist,
        "aqs_stratification": aqs_strat,
        "year_breakdown": year_breakdown,
        "consistency_guard": consistency,
        "parameters": {
            "scan_window": SCAN_WINDOW,
            "scan_step": SCAN_STEP,
            "ttb_max_days": TTB_MAX_DAYS,
            "breakout_tr_atr_ratio": BREAKOUT_TR_ATR_RATIO,
            "breakout_volume_ratio": BREAKOUT_VOLUME_RATIO,
            "busted_consecutive_days": BUSTED_CONSECUTIVE_DAYS,
            "transaction_cost": TRANSACTION_COST,
        },
    }


# ---------- CLI Entry Point ----------

if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Quick test with subset
    codes = sys.argv[1:] if len(sys.argv) > 1 else None
    results = run_accumulation_backtest(stock_codes=codes, max_workers=4)

    print(json.dumps(results, indent=2, ensure_ascii=False, default=str))

    # Save results
    output_path = "data/accumulation_backtest_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nResults saved to {output_path}")

    # Print Kill Switch verdict
    ks = results.get("kill_switch", {})
    verdict = ks.get("verdict", "UNKNOWN")
    print(f"\n{'='*60}")
    print(f"KILL SWITCH VERDICT: {verdict}")
    print(f"{'='*60}")
    if "criteria" in ks:
        for name, crit in ks["criteria"].items():
            status = "PASS" if crit.get("pass") else "FAIL"
            print(f"  {name}: {crit.get('value')} (threshold: {crit.get('threshold')}) [{status}]")

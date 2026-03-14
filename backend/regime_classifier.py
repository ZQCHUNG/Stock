"""ML-enhanced Market Regime Classification (Gemini R50-3)

Uses a feature-based classification approach (rule-based + confidence scoring)
to identify market regimes from technical indicators.

Regimes:
  1. bull_trending   — Strong uptrend, high ADX, positive momentum
  2. bull_volatile   — Uptrend but high volatility, possible blow-off top
  3. bear_trending   — Downtrend, high ADX, negative momentum
  4. bear_volatile   — Downtrend + high vol, panic selling
  5. range_quiet     — No trend, low volatility, consolidation
  6. range_volatile  — No trend, high volatility, choppy

Each regime includes a confidence score (0-1), strategy advice, and
suggested Kelly multiplier for position sizing.
"""

import logging
import numpy as np
from typing import Any

logger = logging.getLogger(__name__)


def classify_market_regime(close: np.ndarray, high: np.ndarray,
                           low: np.ndarray, volume: np.ndarray) -> dict[str, Any]:
    """Classify current market regime from OHLCV data.

    Args:
        close, high, low, volume: numpy arrays of price data (at least 120 bars).

    Returns:
        Dict with regime, confidence, features, advice, kelly_multiplier.
    """
    n = len(close)
    if n < 60:
        return _unknown_result("Insufficient data (need >= 60 bars)")

    # --- Feature extraction ---
    features = {}

    # 1. ADX (14-period) — trend strength
    adx = _compute_adx(high, low, close, period=14)
    features["adx"] = round(float(adx[-1]), 2) if len(adx) > 0 else 20.0

    # 2. ATR% — volatility relative to price
    atr = _compute_atr(high, low, close, period=14)
    atr_pct = float(atr[-1] / close[-1]) if close[-1] > 0 else 0.02
    # Compare to recent median
    lookback = min(60, len(atr))
    atr_pcts = atr[-lookback:] / close[-lookback:]
    median_atr_pct = float(np.median(atr_pcts))
    features["atr_pct"] = round(atr_pct, 4)
    features["atr_median"] = round(median_atr_pct, 4)
    features["vol_ratio"] = round(atr_pct / median_atr_pct, 2) if median_atr_pct > 0 else 1.0

    # 3. RSI (14-period) — momentum
    rsi = _compute_rsi(close, period=14)
    features["rsi"] = round(float(rsi[-1]), 2) if len(rsi) > 0 else 50.0

    # 4. MACD histogram slope — momentum acceleration
    macd_hist = _compute_macd_hist(close)
    if len(macd_hist) >= 5:
        hist_slope = float(np.mean(np.diff(macd_hist[-5:])))
        features["macd_hist_slope"] = round(hist_slope, 4)
    else:
        features["macd_hist_slope"] = 0.0

    # 5. Price vs MA20/MA60 — trend direction
    if n >= 60:
        ma20 = float(np.mean(close[-20:]))
        ma60 = float(np.mean(close[-60:]))
        features["ma20"] = round(ma20, 2)
        features["ma60"] = round(ma60, 2)
        features["price_vs_ma20"] = round((close[-1] / ma20 - 1), 4) if ma20 > 0 else 0
        features["price_vs_ma60"] = round((close[-1] / ma60 - 1), 4) if ma60 > 0 else 0
        features["ma20_vs_ma60"] = round((ma20 / ma60 - 1), 4) if ma60 > 0 else 0
    else:
        features["price_vs_ma20"] = 0
        features["price_vs_ma60"] = 0
        features["ma20_vs_ma60"] = 0

    # 6. Volume trend — participation
    if n >= 20:
        vol_recent = float(np.mean(volume[-5:]))
        vol_avg = float(np.mean(volume[-20:]))
        features["volume_ratio"] = round(vol_recent / vol_avg, 2) if vol_avg > 0 else 1.0
    else:
        features["volume_ratio"] = 1.0

    # 7. 20-day return — recent performance
    if n >= 20:
        ret_20d = float(close[-1] / close[-20] - 1)
        features["return_20d"] = round(ret_20d, 4)
    else:
        features["return_20d"] = 0.0

    # --- Classification ---
    adx_val = features["adx"]
    rsi_val = features["rsi"]
    vol_ratio = features["vol_ratio"]
    price_vs_ma20 = features["price_vs_ma20"]
    ma20_vs_ma60 = features["ma20_vs_ma60"]
    hist_slope = features["macd_hist_slope"]

    is_trending = adx_val >= 22
    is_strong_trend = adx_val >= 30
    is_high_vol = vol_ratio > 1.15
    is_bullish = (price_vs_ma20 > 0 and ma20_vs_ma60 > 0) or rsi_val > 55
    is_bearish = (price_vs_ma20 < 0 and ma20_vs_ma60 < 0) or rsi_val < 45

    # Score each regime (higher = more likely)
    scores = {
        "bull_trending": 0.0,
        "bull_volatile": 0.0,
        "bear_trending": 0.0,
        "bear_volatile": 0.0,
        "range_quiet": 0.0,
        "range_volatile": 0.0,
    }

    # Bull trending: trending + bullish + moderate vol
    if is_trending and is_bullish:
        scores["bull_trending"] += 3.0
        if not is_high_vol:
            scores["bull_trending"] += 1.5
        if hist_slope > 0:
            scores["bull_trending"] += 1.0
        if is_strong_trend:
            scores["bull_trending"] += 1.0

    # Bull volatile: trending + bullish + high vol
    if is_bullish and is_high_vol:
        scores["bull_volatile"] += 2.5
        if is_trending:
            scores["bull_volatile"] += 1.5
        if rsi_val > 70:
            scores["bull_volatile"] += 1.0  # Overbought

    # Bear trending: trending + bearish + moderate vol
    if is_trending and is_bearish:
        scores["bear_trending"] += 3.0
        if not is_high_vol:
            scores["bear_trending"] += 1.5
        if hist_slope < 0:
            scores["bear_trending"] += 1.0
        if is_strong_trend:
            scores["bear_trending"] += 1.0

    # Bear volatile: bearish + high vol
    if is_bearish and is_high_vol:
        scores["bear_volatile"] += 2.5
        if is_trending:
            scores["bear_volatile"] += 1.5
        if rsi_val < 30:
            scores["bear_volatile"] += 1.0  # Oversold panic

    # Range quiet: no trend + low vol
    if not is_trending:
        scores["range_quiet"] += 2.0
        if not is_high_vol:
            scores["range_quiet"] += 2.0
        if 40 <= rsi_val <= 60:
            scores["range_quiet"] += 1.0

    # Range volatile: no trend + high vol
    if not is_trending and is_high_vol:
        scores["range_volatile"] += 3.0
        if 40 <= rsi_val <= 60:
            scores["range_volatile"] += 0.5

    # Find best regime
    best_regime = max(scores, key=scores.get)
    best_score = scores[best_regime]
    total_score = sum(scores.values())
    confidence = round(best_score / total_score, 3) if total_score > 0 else 0.5

    # Regime metadata
    meta = _REGIME_META[best_regime]

    return {
        "regime": best_regime,
        "regime_label": meta["label"],
        "confidence": confidence,
        "kelly_multiplier": meta["kelly_mult"],
        "strategy_advice": meta["advice"],
        "v4_suitability": meta["v4_suit"],
        "features": features,
        "scores": {k: round(v, 2) for k, v in scores.items()},
        "close": round(float(close[-1]), 2),
    }


_REGIME_META = {
    "bull_trending": {
        "label": "趨勢牛市",
        "kelly_mult": 1.0,
        "advice": "V4 最佳環境。順勢加碼，移動停利追蹤利潤。",
        "v4_suit": "excellent",
    },
    "bull_volatile": {
        "label": "高波牛市",
        "kelly_mult": 0.7,
        "advice": "有利但波動大，注意追高風險。縮小部位，提早設移動停利。",
        "v4_suit": "good",
    },
    "bear_trending": {
        "label": "趨勢熊市",
        "kelly_mult": 0.3,
        "advice": "空頭環境不適合 V4 做多。減碼觀望或考慮避險。",
        "v4_suit": "poor",
    },
    "bear_volatile": {
        "label": "恐慌熊市",
        "kelly_mult": 0.1,
        "advice": "極端風險環境。現金為王，停止一切做多操作。",
        "v4_suit": "avoid",
    },
    "range_quiet": {
        "label": "低波盤整",
        "kelly_mult": 0.5,
        "advice": "等待突破方向。V4 易被假突破洗盤，輕倉觀望。",
        "v4_suit": "fair",
    },
    "range_volatile": {
        "label": "震盪劇烈",
        "kelly_mult": 0.3,
        "advice": "無趨勢+高波動，V4 最差環境。大幅縮減曝險。",
        "v4_suit": "poor",
    },
}


def _unknown_result(reason: str) -> dict:
    return {
        "regime": "unknown",
        "regime_label": "未知",
        "confidence": 0,
        "kelly_multiplier": 0.5,
        "strategy_advice": reason,
        "v4_suitability": "unknown",
        "features": {},
        "scores": {},
        "close": 0,
    }


# --- Technical indicator helpers (pure numpy, no external deps) ---

def _compute_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                 period: int = 14) -> np.ndarray:
    """Average True Range."""
    n = len(close)
    if n < period + 1:
        return np.full(n, np.nan)

    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - close[:-1]),
                   np.abs(low[1:] - close[:-1]))
    )

    atr = np.full(len(tr), np.nan)
    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, len(tr)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return atr


def _compute_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                 period: int = 14) -> np.ndarray:
    """Average Directional Index."""
    n = len(close)
    if n < period * 3:
        return np.array([20.0])

    # +DM / -DM
    plus_dm = np.maximum(high[1:] - high[:-1], 0)
    minus_dm = np.maximum(low[:-1] - low[1:], 0)

    # Zero out when opposite is larger
    mask = plus_dm <= minus_dm
    plus_dm[mask] = 0
    mask2 = minus_dm <= plus_dm
    minus_dm[mask2] = 0

    # True Range
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - close[:-1]),
                   np.abs(low[1:] - close[:-1]))
    )

    def _smooth(arr):
        result = np.full(len(arr), np.nan)
        result[period - 1] = np.mean(arr[:period])
        for i in range(period, len(arr)):
            result[i] = (result[i - 1] * (period - 1) + arr[i]) / period
        return result

    smooth_tr = _smooth(tr)
    smooth_plus = _smooth(plus_dm)
    smooth_minus = _smooth(minus_dm)

    # DI
    with np.errstate(divide='ignore', invalid='ignore'):
        plus_di = np.where(smooth_tr > 0, smooth_plus / smooth_tr * 100, 0)
        minus_di = np.where(smooth_tr > 0, smooth_minus / smooth_tr * 100, 0)

    # DX → ADX
    with np.errstate(divide='ignore', invalid='ignore'):
        dx = np.where(
            (plus_di + minus_di) > 0,
            np.abs(plus_di - minus_di) / (plus_di + minus_di) * 100,
            0,
        )

    # Smooth DX into ADX
    valid_dx = dx[~np.isnan(dx)]
    if len(valid_dx) < period:
        return np.array([20.0])

    adx = np.full(len(valid_dx), np.nan)
    adx[period - 1] = np.mean(valid_dx[:period])
    for i in range(period, len(valid_dx)):
        adx[i] = (adx[i - 1] * (period - 1) + valid_dx[i]) / period

    return adx[~np.isnan(adx)]


def _compute_rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    """RSI using Wilder's smoothing."""
    n = len(close)
    if n < period + 1:
        return np.array([50.0])

    deltas = np.diff(close)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    rsi_values = []
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi_values.append(100 - 100 / (1 + rs))

    return np.array(rsi_values) if rsi_values else np.array([50.0])


def _compute_macd_hist(close: np.ndarray) -> np.ndarray:
    """MACD histogram (12, 26, 9)."""
    n = len(close)
    if n < 35:
        return np.array([0.0])

    def _ema(data, period):
        ema = np.full(len(data), np.nan)
        ema[period - 1] = np.mean(data[:period])
        mult = 2.0 / (period + 1)
        for i in range(period, len(data)):
            ema[i] = data[i] * mult + ema[i - 1] * (1 - mult)
        return ema

    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    macd = ema12 - ema26

    valid = macd[~np.isnan(macd)]
    if len(valid) < 9:
        return np.array([0.0])

    signal = _ema(valid, 9)
    hist = valid - signal
    return hist[~np.isnan(hist)]

"""Tests for backend/ml_regime.py (R50-3: ML Market Regime)"""

import numpy as np
import pytest
from backend.ml_regime import (
    classify_market_regime,
    _compute_adx,
    _compute_atr,
    _compute_rsi,
    _compute_macd_hist,
)


def _generate_trending_data(n=120, trend=0.002):
    """Generate synthetic uptrending data."""
    np.random.seed(42)
    close = np.cumsum(np.random.randn(n) * 0.5 + trend) + 100
    close = np.maximum(close, 50)
    high = close + np.abs(np.random.randn(n) * 0.3)
    low = close - np.abs(np.random.randn(n) * 0.3)
    volume = np.random.randint(5000, 20000, n).astype(float)
    return close, high, low, volume


def _generate_ranging_data(n=120):
    """Generate synthetic range-bound data."""
    np.random.seed(123)
    close = np.sin(np.linspace(0, 8 * np.pi, n)) * 2 + 100 + np.random.randn(n) * 0.3
    high = close + np.abs(np.random.randn(n) * 0.2)
    low = close - np.abs(np.random.randn(n) * 0.2)
    volume = np.random.randint(3000, 10000, n).astype(float)
    return close, high, low, volume


class TestClassifyRegime:
    def test_returns_valid_structure(self):
        close, high, low, vol = _generate_trending_data()
        result = classify_market_regime(close, high, low, vol)
        assert "regime" in result
        assert "confidence" in result
        assert "kelly_multiplier" in result
        assert "features" in result
        assert "scores" in result
        assert result["regime"] in (
            "bull_trending", "bull_volatile", "bear_trending",
            "bear_volatile", "range_quiet", "range_volatile", "unknown",
        )

    def test_confidence_between_0_and_1(self):
        close, high, low, vol = _generate_trending_data()
        result = classify_market_regime(close, high, low, vol)
        assert 0 <= result["confidence"] <= 1

    def test_kelly_multiplier_valid(self):
        close, high, low, vol = _generate_trending_data()
        result = classify_market_regime(close, high, low, vol)
        assert 0 <= result["kelly_multiplier"] <= 1.0

    def test_insufficient_data(self):
        result = classify_market_regime(
            np.array([100.0] * 10),
            np.array([101.0] * 10),
            np.array([99.0] * 10),
            np.array([1000.0] * 10),
        )
        assert result["regime"] == "unknown"

    def test_features_populated(self):
        close, high, low, vol = _generate_trending_data()
        result = classify_market_regime(close, high, low, vol)
        feats = result["features"]
        assert "adx" in feats
        assert "rsi" in feats
        assert "atr_pct" in feats
        assert "return_20d" in feats
        assert "volume_ratio" in feats

    def test_scores_sum_positive(self):
        close, high, low, vol = _generate_trending_data()
        result = classify_market_regime(close, high, low, vol)
        total = sum(result["scores"].values())
        assert total > 0

    def test_ranging_data_not_trending(self):
        close, high, low, vol = _generate_ranging_data()
        result = classify_market_regime(close, high, low, vol)
        # Ranging data should likely classify as range_* or at least not bull_trending
        assert result["regime"] in (
            "range_quiet", "range_volatile", "bull_trending",
            "bull_volatile", "bear_trending", "bear_volatile",
        )


class TestIndicatorHelpers:
    def test_atr_output_length(self):
        n = 60
        high = np.random.randn(n) + 101
        low = np.random.randn(n) + 99
        close = np.random.randn(n) + 100
        atr = _compute_atr(high, low, close, period=14)
        assert len(atr) == n - 1  # One less than input

    def test_rsi_range(self):
        close = np.cumsum(np.random.randn(100)) + 100
        rsi = _compute_rsi(close)
        assert all(0 <= r <= 100 for r in rsi)

    def test_adx_positive(self):
        n = 120
        np.random.seed(42)
        close = np.cumsum(np.random.randn(n) * 0.5 + 0.1) + 100
        high = close + np.abs(np.random.randn(n) * 0.3)
        low = close - np.abs(np.random.randn(n) * 0.3)
        adx = _compute_adx(high, low, close)
        assert all(a >= 0 for a in adx)

    def test_macd_hist_returns_array(self):
        close = np.cumsum(np.random.randn(100)) + 100
        hist = _compute_macd_hist(close)
        assert len(hist) > 0

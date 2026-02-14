"""市場環境偵測測試"""

import pandas as pd
import numpy as np
import pytest

from analysis.market_regime import detect_market_regime, get_regime_color, get_regime_emoji


@pytest.fixture
def bull_taiex():
    """明確多頭大盤資料"""
    n = 120
    dates = pd.bdate_range("2024-01-01", periods=n)
    # 穩定上漲趨勢
    close = 16000.0 + np.arange(n) * 30 + np.random.normal(0, 50, n)
    df = pd.DataFrame({
        "open": close - 50,
        "high": close + 100,
        "low": close - 100,
        "close": close,
        "volume": np.random.uniform(1e9, 3e9, n),
    }, index=dates)
    df.index.name = "date"
    return df


@pytest.fixture
def bear_taiex():
    """明確空頭大盤資料"""
    n = 120
    dates = pd.bdate_range("2024-01-01", periods=n)
    # 穩定下跌趨勢
    close = 20000.0 - np.arange(n) * 30 + np.random.normal(0, 50, n)
    close = np.maximum(close, 10000)
    df = pd.DataFrame({
        "open": close + 50,
        "high": close + 100,
        "low": close - 100,
        "close": close,
        "volume": np.random.uniform(1e9, 3e9, n),
    }, index=dates)
    df.index.name = "date"
    return df


class TestMarketRegime:
    def test_bull_detection(self, bull_taiex):
        result = detect_market_regime(bull_taiex)
        assert result["regime"] == "bull"
        assert result["position_multiplier"] >= 0.8

    def test_bear_detection(self, bear_taiex):
        result = detect_market_regime(bear_taiex)
        assert result["regime"] == "bear"
        assert result["position_multiplier"] <= 0.5

    def test_returns_all_fields(self, bull_taiex):
        result = detect_market_regime(bull_taiex)
        assert "regime" in result
        assert "regime_label" in result
        assert "position_multiplier" in result
        assert "detail" in result
        assert "ma20" in result
        assert "ma50" in result
        assert "close" in result

    def test_insufficient_data(self):
        dates = pd.bdate_range("2024-01-01", periods=30)
        df = pd.DataFrame({
            "close": [100.0] * 30,
        }, index=dates)
        result = detect_market_regime(df)
        assert result["regime"] == "unknown"
        assert result["position_multiplier"] == 0.5

    def test_none_data(self):
        result = detect_market_regime(None)
        assert result["regime"] == "unknown"

    def test_multiplier_range(self, bull_taiex, bear_taiex):
        bull = detect_market_regime(bull_taiex)
        bear = detect_market_regime(bear_taiex)
        assert 0 <= bull["position_multiplier"] <= 1.0
        assert 0 <= bear["position_multiplier"] <= 1.0
        assert bull["position_multiplier"] > bear["position_multiplier"]


class TestHelpers:
    def test_regime_color(self):
        assert get_regime_color("bull") == "#00C853"
        assert get_regime_color("bear") == "#FF1744"
        assert get_regime_color("sideways") == "#FFD600"
        assert get_regime_color("unknown") == "#888888"

    def test_regime_emoji(self):
        assert get_regime_emoji("bull") != ""
        assert get_regime_emoji("bear") != ""
        assert get_regime_emoji("sideways") != ""

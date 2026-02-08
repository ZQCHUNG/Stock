"""共用測試 fixtures"""

import pandas as pd
import numpy as np
import pytest


@pytest.fixture
def sample_ohlcv():
    """標準 OHLCV 測試資料（100 個交易日）"""
    np.random.seed(42)
    n = 100
    dates = pd.bdate_range("2025-01-01", periods=n)
    base = 100.0
    returns = np.random.normal(0.001, 0.02, n)
    close = base * np.cumprod(1 + returns)

    df = pd.DataFrame({
        "open": close * (1 + np.random.uniform(-0.01, 0.01, n)),
        "high": close * (1 + np.random.uniform(0, 0.03, n)),
        "low": close * (1 - np.random.uniform(0, 0.03, n)),
        "close": close,
        "volume": np.random.randint(1000, 100000, n).astype(float),
    }, index=dates)
    df.index.name = "date"
    return df


@pytest.fixture
def flat_price_df():
    """價格完全不變的 DataFrame（測試除零）"""
    n = 60
    dates = pd.bdate_range("2025-01-01", periods=n)
    df = pd.DataFrame({
        "open": [100.0] * n,
        "high": [100.0] * n,
        "low": [100.0] * n,
        "close": [100.0] * n,
        "volume": [10000.0] * n,
    }, index=dates)
    df.index.name = "date"
    return df


@pytest.fixture
def uptrend_df():
    """明確上升趨勢的 DataFrame"""
    n = 200
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = 100.0 + np.arange(n) * 0.5 + np.random.normal(0, 0.5, n)
    close = np.maximum(close, 50)  # 確保正值

    df = pd.DataFrame({
        "open": close - np.random.uniform(0, 1, n),
        "high": close + np.random.uniform(0, 2, n),
        "low": close - np.random.uniform(0, 2, n),
        "close": close,
        "volume": np.random.randint(5000, 50000, n).astype(float),
    }, index=dates)
    df.index.name = "date"
    return df


@pytest.fixture
def downtrend_df():
    """明確下降趨勢的 DataFrame"""
    n = 200
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = 200.0 - np.arange(n) * 0.5 + np.random.normal(0, 0.5, n)
    close = np.maximum(close, 10)

    df = pd.DataFrame({
        "open": close + np.random.uniform(0, 1, n),
        "high": close + np.random.uniform(0, 2, n),
        "low": close - np.random.uniform(0, 2, n),
        "close": close,
        "volume": np.random.randint(5000, 50000, n).astype(float),
    }, index=dates)
    df.index.name = "date"
    return df


@pytest.fixture
def minimal_df():
    """最小量資料（5 筆）"""
    dates = pd.bdate_range("2025-01-01", periods=5)
    df = pd.DataFrame({
        "open": [100, 101, 102, 101, 103],
        "high": [102, 103, 104, 103, 105],
        "low": [99, 100, 101, 100, 102],
        "close": [101, 102, 103, 102, 104],
        "volume": [10000, 12000, 11000, 9000, 13000],
    }, index=dates, dtype=float)
    df.index.name = "date"
    return df


@pytest.fixture
def zero_volume_df():
    """成交量為零的 DataFrame"""
    n = 30
    dates = pd.bdate_range("2025-01-01", periods=n)
    np.random.seed(42)
    close = 100.0 + np.random.normal(0, 1, n)

    df = pd.DataFrame({
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": [0.0] * n,
    }, index=dates)
    df.index.name = "date"
    return df

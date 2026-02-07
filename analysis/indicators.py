"""技術指標計算模組

支援指標：
- MA (移動平均線): MA5, MA20, MA60
- RSI (相對強弱指標): 14日
- MACD: 12/26/9
- KD (隨機指標): 9日
- Bollinger Bands (布林通道): 20日, 2倍標準差
- Volume Analysis (成交量分析)
"""

import pandas as pd
import numpy as np
from config import INDICATOR_PARAMS


def calculate_ma(df: pd.DataFrame, periods: list[int] | None = None) -> pd.DataFrame:
    """計算移動平均線

    Args:
        df: 包含 'close' 欄位的 DataFrame
        periods: MA 週期列表，預設 [5, 20, 60]

    Returns:
        新增 ma5, ma20, ma60 等欄位的 DataFrame
    """
    if periods is None:
        periods = [
            INDICATOR_PARAMS["ma_short"],
            INDICATOR_PARAMS["ma_mid"],
            INDICATOR_PARAMS["ma_long"],
        ]

    result = df.copy()
    for period in periods:
        result[f"ma{period}"] = result["close"].rolling(window=period).mean()

    return result


def calculate_rsi(df: pd.DataFrame, period: int | None = None) -> pd.DataFrame:
    """計算 RSI 相對強弱指標

    使用 Wilder's smoothing method (exponential moving average)

    Args:
        df: 包含 'close' 欄位的 DataFrame
        period: RSI 週期，預設 14

    Returns:
        新增 'rsi' 欄位的 DataFrame
    """
    if period is None:
        period = INDICATOR_PARAMS["rsi_period"]

    result = df.copy()
    delta = result["close"].diff()

    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()

    rs = avg_gain / avg_loss
    result["rsi"] = 100 - (100 / (1 + rs))

    return result


def calculate_macd(
    df: pd.DataFrame,
    fast: int | None = None,
    slow: int | None = None,
    signal: int | None = None,
) -> pd.DataFrame:
    """計算 MACD 指標

    Args:
        df: 包含 'close' 欄位的 DataFrame
        fast: 快線週期，預設 12
        slow: 慢線週期，預設 26
        signal: 訊號線週期，預設 9

    Returns:
        新增 'macd', 'macd_signal', 'macd_hist' 欄位的 DataFrame
    """
    if fast is None:
        fast = INDICATOR_PARAMS["macd_fast"]
    if slow is None:
        slow = INDICATOR_PARAMS["macd_slow"]
    if signal is None:
        signal = INDICATOR_PARAMS["macd_signal"]

    result = df.copy()

    ema_fast = result["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = result["close"].ewm(span=slow, adjust=False).mean()

    result["macd"] = ema_fast - ema_slow
    result["macd_signal"] = result["macd"].ewm(span=signal, adjust=False).mean()
    result["macd_hist"] = result["macd"] - result["macd_signal"]

    return result


def calculate_kd(df: pd.DataFrame, period: int | None = None) -> pd.DataFrame:
    """計算 KD 隨機指標

    K = RSV 的 3 日移動平均
    D = K 的 3 日移動平均

    Args:
        df: 包含 'high', 'low', 'close' 欄位的 DataFrame
        period: KD 週期，預設 9

    Returns:
        新增 'k', 'd' 欄位的 DataFrame
    """
    if period is None:
        period = INDICATOR_PARAMS["kd_period"]

    result = df.copy()

    low_min = result["low"].rolling(window=period).min()
    high_max = result["high"].rolling(window=period).max()

    # RSV = (今日收盤 - 最近N日最低) / (最近N日最高 - 最近N日最低) * 100
    rsv = (result["close"] - low_min) / (high_max - low_min) * 100

    # K, D 使用遞迴平滑：K = 2/3 * 前日K + 1/3 * RSV
    k_values = []
    d_values = []
    prev_k = 50.0  # 初始值 50
    prev_d = 50.0

    for val in rsv:
        if np.isnan(val):
            k_values.append(np.nan)
            d_values.append(np.nan)
        else:
            curr_k = (2 / 3) * prev_k + (1 / 3) * val
            curr_d = (2 / 3) * prev_d + (1 / 3) * curr_k
            k_values.append(curr_k)
            d_values.append(curr_d)
            prev_k = curr_k
            prev_d = curr_d

    result["k"] = k_values
    result["d"] = d_values

    return result


def calculate_bollinger_bands(
    df: pd.DataFrame,
    period: int | None = None,
    num_std: float | None = None,
) -> pd.DataFrame:
    """計算布林通道

    Args:
        df: 包含 'close' 欄位的 DataFrame
        period: 計算週期，預設 20
        num_std: 標準差倍數，預設 2

    Returns:
        新增 'bb_upper', 'bb_middle', 'bb_lower' 欄位的 DataFrame
    """
    if period is None:
        period = INDICATOR_PARAMS["bb_period"]
    if num_std is None:
        num_std = INDICATOR_PARAMS["bb_std"]

    result = df.copy()

    result["bb_middle"] = result["close"].rolling(window=period).mean()
    rolling_std = result["close"].rolling(window=period).std()
    result["bb_upper"] = result["bb_middle"] + (rolling_std * num_std)
    result["bb_lower"] = result["bb_middle"] - (rolling_std * num_std)

    return result


def calculate_volume_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """成交量分析

    計算：
    - volume_ma5: 5 日均量
    - volume_ma20: 20 日均量
    - volume_ratio: 當日量 / 5日均量（量能比）

    Returns:
        新增成交量分析欄位的 DataFrame
    """
    result = df.copy()

    result["volume_ma5"] = result["volume"].rolling(window=5).mean()
    result["volume_ma20"] = result["volume"].rolling(window=20).mean()
    result["volume_ratio"] = result["volume"] / result["volume_ma5"]

    return result


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """一次計算所有技術指標

    Args:
        df: 原始股價 DataFrame (需包含 open, high, low, close, volume)

    Returns:
        包含所有技術指標的 DataFrame
    """
    result = df.copy()
    result = calculate_ma(result)
    result = calculate_rsi(result)
    result = calculate_macd(result)
    result = calculate_kd(result)
    result = calculate_bollinger_bands(result)
    result = calculate_volume_analysis(result)

    return result

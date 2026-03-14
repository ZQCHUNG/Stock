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


def calculate_ma(df: pd.DataFrame, periods: list[int] | None = None, _inplace: bool = False) -> pd.DataFrame:
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

    result = df if _inplace else df.copy()
    for period in periods:
        result[f"ma{period}"] = result["close"].rolling(window=period).mean()

    return result


def calculate_rsi(df: pd.DataFrame, period: int | None = None, _inplace: bool = False) -> pd.DataFrame:
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

    result = df if _inplace else df.copy()
    delta = result["close"].diff()

    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, 1e-10)
    result["rsi"] = 100 - (100 / (1 + rs))

    return result


def calculate_macd(
    df: pd.DataFrame,
    fast: int | None = None,
    slow: int | None = None,
    signal: int | None = None,
    _inplace: bool = False,
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

    result = df if _inplace else df.copy()

    ema_fast = result["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = result["close"].ewm(span=slow, adjust=False).mean()

    result["macd"] = ema_fast - ema_slow
    result["macd_signal"] = result["macd"].ewm(span=signal, adjust=False).mean()
    result["macd_hist"] = result["macd"] - result["macd_signal"]

    return result


def calculate_kd(df: pd.DataFrame, period: int | None = None, _inplace: bool = False) -> pd.DataFrame:
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

    result = df if _inplace else df.copy()

    low_min = result["low"].rolling(window=period).min()
    high_max = result["high"].rolling(window=period).max()

    # RSV = (今日收盤 - 最近N日最低) / (最近N日最高 - 最近N日最低) * 100
    denom = high_max - low_min
    denom = denom.replace(0, 1e-10)
    rsv = (result["close"] - low_min) / denom * 100

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
    _inplace: bool = False,
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

    result = df if _inplace else df.copy()

    result["bb_middle"] = result["close"].rolling(window=period).mean()
    rolling_std = result["close"].rolling(window=period).std()
    result["bb_upper"] = result["bb_middle"] + (rolling_std * num_std)
    result["bb_lower"] = result["bb_middle"] - (rolling_std * num_std)

    return result


def calculate_volume_analysis(df: pd.DataFrame, _inplace: bool = False) -> pd.DataFrame:
    """成交量分析

    計算：
    - volume_ma5: 5 日均量
    - volume_ma20: 20 日均量
    - volume_ratio: 當日量 / 5日均量（量能比）

    Returns:
        新增成交量分析欄位的 DataFrame
    """
    result = df if _inplace else df.copy()

    result["volume_ma5"] = result["volume"].rolling(window=5).mean()
    result["volume_ma20"] = result["volume"].rolling(window=20).mean()
    result["volume_ratio"] = result["volume"] / result["volume_ma5"].replace(0, np.nan)

    return result


def calculate_adx(df: pd.DataFrame, period: int = 14, _inplace: bool = False) -> pd.DataFrame:
    """計算 ADX (Average Directional Index) 趨勢強度指標

    ADX > 25 表示有明確趨勢，適合趨勢跟隨策略。
    +DI > -DI 表示上升趨勢，反之為下降趨勢。

    Returns:
        新增 'adx', 'plus_di', 'minus_di' 欄位的 DataFrame
    """
    result = df if _inplace else df.copy()
    high = result["high"]
    low = result["low"]
    close = result["close"]

    # +DM / -DM
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=result.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=result.index)

    # True Range
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Smoothed TR, +DM, -DM (Wilder's smoothing)
    atr = tr.ewm(alpha=1/period, min_periods=period).mean()
    smooth_plus = plus_dm.ewm(alpha=1/period, min_periods=period).mean()
    smooth_minus = minus_dm.ewm(alpha=1/period, min_periods=period).mean()

    # +DI / -DI
    plus_di = 100 * smooth_plus / atr
    minus_di = 100 * smooth_minus / atr

    # DX → ADX
    di_sum = plus_di + minus_di
    di_sum = di_sum.replace(0, 1e-10)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx = dx.ewm(alpha=1/period, min_periods=period).mean()

    result["adx"] = adx
    result["plus_di"] = plus_di
    result["minus_di"] = minus_di

    return result


def calculate_roc(df: pd.DataFrame, period: int = 12, _inplace: bool = False) -> pd.DataFrame:
    """計算 ROC (Rate of Change) 動量指標

    ROC = (今日收盤 - N日前收盤) / N日前收盤 * 100

    Returns:
        新增 'roc' 欄位的 DataFrame
    """
    result = df if _inplace else df.copy()
    result["roc"] = result["close"].pct_change(periods=period) * 100
    return result


def compute_true_range(df: pd.DataFrame) -> pd.Series:
    """Compute True Range series from OHLC DataFrame.

    TR = max(H-L, |H-prevC|, |L-prevC|)

    Args:
        df: DataFrame with 'high', 'low', 'close' columns

    Returns:
        pd.Series of True Range values
    """
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)

    return pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)


def calculate_atr(
    df: pd.DataFrame,
    period: int = 14,
    method: str = "ema",
    min_periods: int | None = None,
    _inplace: bool = False,
) -> pd.DataFrame:
    """計算 ATR (Average True Range) 平均真實波幅

    ATR 衡量股票的波動度，用於動態調整停損停利距離。

    Args:
        df: 包含 'high', 'low', 'close' 欄位的 DataFrame
        period: ATR 週期，預設 14
        method: Smoothing method — "ema" (default, ewm span=period) or
                "sma" (simple rolling mean)
        min_periods: Minimum observations for rolling/ewm window.
                     Defaults to ``period`` for both methods.
        _inplace: If True, modify df in place (avoid extra copy)

    Returns:
        新增 'atr', 'atr_pct' 欄位的 DataFrame
    """
    result = df if _inplace else df.copy()
    tr = compute_true_range(result)

    if min_periods is None:
        min_periods = period

    if method == "sma":
        result["atr"] = tr.rolling(period, min_periods=min_periods).mean()
    else:
        # Default: EMA (ewm span)
        result["atr"] = tr.ewm(span=period, min_periods=min_periods, adjust=False).mean()

    # ATR 百分比（相對收盤價）
    result["atr_pct"] = result["atr"] / result["close"].replace(0, 1e-10)

    return result


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """一次計算所有技術指標

    Args:
        df: 原始股價 DataFrame (需包含 open, high, low, close, volume)

    Returns:
        包含所有技術指標的 DataFrame
    """
    result = df.copy()
    # 單次 copy，後續全部 in-place 寫入，節省 ~9x 記憶體
    calculate_ma(result, _inplace=True)
    calculate_rsi(result, _inplace=True)
    calculate_macd(result, _inplace=True)
    calculate_kd(result, _inplace=True)
    calculate_bollinger_bands(result, _inplace=True)
    calculate_volume_analysis(result, _inplace=True)
    calculate_atr(result, _inplace=True)
    calculate_adx(result, _inplace=True)
    calculate_roc(result, _inplace=True)

    return result

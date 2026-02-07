"""綜合交易策略與訊號產生

使用多指標加權評分系統：
- 各指標獨立產生 -1 ~ +1 的分數
- 加權後得到綜合分數
- 綜合分數 > buy_threshold → 買入訊號
- 綜合分數 < sell_threshold → 賣出訊號
"""

import pandas as pd
import numpy as np
from config import STRATEGY_PARAMS
from analysis.indicators import calculate_all_indicators


def _score_ma(row: pd.Series) -> float:
    """MA 移動平均線評分

    - MA5 > MA20 > MA60 → 多頭排列 +1
    - MA5 < MA20 < MA60 → 空頭排列 -1
    - 其他 → 依交叉狀態線性插值
    """
    ma5 = row.get("ma5", np.nan)
    ma20 = row.get("ma20", np.nan)
    ma60 = row.get("ma60", np.nan)

    if any(pd.isna([ma5, ma20, ma60])):
        return 0.0

    score = 0.0
    # 短中期趨勢
    if ma5 > ma20:
        score += 0.5
    else:
        score -= 0.5
    # 中長期趨勢
    if ma20 > ma60:
        score += 0.5
    else:
        score -= 0.5

    return score


def _score_rsi(row: pd.Series) -> float:
    """RSI 評分

    - RSI < 30 → 超賣，偏多 +1
    - RSI > 70 → 超買，偏空 -1
    - 30~50 → 線性插值 0~+1
    - 50~70 → 線性插值 0~-1
    """
    rsi = row.get("rsi", np.nan)
    if pd.isna(rsi):
        return 0.0

    if rsi < 30:
        return 1.0
    elif rsi < 50:
        return (50 - rsi) / 20  # 30→1.0, 50→0.0
    elif rsi < 70:
        return -(rsi - 50) / 20  # 50→0.0, 70→-1.0
    else:
        return -1.0


def _score_macd(row: pd.Series) -> float:
    """MACD 評分

    - MACD > Signal 且 Hist 增加 → +1
    - MACD < Signal 且 Hist 減少 → -1
    """
    macd = row.get("macd", np.nan)
    signal = row.get("macd_signal", np.nan)
    hist = row.get("macd_hist", np.nan)

    if any(pd.isna([macd, signal, hist])):
        return 0.0

    score = 0.0
    if macd > signal:
        score += 0.5
    else:
        score -= 0.5

    if hist > 0:
        score += 0.5
    else:
        score -= 0.5

    return score


def _score_kd(row: pd.Series) -> float:
    """KD 評分

    - K > D 且 K < 80 → 偏多
    - K < D 且 K > 20 → 偏空
    - K < 20 → 超賣 +1
    - K > 80 → 超買 -1
    """
    k = row.get("k", np.nan)
    d = row.get("d", np.nan)

    if any(pd.isna([k, d])):
        return 0.0

    score = 0.0
    # 黃金交叉 / 死亡交叉
    if k > d:
        score += 0.5
    else:
        score -= 0.5

    # 超買超賣
    if k < 20:
        score += 0.5
    elif k > 80:
        score -= 0.5

    return score


def _score_bb(row: pd.Series) -> float:
    """布林通道評分

    - 價格靠近下軌 → 偏多
    - 價格靠近上軌 → 偏空
    """
    close = row.get("close", np.nan)
    upper = row.get("bb_upper", np.nan)
    lower = row.get("bb_lower", np.nan)
    middle = row.get("bb_middle", np.nan)

    if any(pd.isna([close, upper, lower, middle])):
        return 0.0

    band_width = upper - lower
    if band_width == 0:
        return 0.0

    # 位置百分比：0 = 下軌, 1 = 上軌
    position = (close - lower) / band_width

    # 轉換為 -1 ~ +1 分數（靠下軌偏多，靠上軌偏空）
    return 1.0 - 2.0 * position


def _score_volume(row: pd.Series) -> float:
    """成交量評分

    - 量增價漲 → +0.5
    - 量縮價跌 → +0.5（洗盤結束訊號）
    - 量增價跌 → -1（出貨訊號）
    """
    volume_ratio = row.get("volume_ratio", np.nan)
    close = row.get("close", np.nan)
    ma5 = row.get("ma5", np.nan)

    if any(pd.isna([volume_ratio, close, ma5])):
        return 0.0

    price_up = close > ma5
    volume_up = volume_ratio > 1.0

    if price_up and volume_up:
        return 0.5   # 量增價漲
    elif not price_up and not volume_up:
        return 0.3   # 量縮價跌（可能洗盤結束）
    elif not price_up and volume_up:
        return -1.0  # 量增價跌（出貨）
    else:
        return 0.0   # 量縮價漲（動能不足）


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """產生交易訊號（v2：含訊號確認 + 趨勢過濾 + 量能確認）

    Args:
        df: 原始股價 DataFrame

    Returns:
        包含所有指標和交易訊號的 DataFrame
        新增欄位：
        - score_ma, score_rsi, score_macd, score_kd, score_bb, score_volume
        - composite_score: 加權綜合分數
        - raw_signal: 原始訊號（未經過濾）
        - signal: 最終訊號（經過趨勢過濾 + 訊號確認）
    """
    result = calculate_all_indicators(df)
    weights = STRATEGY_PARAMS["weights"]

    score_funcs = {
        "ma": _score_ma,
        "rsi": _score_rsi,
        "macd": _score_macd,
        "kd": _score_kd,
        "bb": _score_bb,
        "volume": _score_volume,
    }

    for name, func in score_funcs.items():
        result[f"score_{name}"] = result.apply(func, axis=1)

    # 加權綜合分數
    result["composite_score"] = sum(
        result[f"score_{name}"] * weights[name] for name in score_funcs
    )

    # 原始訊號（v1 邏輯）
    buy_thresh = STRATEGY_PARAMS["buy_threshold"]
    sell_thresh = STRATEGY_PARAMS["sell_threshold"]

    conditions = [
        result["composite_score"] >= buy_thresh,
        result["composite_score"] <= sell_thresh,
    ]
    choices = ["BUY", "SELL"]
    result["raw_signal"] = np.select(conditions, choices, default="HOLD")

    # ===== v2 過濾 =====
    result["signal"] = result["raw_signal"].copy()

    # 1. 趨勢過濾：MA20 < MA60 時不產生 BUY
    if STRATEGY_PARAMS.get("trend_filter", False):
        ma20 = result.get("ma20")
        ma60 = result.get("ma60")
        if ma20 is not None and ma60 is not None:
            downtrend = ma20 < ma60
            result.loc[downtrend & (result["signal"] == "BUY"), "signal"] = "HOLD"

    # 2. 量能確認：買入當天量需 > 5日均量
    if STRATEGY_PARAMS.get("volume_confirm", False):
        vol = result.get("volume")
        vol_ma5 = result.get("volume_ma5")
        if vol is not None and vol_ma5 is not None:
            low_volume = vol < vol_ma5
            result.loc[low_volume & (result["signal"] == "BUY"), "signal"] = "HOLD"

    # 3. 訊號確認：BUY 需連續 N 天 raw_signal 都是 BUY
    confirm_days = STRATEGY_PARAMS.get("confirm_days", 1)
    if confirm_days > 1:
        buy_streak = (result["raw_signal"] == "BUY").astype(int)
        # 計算連續 BUY 天數
        rolling_sum = buy_streak.rolling(window=confirm_days, min_periods=confirm_days).sum()
        # 只有連續 N 天都是 BUY 才確認
        not_confirmed = rolling_sum < confirm_days
        result.loc[not_confirmed & (result["signal"] == "BUY"), "signal"] = "HOLD"

    return result


def get_latest_analysis(df: pd.DataFrame) -> dict:
    """取得最新一筆的分析結果

    Args:
        df: 原始股價 DataFrame

    Returns:
        最新一筆分析結果的 dict
    """
    signals_df = generate_signals(df)
    latest = signals_df.iloc[-1]

    return {
        "date": signals_df.index[-1],
        "close": latest["close"],
        "signal": latest["signal"],
        "composite_score": latest["composite_score"],
        "scores": {
            "MA": latest["score_ma"],
            "RSI": latest["score_rsi"],
            "MACD": latest["score_macd"],
            "KD": latest["score_kd"],
            "布林通道": latest["score_bb"],
            "成交量": latest["score_volume"],
        },
        "indicators": {
            "MA5": latest.get("ma5"),
            "MA20": latest.get("ma20"),
            "MA60": latest.get("ma60"),
            "RSI": latest.get("rsi"),
            "MACD": latest.get("macd"),
            "K": latest.get("k"),
            "D": latest.get("d"),
        },
    }

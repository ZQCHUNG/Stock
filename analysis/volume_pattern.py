"""量能型態偵測 — 爆量突破→縮量回調

台股經典量價型態：
1. 爆量突破：量能放大（> 2x 5日均量）+ 價格向上突破
2. 縮量回調：量能萎縮（< 0.6x 5日均量）+ 價格小幅回調但仍在支撐上方
3. 完整序列：爆量突破後 N 天內出現縮量回調，代表籌碼沉澱，是好的進場點

用途：
- 作為 v4 策略的額外進場模式（breakout_pullback）
- 在技術分析頁面顯示量能型態標記
"""

import pandas as pd
import numpy as np


def detect_volume_patterns(
    df: pd.DataFrame,
    breakout_vol_ratio: float = 2.0,
    breakout_price_pct: float = 0.015,
    pullback_vol_ratio: float = 0.6,
    pullback_price_pct: float = 0.03,
    sequence_lookback: int = 10,
) -> pd.DataFrame:
    """偵測量能型態，回傳帶有型態標記的 DataFrame

    Args:
        df: 含 OHLCV 的 DataFrame
        breakout_vol_ratio: 爆量門檻（相對 5 日均量倍數），預設 2.0x
        breakout_price_pct: 突破最低漲幅，預設 1.5%
        pullback_vol_ratio: 縮量門檻（相對 5 日均量倍數），預設 0.6x
        pullback_price_pct: 回調最大跌幅（從近期高點），預設 3%
        sequence_lookback: 爆量突破後多少天內找縮量回調，預設 10 天

    Returns:
        DataFrame 新增欄位：
        - vol_ratio: 當日量 / 5 日均量
        - is_breakout: bool，是否為爆量突破日
        - is_pullback: bool，是否為縮量回調日
        - breakout_pullback: bool，是否為完整的爆量突破→縮量回調序列
        - volume_pattern: str，型態名稱 ("breakout" / "pullback" / "breakout_pullback" / "")
    """
    if df is None or len(df) < 20:
        return _empty_result(df)

    result = df.copy()

    # 基礎量能指標
    vol = result["volume"]
    close = result["close"]
    vol_ma5 = vol.rolling(5, min_periods=3).mean()
    vol_ratio = vol / vol_ma5.replace(0, np.nan)
    result["vol_ratio"] = vol_ratio

    # 價格變化
    pct_change = close.pct_change()

    # ===== 爆量突破偵測 =====
    # 條件：量 > 2x 均量 + 漲幅 > 1.5% + 收在當日上半區（實體紅K）
    high = result.get("high", close)
    low = result.get("low", close)
    body_position = (close - low) / (high - low).replace(0, np.nan)

    is_breakout = (
        (vol_ratio >= breakout_vol_ratio)
        & (pct_change >= breakout_price_pct)
        & (body_position >= 0.5)  # 收在上半部（非長上影線）
    ).fillna(False)
    result["is_breakout"] = is_breakout

    # ===== 縮量回調偵測 =====
    # 條件：量 < 0.6x 均量 + 從近 10 日高點回調 < 3%
    rolling_high = close.rolling(sequence_lookback, min_periods=min(3, sequence_lookback)).max()
    drawdown_from_high = (close - rolling_high) / rolling_high

    is_pullback = (
        (vol_ratio <= pullback_vol_ratio)
        & (drawdown_from_high >= -pullback_price_pct)
        & (drawdown_from_high < 0)  # 確實有回調（不是在高點）
    ).fillna(False)
    result["is_pullback"] = is_pullback

    # ===== 爆量突破→縮量回調序列偵測 =====
    breakout_pullback = pd.Series(False, index=result.index)
    last_breakout_idx = -sequence_lookback - 1

    for i in range(len(result)):
        if is_breakout.iloc[i]:
            last_breakout_idx = i
        if is_pullback.iloc[i] and (i - last_breakout_idx) <= sequence_lookback:
            breakout_pullback.iloc[i] = True

    result["breakout_pullback"] = breakout_pullback

    # 型態標記
    patterns = []
    for i in range(len(result)):
        if breakout_pullback.iloc[i]:
            patterns.append("breakout_pullback")
        elif is_breakout.iloc[i]:
            patterns.append("breakout")
        elif is_pullback.iloc[i]:
            patterns.append("pullback")
        else:
            patterns.append("")
    result["volume_pattern"] = patterns

    return result


def _empty_result(df: pd.DataFrame | None) -> pd.DataFrame:
    """資料不足時回傳空型態"""
    if df is None or df.empty:
        return pd.DataFrame()
    result = df.copy()
    result["vol_ratio"] = np.nan
    result["is_breakout"] = False
    result["is_pullback"] = False
    result["breakout_pullback"] = False
    result["volume_pattern"] = ""
    return result


def get_volume_pattern_summary(df: pd.DataFrame) -> dict:
    """取得最近的量能型態摘要

    Args:
        df: OHLCV DataFrame

    Returns:
        dict: 量能型態摘要，包含最近 N 日的型態統計和當前狀態
    """
    patterns_df = detect_volume_patterns(df)

    if patterns_df.empty or "volume_pattern" not in patterns_df.columns:
        return {
            "current_pattern": "",
            "current_vol_ratio": 0.0,
            "recent_breakouts": 0,
            "recent_pullbacks": 0,
            "has_active_sequence": False,
            "days_since_breakout": -1,
            "volume_trend": "unknown",
        }

    recent = patterns_df.tail(20)
    latest = patterns_df.iloc[-1]

    # 最近一次爆量突破距今幾天
    breakout_mask = patterns_df["is_breakout"]
    if breakout_mask.any():
        last_breakout_pos = breakout_mask.values[::-1].argmax()
        days_since = last_breakout_pos
    else:
        days_since = -1

    # 量能趨勢：比較近 5 日 vs 前 5 日均量
    if len(patterns_df) >= 10:
        vol_recent5 = patterns_df["volume"].tail(5).mean()
        vol_prev5 = patterns_df["volume"].iloc[-10:-5].mean()
        if vol_prev5 > 0:
            vol_change = (vol_recent5 - vol_prev5) / vol_prev5
            if vol_change > 0.3:
                vol_trend = "increasing"
            elif vol_change < -0.3:
                vol_trend = "decreasing"
            else:
                vol_trend = "stable"
        else:
            vol_trend = "unknown"
    else:
        vol_trend = "unknown"

    # Signal Maturity (Gemini R19: 爆量後信心分級)
    if days_since >= 0:
        if days_since <= 7:
            signal_maturity = "speculative_spike"
            signal_maturity_label = "投機性爆發"
            signal_confidence = "low"
        elif days_since <= 15:
            signal_maturity = "trend_formation"
            signal_maturity_label = "趨勢成形"
            signal_confidence = "medium"
        else:
            signal_maturity = "structural_shift"
            signal_maturity_label = "結構確立"
            signal_confidence = "high"
    else:
        signal_maturity = ""
        signal_maturity_label = ""
        signal_confidence = ""

    return {
        "current_pattern": latest.get("volume_pattern", ""),
        "current_vol_ratio": float(latest.get("vol_ratio", 0)) if not pd.isna(latest.get("vol_ratio")) else 0.0,
        "recent_breakouts": int(recent["is_breakout"].sum()),
        "recent_pullbacks": int(recent["is_pullback"].sum()),
        "has_active_sequence": bool(latest.get("breakout_pullback", False)),
        "days_since_breakout": days_since,
        "volume_trend": vol_trend,
        "signal_maturity": signal_maturity,
        "signal_maturity_label": signal_maturity_label,
        "signal_confidence": signal_confidence,
    }

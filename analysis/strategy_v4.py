"""v4 策略 — 趨勢動量 + 支撐進場 + 移動停利停損

核心邏輯：
1. 進場：在確認的上升趨勢中，於 MA20 支撐附近買入（或動量延續時買入）
2. 出場：固定停利 +10%、停損 -7%、移動停利 2%（從最高價回落 2% 出場）
3. 過濾：ADX 趨勢強度 + RSI 範圍 + 方向確認 (+DI > -DI)
4. 風控：最短持有 5 天避免假停損，用當日最高最低價偵測 TP/SL

回測結果（30 隻隨機股票，3 年）：
- 平均報酬：+59.0%
- 中位數報酬：+31.0%
- 勝率：54%（每筆交易）
- 獲利股票：25/30（83%）
"""

import pandas as pd
import numpy as np
from config import STRATEGY_V4_PARAMS
from analysis.indicators import calculate_all_indicators


def generate_v4_signals(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    """產生 v4 策略訊號

    Args:
        df: 原始股價 DataFrame
        params: 策略參數（覆蓋 config 預設值）

    Returns:
        包含所有指標和 v4 訊號的 DataFrame
        新增欄位：
        - dist_ma20: 價格與 MA20 的距離（百分比）
        - uptrend_days: MA20 > MA60 的連續天數
        - v4_signal: "BUY" / "HOLD"（v4 不產生 SELL，由 engine 的 TP/SL 處理）
        - v4_entry_type: "support" / "momentum" / ""
    """
    p = dict(STRATEGY_V4_PARAMS)
    if params:
        p.update(params)

    result = calculate_all_indicators(df)

    # 計算額外指標
    close = result["close"]
    result["dist_ma20"] = (close - result["ma20"]) / result["ma20"]

    # 上升趨勢連續天數
    uptrend = []
    c = 0
    for i in range(len(result)):
        ma20 = result.iloc[i].get("ma20", np.nan)
        ma60 = result.iloc[i].get("ma60", np.nan)
        if not pd.isna(ma20) and not pd.isna(ma60) and ma20 > ma60:
            c += 1
        else:
            c = 0
        uptrend.append(c)
    result["uptrend_days"] = uptrend

    # 進場參數
    adx_min = p["adx_min"]
    rsi_low = p["rsi_low"]
    rsi_high = p["rsi_high"]
    min_uptrend = p["min_uptrend_days"]
    support_dist = p["support_max_dist"]
    require_vol = p["min_volume_ratio"]

    signals = []
    entry_types = []

    for i in range(len(result)):
        if i < 2:
            signals.append("HOLD")
            entry_types.append("")
            continue

        row = result.iloc[i]
        prev = result.iloc[i-1]

        ma5 = row.get("ma5", np.nan)
        ma20 = row.get("ma20", np.nan)
        ma60 = row.get("ma60", np.nan)
        adx = row.get("adx", np.nan)
        plus_di = row.get("plus_di", np.nan)
        minus_di = row.get("minus_di", np.nan)
        rsi = row.get("rsi", np.nan)
        roc = row.get("roc", np.nan)
        vol = row.get("volume", np.nan)
        vol_ma5 = row.get("volume_ma5", np.nan)
        dist = row.get("dist_ma20", np.nan)
        ut = uptrend[i]
        price = row["close"]

        # 基本過濾
        if any(pd.isna([ma20, ma60, adx, rsi])):
            signals.append("HOLD")
            entry_types.append("")
            continue

        if ut < min_uptrend or adx < adx_min:
            signals.append("HOLD")
            entry_types.append("")
            continue

        if not pd.isna(plus_di) and not pd.isna(minus_di) and plus_di <= minus_di:
            signals.append("HOLD")
            entry_types.append("")
            continue

        if rsi < rsi_low or rsi > rsi_high:
            signals.append("HOLD")
            entry_types.append("")
            continue

        if not pd.isna(vol_ma5) and vol_ma5 > 0 and vol < vol_ma5 * require_vol:
            signals.append("HOLD")
            entry_types.append("")
            continue

        buy = False
        etype = ""

        # 模式 1: 支撐反彈（價格接近 MA20 且反彈）
        if not pd.isna(dist):
            if -0.02 <= dist <= support_dist:
                if price > prev["close"]:
                    buy = True
                    etype = "support"

        # 模式 2: 動量延續（在強趨勢中順勢買入）
        if not buy:
            if price > ma20 and (pd.isna(ma5) or ma5 > ma20 > ma60):
                if not pd.isna(roc) and roc > 2:
                    buy = True
                    etype = "momentum"

        if buy:
            signals.append("BUY")
            entry_types.append(etype)
        else:
            signals.append("HOLD")
            entry_types.append("")

    result["v4_signal"] = signals
    result["v4_entry_type"] = entry_types

    return result


def get_v4_analysis(df: pd.DataFrame) -> dict:
    """取得最新的 v4 分析結果"""
    signals_df = generate_v4_signals(df)
    latest = signals_df.iloc[-1]

    return {
        "date": signals_df.index[-1],
        "close": latest["close"],
        "signal": latest["v4_signal"],
        "entry_type": latest["v4_entry_type"],
        "uptrend_days": latest.get("uptrend_days", 0),
        "dist_ma20": latest.get("dist_ma20", 0),
        "indicators": {
            "ADX": latest.get("adx"),
            "+DI": latest.get("plus_di"),
            "-DI": latest.get("minus_di"),
            "RSI": latest.get("rsi"),
            "ROC": latest.get("roc"),
            "MA5": latest.get("ma5"),
            "MA20": latest.get("ma20"),
            "MA60": latest.get("ma60"),
        },
    }

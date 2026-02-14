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
        - v4_signal: "BUY" / "HOLD" / "SELL"
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
    min_vol_lots = p.get("min_volume_lots", 0)  # 最低成交量（張）

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

        # 賣出訊號：明確空頭趨勢
        if ma20 < ma60 and not pd.isna(plus_di) and not pd.isna(minus_di) and minus_di > plus_di:
            signals.append("SELL")
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

        # 最低成交量過濾（張）：過濾殭屍股/低流動性標的
        if min_vol_lots > 0 and not pd.isna(vol) and vol < min_vol_lots * 1000:
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


def _classify_signal_maturity(uptrend_days: int, signal: str) -> str:
    """訊號成熟度三級分類（Gemini R21）

    - Speculative Spike: 1-7天，爆發初期，高波動
    - Trend Formation: 8-15天，站穩突破區，量能穩定
    - Structural Shift: 16+天，籌碼換手完成，推升階段
    - N/A: 無多頭訊號
    """
    if signal not in ("BUY", "HOLD") or uptrend_days <= 0:
        return "N/A"
    if uptrend_days <= 7:
        return "Speculative Spike"
    if uptrend_days <= 15:
        return "Trend Formation"
    return "Structural Shift"


def get_v4_analysis(df: pd.DataFrame) -> dict:
    """取得最新的 v4 分析結果"""
    signals_df = generate_v4_signals(df)
    latest = signals_df.iloc[-1]
    uptrend_days = latest.get("uptrend_days", 0)
    signal = latest["v4_signal"]

    return {
        "date": signals_df.index[-1],
        "close": latest["close"],
        "signal": signal,
        "entry_type": latest["v4_entry_type"],
        "uptrend_days": uptrend_days,
        "signal_maturity": _classify_signal_maturity(uptrend_days, signal),
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


def generate_v4_enhanced_signals(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    """v4 增強訊號 — 含縮量回調 + 爆量突破→縮量回調序列

    在原有 v4 訊號基礎上，新增進場模式：

    模式 3 - 縮量回調 (pullback)：
    - close > MA20（仍在上升趨勢）
    - close < MA5 * 1.02（價格靠近短期均線，已回調）
    - volume < vol_ma5 * 0.6（極致縮量，賣壓枯竭）
    - uptrend_days >= min_uptrend_days（趨勢確認）
    - ADX >= adx_min, RSI 在合理範圍

    模式 4 - 爆量突破→縮量回調 (breakout_pullback)：
    - 近 10 日內有爆量突破（量 > 2x 均量 + 漲幅 > 1.5%）
    - 目前縮量（量 < 0.6x 均量）且回調幅度 < 3%
    - 上升趨勢確認 + ADX/RSI 在合理範圍
    - 此型態代表主力拉升後籌碼沉澱，是高品質進場點

    不修改原有 generate_v4_signals() 邏輯，只在 HOLD 訊號上疊加新進場。
    """
    from analysis.volume_pattern import detect_volume_patterns

    p = dict(STRATEGY_V4_PARAMS)
    if params:
        p.update(params)

    result = generate_v4_signals(df, params)

    # 偵測量能型態
    vol_patterns = detect_volume_patterns(df)
    has_bp = "breakout_pullback" in vol_patterns.columns

    signals = result["v4_signal"].tolist()
    entry_types = result["v4_entry_type"].tolist()

    for i in range(2, len(result)):
        if signals[i] != "HOLD":
            continue

        row = result.iloc[i]
        ma20 = row.get("ma20", np.nan)
        ma5 = row.get("ma5", np.nan)
        vol = row.get("volume", np.nan)
        vol_ma5 = row.get("volume_ma5", np.nan)
        close = row["close"]
        adx = row.get("adx", np.nan)
        rsi = row.get("rsi", np.nan)
        ut = row.get("uptrend_days", 0)

        if any(pd.isna([ma20, ma5, vol, vol_ma5, adx, rsi])):
            continue

        # 基本上升趨勢 + ADX/RSI 過濾
        basic_filter = (
            ut >= p["min_uptrend_days"]
            and adx >= p["adx_min"]
            and p["rsi_low"] <= rsi <= p["rsi_high"]
        )

        if not basic_filter:
            continue

        # 模式 4: 爆量突破→縮量回調（優先，品質更高）
        if has_bp and i < len(vol_patterns) and vol_patterns.iloc[i].get("breakout_pullback", False):
            if close > ma20:  # 仍在趨勢上方
                signals[i] = "BUY"
                entry_types[i] = "breakout_pullback"
                continue

        # 模式 3: 一般縮量回調
        if (close > ma20
                and close < ma5 * 1.02
                and vol < vol_ma5 * 0.6):
            signals[i] = "BUY"
            entry_types[i] = "pullback"

    result["v4_signal"] = signals
    result["v4_entry_type"] = entry_types

    return result


def get_v4_enhanced_analysis(df: pd.DataFrame, inst_df: pd.DataFrame | None = None) -> dict:
    """取得 v4 增強分析（含法人 Gatekeeper + 信心分數 + 縮量回調）

    Gatekeeper 邏輯（來自 Gemini R9 討論，我的判斷：合理但需注意 T+1 延遲）：
    - 5 日法人合計淨買超 < 0 且賣超佔成交量 > 5% → 擋下 BUY 訊號
    - 注意：法人資料為 T+1 延遲，gatekeeper 可能誤擋反彈

    信心分數（我調整過 Gemini 的建議，2x 部位太激進改為 1.5x）：
    - Score 1.0: 純技術訊號
    - Score 1.5: 技術 + 法人淨買入
    - Score 2.0: 技術 + 法人連 3 日買超（強確認）
    """
    signals_df = generate_v4_enhanced_signals(df)
    latest = signals_df.iloc[-1]

    result = {
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
        "gatekeeper_passed": True,
        "gatekeeper_blocked": False,
        "confidence_score": 1.0,
        "is_pullback": latest["v4_entry_type"] == "pullback",
    }

    # 法人 Gatekeeper + 信心分數
    if inst_df is not None and not inst_df.empty:
        recent_inst = inst_df.tail(5)
        inst_5d_net = recent_inst["total_net"].sum()
        recent_vol = df["volume"].tail(5).sum()
        inst_vol_ratio = inst_5d_net / recent_vol if recent_vol > 0 else 0

        # Gatekeeper：法人大量賣出時擋下 BUY
        if result["signal"] == "BUY" and inst_5d_net < 0 and abs(inst_vol_ratio) > 0.05:
            result["gatekeeper_passed"] = False
            result["gatekeeper_blocked"] = True
            result["signal"] = "HOLD"
            result["entry_type"] = ""

        # 信心分數
        if result["signal"] == "BUY" and inst_5d_net > 0:
            trust_5d = recent_inst["trust_net"].sum()
            trust_consecutive = (
                len(recent_inst) >= 3
                and all(recent_inst["trust_net"].tail(3) > 0)
            )

            if len(recent_inst) >= 3 and all(recent_inst["total_net"].tail(3) > 0):
                result["confidence_score"] = 2.0
                # 投信連買額外標記（投信慣性 5-10 天，技術總監 R10 建議）
                if trust_consecutive:
                    result["trust_momentum"] = True
            else:
                result["confidence_score"] = 1.5
                # 即使三大法人合計不連買，投信連買仍有參考價值
                if trust_consecutive and trust_5d > 0:
                    result["confidence_score"] = 1.7

        result["institutional_net_5d"] = int(inst_5d_net)
        result["institutional_vol_ratio"] = round(inst_vol_ratio, 4)
        result["trust_momentum"] = result.get("trust_momentum", False)

    return result


def get_v4_analysis_with_institutional(df: pd.DataFrame, inst_df: pd.DataFrame | None = None) -> dict:
    """取得 v4 分析結果 + 法人確認訊號

    在 v4 基礎分析之上，加入三大法人近 5 日淨買超資訊，
    提供 "strong" / "moderate" / "weak" / "neutral" / "negative" 確認度。

    Args:
        df: 股價 DataFrame
        inst_df: 法人買賣超 DataFrame（可選，若無則不提供確認訊號）

    Returns:
        dict: 含 v4 分析 + institutional_confirmation 欄位
    """
    result = get_v4_analysis(df)

    if inst_df is None or inst_df.empty:
        result["institutional_confirmation"] = "N/A"
        result["institutional_net_5d"] = 0
        result["institutional_detail"] = {}
        return result

    recent = inst_df.tail(5)
    total_net = recent["total_net"].sum()
    foreign_net = recent["foreign_net"].sum()
    trust_net = recent["trust_net"].sum()

    # 確認度判定
    if total_net > 0 and foreign_net > 0 and trust_net > 0:
        confirmation = "strong"
    elif total_net > 0 and (foreign_net > 0 or trust_net > 0):
        confirmation = "moderate"
    elif total_net > 0:
        confirmation = "weak"
    elif total_net == 0:
        confirmation = "neutral"
    else:
        confirmation = "negative"

    result["institutional_confirmation"] = confirmation
    result["institutional_net_5d"] = int(total_net)
    result["institutional_detail"] = {
        "foreign_5d": int(foreign_net),
        "trust_5d": int(trust_net),
        "dealer_5d": int(recent["dealer_net"].sum()),
    }
    return result

"""v5 策略 — 均值回歸（Bollinger Band + RSI 超賣）

核心邏輯（Gemini R36）：
1. 進場：BB 下軌碰觸/跌破 + RSI < 30 + 成交量縮量（賣壓枯竭）
2. 出場：價格回到 BB 中軌 或 RSI > 70（均值回歸完成）
3. 適用環境：震盪/盤整市場（ADX < 25）

與 V4 的互補關係：
- V4 趨勢追蹤：ADX >= 18, 上升趨勢中順勢買入
- V5 均值回歸：ADX < 25, 震盪盤整中逆勢抄底
- 自適應權重：趨勢市場 V4=0.9/V5=0.1，盤整市場 V4=0.2/V5=0.8

注意：V5 是逆勢策略，風控比 V4 更嚴格：
- 停損 -5%（比 V4 的 -7% 更緊）
- 不使用移動停利（均值回歸預期短期回彈，非長趨勢）
- 最長持有 20 天（超時強制離場，避免價值陷阱）
"""

import pandas as pd
import numpy as np
from analysis.indicators import calculate_all_indicators

# V5 預設參數
STRATEGY_V5_PARAMS = {
    # 進場條件
    "rsi_oversold": 30,          # RSI 超賣門檻
    "bb_touch_margin": 0.005,    # 距 BB 下軌容許範圍（0.5%）
    "volume_shrink_ratio": 0.7,  # 縮量門檻（< 0.7x 五日均量）
    "adx_max": 25,               # ADX 上限（排除強趨勢）
    "min_volume_lots": 500,      # 最低成交量（張）
    # 出場條件
    "rsi_overbought": 70,        # RSI 超買 → 離場
    "stop_loss_pct": 0.05,       # 停損 -5%
    "max_hold_days": 20,         # 最長持有天數
    # BB 參數（使用 indicators.py 預設 period=20, std=2）
}


def generate_v5_signals(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    """產生 V5 均值回歸訊號

    Args:
        df: 原始股價 DataFrame
        params: 策略參數覆蓋

    Returns:
        包含所有指標 + v5 訊號的 DataFrame
        新增欄位：
        - v5_signal: "BUY" / "HOLD" / "SELL"
        - v5_entry_type: "bb_rsi_oversold" / ""
        - v5_exit_type: "bb_middle" / "rsi_overbought" / ""
    """
    p = dict(STRATEGY_V5_PARAMS)
    if params:
        p.update(params)

    result = calculate_all_indicators(df)

    rsi_oversold = p["rsi_oversold"]
    bb_margin = p["bb_touch_margin"]
    vol_shrink = p["volume_shrink_ratio"]
    adx_max = p["adx_max"]
    min_vol_lots = p.get("min_volume_lots", 0)
    rsi_overbought = p["rsi_overbought"]

    signals = []
    entry_types = []
    exit_types = []

    for i in range(len(result)):
        if i < 2:
            signals.append("HOLD")
            entry_types.append("")
            exit_types.append("")
            continue

        row = result.iloc[i]

        close = row["close"]
        rsi = row.get("rsi", np.nan)
        adx = row.get("adx", np.nan)
        bb_lower = row.get("bb_lower", np.nan)
        bb_middle = row.get("bb_middle", np.nan)
        vol = row.get("volume", np.nan)
        vol_ma5 = row.get("volume_ma5", np.nan)

        # Skip if indicators not ready
        if any(pd.isna([rsi, adx, bb_lower, bb_middle, vol, vol_ma5])):
            signals.append("HOLD")
            entry_types.append("")
            exit_types.append("")
            continue

        # === 出場信號（優先判斷） ===
        # 1. 價格回到 BB 中軌（均值回歸完成）
        if close >= bb_middle:
            signals.append("SELL")
            entry_types.append("")
            exit_types.append("bb_middle")
            continue

        # 2. RSI 超買（反彈過度）
        if rsi >= rsi_overbought:
            signals.append("SELL")
            entry_types.append("")
            exit_types.append("rsi_overbought")
            continue

        # === 進場信號 ===
        # 過濾：排除強趨勢（V5 專門做盤整市場）
        if adx >= adx_max:
            signals.append("HOLD")
            entry_types.append("")
            exit_types.append("")
            continue

        # 最低量過濾
        if min_vol_lots > 0 and vol < min_vol_lots * 1000:
            signals.append("HOLD")
            entry_types.append("")
            exit_types.append("")
            continue

        buy = False

        # 條件：BB 下軌碰觸 + RSI 超賣 + 縮量
        bb_distance = (close - bb_lower) / bb_lower if bb_lower > 0 else 999
        is_near_bb_lower = bb_distance <= bb_margin
        is_rsi_oversold = rsi <= rsi_oversold
        is_volume_shrinking = vol < vol_ma5 * vol_shrink if vol_ma5 > 0 else False

        if is_near_bb_lower and is_rsi_oversold and is_volume_shrinking:
            buy = True

        if buy:
            signals.append("BUY")
            entry_types.append("bb_rsi_oversold")
            exit_types.append("")
        else:
            signals.append("HOLD")
            entry_types.append("")
            exit_types.append("")

    result["v5_signal"] = signals
    result["v5_entry_type"] = entry_types
    result["v5_exit_type"] = exit_types

    return result


def get_v5_analysis(df: pd.DataFrame) -> dict:
    """取得最新的 V5 分析結果"""
    signals_df = generate_v5_signals(df)
    latest = signals_df.iloc[-1]

    return {
        "date": signals_df.index[-1],
        "close": latest["close"],
        "signal": latest["v5_signal"],
        "entry_type": latest["v5_entry_type"],
        "exit_type": latest["v5_exit_type"],
        "indicators": {
            "RSI": latest.get("rsi"),
            "ADX": latest.get("adx"),
            "BB_Upper": latest.get("bb_upper"),
            "BB_Middle": latest.get("bb_middle"),
            "BB_Lower": latest.get("bb_lower"),
            "Volume_Ratio": latest.get("volume_ratio"),
        },
    }


def adaptive_strategy_score(
    v4_signal: str,
    v5_signal: str,
    regime: str,
    v4_confidence: float = 1.0,
) -> dict:
    """V4 + V5 自適應混合評分

    根據市場狀態動態分配 V4/V5 權重：
    - 趨勢噴發 / 溫和趨勢: V4 主導 (0.9 / 0.1)
    - 震盪劇烈: V5 主導 (0.2 / 0.8)
    - 低波盤整: 均衡偏 V5 (0.3 / 0.7)

    Returns:
        dict with final_signal, v4_weight, v5_weight, composite_score
    """
    # Weight mapping by market regime
    regime_weights = {
        "trend_explosive": (0.9, 0.1),
        "trend_mild": (0.8, 0.2),
        "range_volatile": (0.2, 0.8),
        "range_quiet": (0.3, 0.7),
    }

    w4, w5 = regime_weights.get(regime, (0.5, 0.5))

    # Signal scoring: BUY=1.0, HOLD=0, SELL=-1.0
    signal_score = {"BUY": 1.0, "HOLD": 0.0, "SELL": -1.0}

    s4 = signal_score.get(v4_signal, 0) * v4_confidence
    s5 = signal_score.get(v5_signal, 0)

    composite = w4 * s4 + w5 * s5

    # Determine final signal
    if composite >= 0.5:
        final = "BUY"
    elif composite <= -0.5:
        final = "SELL"
    else:
        final = "HOLD"

    return {
        "final_signal": final,
        "composite_score": round(composite, 3),
        "v4_weight": w4,
        "v5_weight": w5,
        "v4_score": round(s4, 3),
        "v5_score": round(s5, 3),
        "regime": regime,
    }

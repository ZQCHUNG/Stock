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
    # 進場條件（傳統）
    "rsi_oversold": 30,          # RSI 超賣門檻（固定上限）
    "rsi_dynamic_window": 60,    # 動態 RSI 門檻滾動窗口（天）
    "rsi_dynamic_percentile": 15,  # 動態 RSI 百分位（15th = 更自適應）
    "bb_touch_margin": 0.005,    # 距 BB 下軌容許範圍（0.5%）
    "volume_shrink_ratio": 0.7,  # 縮量門檻（< 0.7x 五日均量）
    "adx_max": 25,               # ADX 上限（排除強趨勢）
    "min_volume_lots": 500,      # 最低成交量（張）
    "bias_threshold": -0.05,     # BIAS 門檻（< -5% = 強均值回歸信號）
    # R71-B: Z-Score 動態進場（解決 V5 在多頭市場幾乎無交易的問題）
    "zscore_enabled": True,       # 啟用 Z-Score 進場路徑
    "zscore_threshold": -1.5,     # VALIDATED: N-sweep confirmed plateau (N=1.0→0.19, 1.5→0.45, 2.0→0.32)
    "zscore_adx_max": 35,         # Z-Score 進場允許更高 ADX（捕捉趨勢中回檔）
    "zscore_rsi_max": 45,         # Z-Score 進場的 RSI 上限（不需要極端超賣）
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
    rsi_dyn_window = p.get("rsi_dynamic_window", 60)
    rsi_dyn_pct = p.get("rsi_dynamic_percentile", 15) / 100  # 0.15
    bb_margin = p["bb_touch_margin"]
    vol_shrink = p["volume_shrink_ratio"]
    adx_max = p["adx_max"]
    min_vol_lots = p.get("min_volume_lots", 0)
    rsi_overbought = p["rsi_overbought"]
    bias_threshold = p.get("bias_threshold", -0.05)

    # Pre-compute dynamic RSI threshold (rolling 15th percentile)
    if "rsi" in result.columns:
        result["v5_rsi_threshold"] = result["rsi"].rolling(
            window=rsi_dyn_window, min_periods=20
        ).quantile(rsi_dyn_pct)
    else:
        result["v5_rsi_threshold"] = np.nan

    # BIAS = (close - MA20) / MA20 — 乖離率
    if "ma20" in result.columns:
        result["v5_bias"] = (result["close"] - result["ma20"]) / result["ma20"]
    else:
        result["v5_bias"] = np.nan

    # R71-B: Z-Score = (Price - MA20) / StdDev(20)
    zscore_enabled = p.get("zscore_enabled", False)
    zscore_threshold = p.get("zscore_threshold", -1.5)
    zscore_adx_max = p.get("zscore_adx_max", 35)
    zscore_rsi_max = p.get("zscore_rsi_max", 45)
    if zscore_enabled and "ma20" in result.columns:
        _std20 = result["close"].rolling(20, min_periods=10).std()
        result["v5_zscore"] = (result["close"] - result["ma20"]) / _std20.replace(0, np.nan)
    else:
        result["v5_zscore"] = np.nan

    signals = []
    entry_types = []
    exit_types = []
    bias_confirmed_list = []

    for i in range(len(result)):
        if i < 2:
            signals.append("HOLD")
            entry_types.append("")
            exit_types.append("")
            bias_confirmed_list.append(False)
            continue

        row = result.iloc[i]

        close = row["close"]
        rsi = row.get("rsi", np.nan)
        adx = row.get("adx", np.nan)
        bb_lower = row.get("bb_lower", np.nan)
        bb_middle = row.get("bb_middle", np.nan)
        vol = row.get("volume", np.nan)
        vol_ma5 = row.get("volume_ma5", np.nan)
        rsi_dyn = row.get("v5_rsi_threshold", np.nan)
        bias = row.get("v5_bias", np.nan)
        zscore = row.get("v5_zscore", np.nan)

        # Skip if indicators not ready
        if any(pd.isna([rsi, adx, bb_lower, bb_middle, vol, vol_ma5])):
            signals.append("HOLD")
            entry_types.append("")
            exit_types.append("")
            bias_confirmed_list.append(False)
            continue

        # === 出場信號（優先判斷） ===
        # 1. 價格回到 BB 中軌（均值回歸完成）
        if close >= bb_middle:
            signals.append("SELL")
            entry_types.append("")
            exit_types.append("bb_middle")
            bias_confirmed_list.append(False)
            continue

        # 2. RSI 超買（反彈過度）
        if rsi >= rsi_overbought:
            signals.append("SELL")
            entry_types.append("")
            exit_types.append("rsi_overbought")
            bias_confirmed_list.append(False)
            continue

        # === 進場信號 ===
        buy = False
        entry_type = ""
        has_bias_confirm = False

        # BIAS confirmation: price 5%+ below MA20
        if not pd.isna(bias) and bias < bias_threshold:
            has_bias_confirm = True

        # --- 路徑 1: 傳統 BB+RSI 進場（嚴格條件，盤整市場） ---
        if adx < adx_max:
            # 最低量過濾
            if min_vol_lots <= 0 or vol >= min_vol_lots * 1000:
                effective_rsi_val = min(rsi_oversold, rsi_dyn) if not pd.isna(rsi_dyn) else rsi_oversold
                bb_distance = (close - bb_lower) / bb_lower if bb_lower > 0 else 999
                is_near_bb_lower = bb_distance <= bb_margin
                is_rsi_oversold = rsi <= effective_rsi_val
                is_volume_shrinking = vol < vol_ma5 * vol_shrink if vol_ma5 > 0 else False

                if is_near_bb_lower and is_rsi_oversold and is_volume_shrinking:
                    buy = True
                    entry_type = "bb_rsi_oversold_bias" if has_bias_confirm else "bb_rsi_oversold"

        # --- 路徑 2: R71-B Z-Score 進場（較寬鬆，可在趨勢中回檔時觸發） ---
        if not buy and zscore_enabled and not pd.isna(zscore):
            if (zscore < zscore_threshold
                    and adx < zscore_adx_max
                    and rsi < zscore_rsi_max):
                buy = True
                entry_type = "zscore_pullback"

        if buy:
            signals.append("BUY")
            entry_types.append(entry_type)
            exit_types.append("")
            bias_confirmed_list.append(has_bias_confirm)
        else:
            signals.append("HOLD")
            entry_types.append("")
            exit_types.append("")
            bias_confirmed_list.append(False)

    result["v5_signal"] = signals
    result["v5_entry_type"] = entry_types
    result["v5_exit_type"] = exit_types
    result["v5_bias_confirmed"] = bias_confirmed_list

    return result


def get_v5_analysis(df: pd.DataFrame) -> dict:
    """取得最新的 V5 分析結果"""
    signals_df = generate_v5_signals(df)
    latest = signals_df.iloc[-1]

    rsi_dyn = latest.get("v5_rsi_threshold")
    bias = latest.get("v5_bias")
    bias_confirmed = bool(latest.get("v5_bias_confirmed", False))

    return {
        "date": signals_df.index[-1],
        "close": latest["close"],
        "signal": latest["v5_signal"],
        "entry_type": latest["v5_entry_type"],
        "exit_type": latest["v5_exit_type"],
        "bias_confirmed": bias_confirmed,
        "indicators": {
            "RSI": latest.get("rsi"),
            "RSI_Dynamic_Threshold": float(rsi_dyn) if not pd.isna(rsi_dyn) else None,
            "ADX": latest.get("adx"),
            "BB_Upper": latest.get("bb_upper"),
            "BB_Middle": latest.get("bb_middle"),
            "BB_Lower": latest.get("bb_lower"),
            "Volume_Ratio": latest.get("volume_ratio"),
            "BIAS": float(bias) if not pd.isna(bias) else None,
        },
    }


def adaptive_strategy_score(
    v4_signal: str,
    v5_signal: str,
    regime: str,
    v4_confidence: float = 1.0,
    v5_bias_confirmed: bool = False,
) -> dict:
    """V4 + V5 自適應混合評分

    根據市場狀態動態分配 V4/V5 權重：
    - 趨勢噴發 / 溫和趨勢: V4 主導 (0.9 / 0.1)
    - 震盪劇烈: V5 主導 (0.2 / 0.8)
    - 低波盤整: 均衡偏 V5 (0.3 / 0.7)

    BIAS 確認加成（Gemini R38）：
    - 當 V5 BUY + BIAS < -5% → V5 分數 ×1.2（乖離率大 = 強回歸動能）

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

    # BIAS confirmation boost: V5 BUY with strong mean-reversion signal
    if v5_bias_confirmed and v5_signal == "BUY":
        s5 *= 1.2

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
        "v5_bias_confirmed": v5_bias_confirmed,
        "regime": regime,
    }

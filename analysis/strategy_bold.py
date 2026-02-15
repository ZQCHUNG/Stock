"""Bold 策略 — 能量擠壓突破 + 階梯式停利 (R66-R67)

核心邏輯（Claude + Gemini 共識）：
1. 進場：布林通道擠壓 + 成交量暴增突破（Energy Squeeze Breakout）
   OR 超跌反彈 + RSI < 30 + 量能枯竭後放量
   OR 量能爬坡突破（Volume Ramp — 小型股發現）
2. 出場：階梯式獲利保護（Step-up Buffer）+ Regime-Based Trail
3. 適用場景：長期橫盤後的爆發行情（如生技股、題材股）

與 V4/V5 的關係：
- V4 趨勢追蹤：穩健核心（Core），捕捉已確認的趨勢
- V5 均值回歸：震盪抄底，短線操作
- Bold 大膽策略：衛星倉位（Satellite），捕捉爆發性波段
- Core-Satellite：V4 佔 80%，Bold 佔 15-20% 總資金上限

風控特色：
- 階梯式停損：獲利越多，停損越寬（讓利潤奔跑）
- Regime-Based Trail：MA200 上升時動態放寬 trail（信念模式 2.0）
- 災難停損：無論獲利多少，絕對止損
- 最低持有：10 天（避免被洗出主升段）

參數驗證狀態（R67 Sweep, n=3 stocks, 2021-2026）：
- trail_level3_pct = 0.15 → VALIDATED（跨股一致，robust band 0.15-0.35）
- stop_loss_pct = 0.15-0.18 → VALIDATED
- conviction_hold_gain → DEAD_PARAMETER（已移除，R67 sweep 證明零效果）
- ATR multiplier → NEEDS_MORE_DATA（方向因股不同）
- trail_regime_wide_pct = 0.25 → HYPOTHESIS（Gemini Conviction 2.0 提議）
"""

import pandas as pd
import numpy as np
from analysis.indicators import calculate_all_indicators


# Bold 策略預設參數
STRATEGY_BOLD_PARAMS = {
    # --- 進場條件 ---
    # 能量擠壓突破
    "bb_squeeze_lookback": 120,       # 布林帶寬度觀察窗口
    "bb_squeeze_percentile": 10,      # 帶寬低於歷史 N% → 判定為擠壓
    "volume_breakout_ratio": 2.5,     # 突破量 > N 倍 20 日均量
    "price_breakout_above_bb": True,  # 價格需突破 BB 上軌
    # 超跌反彈（備用進場）
    "rsi_oversold": 30,               # RSI 超賣門檻
    "price_near_52w_low_pct": 0.15,   # 價格距 52 週低點 < 15%
    "volume_capitulation_ratio": 1.5, # 恐慌量 > 1.5x 均量
    # 進場 C：量能爬坡突破（小型股發現）
    "volume_ramp_enabled": True,      # 啟用量能爬坡偵測
    "volume_ramp_min_lots": 30,       # 小型股最低門檻 30 張
    "volume_ramp_ratio": 2.0,         # 近期量 > 遠期量 2 倍以上
    "volume_ramp_lookback_short": 20, # 近期量能窗口 20 日
    "volume_ramp_lookback_long": 120, # 遠期量能窗口 120 日
    "price_breakout_high_days": 60,   # 價格突破 N 日新高
    # 共用
    "min_volume_lots": 200,           # 最低日均量（張）— 標準模式門檻
    "atr_period": 20,                 # ATR 週期

    # --- 出場條件（階梯式 Step-up Buffer）---
    "stop_loss_pct": 0.15,            # 絕對災難停損 -15%
    "min_hold_days": 10,              # 最短持有天數
    # Level 1: 獲利 < 30%
    "trail_level1_pct": 0.15,         # trailing -15%
    # Level 2: 獲利 30-50%
    "trail_level2_threshold": 0.30,   # 進入 Level 2 的獲利門檻
    "trail_level2_floor": 0.10,       # 鎖住成本 +10% 以上（保底）
    # Level 3: 獲利 > 50%（信念模式）
    "trail_level3_threshold": 0.50,   # 進入 Level 3 的獲利門檻
    "trail_level3_pct": 0.15,         # VALIDATED(n=3, 2021-2026): trailing -15%
    # ATR 動態停損
    "atr_trail_multiplier": 3.0,      # NEEDS_MORE_DATA: 停損 = peak - N × ATR
    "use_atr_trail": True,            # 是否啟用 ATR 動態停損

    # --- 部位 ---
    "max_position_pct": 0.20,         # 大膽模式最大倉位 20%（衛星）
    "max_hold_days": 120,             # 最長持有天數

    # --- Regime-Based Trail（Conviction 2.0，取代 DEAD conviction_hold_gain）---
    "ultra_wide": False,              # 是否啟用超寬頻模式
    "regime_trail_enabled": True,     # HYPOTHESIS: MA200 上升時動態放寬 trail
    "ma_slope_threshold": 0.0,        # MA200 斜率 > 此值 → 多頭 regime
    "trail_regime_wide_pct": 0.25,    # HYPOTHESIS: 多頭 regime 下放寬到 -25%
}

# Ultra-Wide 預設（適用 6139 型長線價值股）
STRATEGY_BOLD_ULTRA_WIDE = {
    **STRATEGY_BOLD_PARAMS,
    "ultra_wide": True,
    "trail_level3_pct": 0.15,         # VALIDATED(n=3): 基準 -15%
    "trail_regime_wide_pct": 0.25,    # HYPOTHESIS: 多頭 regime 下放寬到 -25%
    "max_hold_days": 365,             # 名義上最長持有 1 年
    "min_hold_days": 15,              # 最短持有 15 天
    "stop_loss_pct": 0.18,            # VALIDATED(n=3): 災難停損 -18%
}


def _compute_bb_bandwidth(df: pd.DataFrame) -> pd.Series:
    """計算 Bollinger Band 帶寬 (bandwidth = (upper - lower) / middle)"""
    return (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]


def _compute_keltner_channels(df: pd.DataFrame, period: int = 20, atr_mult: float = 1.5) -> tuple:
    """計算 Keltner Channels (用 EMA + ATR)"""
    ema = df["close"].ewm(span=period, adjust=False).mean()
    kc_upper = ema + atr_mult * df["atr"]
    kc_lower = ema - atr_mult * df["atr"]
    return kc_upper, kc_lower


def _detect_squeeze(df: pd.DataFrame, lookback: int = 120, percentile: int = 10) -> pd.Series:
    """偵測布林帶擠壓狀態

    擠壓 = BB 帶寬處於歷史低位 AND BB 被包在 Keltner Channel 內
    """
    bw = _compute_bb_bandwidth(df)
    bw_threshold = bw.rolling(lookback, min_periods=30).apply(
        lambda x: np.percentile(x, percentile), raw=True
    )
    kc_upper, kc_lower = _compute_keltner_channels(df)

    # 擠壓：BB 在 KC 內 + 帶寬低
    squeeze = (
        (df["bb_upper"] < kc_upper) &
        (df["bb_lower"] > kc_lower) &
        (bw <= bw_threshold)
    )
    return squeeze


def _detect_squeeze_release(squeeze: pd.Series) -> pd.Series:
    """偵測擠壓釋放（從 squeeze=True 變成 False 的第一天）"""
    return squeeze.shift(1).fillna(False) & ~squeeze


def generate_bold_signals(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    """產生 Bold 大膽策略訊號

    進場邏輯：
    A) 能量擠壓突破：BB squeeze release + 價格突破 BB 上軌 + 量能 > 2.5x
    B) 超跌反彈：RSI < 30 + 近 52 週低點 + 恐慌量

    出場邏輯（階梯式 Step-up Buffer）：
    - 絕對停損 -15%
    - Level 1 (<30% gain): trailing -15%
    - Level 2 (30-50% gain): 鎖住 +10%，trailing -15%
    - Level 3 (>50% gain): trailing -25% 或 3×ATR

    Returns:
        DataFrame with columns:
        - bold_signal: "BUY" / "HOLD" / "SELL"
        - bold_entry_type: "squeeze_breakout" / "oversold_bounce" / ""
        - bold_squeeze: bool (是否處於擠壓狀態)
        - bold_vol_ratio: float (成交量/20日均量)
    """
    p = dict(STRATEGY_BOLD_PARAMS)
    if params:
        p.update(params)

    result = calculate_all_indicators(df)
    n = len(result)

    # --- 計算額外指標 ---
    # BB 帶寬 & 擠壓偵測
    squeeze = _detect_squeeze(result, p["bb_squeeze_lookback"], p["bb_squeeze_percentile"])
    squeeze_release = _detect_squeeze_release(squeeze)

    # 量能比率
    vol_ratio = result["volume"] / result["volume"].rolling(20).mean()

    # 52 週低點
    rolling_low_252 = result["close"].rolling(252, min_periods=60).min()
    near_52w_low = (result["close"] / rolling_low_252 - 1) < p["price_near_52w_low_pct"]

    # 量能爬坡指標（Volume Ramp — 小型股發現用）
    vol_ramp_short = p.get("volume_ramp_lookback_short", 20)
    vol_ramp_long = p.get("volume_ramp_lookback_long", 120)
    vol_ma_short = result["volume"].rolling(vol_ramp_short, min_periods=10).mean()
    vol_ma_long = result["volume"].rolling(vol_ramp_long, min_periods=30).mean()
    vol_ramp_ratio = vol_ma_short / vol_ma_long  # 近期量 / 遠期量

    # N日新高
    breakout_days = p.get("price_breakout_high_days", 60)
    rolling_high = result["close"].rolling(breakout_days, min_periods=20).max()

    # --- 訊號邏輯 ---
    signals = pd.Series("HOLD", index=result.index)
    entry_types = pd.Series("", index=result.index)

    for i in range(60, n):
        vol_lots = result["volume"].iloc[i] / 1000

        # --- 進場 A：能量擠壓突破（標準門檻）---
        if vol_lots >= p["min_volume_lots"]:
            if (squeeze_release.iloc[i] and
                vol_ratio.iloc[i] > p["volume_breakout_ratio"] and
                (not p["price_breakout_above_bb"] or result["close"].iloc[i] > result["bb_upper"].iloc[i])):
                signals.iloc[i] = "BUY"
                entry_types.iloc[i] = "squeeze_breakout"
                continue

        # --- 進場 B：超跌反彈（標準門檻）---
        if vol_lots >= p["min_volume_lots"]:
            if (result["rsi"].iloc[i] < p["rsi_oversold"] and
                near_52w_low.iloc[i] and
                vol_ratio.iloc[i] > p["volume_capitulation_ratio"]):
                signals.iloc[i] = "BUY"
                entry_types.iloc[i] = "oversold_bounce"
                continue

        # --- 進場 C：量能爬坡突破（小型股發現）---
        # 低門檻：只要 30 張即可，但需要量能趨勢 + 價格突破
        if (p.get("volume_ramp_enabled", True) and
            vol_lots >= p.get("volume_ramp_min_lots", 30)):
            ramp = vol_ramp_ratio.iloc[i]
            is_new_high = result["close"].iloc[i] >= rolling_high.iloc[i] * 0.98  # 接近新高
            above_ma = result["close"].iloc[i] > result["ma20"].iloc[i]

            if (not np.isnan(ramp) and
                ramp >= p.get("volume_ramp_ratio", 2.0) and
                is_new_high and above_ma and
                vol_ratio.iloc[i] > 1.5):  # 當日量 > 1.5x 20日均量
                signals.iloc[i] = "BUY"
                entry_types.iloc[i] = "volume_ramp"
                continue

        # --- 量能先行偵測（pre-breakout alert）---
        # 價格未破前高但量能異常，作為潛在突破預警
        if (vol_ratio.iloc[i] > 2.0 and
            not squeeze.iloc[i] and
            result["close"].iloc[i] > result["ma20"].iloc[i] and
            result["close"].iloc[i] > result["close"].iloc[i-1]):
            # 不直接 BUY，但標記為觀察
            pass

    result["bold_signal"] = signals
    result["bold_entry_type"] = entry_types
    result["bold_squeeze"] = squeeze
    result["bold_vol_ratio"] = vol_ratio
    result["bold_near_52w_low"] = near_52w_low

    return result


def get_bold_analysis(df: pd.DataFrame, params: dict | None = None) -> dict:
    """取得最新 Bold 策略分析結果"""
    signals_df = generate_bold_signals(df, params)
    if signals_df.empty:
        return {"signal": "HOLD", "entry_type": "", "squeeze": False}

    latest = signals_df.iloc[-1]
    # 回顧最近 5 天的擠壓狀態
    recent_squeeze = signals_df["bold_squeeze"].tail(10).sum()

    return {
        "date": str(signals_df.index[-1]),
        "close": float(latest["close"]),
        "signal": latest["bold_signal"],
        "entry_type": latest["bold_entry_type"],
        "squeeze": bool(latest["bold_squeeze"]),
        "squeeze_days_in_10": int(recent_squeeze),
        "vol_ratio": round(float(latest["bold_vol_ratio"]), 2),
        "near_52w_low": bool(latest["bold_near_52w_low"]),
        "rsi": round(float(latest["rsi"]), 1),
        "atr": round(float(latest["atr"]), 2),
        "atr_pct": round(float(latest["atr_pct"]), 4),
        "bb_bandwidth": round(float(
            (latest["bb_upper"] - latest["bb_lower"]) / latest["bb_middle"]
        ), 4),
        "indicators": {
            "bb_upper": round(float(latest["bb_upper"]), 2),
            "bb_middle": round(float(latest["bb_middle"]), 2),
            "bb_lower": round(float(latest["bb_lower"]), 2),
            "ma20": round(float(latest["ma20"]), 2),
            "ma60": round(float(latest["ma60"]), 2),
        },
    }


def compute_bold_exit(
    entry_price: float,
    current_price: float,
    peak_price: float,
    current_atr: float,
    hold_days: int,
    params: dict | None = None,
    ma200_slope: float | None = None,
) -> dict:
    """計算 Bold 策略的出場決策（階梯式 Step-up Buffer）

    Args:
        entry_price: 進場價格
        current_price: 當前價格
        peak_price: 持有期間最高價
        current_atr: 當前 ATR
        hold_days: 已持有天數
        params: 策略參數覆蓋
        ma200_slope: MA200 斜率（20 日變化率），正值表示年線上升

    Returns:
        {
            "should_exit": bool,
            "exit_reason": str,
            "level": int (0/1/2/3),
            "trailing_stop_price": float,
            "gain_pct": float,
        }
    """
    p = dict(STRATEGY_BOLD_PARAMS)
    if params:
        p.update(params)

    gain_pct = (current_price / entry_price) - 1

    # Regime-Based Trail（Conviction 2.0）：MA200 上升時動態放寬 trail
    regime_bullish = (
        p.get("regime_trail_enabled", True)
        and ma200_slope is not None
        and ma200_slope > p.get("ma_slope_threshold", 0.0)
    )

    # 最短持有期保護（除非觸發災難停損）
    if hold_days < p["min_hold_days"] and gain_pct > -p["stop_loss_pct"]:
        return {
            "should_exit": False,
            "exit_reason": "",
            "level": 1,
            "trailing_stop_price": entry_price * (1 - p["stop_loss_pct"]),
            "gain_pct": gain_pct,
        }

    # --- 絕對災難停損 ---
    if gain_pct <= -p["stop_loss_pct"]:
        return {
            "should_exit": True,
            "exit_reason": f"disaster_stop_{p['stop_loss_pct']*100:.0f}pct",
            "level": 0,
            "trailing_stop_price": entry_price * (1 - p["stop_loss_pct"]),
            "gain_pct": gain_pct,
        }

    # --- 最長持有限制 ---
    if hold_days >= p["max_hold_days"]:
        return {
            "should_exit": True,
            "exit_reason": f"max_hold_{p['max_hold_days']}d",
            "level": 3 if gain_pct > p["trail_level3_threshold"] else 2 if gain_pct > p["trail_level2_threshold"] else 1,
            "trailing_stop_price": current_price,
            "gain_pct": gain_pct,
        }

    # --- Level 3: 獲利 > 50%（信念模式）---
    if gain_pct >= p["trail_level3_threshold"]:
        # Regime-Based Trail: 多頭 regime 下放寬 trail
        if regime_bullish and p.get("ultra_wide", False):
            trail_pct = p.get("trail_regime_wide_pct", 0.25)
        else:
            trail_pct = p["trail_level3_pct"]

        # ATR 動態或固定百分比
        if p["use_atr_trail"] and current_atr > 0 and not regime_bullish:
            atr_stop = peak_price - p["atr_trail_multiplier"] * current_atr
            pct_stop = peak_price * (1 - trail_pct)
            trail_price = max(atr_stop, pct_stop)
        else:
            trail_price = peak_price * (1 - trail_pct)

        # Level 2 保底（確保不虧到成本 +10% 以下）
        floor_price = entry_price * (1 + p["trail_level2_floor"])
        trail_price = max(trail_price, floor_price)

        if current_price <= trail_price:
            reason = "trail_level3_regime" if regime_bullish else "trail_level3"
            return {
                "should_exit": True,
                "exit_reason": reason,
                "level": 3,
                "trailing_stop_price": trail_price,
                "gain_pct": gain_pct,
            }
        return {
            "should_exit": False,
            "exit_reason": "",
            "level": 3,
            "trailing_stop_price": trail_price,
            "gain_pct": gain_pct,
        }

    # --- Level 2: 獲利 30-50%（保護模式）---
    if gain_pct >= p["trail_level2_threshold"]:
        floor_price = entry_price * (1 + p["trail_level2_floor"])
        trail_price = peak_price * (1 - p["trail_level1_pct"])
        trail_price = max(trail_price, floor_price)

        if current_price <= trail_price:
            return {
                "should_exit": True,
                "exit_reason": "trail_level2",
                "level": 2,
                "trailing_stop_price": trail_price,
                "gain_pct": gain_pct,
            }
        return {
            "should_exit": False,
            "exit_reason": "",
            "level": 2,
            "trailing_stop_price": trail_price,
            "gain_pct": gain_pct,
        }

    # --- Level 1: 獲利 < 30%（保本模式）---
    trail_price = peak_price * (1 - p["trail_level1_pct"])

    if current_price <= trail_price:
        return {
            "should_exit": True,
            "exit_reason": "trail_level1",
            "level": 1,
            "trailing_stop_price": trail_price,
            "gain_pct": gain_pct,
        }

    return {
        "should_exit": False,
        "exit_reason": "",
        "level": 1,
        "trailing_stop_price": trail_price,
        "gain_pct": gain_pct,
    }

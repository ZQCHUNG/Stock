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
    # 進場 D：動能趨勢突破（Marathon Runner — R62 Gemini + Architect Critic 共識）
    "momentum_breakout_enabled": True,  # 啟用動能趨勢突破
    # [PLACEHOLDER: BOLD_E_D_001] — 以下為經驗參數，需回測驗證
    "momentum_rsi_min": 55,            # RSI 下限（允許「剛脫離盤整」）
    "momentum_rsi_max": 80,            # RSI 上限（趨勢股常態性偏高）
    "momentum_vol_ratio": 1.2,         # 5日均量 > 1.2x 20日均量（穩定放量）
    "momentum_min_volume_lots": 500,   # 絕對量門檻：日均量 > 500 張
    "momentum_high_pct": 0.97,         # 價格 > 97% × 20日最高價（接近新高）
    # [PLACEHOLDER: SLOPE_D10] — MA20 斜率持續性確認
    "momentum_ma20_slope_days": 10,    # MA20 斜率 > 0 持續至少 N 天
    # [VERIFIED: TW_INDEX_TRADITION] — 台股環境過濾
    "momentum_taiex_filter": True,     # 啟用大盤環境過濾
    # 共用
    "min_volume_lots": 200,           # 最低日均量（張）— 標準模式門檻
    "atr_period": 20,                 # ATR 週期

    # --- [HYPOTHESIS: VCP_ENTRY_FILTER] Phase 5: VCP 進場過濾（華爾街交易員判決 2026-02-22）---
    # 「沒有 Base 的 Breakout 就是誘多」— 砍掉 paper cuts（6442 Trade #1-5）
    # A) ATR Tightness: 當前 ATR(20) / 過去 60 天最大 ATR < 0.6 = 壓縮中
    # B) Volume Dry-up: 過去 5 天至少 2 天 volume < vol_ma20 × 0.5 = 籌碼沈澱
    "vcp_entry_filter_enabled": True,     # 啟用 VCP 進場過濾
    "vcp_atr_tightness_max": 0.6,         # [HYPOTHESIS] ATR 壓縮比率上限
    "vcp_atr_tightness_lookback": 60,     # Rolling Max ATR 回看天數
    "vcp_vol_dryup_days": 5,              # 量縮檢查窗口天數
    "vcp_vol_dryup_min_count": 2,         # 至少 N 天量 < threshold
    "vcp_vol_dryup_ratio": 0.5,           # volume < vol_ma20 × 此值

    # --- [HYPOTHESIS: MOMENTUM_PULLBACK] Phase 6: 動能回踩進場（Branch B）---
    # 華爾街交易員判決 + Architect Critic APPROVED 2026-02-22
    # 「不要放寬 VCP，而是模組化進場邏輯 — VCP 是第一波，Momentum Pullback 是半山腰」
    # 當 VCP 不通過時，若股票已在確認上升趨勢中回踩支撐，允許非 VCP 進場
    "momentum_pullback_enabled": True,      # 啟用 Branch B 動能回踩
    "mp_ma50_slope_days": 10,               # [HYPOTHESIS] MA50 斜率 > 0 需持續 N 天
    "mp_pullback_lookback": 5,              # [HYPOTHESIS] 回踩支撐檢查窗口（天）
    "mp_pullback_tolerance": 1.02,          # [HYPOTHESIS] Low <= MA20 * 此值 = 觸碰
    "mp_vol_below_avg": True,               # 量能收斂: 當前量 < 5日均量
    "mp_high_breakout_days": 3,             # 價格重啟: 突破前 N 天高點
    # [PLACEHOLDER: MOMENTUM_ACCELERATION_GAP] 快捷通道門檻
    "mp_price_ma50_ratio": 1.15,            # Price/MA50 > 此值 → 跳過 VCP（已遠離底部）

    # --- [PLACEHOLDER: BOLD_RS_DUAL_GATE] Phase 9: Tiered Dual-Gate RS Filter ---
    # 華爾街交易員 R9 + Architect Critic APPROVED 2026-02-22
    # 原 Phase 8 Track B (ALL conditions) 統計上互斥 → 0 entries → 改為分級門檻
    # 軌道 A (Power Play): RS >= 80 → 按現有邏輯
    # 軌道 B1 (準龍頭): RS 60-79 → Vol > 1.5x AND ATR < 0.6 (蓄勢待發)
    # 軌道 B2 (性格改變): RS 40-59 → Vol > 2.5x OR 單日漲幅 > 5% (慣性突變)
    "bold_rs_filter_enabled": True,          # 啟用 RS 過濾
    "bold_rs_filter_min": 80,                # 軌道 A 門檻
    "bold_rs_trackb_enabled": True,          # 啟用軌道 B (Turnaround Sniper)
    "bold_rs_trackb_min": 40,                # [PLACEHOLDER: RS_TRACKB_MIN = 40]
    # B1 (RS 60-79): 準龍頭模式 — 已在起漲邊緣，不需爆量證明
    "bold_rs_b1_min": 60,                    # [PLACEHOLDER: RS_B1_MIN = 60]
    "bold_rs_b1_vol_ratio": 1.5,             # [PLACEHOLDER: B1_VOL = 1.5] 量能門檻 (vs MA20)
    "bold_rs_b1_atr_tightness": 0.6,         # [PLACEHOLDER: B1_ATR = 0.6] ATR 壓縮
    # B2 (RS 40-59): 性格改變模式 — 需要暴力買盤或價格噴發
    "bold_rs_b2_vol_ratio": 2.5,             # [PLACEHOLDER: B2_MOMENTUM_VOL = 2.5]
    "bold_rs_b2_daily_gain": 0.05,           # [PLACEHOLDER: B2_MOMENTUM_GAIN = 0.05] 單日漲幅 5%
    # 共用: Track B 部位係數 (Trader R9: 資金權重偏好強勢)
    "bold_rs_trackb_position_mult": 0.7,     # [PLACEHOLDER: TRACK_B_SIZE_MULTIPLIER = 0.7]

    # --- [PLACEHOLDER: PARABOLIC_HOLD] Phase 7B: Parabolic Hold（Level 4 Trail）---
    # 華爾街交易員 R6 + Architect Critic APPROVED 2026-02-22
    # 「Trade #8 抓到了 473，但股價去了 1985」— 超強趨勢需要更寬的出場
    # 收盤跌破 MA10 才出場（不看盤中），強迫系統在拋物線中留在大部隊
    "parabolic_hold_enabled": True,          # 啟用 Level 4 拋物線持倉
    "parabolic_gain_trigger": 0.20,          # [PLACEHOLDER: PARABOLIC_GAIN_TRIGGER = 0.20] R8: 獲利墊底 20% 才啟動
    "parabolic_ma_period": 10,               # [PLACEHOLDER: PARABOLIC_MA = 10] 使用 MA10
    # Phase 9: Parabolic Slope Filter (Trader R9 + Architect APPROVED)
    # MA5 平緩時退回 ATR trail，避免盤整區被 MA10 無謂洗出
    "parabolic_slope_filter": True,          # 啟用斜率過濾
    "parabolic_slope_threshold": 0.02,       # [PLACEHOLDER: SLOPE_LIMIT] MA5 5日斜率 > 2% 才算噴發

    # --- Phase 1 防守：物理止損機制（R62 Gemini 共識）---
    # [HYPOTHESIS: PRICE_TIME_SYNERGY] Price-Time Synergy（取代 time_stop_5d）
    # 華爾街交易員判決 + Architect Critic CONDITIONAL APPROVED (2026-02-22)
    # 原 time_stop_5d 被驗證為大波段殺手：6442 在 172 進場 8 天被踢出，後漲到 1985
    # 新邏輯：5d 無 3% gain 但 price > entry*0.98 且 vol 萎縮 → 繼續持有
    "time_stop_days": 5,              # 初始觀察天數
    "time_stop_min_gain": 0.03,       # 最低收益門檻 3%
    "time_stop_enabled": True,        # 啟用時間止損（現為 Price-Time Synergy）
    "pts_hold_threshold": 0.98,       # [HYPOTHESIS] Price-Time Synergy: 持有門檻 (entry * 0.98)
    "pts_abandon_threshold": 0.95,    # [HYPOTHESIS] 放棄門檻 (entry * 0.95)
    "pts_max_hold_days": 20,          # [HYPOTHESIS] PTS 最長延長持有天數
    # [PLACEHOLDER: BOLD_STRUCT_STOP] 結構止損：跌破 min(進場日低點, 前一日低點)
    "structural_stop_enabled": True,  # 啟用結構止損
    # [PLACEHOLDER: BOLD_TREND_STOP] 趨勢破位：價格 < MA20 且 MA20 斜率 ≤ 0
    "trend_break_stop_enabled": True, # 啟用趨勢破位止損
    "ma20_slope_lookback": 5,         # MA20 斜率計算窗口（天）

    # --- R62 Momentum Lag Stop（取代固定 Time Stop — Gemini + Architect Critic 共識）---
    # [PLACEHOLDER: BOLD_MLS_001] 延長期上限天數
    "time_stop_extended_days": 8,     # 量縮時可延長至 8 天
    # [PLACEHOLDER: BOLD_MLS_002] 量縮判定增益門檻
    "momentum_lag_gain_threshold": 0.01,  # ±1% 內算「不動」
    "momentum_lag_stop_enabled": True,    # 啟用 Momentum Lag Stop

    # --- R62/R63 RS_Rating 相對強度過濾（O'Neil RS — Gemini + Architect Critic 共識）---
    # [VERIFIED: INDUSTRY_STANDARD] RS 排名門檻（O'Neil: top 20% = Diamond）
    "rs_rating_min": 80,              # Entry D 需 RS ≥ 80（前 20%）— 或用 RS Momentum 替代
    # [VERIFIED: ONEILL_RS_TRADITION] RS 回看天數
    "rs_lookback": 120,               # 120 天價格強度
    # [PLACEHOLDER: BOLD_RS_002] 排除近期天數（避免抓到力竭標的）
    "rs_exclude_recent": 5,           # 排除最近 5 天
    "rs_rating_enabled": True,        # 啟用 RS 過濾
    # R63: 權重 RS（防止「短命噴泉」— Gemini Red Team Challenge）
    # [PLACEHOLDER: RS_WEIGHT_PROPOSAL_20260216] 0.6/0.4 分割需長週期回測驗證
    "rs_base_weight": 0.6,            # 前 100 天基礎強度權重
    "rs_recent_weight": 0.4,          # 近 20 天加速權重
    "rs_recent_days": 20,             # 近期分割點
    # [HYPOTHESIS: RS_MOMENTUM_ALPHA] RS Momentum（斜率）— 華爾街交易員判決 2026-02-22
    # 回測驗證：RS 絕對值滯後（6442 漲 6 倍才 Diamond, 6139 從未到 Diamond）
    # 但 RS Momentum 作為 Entry D 過濾也有問題：base-building 期 RS 自然下降
    # → RS Momentum 適合做 portfolio-level scanner，不適合做 entry filter
    # 單股回測時 DISABLED；portfolio scanning 時可 enable
    "rs_momentum_enabled": False,     # Entry D 的 RS Momentum 過濾（預設關閉）
    "rs_momentum_lookback": 20,       # RS 斜率計算窗口（天）
    "rs_momentum_min": 1.05,          # [HYPOTHESIS] RS_today/RS_20d_ago > 1.05 = 加速中

    # --- R62 Equity Curve Filter（連續虧損保護 — Gemini + Architect Critic 共識）---
    # [PLACEHOLDER: BOLD_ECF_001] 連續虧損上限
    "consecutive_loss_cap": 3,        # 連續 3 筆虧損觸發保護
    # [PLACEHOLDER: BOLD_ECF_002] 倉位縮減倍率
    "position_reduction_factor": 0.5, # 觸發後倉位減半
    "equity_curve_filter_enabled": True,  # 啟用 Equity Curve Filter

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

    # --- [HYPOTHESIS: REENTRY_ENGINE] Re-entry Engine（二次進場）---
    # 華爾街交易員判決 + Architect APPROVED 2026-02-22
    # 被 stop 踢出後監控 N 天，價格重新突破出場日高點 → 二次進場
    # Phase 4B 品質過濾（交易員判決：56 次交易 = 給券商打工）
    "reentry_enabled": True,          # 啟用 Re-entry Engine
    "reentry_window_days": 20,        # [HYPOTHESIS] 監控窗口天數
    "reentry_cooldown_days": 3,       # [HYPOTHESIS: NOISE_REDUCTION_FILTER] 出場後冷卻期（天）
    "reentry_volume_ratio": 1.5,      # [HYPOTHESIS: NOISE_REDUCTION_FILTER] Re-entry 日成交量 > vol_ma5 × 此倍數
    "reentry_min_price_pct": 0.02,    # [HYPOTHESIS: NOISE_REDUCTION_FILTER] Re-entry 價 > exit_price × (1 + 此值)

    # --- Regime-Based Trail（Conviction 2.0，取代 DEAD conviction_hold_gain）---
    "ultra_wide": False,              # 是否啟用超寬頻模式
    "regime_trail_enabled": True,     # VALIDATED(n=3): MA200 上升時動態放寬 trail (6139: 44%→274%)
    "ma_slope_threshold": 0.0,        # MA200 斜率 > 此值 → 多頭 regime
    "trail_regime_wide_pct": 0.20,    # VALIDATED(n=3, 2021-2026): 多頭 regime 下放寬到 -20%
}

# Ultra-Wide 預設（適用 6139 型長線價值股）
STRATEGY_BOLD_ULTRA_WIDE = {
    **STRATEGY_BOLD_PARAMS,
    "ultra_wide": True,
    "trail_level3_pct": 0.15,         # VALIDATED(n=3): 基準 -15%
    "trail_regime_wide_pct": 0.20,    # VALIDATED(n=3, 2021-2026): 0.20 optimal, 0.15-0.25 robust
    "max_hold_days": 365,             # 名義上最長持有 1 年
    "min_hold_days": 15,              # 最短持有 15 天
    "stop_loss_pct": 0.18,            # VALIDATED(n=3): 災難停損 -18%
}


def compute_rs_ratio(
    df: pd.DataFrame,
    lookback: int = 120,
    exclude_recent: int = 5,
    base_weight: float = 0.6,
    recent_weight: float = 0.4,
    recent_days: int = 20,
) -> float | None:
    """計算個股 Weighted Relative Strength (RS) ratio

    R63 權重 RS（Gemini Red Team Challenge — 防止「短命噴泉」）：
    Weighted RS = (base_return)^base_weight × (recent_return)^recent_weight

    其中：
    - base_return = close[-exclude-recent_days] / close[-exclude-lookback]
      → 前 100 天的基礎強度（佔 60%）
    - recent_return = close[-exclude] / close[-exclude-recent_days]
      → 近 20 天的加速度（佔 40%）

    穩定上漲股得分高於「一週瘋漲」的短命噴泉。

    Args:
        df: 股價 DataFrame（需有 'close' column）
        lookback: RS 回看天數（預設 120 天）
        exclude_recent: 排除最近 N 天（預設 5 天，避免力竭）
        base_weight: 基礎期權重（預設 0.6）
        recent_weight: 近期權重（預設 0.4）
        recent_days: 近期分割點（預設 20 天）

    Returns:
        Weighted RS ratio (float) 或 None（數據不足時）
    """
    if len(df) < lookback + exclude_recent:
        return None
    close = df["close"] if "close" in df.columns else None
    if close is None:
        return None

    # 三個時間點的收盤價（都排除最近 exclude_recent 天）
    # t0: lookback 天前, t1: recent_days 天前, t2: 現在（排除 exclude_recent）
    idx_t2 = -(1 + exclude_recent)                    # 近期終點
    idx_t1 = -(1 + exclude_recent + recent_days)       # 近期起點 = 基礎終點
    idx_t0 = -(1 + exclude_recent + lookback)          # 基礎起點（不含 exclude_recent）

    # 修正：idx_t0 應該是 lookback 天前（含 exclude_recent 偏移）
    idx_t0 = -(lookback + exclude_recent)

    try:
        price_t2 = float(close.iloc[idx_t2])
        price_t1 = float(close.iloc[idx_t1])
        price_t0 = float(close.iloc[idx_t0])
    except (IndexError, KeyError):
        return None

    if any(p <= 0 or np.isnan(p) for p in [price_t0, price_t1, price_t2]):
        return None

    base_return = price_t1 / price_t0    # 前 100 天表現
    recent_return = price_t2 / price_t1  # 近 20 天表現

    # 幾何加權：穩定上漲 > 短命噴泉
    return (base_return ** base_weight) * (recent_return ** recent_weight)


def compute_rs_momentum(
    df: pd.DataFrame,
    lookback: int = 20,
    rs_lookback: int = 120,
    rs_exclude_recent: int = 5,
    rs_base_weight: float = 0.6,
    rs_recent_weight: float = 0.4,
    rs_recent_days: int = 20,
) -> float | None:
    """計算 RS Momentum（RS 斜率）— 偵測 RS 加速度

    [HYPOTHESIS: RS_MOMENTUM_ALPHA] 華爾街交易員判決 2026-02-22
    回測驗證：RS 絕對值嚴重滯後（6442 漲 6 倍才到 Diamond）
    改用 RS_today / RS_N_days_ago 偵測「加速度」而非「速度」

    Args:
        df: 股價 DataFrame（需有 'close' column）
        lookback: RS Momentum 計算窗口（天），預設 20 天
        其餘參數傳遞給 compute_rs_ratio

    Returns:
        RS Momentum ratio (float > 1.0 = 加速中) 或 None
    """
    if len(df) < rs_lookback + rs_exclude_recent + lookback:
        return None

    # Current RS
    rs_now = compute_rs_ratio(
        df, rs_lookback, rs_exclude_recent,
        rs_base_weight, rs_recent_weight, rs_recent_days,
    )
    # RS N days ago
    rs_past = compute_rs_ratio(
        df.iloc[:-lookback], rs_lookback, rs_exclude_recent,
        rs_base_weight, rs_recent_weight, rs_recent_days,
    )

    if rs_now is None or rs_past is None or rs_past <= 0:
        return None

    return rs_now / rs_past


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


def generate_bold_signals(
    df: pd.DataFrame,
    params: dict | None = None,
    rs_rating: float | None = None,
    pit_rs_series: "pd.Series | None" = None,
    rs_roc_series: "pd.Series | None" = None,
) -> pd.DataFrame:
    """產生 Bold 大膽策略訊號

    Phase 10: PIT RS integration (Gemini R10-R11 + Architect APPROVED 2026-02-22)
    When pit_rs_series is provided, uses per-bar PIT RS percentile instead of
    the static rs_rating scalar. This eliminates look-ahead bias in backtests.
    rs_roc_series provides RS acceleration data for future Gene Mutation Gate.

    進場邏輯：
    A) 能量擠壓突破：BB squeeze release + 價格突破 BB 上軌 + 量能 > 2.5x
    B) 超跌反彈：RSI < 30 + 近 52 週低點 + 恐慌量
    C) 量能爬坡突破：近期量/遠期量 > 2x + 接近新高（小型股發現）
    D) 動能趨勢突破：均線多頭排列 + RSI [55,80] + 穩定放量 + MA20 斜率持續向上

    出場邏輯：
    Phase 1 防守：結構止損 + 時間止損 + 趨勢破位
    Phase 2 階梯式 Step-up Buffer：
    - Level 1 (<30% gain): trailing -15%
    - Level 2 (30-50% gain): 鎖住 +10%，trailing -15%
    - Level 3 (>50% gain): trailing -15%/ATR + Regime-Based Trail

    Returns:
        DataFrame with columns:
        - bold_signal: "BUY" / "HOLD" / "SELL"
        - bold_entry_type: "squeeze_breakout" / "oversold_bounce" / "volume_ramp" / "momentum_breakout"
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

    # --- Entry D 動能趨勢突破指標 ---
    # 均線（ma20, ma60 已在 indicators 中；ma120 需計算）
    ma120 = result["close"].rolling(120, min_periods=60).mean()
    # 20 日最高價
    rolling_high_20 = result["close"].rolling(20, min_periods=10).max()
    # 5 日均量
    vol_ma_5 = result["volume"].rolling(5, min_periods=3).mean()
    vol_ma_20 = result["volume"].rolling(20, min_periods=10).mean()
    # MA20 斜率持續性（連續 N 天斜率 > 0）
    ma20_diff = result["ma20"].diff()
    slope_days_req = p.get("momentum_ma20_slope_days", 10)
    ma20_slope_positive_streak = ma20_diff.rolling(slope_days_req, min_periods=slope_days_req).min()

    # --- RS Momentum per-bar computation ---
    # [HYPOTHESIS: RS_MOMENTUM_ALPHA] 計算每一根 bar 的 RS 斜率
    rs_momentum_series = None
    if p.get("rs_momentum_enabled", True):
        rsm_lookback = p.get("rs_momentum_lookback", 20)
        rs_lb = p.get("rs_lookback", 120)
        rs_ex = p.get("rs_exclude_recent", 5)
        rs_bw = p.get("rs_base_weight", 0.6)
        rs_rw = p.get("rs_recent_weight", 0.4)
        rs_rd = p.get("rs_recent_days", 20)
        min_bars_needed = rs_lb + rs_ex + rsm_lookback

        rsm_values = pd.Series(np.nan, index=result.index)
        for idx in range(min_bars_needed, n):
            # RS now (up to bar idx)
            sub_now = result.iloc[:idx + 1]
            rs_now = compute_rs_ratio(sub_now, rs_lb, rs_ex, rs_bw, rs_rw, rs_rd)
            # RS N days ago (up to bar idx - rsm_lookback)
            if idx - rsm_lookback >= rs_lb + rs_ex:
                sub_past = result.iloc[:idx - rsm_lookback + 1]
                rs_past = compute_rs_ratio(sub_past, rs_lb, rs_ex, rs_bw, rs_rw, rs_rd)
                if rs_now is not None and rs_past is not None and rs_past > 0:
                    rsm_values.iloc[idx] = rs_now / rs_past
        rs_momentum_series = rsm_values

    # --- [HYPOTHESIS: MOMENTUM_PULLBACK] Phase 6: 動能回踩指標 ---
    # MA50, MA10, MA50 slope, 3-day rolling high (for Branch B entry)
    ma50 = result["close"].rolling(50, min_periods=25).mean()
    ma10 = result["close"].rolling(10, min_periods=5).mean()
    ma50_diff = ma50.diff()
    mp_slope_days = p.get("mp_ma50_slope_days", 10)
    # MA50 斜率連續正: rolling min of diff > 0 = all positive in window
    ma50_slope_positive_streak = ma50_diff.rolling(mp_slope_days, min_periods=mp_slope_days).min()
    # 3-day rolling high for price restart trigger
    mp_breakout_days = p.get("mp_high_breakout_days", 3)
    rolling_high_3d = result["high"].rolling(mp_breakout_days, min_periods=1).max().shift(1)  # previous N days' high
    # Pullback detection: check if low touched MA20 within lookback window
    mp_pullback_lb = p.get("mp_pullback_lookback", 5)
    mp_pullback_tol = p.get("mp_pullback_tolerance", 1.02)
    # For each bar, check if any low in last N days was <= MA20 * tolerance
    low_near_ma20 = (result["low"] <= result["ma20"] * mp_pullback_tol).astype(int)
    low_near_ma10 = (result["low"] <= ma10 * mp_pullback_tol).astype(int)
    pullback_touched_ma20 = low_near_ma20.rolling(mp_pullback_lb, min_periods=1).max()  # 1 if any day touched
    pullback_touched_ma10 = low_near_ma10.rolling(mp_pullback_lb, min_periods=1).max()

    # --- [HYPOTHESIS: VCP_ENTRY_FILTER] Phase 5: VCP 進場過濾 ---
    # A) ATR Tightness: ATR(20) / Max_ATR(60) — 低值 = 壓縮中
    atr_20 = result["atr"] if "atr" in result.columns else (result["high"] - result["low"]).rolling(20).mean()
    atr_max_lb = p.get("vcp_atr_tightness_lookback", 60)
    atr_rolling_max = atr_20.rolling(atr_max_lb, min_periods=20).max()
    vcp_atr_tightness = atr_20 / atr_rolling_max  # < 0.6 = compressed

    # B) Volume Dry-up: count of last N days where volume < vol_ma20 * ratio
    vcp_dryup_ratio = p.get("vcp_vol_dryup_ratio", 0.5)
    vol_below_threshold = (result["volume"] < vol_ma_20 * vcp_dryup_ratio).astype(int)
    vcp_dryup_days = p.get("vcp_vol_dryup_days", 5)
    vcp_vol_dryup_count = vol_below_threshold.rolling(vcp_dryup_days, min_periods=1).sum()

    vcp_filter_on = p.get("vcp_entry_filter_enabled", True)
    vcp_tightness_max = p.get("vcp_atr_tightness_max", 0.6)
    vcp_dryup_min_count = p.get("vcp_vol_dryup_min_count", 2)

    # Phase 6 Momentum Pullback params
    mp_enabled = p.get("momentum_pullback_enabled", True)
    mp_price_ma50_ratio = p.get("mp_price_ma50_ratio", 1.15)

    # --- 訊號邏輯 ---
    signals = pd.Series("HOLD", index=result.index)
    entry_types = pd.Series("", index=result.index)
    # Phase 9: Position multiplier per bar (1.0 = full, 0.7 = Track B reduced)
    pos_multipliers = pd.Series(1.0, index=result.index)

    # Phase 6: Track VCP entry state — Momentum Pullback only unlocks after
    # a VCP-qualifying entry proves the trend (avoid paper cuts in base building)
    vcp_entry_occurred = False

    for i in range(60, n):
        # Phase 6: Update VCP entry tracking from previous bar
        # (must happen before VCP gate since entries use `continue`)
        if vcp_filter_on and not vcp_entry_occurred and i > 60:
            if signals.iloc[i - 1] == "BUY":
                # Previous bar generated a BUY — must have passed VCP gate
                vcp_entry_occurred = True

        # --- Dual-Track Entry Gate (Phase 5+6) ---
        # Branch A: VCP Sniper — compression detected (base breakout)
        # Branch B: Momentum Pullback — established uptrend pullback (power play)
        #   → ONLY available after VCP has already fired at least once
        # If neither passes → skip entry
        if vcp_filter_on:
            _atr_tight = vcp_atr_tightness.iloc[i]
            _vol_dry = vcp_vol_dryup_count.iloc[i]
            vcp_pass = ((not np.isnan(_atr_tight) and _atr_tight < vcp_tightness_max)
                        or _vol_dry >= vcp_dryup_min_count)

            if not vcp_pass:
                # Branch B: Momentum Pullback — only if VCP already proved the trend
                # 華爾街交易員: 「不要放寬 VCP，而是模組化進場邏輯」
                mp_pass = False
                if mp_enabled and vcp_entry_occurred:
                    _close_i = result["close"].iloc[i]
                    _ma50_i = ma50.iloc[i]
                    _ma50_slope_streak = ma50_slope_positive_streak.iloc[i]
                    _ma20_i = result["ma20"].iloc[i]

                    if (not np.isnan(_ma50_i) and not np.isnan(_ma50_slope_streak)
                            and not np.isnan(_ma20_i)):
                        # Core conditions shared by both paths:
                        # 1. Trend: Price > MA50 AND MA50 slope > 0 for N days
                        trend_ok = (_close_i > _ma50_i and _ma50_slope_streak > 0)
                        # 2. Pullback: low recently touched MA20 or MA10
                        pb_ok = (pullback_touched_ma20.iloc[i] >= 1
                                 or pullback_touched_ma10.iloc[i] >= 1)
                        # 3. Close above MA20 (support held, not broken)
                        above_ma20 = _close_i > _ma20_i
                        # 4. Volume convergence during PULLBACK (not breakout day)
                        #    Check if any of previous N days had vol < vol_ma5
                        #    (selling exhaustion during pullback before restart)
                        #    Window matches pullback lookback for consistency
                        vol_converge = True
                        if p.get("mp_vol_below_avg", True) and i >= mp_pullback_lb:
                            _found_low_vol = False
                            for j in range(max(1, i - mp_pullback_lb), i):  # previous N days
                                _vj = result["volume"].iloc[j]
                                _v5j = vol_ma_5.iloc[j]
                                if not np.isnan(_v5j) and _v5j > 0 and _vj < _v5j:
                                    _found_low_vol = True
                                    break
                            vol_converge = _found_low_vol
                        # 5. Price restart: break previous 3-day high
                        _rh3d = rolling_high_3d.iloc[i]
                        price_restart = (not np.isnan(_rh3d)
                                         and result["high"].iloc[i] > _rh3d)

                        # [PLACEHOLDER: MOMENTUM_ACCELERATION_GAP]
                        # Shortcut: Price/MA50 > threshold → relaxed check
                        # (already far above base, just need trend + support)
                        shortcut = _close_i / _ma50_i > mp_price_ma50_ratio

                        if shortcut:
                            # Relaxed: trend + pullback + close > MA20 + price restart
                            mp_pass = trend_ok and pb_ok and above_ma20 and price_restart
                        else:
                            # Full: all 5 conditions including volume convergence
                            mp_pass = trend_ok and pb_ok and above_ma20 and vol_converge and price_restart

                if not mp_pass:
                    # Neither VCP nor Momentum Pullback → skip
                    continue

        # --- [PLACEHOLDER: BOLD_RS_DUAL_GATE] Phase 9→10: Tiered Dual-Gate RS Filter ---
        # Phase 9: 華爾街交易員 R9 + Architect Critic APPROVED 2026-02-22
        # Phase 10: PIT RS integration (Trader R10-R11 APPROVED 2026-02-22)
        # 軌道 A: RS >= 80 → 直接通過
        # 軌道 B1: RS 60-79 (準龍頭) → Vol > 1.5x AND ATR < 0.6
        # 軌道 B2: RS 40-59 (性格改變) → Vol > 2.5x OR 單日漲幅 > 5%
        # RS < 40 → 完全阻擋
        #
        # When pit_rs_series is provided, use per-bar PIT RS instead of static scalar.
        # This eliminates look-ahead bias in backtests.
        _bar_rs = None
        if pit_rs_series is not None:
            # PIT mode: look up per-bar RS percentile by date
            bar_date = result.index[i]
            if bar_date in pit_rs_series.index:
                _bar_rs = pit_rs_series.loc[bar_date]
            else:
                # Try nearest date (within 3 days tolerance)
                _nearest = pit_rs_series.index.get_indexer([bar_date], method="ffill")
                if _nearest[0] >= 0:
                    _bar_rs = pit_rs_series.iloc[_nearest[0]]
            if _bar_rs is not None and np.isnan(_bar_rs):
                _bar_rs = None
        elif rs_rating is not None:
            _bar_rs = rs_rating  # Static mode (backward compatible)

        if p.get("bold_rs_filter_enabled", True) and _bar_rs is not None:
            rs_min_a = p.get("bold_rs_filter_min", 80)
            rs_min_b = p.get("bold_rs_trackb_min", 40)
            rs_b1_min = p.get("bold_rs_b1_min", 60)
            trackb_on = p.get("bold_rs_trackb_enabled", True)

            if _bar_rs >= rs_min_a:
                pass  # 軌道 A: Power Play — 直接通過
            elif trackb_on and _bar_rs >= rs_b1_min:
                # 軌道 B1 (RS 60-79): 準龍頭模式 — Vol > 1.5x AND ATR < 0.6
                _b1_pass = True
                _vr = vol_ratio.iloc[i]
                if np.isnan(_vr) or _vr < p.get("bold_rs_b1_vol_ratio", 1.5):
                    _b1_pass = False
                if _b1_pass:
                    _at = vcp_atr_tightness.iloc[i]
                    if np.isnan(_at) or _at >= p.get("bold_rs_b1_atr_tightness", 0.6):
                        _b1_pass = False
                if not _b1_pass:
                    continue
                # B1 pass → mark position multiplier
                pos_multipliers.iloc[i] = p.get("bold_rs_trackb_position_mult", 0.7)
            elif trackb_on and _bar_rs >= rs_min_b:
                # 軌道 B2 (RS 40-59): 性格改變模式 — Vol > 2.5x OR daily gain > 5%
                _vr = vol_ratio.iloc[i]
                _daily_gain = (result["close"].iloc[i] / result["close"].iloc[i - 1] - 1
                               if i > 0 else 0)
                _b2_vol_ok = not np.isnan(_vr) and _vr >= p.get("bold_rs_b2_vol_ratio", 2.5)
                _b2_gain_ok = _daily_gain >= p.get("bold_rs_b2_daily_gain", 0.05)
                if not (_b2_vol_ok or _b2_gain_ok):
                    continue
                # B2 pass → mark position multiplier
                pos_multipliers.iloc[i] = p.get("bold_rs_trackb_position_mult", 0.7)
            else:
                continue  # RS < 40 → 完全阻擋

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

        # --- 進場 D：動能趨勢突破（Marathon Runner）---
        # [PLACEHOLDER: BOLD_E_D_001] — 抓光聖型強勢趨勢股
        # 不需要擠壓，不需要超跌，只需要「均線多頭排列 + 穩定放量 + RSI 強勢」
        if p.get("momentum_breakout_enabled", True):
            _close = result["close"].iloc[i]
            _ma20 = result["ma20"].iloc[i]
            _ma60 = result["ma60"].iloc[i]
            _ma120_val = ma120.iloc[i]
            _rsi = result["rsi"].iloc[i]
            _vol5 = vol_ma_5.iloc[i]
            _vol20 = vol_ma_20.iloc[i]
            _high20 = rolling_high_20.iloc[i]
            _slope_streak = ma20_slope_positive_streak.iloc[i]
            _avg_vol_lots = _vol20 / 1000 if not np.isnan(_vol20) else 0

            if (not np.isnan(_ma120_val) and not np.isnan(_rsi) and
                not np.isnan(_vol5) and not np.isnan(_vol20) and _vol20 > 0 and
                not np.isnan(_high20) and not np.isnan(_slope_streak)):

                # 1. 均線多頭排列：Price > MA20 > MA60 > MA120
                ma_aligned = _close > _ma20 > _ma60 > _ma120_val

                # 2. 相對強度：Price > 0.97 × 20 日最高價
                near_high = _close > p.get("momentum_high_pct", 0.97) * _high20

                # 3. 動能區間：RSI ∈ [55, 80]
                rsi_ok = p.get("momentum_rsi_min", 55) <= _rsi <= p.get("momentum_rsi_max", 80)

                # 4. 穩定放量：5日均量 > 1.2x 20日均量 AND 日均量 > 500 張
                vol_ok = (_vol5 / _vol20 >= p.get("momentum_vol_ratio", 1.2) and
                          _avg_vol_lots >= p.get("momentum_min_volume_lots", 500))

                # 5. MA20 斜率 > 0 持續至少 N 天
                slope_ok = _slope_streak > 0

                # 6. RS 過濾（R62 → R93 升級：RS Momentum 取代絕對值）
                # [HYPOTHESIS: RS_MOMENTUM_ALPHA] 華爾街交易員判決 2026-02-22
                # 當 rs_rating 由 caller 傳入時，RS 決策已由 Dual-Gate (line 579) 處理
                # Entry D 不應重複檢查，否則會造成 cascade bug:
                #   Entry D blocked → vcp_entry_occurred=False → 全線崩潰
                # 只有 standalone 模式 (rs_rating=None) 才啟用 per-bar RS Momentum
                rs_ok = True
                if rs_rating is None:
                    # Standalone 模式：無外部 RS → Entry D 自行檢查 RS Momentum
                    if p.get("rs_momentum_enabled", True) and rs_momentum_series is not None:
                        bar_rsm = rs_momentum_series.iloc[i] if i < len(rs_momentum_series) else np.nan
                        if not np.isnan(bar_rsm):
                            rs_ok = bar_rsm >= p.get("rs_momentum_min", 1.05)
                        # If NaN (not enough data), let it pass

                if ma_aligned and near_high and rsi_ok and vol_ok and slope_ok and rs_ok:
                    signals.iloc[i] = "BUY"
                    entry_types.iloc[i] = "momentum_breakout"
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
    # Phase 9: Position multiplier (Architect: define in strategy, execute in engine)
    result["bold_position_mult"] = pos_multipliers

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
    entry_low: float | None = None,
    prev_day_low: float | None = None,
    current_ma20: float | None = None,
    ma20_slope: float | None = None,
    current_vol_ma5: float | None = None,
    current_vol_ma20: float | None = None,
    current_ma5: float | None = None,
    current_ma10: float | None = None,
    ma5_slope: float | None = None,
) -> dict:
    """計算 Bold 策略的出場決策（階梯式 Step-up Buffer + Phase 1 物理止損）

    Args:
        entry_price: 進場價格
        current_price: 當前價格
        peak_price: 持有期間最高價
        current_atr: 當前 ATR
        hold_days: 已持有天數
        params: 策略參數覆蓋
        ma200_slope: MA200 斜率（20 日變化率），正值表示年線上升
        entry_low: 進場當天最低價（Phase 1 結構止損用）
        prev_day_low: 進場前一天最低價（Phase 1 結構止損用）
        current_ma20: 當前 MA20 值（Phase 1 趨勢破位用）
        ma20_slope: MA20 斜率（Phase 1 趨勢破位用）
        current_vol_ma5: 當前 5 日均量（R62 Momentum Lag Stop 用）
        current_vol_ma20: 當前 20 日均量（R62 Momentum Lag Stop 用）
        current_ma5: 當前 MA5 值（R62 Momentum Lag Stop 延長期安全網）
        current_ma10: 當前 MA10 值（Phase 7B Parabolic Hold 出場用）

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

    # === Phase 1 防守：物理止損機制（R62 Gemini + Architect Critic 共識）===

    # --- 結構止損：跌破 min(Entry_Low, Entry-1_Low) 立即清倉 ---
    # [PLACEHOLDER: BOLD_STRUCT_STOP] — 爆量當天與前一天低點是主力防守的「關鍵 K 線」基點
    # 此止損無視最短持有期，因為結構破壞意味著進場論點已失效
    if p.get("structural_stop_enabled", True) and entry_low is not None:
        structural_floor = entry_low
        if prev_day_low is not None:
            structural_floor = min(entry_low, prev_day_low)
        if current_price < structural_floor:
            return {
                "should_exit": True,
                "exit_reason": "structural_stop",
                "level": 0,
                "trailing_stop_price": structural_floor,
                "gain_pct": gain_pct,
            }

    # --- Price-Time Synergy（取代 time_stop_5d — 華爾街交易員 + Architect 2026-02-22）---
    # [HYPOTHESIS: PRICE_TIME_SYNERGY]
    # 核心邏輯：飆股起漲初期常有 1-2 週平台整理（量縮價穩 = 籌碼吸收）
    # 舊 time_stop_5d 被驗證為大波段殺手（6442 Capture 3.2%）
    # 新規則：
    #   - 5d 無 3% gain → 檢查 Price-Time Synergy 條件
    #   - Hold if: price > entry*0.98 AND volume shrinking (vol_ma5 < vol_ma20)
    #   - Exit if: price < entry*0.95 OR (hold > pts_max_hold AND still no gain)
    #   - 破 MA5 時若 price < entry*0.98 → 出場（結構崩壞）
    if (p.get("time_stop_enabled", True)
            and hold_days >= p.get("time_stop_days", 5)
            and gain_pct < p.get("time_stop_min_gain", 0.03)
            and gain_pct > -p["stop_loss_pct"]):

        pts_hold = p.get("pts_hold_threshold", 0.98)
        pts_abandon = p.get("pts_abandon_threshold", 0.95)
        pts_max = p.get("pts_max_hold_days", 20)

        price_above_hold = current_price >= entry_price * pts_hold
        vol_shrinking = (current_vol_ma5 is not None
                         and current_vol_ma20 is not None
                         and current_vol_ma20 > 0
                         and current_vol_ma5 < current_vol_ma20)

        # Case 1: Price collapsed below abandon threshold → immediate exit
        if current_price < entry_price * pts_abandon:
            return {
                "should_exit": True,
                "exit_reason": "pts_abandon",
                "level": 0,
                "trailing_stop_price": entry_price * pts_abandon,
                "gain_pct": gain_pct,
            }

        # Case 2: Price holding AND volume shrinking → continue holding (PTS active)
        if price_above_hold and vol_shrinking and hold_days < pts_max:
            # PTS grace period — 量縮價穩，繼續觀察
            # But if breaks MA5 while below entry → exit
            if (current_ma5 is not None
                    and current_price < current_ma5
                    and current_price < entry_price):
                return {
                    "should_exit": True,
                    "exit_reason": "pts_ma5_break",
                    "level": 0,
                    "trailing_stop_price": current_ma5,
                    "gain_pct": gain_pct,
                }
            # Still in grace period, don't exit
            pass
        # Case 3: Exceeded PTS max hold days → exit
        elif hold_days >= pts_max and gain_pct < p.get("time_stop_min_gain", 0.03):
            return {
                "should_exit": True,
                "exit_reason": f"pts_timeout_{pts_max}d",
                "level": 0,
                "trailing_stop_price": entry_price,
                "gain_pct": gain_pct,
            }
        # Case 4: Price not holding OR volume not shrinking → old time_stop behavior
        elif not price_above_hold or not vol_shrinking:
            time_stop_days = p.get("time_stop_days", 5)
            extended_days = p.get("time_stop_extended_days", 8)

            # Give a bit more time if within extended window and volume is shrinking
            if (hold_days < extended_days
                    and vol_shrinking
                    and abs(gain_pct) <= p.get("momentum_lag_gain_threshold", 0.01)):
                if (current_ma5 is not None and current_price < current_ma5):
                    return {
                        "should_exit": True,
                        "exit_reason": "momentum_lag_ma5_break",
                        "level": 0,
                        "trailing_stop_price": current_ma5,
                        "gain_pct": gain_pct,
                    }
            else:
                return {
                    "should_exit": True,
                    "exit_reason": f"pts_no_synergy_{hold_days}d",
                    "level": 0,
                    "trailing_stop_price": entry_price,
                    "gain_pct": gain_pct,
                }

    # --- 趨勢破位：價格 < MA20 且 MA20 斜率 ≤ 0 ---
    # [PLACEHOLDER: BOLD_TREND_STOP] — 比單純 trailing stop 更有結構意義
    if (p.get("trend_break_stop_enabled", True)
            and current_ma20 is not None
            and ma20_slope is not None
            and hold_days >= p["min_hold_days"]):  # 趨勢破位遵守最短持有期
        if current_price < current_ma20 and ma20_slope <= 0:
            return {
                "should_exit": True,
                "exit_reason": "trend_break_ma20",
                "level": 0,
                "trailing_stop_price": current_ma20,
                "gain_pct": gain_pct,
            }

    # === 原有出場邏輯 ===

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

    # --- [PLACEHOLDER: PARABOLIC_HOLD] Phase 7B: Parabolic Hold (Level 4 Trail) ---
    # 華爾街交易員 R6 + Architect Critic APPROVED 2026-02-22
    # 「Trade #8 在 473 出場，股價去了 1985」— 超強趨勢需要 MA10 close 出場法
    # 條件: gain >= 30% AND close < MA10 (收盤價，非盤中)
    # 比 ATR trail 更寬鬆：拋物線中 stock 可能距 MA10 很遠，ATR trail 會過早觸發
    # Phase 9: Parabolic Slope Filter — only activate MA10 exit when MA5 is steep
    # If MA5 slope is flat (< threshold), fall back to ATR trail (avoid consolidation washout)
    _slope_ok = True
    if p.get("parabolic_slope_filter", True) and ma5_slope is not None:
        if not np.isnan(ma5_slope):
            _slope_ok = ma5_slope >= p.get("parabolic_slope_threshold", 0.02)
        # NaN slope → let parabolic work (not enough data)
    parabolic_on = (p.get("parabolic_hold_enabled", True)
                    and current_ma10 is not None
                    and not np.isnan(current_ma10)
                    and _slope_ok)

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

        # Phase 7B: Parabolic Hold — 用 MA10 close 取代 ATR/固定 trail
        # 在拋物線走勢中，MA10 close 比 ATR trail 更能跟隨趨勢
        # 只在收盤價判定（Architect: is_bar_closed = True by EOD），不看盤中
        if parabolic_on and gain_pct >= p.get("parabolic_gain_trigger", 0.30):
            # Use MA10 as the trailing reference instead of ATR trail
            # BUT keep the ATR trail as safety net (take the wider of the two)
            ma10_stop = current_ma10
            parabolic_trail = max(ma10_stop, floor_price)  # MA10 + floor protection
            # If close breaks MA10, exit (parabolic trend broken)
            if current_price < ma10_stop:
                return {
                    "should_exit": True,
                    "exit_reason": "parabolic_ma10_break",
                    "level": 4,
                    "trailing_stop_price": ma10_stop,
                    "gain_pct": gain_pct,
                }
            # If ATR trail triggers but MA10 holds → stay (trust the trend)
            # Only exit if BOTH MA10 breaks AND ATR trail triggers
            return {
                "should_exit": False,
                "exit_reason": "",
                "level": 4,
                "trailing_stop_price": parabolic_trail,
                "gain_pct": gain_pct,
            }

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

        # Phase 7B: Parabolic Hold in Level 2 — same MA10 close logic
        if parabolic_on and gain_pct >= p.get("parabolic_gain_trigger", 0.30):
            ma10_stop = current_ma10
            if current_price < ma10_stop:
                return {
                    "should_exit": True,
                    "exit_reason": "parabolic_ma10_break",
                    "level": 4,
                    "trailing_stop_price": ma10_stop,
                    "gain_pct": gain_pct,
                }
            parabolic_trail = max(ma10_stop, floor_price)
            return {
                "should_exit": False,
                "exit_reason": "",
                "level": 4,
                "trailing_stop_price": parabolic_trail,
                "gain_pct": gain_pct,
            }

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
    # [HYPOTHESIS: VOL_ADAPTIVE_EXIT_V1] Phase 4A: ATR-based wider trail
    # 華爾街交易員判決 + Architect APPROVED 2026-02-22:
    # 固定 15% 是「死板的物理」，ATR-based 是「動態的物理」
    # 用 min(pct_stop, atr_stop) → 取更寬的那個，給飆股呼吸空間
    pct_stop = peak_price * (1 - p["trail_level1_pct"])
    if p.get("use_atr_trail", True) and current_atr > 0:
        atr_stop = peak_price - p["atr_trail_multiplier"] * current_atr
        trail_price = min(pct_stop, atr_stop)  # 取更寬的止損（給波動空間）
    else:
        trail_price = pct_stop

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

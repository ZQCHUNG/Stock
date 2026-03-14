"""Accumulation Scanner — Wyckoff-based 洗盤偵測策略 (Architect APPROVED 2026-02-24)

背景：
系統現有策略（V4 趨勢動量、Bold Energy Squeeze）都是「趨勢確立後進場」型，
在 6748 亞果生醫案例中，V4 在 69+ 元才 BUY，而 Joe 在 66 元就憑直覺發現洗盤機會。
此模組填補「趨勢孕育期」的感知空白。

定位：不是獨立 BUY 策略，而是「觀察名單預警系統」
- Alpha 預警（Phase B 觸發）→ 加入觀察名單
- Beta 試單（量縮不破底）→ Joe 手動建 10-20% 底倉
- Gamma 全力（V4/Bold BUY）→ 已有成本優勢，推滿倉位

V4 幫你確認「對錯」，本策略幫你優化「成本」。

五大量化條件（華爾街交易員 + Architect Critic 共識）：
1. 底部結構：連續 3 個 Swing Low 遞增
2. 量能試盤：爆量紅棒 = Test for Supply
3. 洗盤確認：試盤後量縮且跌幅有限
4. 能量儲備：ADX < 20 持續 20+ 天
5. 相對強度：RS Rating vs 同業 > 70

Architect 額外指令：
- 試盤紅棒低點必須記憶，跌破即失效
- RS 必須相對於同業板塊

Protocol v3: 華爾街交易員 → Architect Critic APPROVED
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

_logger = logging.getLogger(__name__)

# ---------- Parameters (all tagged per 假精確 Protocol) ----------

# [PLACEHOLDER: ACCUM_SWING_LOW_MIN_COUNT_001] — 需回測驗證最佳值
SWING_LOW_MIN_COUNT = 3  # 至少 3 個遞增 Swing Low

# [PLACEHOLDER: ACCUM_SWING_LOW_UPLIFT_001] — 底部抬升最低幅度
# 1.02 太嚴格：57.3→58.0 只有 +1.2% 就不過。放寬到 1.005 (0.5%)
SWING_LOW_UPLIFT = 1.005  # Low_n > Low_(n-1) × 1.005 (nearly flat is OK for accumulation)

# [PLACEHOLDER: ACCUM_SWING_LOOKBACK_001]
SWING_LOOKBACK_HALF_WIN = 8  # Swing point detection half-window

# [PLACEHOLDER: ACCUM_VOL_SPIKE_2.5] — 試盤量能門檻
VOL_SPIKE_MULTIPLIER = 2.5  # Vol > 2.5× MA(Vol,20)

# [PLACEHOLDER: ACCUM_PULLBACK_VOL_0.7] — 試盤後量縮確認
POST_TEST_VOL_RATIO = 0.7  # Vol < 0.7× MA(Vol,20)

# [PLACEHOLDER: ACCUM_POST_TEST_WINDOW_001]
POST_TEST_MIN_DAYS = 5   # 試盤後觀察窗口最小天數
POST_TEST_MAX_DAYS = 10  # 試盤後觀察窗口最大天數

# [PLACEHOLDER: ACCUM_PULLBACK_MAX_001] — 試盤後最大回撤
POST_TEST_MAX_PULLBACK = 0.50  # 跌幅不超過試盤紅棒漲幅的 50%

# [PLACEHOLDER: ACCUM_ADX_THRESHOLD_001]
ADX_LOW_THRESHOLD = 25  # ADX < 25 = 趨勢未確立（華爾街交易員建議 ADX>25 才算有趨勢）

# [PLACEHOLDER: ACCUM_ADX_DURATION_001]
ADX_LOW_MIN_DAYS = 20  # ADX 低於門檻持續天數

# [PLACEHOLDER: ACCUM_RS_THRESHOLD_001]
RS_MIN_RATING = 70  # RS vs 同業 > 70

# [PLACEHOLDER: ACCUM_PRICE_RANGE_HIGH_001]
PRICE_RANGE_FROM_HIGH_MIN = 0.20  # 距 52W 高至少 -20%
PRICE_RANGE_FROM_HIGH_MAX = 0.45  # 距 52W 高最多 -45%

# [PLACEHOLDER: ACCUM_CONSOLIDATION_DAYS_060] — 華爾街交易員建議：120→60
# 「台股 120 天沒動靜通常已經壞掉了」
MAX_CONSOLIDATION_WITHOUT_TEST = 60  # 盤整超過 60 天未試盤 → 降權

# [PLACEHOLDER: ACCUM_MIN_VOLUME_LOTS_001]
MIN_AVG_VOLUME_LOTS = 100  # 最低日均量（張），過濾極冷門股

# ADX period
ADX_PERIOD = 14

# ---------- AQS Parameters (R95.1 — Architect APPROVED 2026-02-24) ----------
# AQS = Accumulation Quality Score (分點 DNA 品質評分)
# 華爾街交易員：「如果不是贏家分點在買，後面三個指標再漂亮都是假的」
# Architect：「請確保四個分項指標在計算前皆已完成標準化處理」

# [PLACEHOLDER: AQS_WEIGHT_WINNER_MOMENTUM]
AQS_W_WINNER_MOMENTUM = 0.40  # 贏家分點動量 — 核心指標

# [PLACEHOLDER: AQS_WEIGHT_NET_BUY_PERSISTENCE]
AQS_W_NET_BUY_PERSISTENCE = 0.25  # 淨買超持續性

# [PLACEHOLDER: AQS_WEIGHT_CONCENTRATION]
AQS_W_CONCENTRATION = 0.20  # 分點集中度趨勢

# [PLACEHOLDER: AQS_WEIGHT_ANTI_DAYTRADE]
AQS_W_ANTI_DAYTRADE = 0.15  # 反隔日沖比率

# [PLACEHOLDER: AQS_THRESHOLD_BETA]
AQS_THRESHOLD = 0.5  # AQS >= 0.5 → has_smart_money = True (Z-score scale)

# AQS lookback window (trading days)
AQS_LOOKBACK = 20

# Parquet feature column mapping (from R88.7P5, already rolling Z-scored)
# broker_purity_score = Top3 conc × Winner overlap (more robust than sparse winner_momentum)
# broker_winner_momentum = Tier 1 winner count (0/50/100, sparse)
AQS_COL_WINNER = "broker_purity_score"       # Primary smart money signal
AQS_COL_WINNER_BONUS = "broker_winner_momentum"  # Bonus when available
AQS_COL_PERSISTENCE = "broker_consistency_streak"  # Consecutive net-buy days
AQS_COL_CONCENTRATION = "broker_top3_pct"    # Top 3 buy broker concentration
AQS_COL_ANTI_DAYTRADE = "broker_net_buy_ratio"  # Net buy / total (high = less daytrade)

# Parquet file path
FEATURES_PARQUET = "data/pattern_data/features/features_all.parquet"


# ---------- Data Classes ----------

@dataclass
class SwingLow:
    """A detected swing low point."""
    idx: int
    date: str
    price: float


@dataclass
class TestBar:
    """A volume spike bar (Test for Supply)."""
    idx: int
    date: str
    open_price: float
    close_price: float
    low_price: float
    high_price: float
    volume: float
    vol_ratio: float  # vs MA(Vol,20)
    gain_pct: float   # (close - open) / open


@dataclass
class AccumulationResult:
    """Result of accumulation scan for a single stock."""
    # Phase detection
    phase: str = "NONE"  # NONE / ALPHA / BETA / GAMMA_READY
    score: int = 0       # 0-100 composite score

    # Condition flags
    has_higher_lows: bool = False
    swing_lows: list[dict] = field(default_factory=list)
    swing_low_count: int = 0

    has_volume_test: bool = False
    test_bars: list[dict] = field(default_factory=list)
    test_bar_floor: float | None = None  # Architect: 記住試盤低點

    has_post_test_confirm: bool = False
    post_test_vol_avg: float | None = None
    post_test_pullback_pct: float | None = None

    has_low_adx: bool = False
    adx_current: float | None = None
    adx_low_days: int = 0

    has_rs_strength: bool = False
    rs_rating: float | None = None

    has_smart_money: bool = False
    aqs_score: float | None = None
    aqs_breakdown: dict = field(default_factory=dict)

    # Filters
    price_in_range: bool = False
    price_vs_52w_high_pct: float | None = None
    volume_floor_pass: bool = False
    consolidation_days: int = 0
    consolidation_timeout: bool = False

    # Invalidation
    is_invalidated: bool = False
    invalidation_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "score": self.score,
            "has_higher_lows": self.has_higher_lows,
            "swing_lows": self.swing_lows,
            "swing_low_count": self.swing_low_count,
            "has_volume_test": self.has_volume_test,
            "test_bars": self.test_bars,
            "test_bar_floor": self.test_bar_floor,
            "has_post_test_confirm": self.has_post_test_confirm,
            "post_test_vol_avg": self.post_test_vol_avg,
            "post_test_pullback_pct": self.post_test_pullback_pct,
            "has_low_adx": self.has_low_adx,
            "adx_current": self.adx_current,
            "adx_low_days": self.adx_low_days,
            "has_rs_strength": self.has_rs_strength,
            "rs_rating": self.rs_rating,
            "has_smart_money": self.has_smart_money,
            "aqs_score": self.aqs_score,
            "aqs_breakdown": self.aqs_breakdown,
            "price_in_range": self.price_in_range,
            "price_vs_52w_high_pct": self.price_vs_52w_high_pct,
            "volume_floor_pass": self.volume_floor_pass,
            "consolidation_days": self.consolidation_days,
            "consolidation_timeout": self.consolidation_timeout,
            "is_invalidated": self.is_invalidated,
            "invalidation_reason": self.invalidation_reason,
        }


# ---------- Helper Functions ----------

def _find_swing_lows(
    lows: np.ndarray,
    half_win: int = SWING_LOOKBACK_HALF_WIN,
) -> list[tuple[int, float]]:
    """Find local swing low points using a rolling window approach.

    Returns list of (index, price) tuples.
    """
    n = len(lows)
    if n < half_win * 2 + 1:
        return []

    swing_lows = []
    for i in range(half_win, n - half_win):
        window = lows[max(0, i - half_win): i + half_win + 1]
        if lows[i] == np.min(window):
            # Avoid duplicates: skip if too close to previous swing low
            if swing_lows and i - swing_lows[-1][0] < half_win:
                # Keep the lower one
                if lows[i] < swing_lows[-1][1]:
                    swing_lows[-1] = (i, float(lows[i]))
            else:
                swing_lows.append((i, float(lows[i])))

    return swing_lows


def _check_higher_lows(
    swing_lows: list[tuple[int, float]],
    min_count: int = SWING_LOW_MIN_COUNT,
    uplift: float = SWING_LOW_UPLIFT,
) -> tuple[bool, list[tuple[int, float]]]:
    """Check if swing lows show a rising support pattern (accumulation signature).

    Three strategies (from strict to relaxed):
    1. Last N consecutive swing lows are strictly rising
    2. Find N rising lows from the tail (skip intermediate bounces)
    3. "Major Lows" approach: find the deepest low, then check if subsequent
       major support tests are progressively higher

    Returns (is_higher_lows, qualifying_swing_lows).
    """
    if len(swing_lows) < min_count:
        return False, []

    # Strategy 1: Strict consecutive rising
    recent = swing_lows[-min_count:]
    strict_rising = all(
        recent[i][1] >= recent[i - 1][1] * uplift
        for i in range(1, len(recent))
    )
    if strict_rising:
        return True, recent

    # Strategy 2: Rising subsequence from end
    rising_lows = [swing_lows[-1]]
    for i in range(len(swing_lows) - 2, -1, -1):
        if swing_lows[i][1] < rising_lows[-1][1]:
            rising_lows.append(swing_lows[i])
            if len(rising_lows) >= min_count:
                break
    rising_lows.reverse()
    if len(rising_lows) >= min_count:
        valid = all(
            rising_lows[i][1] >= rising_lows[i - 1][1] * uplift
            for i in range(1, len(rising_lows))
        )
        if valid:
            return True, rising_lows

    # Strategy 3: Major support test approach
    # Find the deepest swing low (the "Spring" in Wyckoff terms),
    # then check if all subsequent swing lows are above it = support holds
    if len(swing_lows) >= 4:
        # Look at last half of swing lows (post-selloff phase)
        half = len(swing_lows) // 2
        post_lows = swing_lows[half:]

        # Find the deepest low in this set
        deepest_idx = min(range(len(post_lows)), key=lambda i: post_lows[i][1])

        # Check: everything AFTER the deepest low should be higher
        if deepest_idx < len(post_lows) - 1:
            after_deepest = post_lows[deepest_idx:]
            if len(after_deepest) >= min_count:
                # Check if subsequent lows hold above or near the deepest
                deepest_price = after_deepest[0][1]
                rising = [after_deepest[0]]
                for i in range(1, len(after_deepest)):
                    if after_deepest[i][1] >= deepest_price * 0.98:  # Allow 2% tolerance
                        rising.append(after_deepest[i])

                if len(rising) >= min_count:
                    # Check net direction: last > first
                    if rising[-1][1] > rising[0][1] * uplift:
                        return True, rising

    return False, []


def _find_test_bars(
    df: pd.DataFrame,
    vol_ma20: pd.Series,
    multiplier: float = VOL_SPIKE_MULTIPLIER,
) -> list[TestBar]:
    """Find volume spike bars (Test for Supply).

    Criteria: Volume > multiplier × MA(Vol,20) AND Close > Open (red bar = bullish)
    """
    test_bars = []
    for i in range(len(df)):
        if vol_ma20.iloc[i] <= 0 or pd.isna(vol_ma20.iloc[i]):
            continue
        vol_ratio = df["volume"].iloc[i] / vol_ma20.iloc[i]
        if vol_ratio >= multiplier and df["close"].iloc[i] > df["open"].iloc[i]:
            gain = (df["close"].iloc[i] - df["open"].iloc[i]) / df["open"].iloc[i]
            test_bars.append(TestBar(
                idx=i,
                date=df.index[i].strftime("%Y-%m-%d") if hasattr(df.index[i], "strftime") else str(df.index[i]),
                open_price=float(df["open"].iloc[i]),
                close_price=float(df["close"].iloc[i]),
                low_price=float(df["low"].iloc[i]),
                high_price=float(df["high"].iloc[i]),
                volume=float(df["volume"].iloc[i]),
                vol_ratio=float(vol_ratio),
                gain_pct=float(gain),
            ))
    return test_bars


def _check_post_test_consolidation(
    df: pd.DataFrame,
    vol_ma20: pd.Series,
    test_bar: TestBar,
    min_days: int = POST_TEST_MIN_DAYS,
    max_days: int = POST_TEST_MAX_DAYS,
    max_vol_ratio: float = POST_TEST_VOL_RATIO,
    max_pullback: float = POST_TEST_MAX_PULLBACK,
) -> tuple[bool, float | None, float | None]:
    """Check post-test-bar consolidation: volume shrinks, price holds.

    Returns (confirmed, avg_vol_ratio, pullback_pct).
    """
    start = test_bar.idx + 1
    end = min(test_bar.idx + max_days + 1, len(df))

    if end - start < min_days:
        return False, None, None

    post_slice = df.iloc[start:end]
    post_vol_ma = vol_ma20.iloc[start:end]

    # Volume should shrink
    valid_ratios = []
    for i in range(len(post_slice)):
        if post_vol_ma.iloc[i] > 0 and not pd.isna(post_vol_ma.iloc[i]):
            valid_ratios.append(post_slice["volume"].iloc[i] / post_vol_ma.iloc[i])

    if not valid_ratios:
        return False, None, None

    avg_vol_ratio = float(np.mean(valid_ratios))
    vol_ok = avg_vol_ratio < max_vol_ratio

    # Price should not drop more than max_pullback of test bar's close price
    # (Using pct of close rather than pct of gain, to avoid division by tiny gains)
    lowest_after = float(post_slice["low"].min())
    pullback_from_close = (test_bar.close_price - lowest_after) / test_bar.close_price
    pullback_pct = float(pullback_from_close)
    # max_pullback here means: price can't drop more than 50% of test bar's gain %
    # e.g., if test bar gained 13%, price can't drop more than 6.5% from test bar close
    max_allowed_drop = test_bar.gain_pct * max_pullback
    price_ok = pullback_pct <= max(max_allowed_drop, 0.05)  # floor at 5%

    return vol_ok and price_ok, avg_vol_ratio, pullback_pct


def _compute_adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.Series:
    """Compute ADX from OHLC data."""
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1.0 / period, min_periods=period).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1.0 / period, min_periods=period).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1.0 / period, min_periods=period).mean() / atr)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1.0 / period, min_periods=period).mean()

    return adx


def _check_adx_low(
    adx: pd.Series,
    threshold: float = ADX_LOW_THRESHOLD,
    min_days: int = ADX_LOW_MIN_DAYS,
) -> tuple[bool, float, int]:
    """Check if ADX has been predominantly below threshold.

    Uses a relaxed approach: count days below threshold in the last 30 trading days.
    If >= min_days out of the last 30 are below threshold, it passes.

    Returns (is_low, current_adx, low_days_in_window).
    """
    if len(adx) < min_days or adx.isna().all():
        return False, 0.0, 0

    current_adx = float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 0.0

    # Count days below threshold in last 30 bars
    window = min(30, len(adx))
    recent_adx = adx.iloc[-window:]
    count = int((recent_adx.dropna() < threshold).sum())

    return count >= min_days, current_adx, count


def _check_price_range(
    df: pd.DataFrame,
    range_min: float = PRICE_RANGE_FROM_HIGH_MIN,
    range_max: float = PRICE_RANGE_FROM_HIGH_MAX,
) -> tuple[bool, float]:
    """Check if current price is within acceptable range from 52W high.

    Range: -20% to -45% from 52W high.
    Returns (in_range, pct_from_high).
    """
    high_52w = float(df["high"].max())
    current = float(df["close"].iloc[-1])

    if high_52w <= 0:
        return False, 0.0

    pct_from_high = 1.0 - (current / high_52w)  # e.g., 0.30 = -30%

    in_range = range_min <= pct_from_high <= range_max
    return in_range, float(pct_from_high)


def _check_invalidation(
    df: pd.DataFrame,
    test_bar_floor: float | None,
) -> tuple[bool, str]:
    """Architect directive: if price closes below test bar's low, invalidate.

    Returns (is_invalidated, reason).
    """
    if test_bar_floor is None:
        return False, ""

    current_close = float(df["close"].iloc[-1])
    if current_close < test_bar_floor:
        return True, f"Price {current_close:.2f} closed below test bar floor {test_bar_floor:.2f}"

    return False, ""


def _count_consolidation_days(df: pd.DataFrame) -> int:
    """Count days since last significant swing high (proxy for consolidation duration)."""
    if len(df) < 20:
        return 0

    # Find the most recent 52W high date
    high_52w = df["high"].max()
    high_idx = df["high"].idxmax()

    # Count trading days from peak to now
    if hasattr(high_idx, "strftime"):
        days = len(df.loc[high_idx:]) - 1
    else:
        peak_pos = df.index.get_loc(high_idx)
        days = len(df) - 1 - peak_pos

    return int(days)


# ---------- AQS (Accumulation Quality Score) ----------

_aqs_cache: dict = {"df": None, "mtime": 0}


def _load_features_parquet() -> pd.DataFrame | None:
    """Load features Parquet (lazy, cached with mtime check for nightly refresh)."""
    import os

    # Try both relative and absolute paths
    for path in [FEATURES_PARQUET, os.path.join(os.path.dirname(__file__), "..", FEATURES_PARQUET)]:
        if os.path.exists(path):
            mtime = os.path.getmtime(path)
            if _aqs_cache["df"] is not None and mtime <= _aqs_cache["mtime"]:
                return _aqs_cache["df"]
            try:
                df = pd.read_parquet(path)
                df["date"] = pd.to_datetime(df["date"])
                _aqs_cache["df"] = df
                _aqs_cache["mtime"] = mtime
                return df
            except Exception as e:
                _logger.warning("Failed to load features Parquet: %s", e)
                return None
    return None


def calculate_aqs(
    stock_code: str,
    features_df: pd.DataFrame | None = None,
    lookback: int = AQS_LOOKBACK,
) -> tuple[float | None, dict]:
    """Calculate AQS (Accumulation Quality Score) from broker features.

    Uses Z-scored broker features from R88.7P5 Parquet data.
    AQS = 0.40 × WM + 0.25 × NBP + 0.20 × BC + 0.15 × ADR

    Args:
        stock_code: Stock code (e.g., "6748")
        features_df: Pre-loaded features DataFrame (optional, will lazy-load if None)
        lookback: Number of recent trading days to average

    Returns:
        (aqs_score, breakdown_dict). Returns (None, {}) if data unavailable.
    """
    if features_df is None:
        features_df = _load_features_parquet()

    if features_df is None:
        return None, {}

    # Filter to this stock's data
    stock_data = features_df[features_df["stock_code"] == stock_code]
    if len(stock_data) < lookback:
        return None, {"reason": f"Insufficient data: {len(stock_data)} rows < {lookback}"}

    # Get last N rows (most recent)
    recent = stock_data.sort_values("date").tail(lookback)

    # Extract Z-scored features (already normalized in Parquet build)
    breakdown = {}

    # 1. Winner Momentum (40%) — broker_purity_score primary, winner_momentum bonus
    wm_vals = recent[AQS_COL_WINNER].dropna() if AQS_COL_WINNER in recent.columns else pd.Series(dtype=float)
    wm_mean = float(wm_vals.mean()) if len(wm_vals) > 0 else 0.0

    # Bonus: if broker_winner_momentum is also available and positive, boost
    if AQS_COL_WINNER_BONUS in recent.columns:
        wm_bonus = recent[AQS_COL_WINNER_BONUS].dropna()
        if len(wm_bonus) > 0 and float(wm_bonus.mean()) > 0:
            wm_mean = wm_mean * 1.2  # 20% bonus for confirmed winner presence
    breakdown["winner_momentum"] = round(wm_mean, 3)

    # 2. Net Buy Persistence (25%) — broker_consistency_streak
    nbp_vals = recent[AQS_COL_PERSISTENCE].dropna() if AQS_COL_PERSISTENCE in recent.columns else pd.Series(dtype=float)
    nbp_mean = float(nbp_vals.mean()) if len(nbp_vals) > 0 else 0.0
    breakdown["net_buy_persistence"] = round(nbp_mean, 3)

    # 3. Broker Concentration (20%) — broker_top3_pct
    bc_vals = recent[AQS_COL_CONCENTRATION].dropna() if AQS_COL_CONCENTRATION in recent.columns else pd.Series(dtype=float)
    bc_mean = float(bc_vals.mean()) if len(bc_vals) > 0 else 0.0
    breakdown["concentration"] = round(bc_mean, 3)

    # 4. Anti-Daytrade Ratio (15%) — broker_net_buy_ratio
    adr_vals = recent[AQS_COL_ANTI_DAYTRADE].dropna() if AQS_COL_ANTI_DAYTRADE in recent.columns else pd.Series(dtype=float)
    adr_mean = float(adr_vals.mean()) if len(adr_vals) > 0 else 0.0
    breakdown["anti_daytrade"] = round(adr_mean, 3)

    # Weighted AQS score
    aqs = (
        AQS_W_WINNER_MOMENTUM * wm_mean
        + AQS_W_NET_BUY_PERSISTENCE * nbp_mean
        + AQS_W_CONCENTRATION * bc_mean
        + AQS_W_ANTI_DAYTRADE * adr_mean
    )

    breakdown["weights"] = {
        "winner_momentum": AQS_W_WINNER_MOMENTUM,
        "net_buy_persistence": AQS_W_NET_BUY_PERSISTENCE,
        "concentration": AQS_W_CONCENTRATION,
        "anti_daytrade": AQS_W_ANTI_DAYTRADE,
    }

    return round(aqs, 3), breakdown


# ---------- Main Detection Function ----------

def detect_accumulation(
    df: pd.DataFrame,
    rs_rating: float | None = None,
    stock_code: str | None = None,
    features_df: pd.DataFrame | None = None,
) -> AccumulationResult:
    """Detect Wyckoff Accumulation pattern in price data.

    Args:
        df: OHLCV DataFrame with columns: open, high, low, close, volume
            Index should be datetime.
        rs_rating: Pre-computed RS rating vs sector (0-100). If None, RS check skipped.
        stock_code: Stock code for AQS lookup (e.g., "6748"). If None, AQS skipped.
        features_df: Pre-loaded features Parquet DataFrame (optional, lazy-loads if None).

    Returns:
        AccumulationResult with phase, score, and condition details.
    """
    result = AccumulationResult()

    # --- Basic validation ---
    if df is None or len(df) < 60:
        result.invalidation_reason = "Insufficient data (need >= 60 days)"
        return result

    # Volume floor check
    avg_vol_lots = float(df["volume"].tail(20).mean() / 1000)
    result.volume_floor_pass = avg_vol_lots >= MIN_AVG_VOLUME_LOTS
    if not result.volume_floor_pass:
        result.invalidation_reason = f"Volume floor fail: {avg_vol_lots:.0f} lots < {MIN_AVG_VOLUME_LOTS}"
        return result

    # --- Price range filter ---
    result.price_in_range, pct = _check_price_range(df)
    result.price_vs_52w_high_pct = round(pct * 100, 1)

    # --- Consolidation duration ---
    result.consolidation_days = _count_consolidation_days(df)
    result.consolidation_timeout = result.consolidation_days > MAX_CONSOLIDATION_WITHOUT_TEST

    # --- Determine correction phase ---
    # Only analyze data AFTER the 52W high (the correction/accumulation phase)
    high_52w_idx = int(df["high"].values.argmax())
    # Use at least 60 days post-peak, or all data after peak
    correction_start = max(high_52w_idx, len(df) - 200)
    df_correction = df.iloc[correction_start:]

    if len(df_correction) < 30:
        df_correction = df  # fallback: use all data

    # --- Condition 1: Higher Lows (in correction phase only) ---
    swing_lows_raw = _find_swing_lows(df_correction["low"].values)
    has_hl, qualifying_lows = _check_higher_lows(swing_lows_raw)
    result.has_higher_lows = has_hl
    result.swing_low_count = len(swing_lows_raw)
    result.swing_lows = [
        {
            "date": (df_correction.index[idx].strftime("%Y-%m-%d")
                     if hasattr(df_correction.index[idx], "strftime")
                     else str(df_correction.index[idx])),
            "price": round(price, 2),
        }
        for idx, price in qualifying_lows
    ]

    # --- Condition 2: Volume Test (Test for Supply, correction phase only) ---
    vol_ma20 = df_correction["volume"].rolling(20).mean()
    test_bars = _find_test_bars(df_correction, vol_ma20)
    result.has_volume_test = len(test_bars) > 0
    result.test_bars = [
        {
            "date": tb.date,
            "close": round(tb.close_price, 2),
            "vol_ratio": round(tb.vol_ratio, 1),
            "gain_pct": round(tb.gain_pct * 100, 1),
        }
        for tb in test_bars[-3:]  # Keep last 3 at most
    ]

    # Architect: remember test bar floor (lowest low among all test bars)
    if test_bars:
        result.test_bar_floor = round(min(tb.low_price for tb in test_bars), 2)

    # --- Condition 3: Post-test consolidation ---
    if test_bars:
        # Check the most recent test bar
        latest_test = test_bars[-1]
        confirmed, avg_vol, pullback = _check_post_test_consolidation(
            df_correction, vol_ma20, latest_test,
        )
        result.has_post_test_confirm = confirmed
        result.post_test_vol_avg = round(avg_vol, 2) if avg_vol is not None else None
        result.post_test_pullback_pct = round(pullback * 100, 1) if pullback is not None else None

    # --- Condition 4: Low ADX (energy reserve) ---
    # Use full df for ADX warmup, then slice to correction phase
    adx_full = _compute_adx(df)
    adx = adx_full.iloc[correction_start:]
    has_low, current_adx, low_days = _check_adx_low(adx)
    result.has_low_adx = has_low
    result.adx_current = round(current_adx, 1)
    result.adx_low_days = low_days

    # --- Condition 5: Relative Strength ---
    if rs_rating is not None:
        result.has_rs_strength = rs_rating >= RS_MIN_RATING
        result.rs_rating = round(rs_rating, 1)

    # --- Condition 6: AQS (Accumulation Quality Score) — R95.1 ---
    if stock_code is not None:
        aqs_score, aqs_breakdown = calculate_aqs(stock_code, features_df)
        if aqs_score is not None:
            result.aqs_score = aqs_score
            result.aqs_breakdown = aqs_breakdown
            result.has_smart_money = aqs_score >= AQS_THRESHOLD

    # --- Invalidation check (use full df for current price) ---
    invalidated, reason = _check_invalidation(df, result.test_bar_floor)
    result.is_invalidated = invalidated
    if invalidated:
        result.invalidation_reason = reason

    # --- Scoring & Phase determination ---
    score = 0
    conditions_met = 0

    if result.has_higher_lows:
        score += 25
        conditions_met += 1

    if result.has_volume_test:
        score += 20
        conditions_met += 1

    if result.has_post_test_confirm:
        score += 20
        conditions_met += 1

    if result.has_low_adx:
        score += 15
        conditions_met += 1

    if result.has_rs_strength:
        score += 10
        conditions_met += 1

    if result.has_smart_money:
        score += 10
        conditions_met += 1

    # Bonus: price in sweet spot
    if result.price_in_range:
        score += 10

    # Penalties
    if result.consolidation_timeout:
        score = max(0, score - 15)

    if result.is_invalidated:
        score = 0

    result.score = min(100, score)

    # Phase determination
    # Architect directive: AQS low + other conditions pass → downgrade BETA → ALPHA
    if result.is_invalidated:
        result.phase = "INVALIDATED"
    elif conditions_met >= 4 and result.has_post_test_confirm:
        if result.aqs_score is not None and not result.has_smart_money:
            # AQS data available but score too low → downgrade to ALPHA
            result.phase = "ALPHA"
        else:
            result.phase = "BETA"   # Ready for trial position
    elif conditions_met >= 2 and result.has_higher_lows:
        result.phase = "ALPHA"  # Watchlist alert
    else:
        result.phase = "NONE"

    return result


# ---------- Convenience / API ----------

def get_accumulation_analysis(
    code: str,
    period_days: int = 365,
    rs_rating: float | None = None,
) -> dict[str, Any]:
    """High-level API: fetch data and run accumulation scan for a single stock.

    Args:
        code: Stock code (e.g., "6748")
        period_days: How many days of data to fetch
        rs_rating: Pre-computed RS rating (optional)

    Returns:
        dict with scan results
    """
    from data.fetcher import get_stock_data

    df = get_stock_data(code, period_days=period_days)
    if df is None or len(df) < 60:
        return {
            "code": code,
            "error": "Insufficient data",
            "phase": "NONE",
            "score": 0,
        }

    result = detect_accumulation(df, rs_rating=rs_rating, stock_code=code)
    output = result.to_dict()
    output["code"] = code
    output["latest_close"] = round(float(df["close"].iloc[-1]), 2)
    output["high_52w"] = round(float(df["high"].max()), 2)
    output["low_52w"] = round(float(df["low"].min()), 2)
    output["data_points"] = len(df)

    return output

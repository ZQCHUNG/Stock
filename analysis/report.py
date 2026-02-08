"""專業股票分析報告模組

產生證券研究等級的技術分析報告，包含：
公司概況、價格績效、技術面評估、支撐壓力、費氏回檔、
目標價、動能分析、成交量分析、波動度、風險評估、展望、500字摘要
"""

import math
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime

from data.fetcher import get_stock_data, get_stock_info, get_stock_fundamentals, get_stock_news, get_google_news
from data.stock_list import get_stock_name, get_all_stocks
from analysis.indicators import calculate_all_indicators
from analysis.strategy import get_latest_analysis
from analysis.strategy_v4 import get_v4_analysis


# ============================================================
# Data Structures
# ============================================================

@dataclass
class SupportResistanceLevel:
    price: float
    level_type: str   # "support" or "resistance"
    source: str       # "swing", "ma20", "ma60", "ma120", "ma240", "bb", "round"
    strength: int     # 1-3


@dataclass
class FibonacciLevels:
    swing_high: float
    swing_low: float
    direction: str           # "uptrend" or "downtrend"
    retracement: dict        # {0.236: price, ...}
    extension: dict          # {1.272: price, ...}


@dataclass
class PriceTarget:
    scenario: str            # "bull", "base", "bear"
    target_price: float
    upside_pct: float
    rationale: str
    timeframe: str           # "3M", "6M", "1Y"
    confidence: str          # "高", "中", "低"


@dataclass
class OutlookScenario:
    timeframe: str
    bull_case: str
    bull_target: float
    bull_probability: int
    base_case: str
    base_target: float
    base_probability: int
    bear_case: str
    bear_target: float
    bear_probability: int


@dataclass
class ReportResult:
    stock_code: str
    stock_name: str
    report_date: datetime
    data_period_days: int

    company_info: dict

    current_price: float
    price_change_1w: float
    price_change_1m: float
    price_change_3m: float
    price_change_6m: float
    price_change_1y: float
    high_52w: float
    low_52w: float
    high_52w_date: str
    low_52w_date: str
    pct_from_52w_high: float
    pct_from_52w_low: float

    trend_direction: str
    trend_strength: str
    momentum_status: str
    volatility_level: str
    overall_rating: str
    ma_alignment: str

    support_levels: list
    resistance_levels: list

    fibonacci: FibonacciLevels

    price_targets: list

    adx_value: float
    adx_interpretation: str
    rsi_value: float
    rsi_interpretation: str
    macd_value: float
    macd_signal_value: float
    macd_histogram: float
    macd_interpretation: str
    k_value: float
    d_value: float
    kd_interpretation: str

    volume_trend: str
    volume_ratio: float
    accumulation_distribution: str
    volume_interpretation: str

    atr_value: float
    atr_pct: float
    historical_volatility_20d: float
    historical_volatility_60d: float
    bollinger_width: float
    bollinger_position: float
    volatility_interpretation: str

    max_drawdown_1y: float
    current_drawdown: float
    key_risk_level: float
    risk_reward_ratio: float
    risk_interpretation: str

    outlook_3m: OutlookScenario
    outlook_6m: OutlookScenario
    outlook_1y: OutlookScenario

    summary_text: str

    v4_analysis: dict
    v2_analysis: dict

    # 基本面
    fundamentals: dict = field(default_factory=dict)
    fundamental_interpretation: str = ""
    fundamental_score: float = 0.0
    analyst_data: dict = field(default_factory=dict)

    # 消息面
    news_items: list = field(default_factory=list)
    news_sentiment_score: float = 0.0
    news_sentiment_label: str = "無資料"

    indicators_df: pd.DataFrame = field(default=None, repr=False)


# ============================================================
# Helper Functions
# ============================================================

def _safe(val, default=0.0):
    """安全取值，處理 NaN"""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    return float(val)


# 新聞可信度常數
_TRUSTED_SOURCES = {
    "Reuters", "Bloomberg", "WSJ", "CNBC", "Yahoo Finance",
    "經濟日報", "工商時報", "中央社", "MoneyDJ", "鉅亨網",
    "The Wall Street Journal", "Financial Times", "Barron's",
    "AP", "AFP",
    # Google News 常見台灣來源
    "聯合新聞網", "自由財經", "ETtoday", "三立新聞網",
    "TVBS新聞網", "風傳媒", "商周", "天下雜誌",
    "Anue鉅亨", "Yahoo奇摩股市",
}
_QUESTIONABLE_SOURCES = {
    "Seeking Alpha", "Motley Fool", "InvestorPlace", "Benzinga",
    "GlobeNewsWire", "PR Newswire", "Business Wire",
    # 台灣論壇/散戶討論區（非正式新聞）
    "PTT", "Mobile01",
}
# 論壇帖子特徵（出現在標題中代表非正式新聞）
_FORUM_INDICATORS = [
    "同學會", "爆料", "｜CMoney 股市", "CMoney 股市爆料",
    "PTT", "Dcard", "Mobile01",
]
_CLICKBAIT_KEYWORDS = [
    "skyrocket", "crash", "plunge", "moon", "100%", "10x", "guaranteed",
    "暴漲", "崩盤", "飆漲", "穩賺", "內線", "翻倍", "噴出", "必漲",
]
_UNCERTAIN_KEYWORDS = [
    "could", "might", "rumor", "rumour", "speculate", "unconfirmed",
    "傳言", "據傳", "可能", "消息指出", "市場傳聞", "未經證實",
]


def _calculate_price_performance(df: pd.DataFrame) -> dict:
    """計算多期間報酬率與 52 週高低點"""
    close = df["close"]
    n = len(close)
    current = close.iloc[-1]

    def pct(days):
        if n > days:
            return (current / close.iloc[-days - 1] - 1)
        return 0.0

    last_252 = df.tail(252)
    h52 = last_252["high"].max()
    l52 = last_252["low"].min()
    h52_date = last_252["high"].idxmax()
    l52_date = last_252["low"].idxmin()

    return {
        "price_change_1w": pct(5),
        "price_change_1m": pct(21),
        "price_change_3m": pct(63),
        "price_change_6m": pct(126),
        "price_change_1y": pct(252),
        "high_52w": h52,
        "low_52w": l52,
        "high_52w_date": h52_date.strftime("%Y-%m-%d") if hasattr(h52_date, "strftime") else str(h52_date)[:10],
        "low_52w_date": l52_date.strftime("%Y-%m-%d") if hasattr(l52_date, "strftime") else str(l52_date)[:10],
        "pct_from_52w_high": (current / h52 - 1) if h52 > 0 else 0,
        "pct_from_52w_low": (current / l52 - 1) if l52 > 0 else 0,
    }


def _detect_swing_points(df: pd.DataFrame, window: int = 15) -> dict:
    """偵測波段高低點"""
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    swing_highs = []
    swing_lows = []

    for i in range(window, n - window):
        # swing high
        if highs[i] == max(highs[i - window:i + window + 1]):
            swing_highs.append((df.index[i], float(highs[i])))
        # swing low
        if lows[i] == min(lows[i - window:i + window + 1]):
            swing_lows.append((df.index[i], float(lows[i])))

    # 過濾太近的點（保留更極端的）
    def filter_nearby(points, min_bars=10):
        if not points:
            return points
        filtered = [points[0]]
        for p in points[1:]:
            idx_diff = abs(df.index.get_loc(p[0]) - df.index.get_loc(filtered[-1][0]))
            if idx_diff < min_bars:
                # 保留更極端的
                if "high" in str(type(p)):
                    if p[1] > filtered[-1][1]:
                        filtered[-1] = p
                else:
                    if p[1] < filtered[-1][1]:
                        filtered[-1] = p
            else:
                filtered.append(p)
        return filtered

    swing_highs = filter_nearby(swing_highs)
    swing_lows = filter_nearby(swing_lows)

    recent_high = max([p[1] for p in swing_highs[-5:]]) if swing_highs else df["high"].max()
    recent_low = min([p[1] for p in swing_lows[-5:]]) if swing_lows else df["low"].min()

    return {
        "swing_highs": swing_highs,
        "swing_lows": swing_lows,
        "recent_swing_high": recent_high,
        "recent_swing_low": recent_low,
    }


def _get_round_numbers(current_price: float) -> list:
    """取得附近的整數關卡"""
    if current_price < 50:
        step = 5
    elif current_price < 200:
        step = 10
    elif current_price < 500:
        step = 25
    elif current_price < 2000:
        step = 50
    else:
        step = 100

    base = int(current_price / step) * step
    return [base + i * step for i in range(-3, 4) if base + i * step > 0]


def _calculate_support_resistance(df, swing_points, current_price):
    """計算支撐與壓力價位"""
    candidates = []

    # Swing highs / lows
    for _, price in swing_points["swing_highs"][-10:]:
        candidates.append((price, "swing"))
    for _, price in swing_points["swing_lows"][-10:]:
        candidates.append((price, "swing"))

    # MA levels
    latest = df.iloc[-1]
    for ma_name in ["ma20", "ma60", "ma120", "ma240"]:
        val = latest.get(ma_name)
        if val is not None and not (isinstance(val, float) and math.isnan(val)):
            candidates.append((float(val), ma_name))

    # Bollinger
    for bb_name in ["bb_upper", "bb_lower"]:
        val = latest.get(bb_name)
        if val is not None and not (isinstance(val, float) and math.isnan(val)):
            candidates.append((float(val), "bb"))

    # Round numbers
    for rn in _get_round_numbers(current_price):
        candidates.append((rn, "round"))

    # 計算強度：歷史上股價在此價位附近反轉的次數
    close_arr = df["close"].tail(250).values
    low_arr = df["low"].tail(250).values
    high_arr = df["high"].tail(250).values

    def count_reactions(level, tolerance=0.015):
        count = 0
        for i in range(1, len(close_arr) - 1):
            near_low = abs(low_arr[i] - level) / level < tolerance
            near_high = abs(high_arr[i] - level) / level < tolerance
            if near_low and close_arr[i] > close_arr[i - 1]:
                count += 1
            elif near_high and close_arr[i] < close_arr[i - 1]:
                count += 1
        return min(count, 3)

    # 合併相近的價位
    candidates.sort(key=lambda x: x[0])
    merged = []
    for price, source in candidates:
        if price <= 0:
            continue
        found = False
        for m in merged:
            if abs(m["price"] - price) / price < 0.015:
                m["strength"] = max(m["strength"], count_reactions(price))
                if source not in m["source"]:
                    m["source"] += "+" + source
                found = True
                break
        if not found:
            merged.append({
                "price": price,
                "source": source,
                "strength": max(1, count_reactions(price)),
            })

    supports = []
    resistances = []
    for m in merged:
        if m["price"] < current_price * 0.998:
            supports.append(SupportResistanceLevel(
                price=m["price"], level_type="support",
                source=m["source"], strength=m["strength"],
            ))
        elif m["price"] > current_price * 1.002:
            resistances.append(SupportResistanceLevel(
                price=m["price"], level_type="resistance",
                source=m["source"], strength=m["strength"],
            ))

    supports.sort(key=lambda x: x.price, reverse=True)
    resistances.sort(key=lambda x: x.price)

    return supports[:5], resistances[:5]


def _calculate_fibonacci(df, swing_points):
    """計算費氏回檔與延伸"""
    sh = swing_points["recent_swing_high"]
    sl = swing_points["recent_swing_low"]
    current = df["close"].iloc[-1]

    if sh <= sl:
        sh = df["high"].max()
        sl = df["low"].min()

    # 當現價已超過偵測到的 swing high，代表偵測的波段已過時
    # 改用實際近期高點與近半年低點重新計算
    if current > sh * 1.02:
        sh = df["high"].max()
        recent_bars = min(120, len(df))
        sl = df["low"].iloc[-recent_bars:].min()
        if sh <= sl:
            sl = df["low"].min()

    diff = sh - sl

    # 如果目前價格偏高端 -> uptrend (回檔從高點往下算)
    # 如果偏低端 -> downtrend
    direction = "uptrend" if (current - sl) > diff * 0.5 else "downtrend"

    ratios = [0.236, 0.382, 0.5, 0.618, 0.786]
    ext_ratios = [1.0, 1.272, 1.618, 2.0]

    retracement = {}
    extension = {}

    if direction == "uptrend":
        for r in ratios:
            retracement[r] = sh - diff * r
        for r in ext_ratios:
            extension[r] = sl + diff * r
    else:
        for r in ratios:
            retracement[r] = sl + diff * r
        for r in ext_ratios:
            extension[r] = sh - diff * r

    return FibonacciLevels(
        swing_high=sh, swing_low=sl,
        direction=direction,
        retracement=retracement,
        extension=extension,
    )


def _assess_trend(df):
    """評估趨勢"""
    latest = df.iloc[-1]
    ma5 = _safe(latest.get("ma5"))
    ma20 = _safe(latest.get("ma20"))
    ma60 = _safe(latest.get("ma60"))
    ma120 = _safe(latest.get("ma120"))
    adx = _safe(latest.get("adx"))

    # 均線排列
    if ma5 > ma20 > ma60:
        ma_alignment = "多頭排列"
    elif ma5 < ma20 < ma60:
        ma_alignment = "空頭排列"
    else:
        ma_alignment = "糾結"

    # MA20 斜率
    ma20_series = df["ma20"].dropna()
    if len(ma20_series) >= 10:
        slope = (ma20_series.iloc[-1] - ma20_series.iloc[-10]) / ma20_series.iloc[-10]
    else:
        slope = 0

    # 趨勢方向
    if slope > 0.01 and adx > 25:
        trend_direction = "強勢上漲"
    elif slope > 0.003:
        trend_direction = "溫和上漲"
    elif slope < -0.01 and adx > 25:
        trend_direction = "強勢下跌"
    elif slope < -0.003:
        trend_direction = "溫和下跌"
    else:
        trend_direction = "盤整"

    # 趨勢強度
    if adx > 30:
        trend_strength = "強"
    elif adx > 18:
        trend_strength = "中"
    else:
        trend_strength = "弱"

    return {
        "trend_direction": trend_direction,
        "trend_strength": trend_strength,
        "ma_alignment": ma_alignment,
    }


def _assess_momentum(df):
    """評估動能"""
    latest = df.iloc[-1]
    adx = _safe(latest.get("adx"))
    plus_di = _safe(latest.get("plus_di"))
    minus_di = _safe(latest.get("minus_di"))
    rsi = _safe(latest.get("rsi"))
    macd = _safe(latest.get("macd"))
    macd_sig = _safe(latest.get("macd_signal"))
    macd_hist = _safe(latest.get("macd_hist"))
    k = _safe(latest.get("k"))
    d = _safe(latest.get("d"))

    # ADX
    if adx > 40:
        adx_interp = "趨勢極強，方向明確"
    elif adx > 25:
        adx_interp = "趨勢明確，可順勢操作"
    elif adx > 18:
        adx_interp = "趨勢偏弱，宜謹慎"
    else:
        adx_interp = "無明顯趨勢，盤整格局"

    if plus_di > minus_di:
        adx_interp += f"（+DI={plus_di:.1f} > -DI={minus_di:.1f}，方向偏多）"
    else:
        adx_interp += f"（+DI={plus_di:.1f} < -DI={minus_di:.1f}，方向偏空）"

    # RSI
    if rsi > 80:
        rsi_interp = "嚴重超買，短線回檔風險極高"
    elif rsi > 70:
        rsi_interp = "超買區域，注意回檔壓力"
    elif rsi > 50:
        rsi_interp = "偏多格局，動能尚可"
    elif rsi > 30:
        rsi_interp = "偏空格局，動能偏弱"
    elif rsi > 20:
        rsi_interp = "超賣區域，具反彈空間"
    else:
        rsi_interp = "嚴重超賣，反彈機率高"

    # MACD
    if macd > macd_sig and macd_hist > 0:
        if macd > 0:
            macd_interp = "多頭格局，MACD 在零軸之上且持續擴張"
        else:
            macd_interp = "由空轉多中，MACD 已金叉但尚未突破零軸"
    elif macd < macd_sig and macd_hist < 0:
        if macd < 0:
            macd_interp = "空頭格局，MACD 在零軸之下且持續擴張"
        else:
            macd_interp = "由多轉空中，MACD 已死叉但尚在零軸之上"
    else:
        macd_interp = "MACD 訊號不明確，多空力道拉鋸"

    # 柱狀圖趨勢
    hist_series = df["macd_hist"].dropna().tail(5)
    if len(hist_series) >= 3:
        if hist_series.iloc[-1] > hist_series.iloc[-3]:
            macd_interp += "，柱狀圖趨勢轉強"
        elif hist_series.iloc[-1] < hist_series.iloc[-3]:
            macd_interp += "，柱狀圖趨勢轉弱"

    # KD
    if k > d and k < 20:
        kd_interp = "低檔黃金交叉，強烈反彈訊號"
    elif k > d and k < 50:
        kd_interp = "黃金交叉，偏多格局"
    elif k > d and k > 80:
        kd_interp = "高檔黃金交叉，注意超買鈍化"
    elif k < d and k > 80:
        kd_interp = "高檔死亡交叉，短線回檔壓力"
    elif k < d and k > 50:
        kd_interp = "死亡交叉，偏空格局"
    elif k < d:
        kd_interp = "低檔死亡交叉，空方主導"
    else:
        kd_interp = "KD 糾結，方向不明"

    # 綜合動能
    score = 0
    if plus_di > minus_di:
        score += 1
    else:
        score -= 1
    if rsi > 50:
        score += 1
    else:
        score -= 1
    if macd > macd_sig:
        score += 1
    else:
        score -= 1
    if k > d:
        score += 1
    else:
        score -= 1

    if score >= 3:
        momentum_status = "強勁多頭"
    elif score >= 1:
        momentum_status = "偏多"
    elif score >= -1:
        momentum_status = "中性"
    elif score >= -3:
        momentum_status = "偏空"
    else:
        momentum_status = "強勁空頭"

    return {
        "momentum_status": momentum_status,
        "adx_value": adx,
        "adx_interpretation": adx_interp,
        "rsi_value": rsi,
        "rsi_interpretation": rsi_interp,
        "macd_value": macd,
        "macd_signal_value": macd_sig,
        "macd_histogram": macd_hist,
        "macd_interpretation": macd_interp,
        "k_value": k,
        "d_value": d,
        "kd_interpretation": kd_interp,
    }


def _assess_volume(df):
    """評估成交量"""
    latest = df.iloc[-1]
    vol = _safe(latest.get("volume"))
    vol_ma5 = _safe(latest.get("volume_ma5"))
    vol_ma20 = _safe(latest.get("volume_ma20"))
    vol_ratio = _safe(latest.get("volume_ratio"), 1.0)

    # 量能趨勢
    if vol_ma5 > 0 and vol_ma20 > 0:
        ratio_5_20 = vol_ma5 / vol_ma20
    else:
        ratio_5_20 = 1.0

    if ratio_5_20 > 1.3:
        volume_trend = "放量"
    elif ratio_5_20 < 0.7:
        volume_trend = "縮量"
    else:
        volume_trend = "平穩"

    # 吸籌/出貨：看近 20 天的量價關係
    tail20 = df.tail(20)
    up_vol = 0  # 收紅且量大
    down_vol = 0  # 收黑且量大
    for _, row in tail20.iterrows():
        v = _safe(row.get("volume"))
        vma = _safe(row.get("volume_ma5"), 1)
        if vma == 0:
            vma = 1
        c = _safe(row.get("close"))
        o = _safe(row.get("open"))
        if c > o and v > vma:
            up_vol += 1
        elif c < o and v > vma:
            down_vol += 1

    if up_vol > down_vol + 3:
        accum = "吸籌"
    elif down_vol > up_vol + 3:
        accum = "出貨"
    else:
        accum = "中性"

    # 解讀
    parts = [f"近期量能{volume_trend}"]
    if volume_trend == "放量":
        parts.append("短期資金關注度提升")
    elif volume_trend == "縮量":
        parts.append("市場觀望氣氛濃厚")

    if accum == "吸籌":
        parts.append("量價結構偏多，疑似有主力吸籌跡象")
    elif accum == "出貨":
        parts.append("量價結構偏空，須留意主力出貨可能")
    else:
        parts.append("量價結構中性，尚無明顯籌碼方向")

    return {
        "volume_trend": volume_trend,
        "volume_ratio": vol_ratio,
        "accumulation_distribution": accum,
        "volume_interpretation": "。".join(parts) + "。",
    }


def _assess_volatility(df):
    """評估波動度"""
    latest = df.iloc[-1]
    atr_val = _safe(latest.get("atr"))
    atr_pct = _safe(latest.get("atr_pct"))
    bb_upper = _safe(latest.get("bb_upper"))
    bb_lower = _safe(latest.get("bb_lower"))
    bb_middle = _safe(latest.get("bb_middle"), 1)
    close = _safe(latest.get("close"))

    # 歷史波動率
    pct_changes = df["close"].pct_change().dropna()
    hvol_20 = float(pct_changes.tail(20).std() * np.sqrt(252)) if len(pct_changes) >= 20 else 0
    hvol_60 = float(pct_changes.tail(60).std() * np.sqrt(252)) if len(pct_changes) >= 60 else 0

    # 布林寬度
    bb_width = (bb_upper - bb_lower) / bb_middle if bb_middle > 0 else 0
    bb_pos = (close - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5

    # 波動度級別
    if atr_pct > 0.04:
        vol_level = "高"
    elif atr_pct > 0.02:
        vol_level = "中"
    else:
        vol_level = "低"

    # 解讀
    parts = []
    parts.append(f"14 日 ATR 為 {atr_val:.2f} 元（佔股價 {atr_pct:.1%}），波動度{vol_level}")
    if bb_width > 0.15:
        parts.append("布林通道大幅張開，顯示近期波動劇烈")
    elif bb_width < 0.06:
        parts.append("布林通道收斂，可能醞釀方向性突破")
    else:
        parts.append("布林通道寬度正常")

    if bb_pos > 0.8:
        parts.append("股價位於通道上緣，短線偏強但須留意拉回")
    elif bb_pos < 0.2:
        parts.append("股價位於通道下緣，短線偏弱但具反彈條件")
    else:
        parts.append("股價位於通道中段")

    return {
        "atr_value": atr_val,
        "atr_pct": atr_pct,
        "historical_volatility_20d": hvol_20,
        "historical_volatility_60d": hvol_60,
        "bollinger_width": bb_width,
        "bollinger_position": bb_pos,
        "volatility_level": vol_level,
        "volatility_interpretation": "。".join(parts) + "。",
    }


def _assess_risk(df, support_levels):
    """評估風險"""
    close_series = df["close"]
    current = close_series.iloc[-1]

    # 最大回撤 (1Y)
    tail252 = close_series.tail(252)
    running_max = tail252.cummax()
    drawdowns = (tail252 - running_max) / running_max
    max_dd = float(drawdowns.min())

    # 目前回撤
    peak = close_series.max()
    current_dd = (current - peak) / peak

    # 關鍵風險價位（第一個強支撐）
    if support_levels:
        key_risk = support_levels[0].price
    else:
        key_risk = current * 0.93

    # 風險報酬比
    nearest_resistance = current * 1.10
    rr = (nearest_resistance - current) / (current - key_risk) if current > key_risk else 0

    # 解讀
    parts = []
    parts.append(f"近一年最大回撤為 {max_dd:.1%}，目前距歷史高點 {current_dd:.1%}")
    if max_dd < -0.20:
        parts.append("歷史回撤幅度偏大，須注意下檔風險")
    if rr > 2:
        parts.append(f"風險報酬比 {rr:.1f}:1，以技術面而言進場條件有利")
    elif rr > 1:
        parts.append(f"風險報酬比 {rr:.1f}:1，風險與報酬尚稱平衡")
    else:
        parts.append(f"風險報酬比 {rr:.1f}:1，下檔風險大於潛在報酬，宜謹慎")

    return {
        "max_drawdown_1y": max_dd,
        "current_drawdown": current_dd,
        "key_risk_level": key_risk,
        "risk_reward_ratio": max(rr, 0),
        "risk_interpretation": "。".join(parts) + "。",
    }


def _calculate_price_targets(current_price, fibonacci, atr_pct, resistance_levels,
                              support_levels, trend_direction, adx_value,
                              analyst_data=None):
    """估算目標價（技術面 + 法人共識）"""
    targets = []
    is_strong_uptrend = "上漲" in trend_direction and adx_value > 25
    is_uptrend = "上漲" in trend_direction
    is_downtrend = "下跌" in trend_direction

    # 法人目標價（如有）
    analyst_target = None
    analyst_high = None
    analyst_low = None
    if analyst_data:
        analyst_target = analyst_data.get("target_mean")
        analyst_high = analyst_data.get("target_high")
        analyst_low = analyst_data.get("target_low")

    for tf, tf_label, trading_days in [("3M", "三個月", 63), ("6M", "六個月", 126), ("1Y", "一年", 252)]:
        # ATR 投射 (按時間比例根號縮放)
        scale = math.sqrt(trading_days / 14)
        atr_up = current_price * (1 + atr_pct * 2 * scale)
        atr_down = current_price * (1 - atr_pct * 2 * scale)

        # Bull case
        fib_ext = fibonacci.extension.get(1.272, current_price * 1.15)
        if tf == "1Y":
            fib_ext = fibonacci.extension.get(1.618, current_price * 1.25)
        elif tf == "6M":
            fib_ext = fibonacci.extension.get(1.272, current_price * 1.15)

        # 當 Fibonacci 延伸低於現價（波段已過時），改用 ATR 推估
        if fib_ext < current_price * 1.01:
            trend_mult = 1.5 if is_strong_uptrend else 1.0
            fib_ext = current_price * (1 + atr_pct * trend_mult * scale)

        # 壓力位：跳過太靠近的（<2%），取有意義的壓力
        nearest_res = current_price * 1.05  # fallback
        for r in resistance_levels:
            if r.price >= current_price * 1.02:
                nearest_res = r.price
                break

        bull_target = (fib_ext * 0.4 + atr_up * 0.3 + nearest_res * 0.3)
        # 上限：不超過 +100%
        bull_target = min(bull_target, current_price * 2.0)

        # 法人目標高價融合（6M, 1Y）
        if analyst_high and analyst_high > current_price and tf in ("6M", "1Y"):
            blend = 0.2 if tf == "6M" else 0.3
            bull_target = bull_target * (1 - blend) + analyst_high * blend

        # Bear case
        fib_ret = list(fibonacci.retracement.values())
        if fibonacci.direction == "uptrend" and fib_ret:
            bear_fib = fib_ret[-1] if tf == "1Y" else fib_ret[2] if len(fib_ret) > 2 else fib_ret[-1]
        else:
            bear_fib = current_price * 0.85

        nearest_sup = support_levels[0].price if support_levels else current_price * 0.93
        bear_target = (bear_fib * 0.4 + atr_down * 0.3 + nearest_sup * 0.3)
        # 下限：不低於 -50%
        bear_target = max(bear_target, current_price * 0.5)

        # 法人目標低價融合（6M, 1Y）
        if analyst_low and analyst_low > 0 and tf in ("6M", "1Y"):
            blend = 0.2 if tf == "6M" else 0.3
            bear_target = bear_target * (1 - blend) + analyst_low * blend

        # Base case：依趨勢方向加權，而非簡單取中點
        if is_strong_uptrend:
            base_target = bull_target * 0.6 + bear_target * 0.4
        elif is_uptrend:
            base_target = bull_target * 0.55 + bear_target * 0.45
        elif is_downtrend:
            base_target = bull_target * 0.4 + bear_target * 0.6
        else:
            base_target = (bull_target + bear_target) / 2

        # 法人共識均價融合 base case（6M, 1Y）
        if analyst_target and analyst_target > 0 and tf in ("6M", "1Y"):
            blend = 0.25 if tf == "6M" else 0.35
            base_target = base_target * (1 - blend) + analyst_target * blend

        # 信心度
        if adx_value > 25:
            base_conf = "高"
        elif adx_value > 18:
            base_conf = "中"
        else:
            base_conf = "低"

        # rationale 標注是否有法人數據
        analyst_note = "（含法人共識）" if analyst_target and tf in ("6M", "1Y") else ""

        targets.append(PriceTarget(
            scenario="bull", target_price=round(bull_target, 2),
            upside_pct=(bull_target / current_price - 1),
            rationale=f"依費氏延伸、ATR 波動推估及壓力位綜合計算之{tf_label}樂觀目標{analyst_note}",
            timeframe=tf, confidence="中",
        ))
        targets.append(PriceTarget(
            scenario="base", target_price=round(base_target, 2),
            upside_pct=(base_target / current_price - 1),
            rationale=f"綜合趨勢投射與支撐壓力中位數推估之{tf_label}基本目標{analyst_note}",
            timeframe=tf, confidence=base_conf,
        ))
        targets.append(PriceTarget(
            scenario="bear", target_price=round(bear_target, 2),
            upside_pct=(bear_target / current_price - 1),
            rationale=f"依費氏回檔、ATR 下行推估及支撐位綜合計算之{tf_label}保守目標{analyst_note}",
            timeframe=tf, confidence="中",
        ))

    return targets


def _calculate_overall_rating(trend_direction, momentum_status, v4_signal,
                               v2_composite, rsi, rr_ratio, base_3m_upside=0,
                               fundamental_score=0.0):
    """計算綜合評等"""
    score = 0
    trend_map = {"強勢上漲": 2, "溫和上漲": 1, "盤整": 0, "溫和下跌": -1, "強勢下跌": -2}
    score += trend_map.get(trend_direction, 0)

    if v4_signal == "BUY":
        score += 2
    elif v4_signal == "SELL":
        score -= 2
    if v2_composite > 0.3:
        score += 1
    elif v2_composite < -0.3:
        score -= 1

    mom_map = {"強勁多頭": 2, "偏多": 1, "中性": 0, "偏空": -1, "強勁空頭": -2}
    score += mom_map.get(momentum_status, 0)

    if rsi < 30:
        score += 1
    elif rsi > 70:
        score -= 1

    if rr_ratio > 2:
        score += 1
    elif rr_ratio < 0.5:
        score -= 1

    # 基本面評分（-5~+5 → 約 -2~+2）
    score += fundamental_score * 0.4

    # 目標價上檔空間調整：技術面再好，預期報酬低就不該強力推薦
    if base_3m_upside > 0.10:
        score += 2
    elif base_3m_upside > 0.05:
        score += 1
    elif base_3m_upside < -0.05:
        score -= 2
    elif base_3m_upside < 0:
        score -= 1

    if score >= 6:
        return "強力買進"
    elif score >= 3:
        return "買進"
    elif score >= -1:
        return "中性"
    elif score >= -4:
        return "賣出"
    else:
        return "強力賣出"


def _generate_outlook(trend_direction, momentum_status, price_targets,
                       volatility_level, current_price, adx, rsi,
                       fundamental_score=0.0,
                       fund_interpretation="",
                       analyst_data=None):
    """產生展望（技術面 + 基本面綜合）"""
    # 基礎機率（技術面）
    if trend_direction in ("強勢上漲", "溫和上漲"):
        probs = {"3M": [40, 40, 20], "6M": [35, 35, 30], "1Y": [30, 35, 35]}
    elif trend_direction == "盤整":
        probs = {"3M": [25, 50, 25], "6M": [30, 40, 30], "1Y": [30, 35, 35]}
    else:
        probs = {"3M": [15, 35, 50], "6M": [25, 35, 40], "1Y": [30, 35, 35]}

    # RSI 調整
    for tf in probs:
        b, m, e = probs[tf]
        if rsi > 70:
            b -= 5; e += 5
        elif rsi < 30:
            b += 5; e -= 5
        probs[tf] = [b, m, e]

    # 基本面調整（影響中長期較大）
    if fundamental_score >= 2.5:
        for tf, (short_adj, long_adj) in [("3M", (3, 3)), ("6M", (5, 5)), ("1Y", (7, 7))]:
            probs[tf][0] += long_adj; probs[tf][2] -= long_adj
    elif fundamental_score >= 1.0:
        for tf, adj in [("3M", 2), ("6M", 3), ("1Y", 4)]:
            probs[tf][0] += adj; probs[tf][2] -= adj
    elif fundamental_score <= -2.5:
        for tf, adj in [("3M", 3), ("6M", 5), ("1Y", 7)]:
            probs[tf][0] -= adj; probs[tf][2] += adj
    elif fundamental_score <= -1.0:
        for tf, adj in [("3M", 2), ("6M", 3), ("1Y", 4)]:
            probs[tf][0] -= adj; probs[tf][2] += adj

    # 法人目標價調整
    if analyst_data and analyst_data.get("upside") is not None:
        analyst_upside = analyst_data["upside"]
        if analyst_upside > 0.20:
            for tf, adj in [("3M", 2), ("6M", 4), ("1Y", 5)]:
                probs[tf][0] += adj; probs[tf][2] -= adj
        elif analyst_upside < -0.10:
            for tf, adj in [("3M", 2), ("6M", 4), ("1Y", 5)]:
                probs[tf][0] -= adj; probs[tf][2] += adj

    # 正規化：確保機率 ≥5% 且總和 = 100%
    for tf in probs:
        probs[tf] = [max(p, 5) for p in probs[tf]]
        total = sum(probs[tf])
        probs[tf] = [round(p / total * 100) for p in probs[tf]]
        # 修正進位誤差
        diff = 100 - sum(probs[tf])
        probs[tf][1] += diff  # 調整 base case

    def get_target(tf, scenario):
        for t in price_targets:
            if t.timeframe == tf and t.scenario == scenario:
                return t.target_price
        return current_price

    # 構建基本面附加描述
    def _fund_context(tf):
        """根據時間框架產生基本面附注"""
        parts = []
        if tf in ("6M", "1Y"):
            if fundamental_score >= 2.5:
                parts.append("基本面表現優異提供額外支撐")
            elif fundamental_score >= 1.0:
                parts.append("基本面穩健有利中長期表現")
            elif fundamental_score <= -2.5:
                parts.append("基本面偏弱構成下行壓力")
            elif fundamental_score <= -1.0:
                parts.append("基本面欠佳限制反彈空間")
        if analyst_data and analyst_data.get("upside") is not None and tf in ("6M", "1Y"):
            upside = analyst_data["upside"]
            if upside > 0.20:
                parts.append(f"法人目標均價上檔空間 {upside:.0%}")
            elif upside < -0.10:
                parts.append(f"目前股價已高於法人目標均價")
        return "，" + "、".join(parts) if parts else ""

    def make_outlook(tf, tf_label):
        b, m, e = probs[tf]
        bt = get_target(tf, "bull")
        mt = get_target(tf, "base")
        et = get_target(tf, "bear")
        ctx = _fund_context(tf)

        if "上漲" in trend_direction:
            bull_desc = f"延續現有上升趨勢，突破近期壓力後持續走高，目標挑戰 ${bt:.2f} 價位{ctx}"
            base_desc = f"維持目前格局，於支撐壓力區間內震盪整理，預期在 ${et:.2f}～${bt:.2f} 之間波動"
            bear_desc = f"若趨勢反轉跌破關鍵支撐，可能回落至 ${et:.2f} 附近，主要風險來自獲利回吐及市場系統性風險"
        elif "下跌" in trend_direction:
            bull_desc = f"若出現技術面反轉訊號，有望反彈至 ${bt:.2f}，但需確認量能配合{ctx}"
            base_desc = f"延續弱勢整理格局，預期在 ${et:.2f}～${mt:.2f} 之間波動"
            bear_desc = f"空方趨勢延續，可能進一步下探 ${et:.2f}，須留意支撐失守的連鎖效應"
        else:
            bull_desc = f"若突破盤整區間上緣，有望啟動新一輪上漲至 ${bt:.2f}{ctx}"
            base_desc = f"維持區間盤整格局，預期在 ${et:.2f}～${bt:.2f} 之間來回震盪"
            bear_desc = f"若跌破盤整區間下緣，可能轉為空方走勢，下探 ${et:.2f}"

        # 技術面與基本面矛盾時，在 base_desc 附注
        if "下跌" in trend_direction and fundamental_score >= 2.0 and tf in ("6M", "1Y"):
            base_desc += "；惟基本面仍具支撐力，中長期不宜過度悲觀"
        elif "上漲" in trend_direction and fundamental_score <= -2.0 and tf in ("6M", "1Y"):
            base_desc += "；惟基本面偏弱，漲勢持續性存疑"

        return OutlookScenario(
            timeframe=tf_label,
            bull_case=bull_desc, bull_target=bt, bull_probability=b,
            base_case=base_desc, base_target=mt, base_probability=m,
            bear_case=bear_desc, bear_target=et, bear_probability=e,
        )

    return (
        make_outlook("3M", "3 個月"),
        make_outlook("6M", "6 個月"),
        make_outlook("1Y", "1 年"),
    )


def _assess_fundamentals(fundamentals: dict, current_price: float) -> dict:
    """評估基本面，回傳分數與解讀"""
    score = 0.0
    parts = []
    available = 0

    def _val(key):
        v = fundamentals.get(key)
        if v is not None:
            return v
        return None

    # --- 估值 ---
    pe = _val("trailing_pe")
    fwd_pe = _val("forward_pe")
    if pe is not None:
        available += 1
        if pe < 10:
            score += 1.0
            parts.append(f"本益比 {pe:.1f} 倍，估值偏低")
        elif pe < 15:
            score += 0.5
            parts.append(f"本益比 {pe:.1f} 倍，估值合理")
        elif pe > 40:
            score -= 1.0
            parts.append(f"本益比 {pe:.1f} 倍，估值偏高")
        else:
            parts.append(f"本益比 {pe:.1f} 倍")

    if pe is not None and fwd_pe is not None and pe > 0:
        available += 1
        if fwd_pe < pe * 0.8:
            score += 0.5
            parts.append(f"預估本益比 {fwd_pe:.1f} 倍，獲利預期成長")

    # --- 獲利成長 ---
    eg = _val("earnings_growth")
    if eg is not None:
        available += 1
        if eg > 0.30:
            score += 1.5
            parts.append(f"獲利成長率 {eg:.0%}，成長強勁")
        elif eg > 0.10:
            score += 0.5
            parts.append(f"獲利成長率 {eg:.0%}，穩健成長")
        elif eg < -0.10:
            score -= 1.0
            parts.append(f"獲利成長率 {eg:.0%}，獲利衰退")
        elif eg < 0:
            score -= 0.5
            parts.append(f"獲利成長率 {eg:.0%}，小幅衰退")

    # --- 營收成長 ---
    rg = _val("revenue_growth")
    if rg is not None:
        available += 1
        if rg > 0.20:
            score += 1.0
            parts.append(f"營收成長率 {rg:.0%}，營收動能強")
        elif rg > 0.05:
            score += 0.3
        elif rg < -0.05:
            score -= 0.5
            parts.append(f"營收成長率 {rg:.0%}，營收下滑")

    # --- ROE ---
    roe = _val("return_on_equity")
    if roe is not None:
        available += 1
        if roe > 0.25:
            score += 1.0
            parts.append(f"ROE {roe:.0%}，股東權益報酬率優秀")
        elif roe > 0.15:
            score += 0.5
        elif roe < 0.08:
            score -= 0.5
            parts.append(f"ROE {roe:.0%}，獲利效率偏低")

    # --- 淨利率 ---
    pm = _val("profit_margins")
    if pm is not None:
        available += 1
        if pm > 0.30:
            score += 0.5
        elif pm < 0.05:
            score -= 0.5
            parts.append(f"淨利率 {pm:.0%}，利潤率偏低")

    # --- 負債 ---
    de = _val("debt_to_equity")
    if de is not None:
        available += 1
        if de < 30:
            score += 0.3
        elif de > 100:
            score -= 0.5
            parts.append(f"負債權益比 {de:.0f}%，財務槓桿偏高")

    # --- 殖利率 ---
    dy = _val("dividend_yield")
    if dy is not None:
        # yfinance 台股有時回傳百分比形式 (e.g. 1.15 表示 1.15%)，需正規化為小數
        if dy > 1:
            dy = dy / 100
        available += 1
        if dy > 0.05:
            score += 0.5
            parts.append(f"殖利率 {dy:.1%}，配息豐厚")
        elif dy > 0.03:
            score += 0.2

    # --- 法人目標價 ---
    target_mean = _val("target_mean_price")
    analyst_data = {}
    if target_mean is not None and current_price > 0:
        available += 1
        upside = (target_mean / current_price - 1)
        analyst_data = {
            "target_mean": target_mean,
            "target_median": _val("target_median_price"),
            "target_high": _val("target_high_price"),
            "target_low": _val("target_low_price"),
            "num_analysts": _val("number_of_analysts"),
            "rating": fundamentals.get("analyst_rating", "N/A"),
            "upside": upside,
        }
        if upside > 0.20:
            score += 1.0
            parts.append(f"法人目標均價 {target_mean:.0f} 元，上檔空間 {upside:.0%}")
        elif upside > 0.05:
            score += 0.3
        elif upside < -0.10:
            score -= 0.5
            parts.append(f"法人目標均價 {target_mean:.0f} 元，低於現價 {abs(upside):.0%}")

    # Clamp
    score = max(-5.0, min(5.0, score))

    # 格式化指標
    def _fmt(val, fmt_str, suffix=""):
        if val is None:
            return "N/A"
        return f"{val:{fmt_str}}{suffix}"

    metrics = {
        "trailing_pe": _fmt(pe, ".1f", " 倍"),
        "forward_pe": _fmt(fwd_pe, ".1f", " 倍"),
        "price_to_book": _fmt(_val("price_to_book"), ".2f", " 倍"),
        "trailing_eps": _fmt(_val("trailing_eps"), ".2f", " 元"),
        "forward_eps": _fmt(_val("forward_eps"), ".2f", " 元"),
        "earnings_growth": _fmt(eg, ".1%") if eg is not None else "N/A",
        "revenue_growth": _fmt(rg, ".1%") if rg is not None else "N/A",
        "roe": _fmt(roe, ".1%") if roe is not None else "N/A",
        "roa": _fmt(_val("return_on_assets"), ".1%") if _val("return_on_assets") is not None else "N/A",
        "gross_margins": _fmt(_val("gross_margins"), ".1%") if _val("gross_margins") is not None else "N/A",
        "operating_margins": _fmt(_val("operating_margins"), ".1%") if _val("operating_margins") is not None else "N/A",
        "profit_margins": _fmt(pm, ".1%") if pm is not None else "N/A",
        "debt_to_equity": _fmt(de, ".0f", "%") if de is not None else "N/A",
        "current_ratio": _fmt(_val("current_ratio"), ".2f") if _val("current_ratio") is not None else "N/A",
        "dividend_yield": _fmt(dy, ".2%") if dy is not None else "N/A",
        "dividend_rate": _fmt(_val("dividend_rate"), ".2f", " 元") if _val("dividend_rate") is not None else "N/A",
        "beta": _fmt(_val("beta"), ".2f") if _val("beta") is not None else "N/A",
    }

    # 綜合解讀
    if score >= 3:
        interpretation = "基本面表現優異。" + "；".join(parts[:4]) + "。"
    elif score >= 1:
        interpretation = "基本面表現穩健。" + "；".join(parts[:4]) + "。"
    elif score >= -1:
        interpretation = "基本面表現中性。" + ("；".join(parts[:4]) + "。" if parts else "")
    else:
        interpretation = "基本面表現偏弱。" + "；".join(parts[:4]) + "。"

    return {
        "fundamental_score": score,
        "fundamental_interpretation": interpretation,
        "metrics": metrics,
        "analyst_data": analyst_data,
        "available_count": available,
    }


def _assess_news(news_items: list) -> list:
    """評估新聞可信度，回傳帶 credibility 欄位的新聞列表"""
    results = []
    for item in news_items:
        source = item.get("source", "Unknown")
        title = item.get("title", "")
        summary = item.get("summary", "")
        text = (title + " " + summary).lower()

        # 來源基礎分 — substring matching for Google News sources
        if any(ts in source or source in ts for ts in _TRUSTED_SOURCES):
            base = 2
        elif any(qs in source or source in qs for qs in _QUESTIONABLE_SOURCES):
            base = 0
        else:
            base = 1

        # 論壇帖子偵測：標題含論壇特徵直接降為 0
        if any(fi in title for fi in _FORUM_INDICATORS):
            base = 0

        # 聳動詞扣分
        penalty = 0
        for kw in _CLICKBAIT_KEYWORDS:
            if kw.lower() in text:
                penalty += 2
                break
        for kw in _UNCERTAIN_KEYWORDS:
            if kw.lower() in text:
                penalty += 1
                break

        credibility_score = base - penalty

        if credibility_score >= 2:
            credibility = "可信"
            icon = "🟢"
        elif credibility_score >= 1:
            credibility = "待確認"
            icon = "🟡"
        else:
            credibility = "存疑"
            icon = "🔴"

        results.append({
            **item,
            "credibility": credibility,
            "credibility_icon": icon,
            "credibility_score": credibility_score,
        })

    return results


# 情緒分析關鍵字（英文，因為 yfinance 新聞為英文）
_POSITIVE_KEYWORDS = [
    # English
    "upgrade", "buy", "beat", "record", "growth", "profit", "launch",
    "partnership", "deal", "surge", "rally", "boost", "strong", "rise",
    "gain", "revenue", "expand", "approve", "breakthrough", "award",
    "outperform", "dividend", "bullish", "recovery", "exceed",
    # Chinese
    "營收成長", "獲利", "專利", "合作", "得獎", "突破", "上漲",
    "利多", "看好", "買進", "目標價", "新高", "擴產", "訂單",
    "法說會", "轉盈", "認證", "通過", "上調", "強勁",
    "獲獎", "勇奪", "榮獲", "授權", "簽約", "雙增", "轉機",
]
_NEGATIVE_KEYWORDS = [
    # English
    "downgrade", "sell", "miss", "loss", "cut", "risk", "decline",
    "fall", "drop", "warning", "lawsuit", "debt", "weak", "delay",
    "recall", "penalty", "bearish", "layoff", "default", "fraud",
    "investigation", "concern", "slowdown", "underperform", "suspend",
    # Chinese
    "虧損", "下跌", "衰退", "利空", "看壞", "賣出", "下調",
    "減資", "裁員", "違約", "訴訟", "調查", "警示", "跌停",
    "下修", "疲弱", "風險", "負債", "停工", "召回",
]


def _analyze_news_sentiment(scored_news: list) -> dict:
    """分析新聞情緒，回傳整體情緒分數與標籤，並在每篇新聞加上 sentiment 欄位"""
    if not scored_news:
        return {"score": 0.0, "label": "無資料", "positive_count": 0,
                "negative_count": 0, "total": 0}

    total_score = 0.0
    pos_count = 0
    neg_count = 0

    for item in scored_news:
        text = (item.get("title", "") + " " + item.get("summary", "")).lower()

        pos_hits = sum(1 for kw in _POSITIVE_KEYWORDS if kw in text)
        neg_hits = sum(1 for kw in _NEGATIVE_KEYWORDS if kw in text)

        if pos_hits > neg_hits:
            sentiment = 1
            label = "正面"
            icon = "📈"
        elif neg_hits > pos_hits:
            sentiment = -1
            label = "負面"
            icon = "📉"
        else:
            sentiment = 0
            label = "中性"
            icon = "➖"

        # 可信來源權重較高
        cred = item.get("credibility_score", 1)
        if cred >= 2:
            weight = 1.5
        elif cred <= 0:
            weight = 0.5
        else:
            weight = 1.0

        total_score += sentiment * weight
        if sentiment > 0:
            pos_count += 1
        elif sentiment < 0:
            neg_count += 1

        item["sentiment"] = label
        item["sentiment_icon"] = icon

    if total_score >= 1.5:
        overall_label = "偏多"
    elif total_score <= -1.5:
        overall_label = "偏空"
    else:
        overall_label = "中性"

    return {
        "score": round(total_score, 2),
        "label": overall_label,
        "positive_count": pos_count,
        "negative_count": neg_count,
        "total": len(scored_news),
    }


def _generate_summary(data: dict) -> str:
    """產生 500 字專業中文摘要"""
    code = data["stock_code"]
    name = data["stock_name"]
    price = data["current_price"]
    perf = data["performance"]
    trend = data["trend"]
    mom = data["momentum"]
    vol = data["volume"]
    volatility = data["volatility"]
    risk = data["risk"]
    targets = data["targets"]
    outlook_3m = data["outlook_3m"]
    fib = data["fibonacci"]
    supports = data["supports"]
    resistances = data["resistances"]
    rating = data["overall_rating"]

    # 績效描述
    perf_parts = []
    for label, key in [("一週", "price_change_1w"), ("一個月", "price_change_1m"),
                       ("三個月", "price_change_3m")]:
        val = perf[key]
        perf_parts.append(f"{label}{val:+.1%}")
    perf_str = "、".join(perf_parts)

    # 支撐壓力
    r_str = "、".join([f"${r.price:.2f}" for r in resistances[:2]]) if resistances else "暫無明顯壓力"
    s_str = "、".join([f"${s.price:.2f}" for s in supports[:2]]) if supports else "暫無明顯支撐"

    # 目標價 (6M)
    bull_6m = [t for t in targets if t.timeframe == "6M" and t.scenario == "bull"]
    base_6m = [t for t in targets if t.timeframe == "6M" and t.scenario == "base"]
    bear_6m = [t for t in targets if t.timeframe == "6M" and t.scenario == "bear"]

    bull_p = f"${bull_6m[0].target_price:.2f}" if bull_6m else "N/A"
    base_p = f"${base_6m[0].target_price:.2f}" if base_6m else "N/A"
    bear_p = f"${bear_6m[0].target_price:.2f}" if bear_6m else "N/A"

    # 第一段：概況
    p1 = (
        f"{name}（{code}）截至報告日收盤價為 ${price:.2f} 元，"
        f"近期表現方面，{perf_str}。"
        f"52 週最高 ${perf['high_52w']:.2f}（{perf['high_52w_date']}），"
        f"最低 ${perf['low_52w']:.2f}（{perf['low_52w_date']}），"
        f"目前距 52 週高點 {perf['pct_from_52w_high']:.1%}。"
        f"從技術面綜合評估，本報告給予「{rating}」評等。"
    )

    # 第二段：趨勢與動能
    p2 = (
        f"趨勢面觀察，該股目前處於{trend['trend_direction']}格局，"
        f"均線呈{trend['ma_alignment']}，趨勢強度{trend['trend_strength']}。"
        f"動能指標方面，ADX 報 {mom['adx_value']:.1f}，{mom['adx_interpretation'][:15]}；"
        f"RSI 為 {mom['rsi_value']:.1f}，{mom['rsi_interpretation'][:10]}；"
        f"MACD {mom['macd_interpretation'][:20]}；"
        f"KD 指標 {mom['kd_interpretation'][:15]}。"
        f"整體動能評估為「{mom['momentum_status']}」。"
    )

    # 第三段：量能與波動
    p3 = (
        f"成交量方面，近期量能{vol['volume_trend']}，"
        f"量能比為 {vol['volume_ratio']:.1f} 倍，"
        f"籌碼面評估為{vol['accumulation_distribution']}。"
        f"波動度方面，14 日 ATR 佔股價 {volatility['atr_pct']:.1%}，"
        f"波動度{volatility['volatility_level']}；"
        f"20 日歷史波動率為 {volatility['historical_volatility_20d']:.1%}。"
    )

    # 第四段：關鍵價位與目標價
    p4 = (
        f"關鍵價位分析，上方主要壓力位於 {r_str}，"
        f"下方支撐位於 {s_str}。"
        f"費氏分析顯示波段高點 ${fib.swing_high:.2f}、低點 ${fib.swing_low:.2f}，"
        f"方向為{fib.direction}。"
        f"綜合目標價估算（六個月），樂觀情境 {bull_p}、"
        f"基本情境 {base_p}、保守情境 {bear_p}。"
        f"風險報酬比為 {risk['risk_reward_ratio']:.1f}:1。"
    )

    # 第五段：展望與結論
    o3 = outlook_3m
    p5 = (
        f"展望未來三個月，基本情境（機率 {o3.base_probability}%）預期"
        f"{o3.base_case[:30]}。"
        f"近一年最大回撤為 {risk['max_drawdown_1y']:.1%}，"
        f"關鍵風險價位在 ${risk['key_risk_level']:.2f}，若有效跌破恐引發進一步修正。"
        f"綜合技術面與基本面分析，建議投資人"
    )

    if rating in ("強力買進", "買進"):
        p5 += "可於支撐附近分批佈局，並嚴設停損控制風險。"
    elif rating == "中性":
        p5 += "保持觀望，待明確方向訊號出現後再行操作。"
    else:
        p5 += "宜降低持股比重或暫時觀望，等待技術面轉強。"
    p5 += "（以上分析僅供參考，不構成投資建議。）"

    # 第六段：基本面摘要（如有資料）
    fund = data.get("fundamentals", {})
    fund_interp = data.get("fundamental_interpretation", "")
    analyst = data.get("analyst_data", {})
    p6 = ""
    if fund_interp:
        p6 = f"基本面方面，{fund_interp}"
        if analyst.get("target_mean"):
            n = analyst.get("num_analysts")
            n_str = f"（{int(n)} 位分析師）" if n else ""
            p6 += f"法人共識目標均價為 {analyst['target_mean']:.0f} 元{n_str}，上檔空間 {analyst.get('upside', 0):.0%}。"

    # 第七段：消息面摘要（如有資料）
    news_label = data.get("news_sentiment_label", "無資料")
    news_items = data.get("news_items", [])
    p_news = ""
    if news_items and news_label != "無資料":
        p_news = f"消息面方面，近期共有 {len(news_items)} 則相關新聞，整體情緒{news_label}。"
        credible = [n for n in news_items if n.get("credibility") == "可信"][:2]
        if credible:
            titles = "、".join([f"「{n['title'][:40]}」" for n in credible])
            p_news += f"主要消息包括：{titles}。"

    result = p1 + "\n\n" + p2 + "\n\n" + p3 + "\n\n" + p4 + "\n\n" + p5
    if p6:
        result += "\n\n" + p6
    if p_news:
        result += "\n\n" + p_news
    return result


# ============================================================
# Main Function
# ============================================================

def generate_report(stock_code: str, period_days: int = 730) -> ReportResult:
    """產生完整專業分析報告"""
    # 1. 取得資料
    raw_df = get_stock_data(stock_code, period_days=period_days)
    try:
        company_info = get_stock_info(stock_code)
    except Exception:
        name = get_stock_name(stock_code, get_all_stocks())
        company_info = {"name": name, "sector": "N/A", "industry": "N/A",
                        "market_cap": 0, "currency": "TWD"}

    # 2. 計算指標
    df = calculate_all_indicators(raw_df)
    df["ma120"] = df["close"].rolling(120).mean()
    df["ma240"] = df["close"].rolling(240).mean()

    # 3. 策略訊號
    try:
        v4 = get_v4_analysis(raw_df)
    except Exception:
        v4 = {"signal": "HOLD", "entry_type": "", "uptrend_days": 0,
              "dist_ma20": 0, "indicators": {}}
    try:
        v2 = get_latest_analysis(raw_df)
    except Exception:
        v2 = {"signal": "HOLD", "composite_score": 0, "scores": {}, "indicators": {}}

    current_price = float(df["close"].iloc[-1])

    # 3b. 基本面與消息面
    try:
        fundamentals_raw = get_stock_fundamentals(stock_code)
    except Exception:
        fundamentals_raw = {}
    # 中文名稱（用於報告標題、Google News 搜尋）
    cn_name = get_stock_name(stock_code, get_all_stocks())
    # 優先使用中文名；若 stock_list 無此股則用 yfinance 英文名
    display_name = cn_name if cn_name and cn_name != stock_code else company_info["name"]

    # 多來源新聞：Google News 中文 + Google News 英文 + yfinance
    raw_news = []
    try:
        google_news = get_google_news(stock_code, cn_name)
        raw_news.extend(google_news)
    except Exception:
        pass
    # 英文 Google News（用 yfinance 英文名搜尋，適合跨國合作消息）
    en_name = company_info.get("name", "")
    if en_name and en_name != stock_code:
        try:
            google_news_en = get_google_news(stock_code, en_name, lang="en")
            existing_titles = {n["title"].lower() for n in raw_news}
            for n in google_news_en:
                if n["title"].lower() not in existing_titles:
                    raw_news.append(n)
        except Exception:
            pass
    try:
        yf_news = get_stock_news(stock_code)
        # 去重：如果已有同標題則跳過
        existing_titles = {n["title"].lower() for n in raw_news}
        for n in yf_news:
            if n["title"].lower() not in existing_titles:
                raw_news.append(n)
    except Exception:
        pass

    fund_result = _assess_fundamentals(fundamentals_raw, current_price)
    scored_news = _assess_news(raw_news)
    news_sentiment = _analyze_news_sentiment(scored_news)

    # 4. 計算各 section
    perf = _calculate_price_performance(df)
    swings = _detect_swing_points(df)
    trend = _assess_trend(df)
    momentum = _assess_momentum(df)
    volume = _assess_volume(df)
    volatility = _assess_volatility(df)
    supports, resistances = _calculate_support_resistance(df, swings, current_price)
    fib = _calculate_fibonacci(df, swings)
    risk = _assess_risk(df, supports)

    targets = _calculate_price_targets(
        current_price, fib,
        _safe(df["atr_pct"].iloc[-1]),
        resistances, supports,
        trend["trend_direction"],
        _safe(df["adx"].iloc[-1]),
        analyst_data=fund_result.get("analyst_data"),
    )

    # 取得 3M base case 上檔空間供評等參考
    base_3m = next((t for t in targets if t.timeframe == "3M" and t.scenario == "base"), None)
    base_3m_upside = base_3m.upside_pct if base_3m else 0

    overall_rating = _calculate_overall_rating(
        trend["trend_direction"], momentum["momentum_status"],
        v4["signal"], v2.get("composite_score", 0),
        momentum["rsi_value"], risk["risk_reward_ratio"],
        base_3m_upside=base_3m_upside,
        fundamental_score=fund_result["fundamental_score"],
    )

    outlook_3m, outlook_6m, outlook_1y = _generate_outlook(
        trend["trend_direction"], momentum["momentum_status"],
        targets, volatility["volatility_level"],
        current_price, momentum["adx_value"], momentum["rsi_value"],
        fundamental_score=fund_result["fundamental_score"],
        fund_interpretation=fund_result["fundamental_interpretation"],
        analyst_data=fund_result.get("analyst_data"),
    )

    # 5. 摘要
    summary_data = {
        "stock_code": stock_code,
        "stock_name": display_name,
        "current_price": current_price,
        "performance": perf,
        "trend": trend,
        "momentum": momentum,
        "volume": volume,
        "volatility": volatility,
        "risk": risk,
        "targets": targets,
        "outlook_3m": outlook_3m,
        "fibonacci": fib,
        "supports": supports,
        "resistances": resistances,
        "overall_rating": overall_rating,
        "fundamentals": fund_result.get("metrics", {}),
        "fundamental_interpretation": fund_result["fundamental_interpretation"],
        "analyst_data": fund_result["analyst_data"],
        "news_sentiment_label": news_sentiment["label"],
        "news_items": scored_news,
    }
    summary = _generate_summary(summary_data)

    # 6. 組裝
    return ReportResult(
        stock_code=stock_code,
        stock_name=display_name,
        report_date=datetime.now(),
        data_period_days=period_days,
        company_info=company_info,
        current_price=current_price,
        price_change_1w=perf["price_change_1w"],
        price_change_1m=perf["price_change_1m"],
        price_change_3m=perf["price_change_3m"],
        price_change_6m=perf["price_change_6m"],
        price_change_1y=perf["price_change_1y"],
        high_52w=perf["high_52w"],
        low_52w=perf["low_52w"],
        high_52w_date=perf["high_52w_date"],
        low_52w_date=perf["low_52w_date"],
        pct_from_52w_high=perf["pct_from_52w_high"],
        pct_from_52w_low=perf["pct_from_52w_low"],
        trend_direction=trend["trend_direction"],
        trend_strength=trend["trend_strength"],
        momentum_status=momentum["momentum_status"],
        volatility_level=volatility["volatility_level"],
        overall_rating=overall_rating,
        ma_alignment=trend["ma_alignment"],
        support_levels=supports,
        resistance_levels=resistances,
        fibonacci=fib,
        price_targets=targets,
        adx_value=momentum["adx_value"],
        adx_interpretation=momentum["adx_interpretation"],
        rsi_value=momentum["rsi_value"],
        rsi_interpretation=momentum["rsi_interpretation"],
        macd_value=momentum["macd_value"],
        macd_signal_value=momentum["macd_signal_value"],
        macd_histogram=momentum["macd_histogram"],
        macd_interpretation=momentum["macd_interpretation"],
        k_value=momentum["k_value"],
        d_value=momentum["d_value"],
        kd_interpretation=momentum["kd_interpretation"],
        volume_trend=volume["volume_trend"],
        volume_ratio=volume["volume_ratio"],
        accumulation_distribution=volume["accumulation_distribution"],
        volume_interpretation=volume["volume_interpretation"],
        atr_value=volatility["atr_value"],
        atr_pct=volatility["atr_pct"],
        historical_volatility_20d=volatility["historical_volatility_20d"],
        historical_volatility_60d=volatility["historical_volatility_60d"],
        bollinger_width=volatility["bollinger_width"],
        bollinger_position=volatility["bollinger_position"],
        volatility_interpretation=volatility["volatility_interpretation"],
        max_drawdown_1y=risk["max_drawdown_1y"],
        current_drawdown=risk["current_drawdown"],
        key_risk_level=risk["key_risk_level"],
        risk_reward_ratio=risk["risk_reward_ratio"],
        risk_interpretation=risk["risk_interpretation"],
        outlook_3m=outlook_3m,
        outlook_6m=outlook_6m,
        outlook_1y=outlook_1y,
        summary_text=summary,
        v4_analysis=v4,
        v2_analysis=v2,
        fundamentals=fund_result.get("metrics", {}),
        fundamental_interpretation=fund_result["fundamental_interpretation"],
        fundamental_score=fund_result["fundamental_score"],
        analyst_data=fund_result["analyst_data"],
        news_items=scored_news,
        news_sentiment_score=news_sentiment["score"],
        news_sentiment_label=news_sentiment["label"],
        indicators_df=df,
    )

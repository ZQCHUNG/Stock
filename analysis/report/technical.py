"""技術分析模組 — 價格、趨勢、動能、量能、波動度、支撐壓力、目標價"""

import math
import pandas as pd
import numpy as np
from analysis.report_models import SupportResistanceLevel, FibonacciLevels, PriceTarget, _safe


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
    def filter_nearby(points, keep_higher=True, min_bars=10):
        if not points:
            return points
        filtered = [points[0]]
        for p in points[1:]:
            idx_diff = abs(df.index.get_loc(p[0]) - df.index.get_loc(filtered[-1][0]))
            if idx_diff < min_bars:
                # 保留更極端的
                if keep_higher:
                    if p[1] > filtered[-1][1]:
                        filtered[-1] = p
                else:
                    if p[1] < filtered[-1][1]:
                        filtered[-1] = p
            else:
                filtered.append(p)
        return filtered

    swing_highs = filter_nearby(swing_highs, keep_higher=True)
    swing_lows = filter_nearby(swing_lows, keep_higher=False)

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

    # 短期價格變動（5 日），用來修正 MA 斜率滯後
    close_series = df["close"].dropna()
    if len(close_series) >= 5:
        short_chg = (close_series.iloc[-1] - close_series.iloc[-5]) / close_series.iloc[-5]
    else:
        short_chg = 0

    # 趨勢方向（MA 斜率 + 短期價格修正）
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

    # 修正：MA 斜率滯後導致趨勢與短期走勢矛盾
    # 當 MA 說上漲但近 5 日跌 > 5%，降級趨勢判定
    if trend_direction in ("強勢上漲", "溫和上漲") and short_chg < -0.05:
        trend_direction = "盤整"
    elif trend_direction in ("強勢下跌", "溫和下跌") and short_chg > 0.05:
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


def _assess_risk(df, support_levels, resistance_levels=None):
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

    # 風險報酬比：用實際最近壓力位當報酬目標
    if resistance_levels:
        nearest_resistance = resistance_levels[0].price
    else:
        nearest_resistance = current * 1.05
    rr = (nearest_resistance - current) / (current - key_risk) if current > key_risk else 0

    # 解讀
    parts = []
    parts.append(f"近一年最大回撤為 {max_dd:.1%}，目前距歷史高點 {current_dd:.1%}")
    if max_dd < -0.20:
        parts.append("歷史回撤幅度偏大，須注意下檔風險")
    if rr > 2:
        parts.append(f"風險報酬比 {rr:.1f}:1，上檔空間相對充裕")
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
    # 過濾條件：分析師 >= 2 人且目標價偏離現價 < 200%，否則視為不可靠
    analyst_target = None
    analyst_high = None
    analyst_low = None
    if analyst_data:
        num_analysts = analyst_data.get("num_analysts", 0) or 0
        _at = analyst_data.get("target_mean")
        _ah = analyst_data.get("target_high")
        _al = analyst_data.get("target_low")
        if num_analysts >= 2:
            # 只採用偏離 < 200% 的法人目標
            if _at and _at > 0 and abs(_at / current_price - 1) < 2.0:
                analyst_target = _at
            if _ah and _ah > 0 and abs(_ah / current_price - 1) < 2.0:
                analyst_high = _ah
            if _al and _al > 0 and abs(_al / current_price - 1) < 2.0:
                analyst_low = _al

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

        # 強制保持 bull >= base >= bear 排序
        if bull_target < bear_target:
            bull_target, bear_target = bear_target, bull_target
        if base_target > bull_target:
            base_target = bull_target * 0.95
        if base_target < bear_target:
            base_target = bear_target * 1.05

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

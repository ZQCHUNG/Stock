"""推薦與展望模組 — 評等、矛盾偵測、行動建議、展望、摘要"""

from analysis.report_models import OutlookScenario, _safe

import pandas as pd


def _calculate_overall_rating(trend_direction, momentum_status, v4_signal,
                               v2_composite, rsi, rr_ratio, base_3m_upside=0,
                               fundamental_score=0.0, market_regime=None,
                               technical_conflicts=None):
    """計算綜合評等（含 RR 矛盾修正 + 技術面矛盾降級 + 市場環境上限）

    評分邏輯：
    - 趨勢（-2~+2）+ v4 訊號（-2~+2）+ v2 分數（-1~+1）
    - 動能（-2~+2）+ RSI 極端（-1~+1）+ RR 比（-3~+1）
    - 基本面（-2~+2）+ 目標價上檔（-2~+2）
    - 技術面矛盾扣分（每個矛盾 -0.5，最多 -2）
    - 最終評等：≥6 強力買進, ≥3 買進, ≥-1 中性, ≥-4 賣出, else 強力賣出
    """
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

    # RR 修正：強化低 RR 懲罰
    if rr_ratio > 2:
        score += 1
    elif rr_ratio < 0.3:
        score -= 3
    elif rr_ratio < 0.5:
        score -= 2
    elif rr_ratio < 0.8:
        score -= 1

    # 基本面評分（-5~+5 → 約 -2~+2）
    score += fundamental_score * 0.4

    # 目標價上檔空間調整
    if base_3m_upside > 0.10:
        score += 2
    elif base_3m_upside > 0.05:
        score += 1
    elif base_3m_upside < -0.05:
        score -= 2
    elif base_3m_upside < 0:
        score -= 1

    # 技術面矛盾扣分：存在矛盾時降低評等，避免「強力買進」與「謹慎偏多」矛盾
    conflicts = technical_conflicts or []
    conflict_penalty = min(len(conflicts) * 0.5, 2.0)
    score -= conflict_penalty

    if score >= 6:
        rating = "強力買進"
    elif score >= 3:
        rating = "買進"
    elif score >= -1:
        rating = "中性"
    elif score >= -4:
        rating = "賣出"
    else:
        rating = "強力賣出"

    # 市場環境上限：空頭時最高「買進」
    if market_regime == "bear" and rating == "強力買進":
        rating = "買進"

    # 技術面矛盾 + 強力買進 = 不允許（Gemini R10: 矛盾信號不應給最高評等）
    # 只要存在任何技術面矛盾，就不能給「強力買進」
    if conflicts and rating == "強力買進":
        rating = "買進"

    # RSI 超買（>70）+ 強力買進 = 不允許
    if rsi > 70 and rating == "強力買進":
        rating = "買進"

    return rating


def _resolve_technical_conflicts(momentum_data: dict, trend_data: dict,
                                  risk_data: dict, df: pd.DataFrame) -> dict:
    """偵測技術指標之間的矛盾並給出綜合偏向（Gemini 項目 5: 邏輯連貫性）"""
    conflicts = []
    adx = momentum_data.get("adx_value", 0)
    rsi = momentum_data.get("rsi_value", 50)
    macd_interp = momentum_data.get("macd_interpretation", "")
    kd_interp = momentum_data.get("kd_interpretation", "")
    macd_val = momentum_data.get("macd_value", 0)
    macd_sig = momentum_data.get("macd_signal_value", 0)
    macd_hist = momentum_data.get("macd_histogram", 0)
    k = momentum_data.get("k_value", 50)
    d = momentum_data.get("d_value", 50)
    trend_dir = trend_data.get("trend_direction", "盤整")
    ma_align = trend_data.get("ma_alignment", "糾結")
    rr = risk_data.get("risk_reward_ratio", 1.0)

    # 1) MACD vs KD 方向衝突
    macd_bullish = macd_val > macd_sig and macd_val > 0
    kd_bearish = k < d
    kd_bullish = k > d
    macd_bearish = macd_val < macd_sig and macd_val < 0
    if macd_bullish and kd_bearish:
        weight_note = "ADX 偏強，以趨勢指標（MACD）為主" if adx > 25 else "ADX 偏弱，KD 短線訊號權重較高"
        conflicts.append(f"MACD 多頭格局 vs KD 死亡交叉：{weight_note}")
    elif macd_bearish and kd_bullish:
        conflicts.append("MACD 空頭格局 vs KD 黃金交叉：短線可能反彈但中期趨勢仍偏空")

    # 2) MACD 柱狀圖動能衰退
    if macd_bullish and macd_hist > 0:
        hist_series = df["macd_hist"].dropna().tail(5)
        if len(hist_series) >= 3 and hist_series.iloc[-1] < hist_series.iloc[-3]:
            conflicts.append("MACD 在零軸之上但柱狀圖收斂，多頭動能可能正在衰退")

    # 3) 評等 vs 風險報酬比衝突
    if rr < 0.5:
        conflicts.append(f"風險報酬比僅 {rr:.1f}:1，下檔風險遠大於潛在報酬，操作需極度謹慎")

    # 4) 均線多頭 + RSI 超買 — 提供專業解讀
    if ma_align == "多頭排列" and rsi > 70:
        if adx > 30:
            conflicts.append(
                f"均線多頭排列但 RSI={rsi:.0f} 超買（ADX={adx:.0f} 趨勢強勁）：強趨勢下 RSI 可維持高位較久，"
                f"但短線回檔機率升高。建議：逢低承接而非追高，等待 RSI 回落至 60 以下或股價回測 MA20 再加碼"
            )
        else:
            conflicts.append(
                f"均線多頭排列但 RSI={rsi:.0f} 超買（ADX={adx:.0f} 趨勢偏弱）：趨勢力道不足下 RSI 超買，"
                f"回檔風險較高。建議：減碼或等待，觀察是否跌破 MA20 確認趨勢轉弱"
            )

    # 5) 量價背離
    tail5 = df.tail(5)
    if len(tail5) >= 5:
        price_up = tail5["close"].iloc[-1] > tail5["close"].iloc[0]
        vol_down = tail5["volume"].iloc[-1] < tail5["volume"].iloc[0] * 0.7
        price_down = tail5["close"].iloc[-1] < tail5["close"].iloc[0]
        vol_up = tail5["volume"].iloc[-1] > tail5["volume"].iloc[0] * 1.3
        if price_up and vol_down:
            conflicts.append("股價上漲但量能萎縮，上漲缺乏量能支撐，須留意假突破")
        elif price_down and vol_up:
            conflicts.append("股價下跌伴隨放量，可能有主力出貨跡象")

    # 綜合技術偏向
    bullish_count = sum([
        macd_bullish, kd_bullish, rsi > 50,
        "上漲" in trend_dir, ma_align == "多頭排列",
    ])
    bearish_count = sum([
        macd_bearish, kd_bearish, rsi < 50,
        "下跌" in trend_dir, ma_align == "空頭排列",
    ])
    if conflicts:
        if bullish_count > bearish_count + 1:
            bias = "謹慎偏多（存在矛盾訊號）"
        elif bearish_count > bullish_count + 1:
            bias = "謹慎偏空（存在矛盾訊號）"
        else:
            bias = "中性偏觀望（多空訊號分歧）"
    else:
        if bullish_count >= 4:
            bias = "偏多"
        elif bearish_count >= 4:
            bias = "偏空"
        elif bullish_count > bearish_count:
            bias = "略偏多"
        elif bearish_count > bullish_count:
            bias = "略偏空"
        else:
            bias = "中性"

    return {"conflicts": conflicts, "technical_bias": bias}


def _generate_actionable_recommendation(
    overall_rating: str, risk_data: dict, momentum_data: dict,
    trend_data: dict, volatility_data: dict,
    support_levels: list, resistance_levels: list,
    current_price: float, industry_risks: list,
    technical_bias: str, fundamentals: dict,
) -> dict:
    """產生具體行動建議（Gemini 項目 1+2: 投資論點 + 操作建議）"""
    rr = risk_data.get("risk_reward_ratio", 1.0)
    atr_pct = volatility_data.get("atr_pct", 0.02)
    atr_val = volatility_data.get("atr_value", current_price * 0.02)
    trend_dir = trend_data.get("trend_direction", "盤整")
    rsi = momentum_data.get("rsi_value", 50)

    # --- 決定 action ---
    if overall_rating == "強力買進":
        action = "BUY"
    elif overall_rating == "買進":
        action = "BUY"
    elif overall_rating == "強力賣出":
        action = "SELL"
    elif overall_rating == "賣出":
        if rr < 0.5:
            action = "AVOID"
        else:
            action = "SELL"
    else:  # 中性
        if rr < 0.5:
            action = "AVOID"
        elif rr < 0.8 and "偏空" in technical_bias:
            action = "AVOID"
        else:
            action = "HOLD"

    # --- 投資論點（含基本面 + 產業脈絡）---
    rg = fundamentals.get("revenue_growth")
    eg = fundamentals.get("earnings_growth")
    pe = fundamentals.get("pe_ratio")
    roe = fundamentals.get("roe")
    gm = fundamentals.get("gross_margin")

    thesis_parts = []
    if action == "BUY":
        # 趨勢面
        if "上漲" in trend_dir:
            thesis_parts.append("技術面趨勢向上")
        # 基本面亮點
        if eg is not None and eg > 0.2:
            thesis_parts.append(f"獲利成長 {eg:.0%} 動能強勁")
        elif rg is not None and rg > 0.15:
            thesis_parts.append(f"營收成長 {rg:.0%} 支撐估值")
        if roe is not None and roe > 0.20:
            thesis_parts.append(f"ROE {roe:.0%} 具高資本效率")
        if rr > 1.5:
            thesis_parts.append(f"風險報酬比 {rr:.1f}:1 具吸引力")
        if rsi < 40:
            thesis_parts.append("RSI 超賣具反彈空間")
        if not thesis_parts:
            thesis_parts.append("綜合技術面與基本面訊號偏多")
    elif action == "SELL":
        if "下跌" in trend_dir:
            thesis_parts.append("技術面趨勢向下")
        if eg is not None and eg < -0.1:
            thesis_parts.append(f"獲利衰退 {eg:.0%}")
        elif rg is not None and rg < -0.1:
            thesis_parts.append(f"營收衰退 {rg:.0%}")
        if rr < 0.5:
            thesis_parts.append(f"風險報酬比 {rr:.1f}:1 不利")
        if rsi > 70:
            thesis_parts.append("RSI 超買有回檔壓力")
        if not thesis_parts:
            thesis_parts.append("綜合技術面與基本面訊號偏空")
    elif action == "AVOID":
        if rr < 0.5:
            thesis_parts.append(f"風險報酬比僅 {rr:.1f}:1，下檔風險遠大於上檔空間")
        high_risks = [r for r in industry_risks if r["severity"] == "high"]
        if high_risks:
            thesis_parts.append(f"存在 {len(high_risks)} 項高嚴重度產業風險")
        if eg is not None and eg < -0.2:
            thesis_parts.append(f"獲利大幅衰退 {eg:.0%}")
        if not thesis_parts:
            thesis_parts.append("風險過高且缺乏明確催化劑")
    else:  # HOLD
        parts = []
        if "上漲" in trend_dir and rsi > 70:
            parts.append("趨勢向上但 RSI 超買，等待拉回再進場")
        elif "下跌" in trend_dir and rsi < 30:
            parts.append("趨勢向下但 RSI 超賣，等待止穩訊號")
        else:
            parts.append("多空訊號不明確，等待方向確認")
        thesis_parts.extend(parts)

    thesis = "，".join(thesis_parts) + "。"

    # --- 價位計算（含計算依據）---
    # 支撐位（來源：技術面支撐偵測，基於 pivot points + 密集成交區聚類）
    sup1 = support_levels[0].price if len(support_levels) >= 1 else current_price * 0.93
    sup2 = support_levels[1].price if len(support_levels) >= 2 else sup1 * 0.95
    sup1_method = support_levels[0].method if len(support_levels) >= 1 and hasattr(support_levels[0], 'method') else "pivot聚類"

    # 壓力位（來源：技術面壓力偵測）
    res1 = resistance_levels[0].price if len(resistance_levels) >= 1 else current_price * 1.05
    res2 = resistance_levels[1].price if len(resistance_levels) >= 2 else res1 * 1.05

    # 進場區間
    entry_basis = ""
    if action == "BUY":
        entry_low = round(sup1, 2)
        entry_high = round(current_price * 1.01, 2)
        entry_basis = f"下緣=第一支撐位（{sup1_method}），上緣=現價+1%"
    elif action == "SELL":
        entry_low = round(current_price * 0.99, 2)
        entry_high = round(res1, 2)
        entry_basis = "下緣=現價-1%，上緣=第一壓力位"
    else:
        entry_low = None
        entry_high = None

    # 停損（基於第二支撐位 - 0.5x ATR 緩衝）
    if action == "BUY":
        stop_loss = round(sup2 - atr_val * 0.5, 2)
        sl_basis = f"第二支撐位 ${sup2:.2f} - 0.5×ATR (${atr_val:.2f}) 緩衝"
        sl_pct = (stop_loss - current_price) / current_price
    else:
        stop_loss = None
        sl_basis = ""
        sl_pct = 0

    # 停利目標（基於壓力位 + 技術型態）
    tp_basis = ""
    if action == "BUY":
        tp1 = round(res1, 2)
        tp2 = round(res2, 2) if res2 > res1 else round(res1 * 1.1, 2)
        tp_basis = f"T1=第一壓力位 ${res1:.2f}，T2=第二壓力位或+10%"
    elif action == "SELL":
        tp1 = round(sup1, 2)
        tp2 = round(sup2, 2)
        tp_basis = f"T1=第一支撐位，T2=第二支撐位"
    else:
        tp1 = None
        tp2 = None

    # --- 部位建議（基於 ATR% 波動度 + Kelly 簡化概念）---
    if action in ("AVOID", "HOLD"):
        position_pct = "N/A（不建議新增部位）"
        position_basis = ""
    elif atr_pct > 0.04:
        position_pct = "3-5%（高波動，降低部位）"
        position_basis = f"ATR%={atr_pct:.1%}（高波動），參考 2% 風險法則：單筆虧損上限=總資產 2%"
    elif atr_pct > 0.02:
        position_pct = "5-8%（中等波動）"
        position_basis = f"ATR%={atr_pct:.1%}（中等波動），參考 2% 風險法則"
    else:
        position_pct = "8-12%（低波動）"
        position_basis = f"ATR%={atr_pct:.1%}（低波動），參考 2% 風險法則"

    # --- 觸發條件（具體化 K 線形態定義）---
    triggers = []
    if action == "BUY":
        triggers.append(
            f"股價回測支撐 ${sup1:.2f} 附近且量縮（量能比<0.7x），"
            f"出現止穩 K 線（帶長下影線且收盤 > 開盤，或連續兩日收紅），可分批進場"
        )
        if resistance_levels:
            triggers.append(f"突破壓力 ${res1:.2f} 且帶量（量能比 > 1.5x 5日均量），可追買")
        if rsi > 70:
            triggers.append(
                f"注意：RSI={rsi:.1f} 已超買，建議等待 RSI 回落至 60 以下或股價回測均線再進場，"
                f"勿追高"
            )
    elif action == "SELL":
        triggers.append(f"跌破支撐 ${sup1:.2f} 且帶量（量能比 > 1.3x），確認賣出訊號")
    elif action == "AVOID":
        triggers.append(f"重新評估條件 1：風險報酬比回升至 1.0 以上（需壓力下移或支撐上移）")
        triggers.append(f"重新評估條件 2：放量突破壓力 ${res1:.2f}，確認趨勢轉強")
        if high_risks:
            triggers.append(f"重新評估條件 3：高嚴重度風險緩解（如：基本面出現轉機、營收翻正）")
        triggers.append(f"若跌破 ${sup1:.2f} 確認弱勢，則維持避開直到出現底部反轉訊號")
    else:
        if resistance_levels:
            triggers.append(f"轉買訊號：突破 ${res1:.2f} 帶量（量能比 > 1.5x），確認方向")
        if support_levels:
            triggers.append(f"轉賣訊號：跌破 ${sup1:.2f} 帶量，確認弱勢")
        triggers.append("持續觀察技術面矛盾是否收斂（MACD/KD 方向一致化）")

    return {
        "action": action,
        "thesis": thesis,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_basis": entry_basis,
        "stop_loss": stop_loss,
        "stop_loss_basis": sl_basis,
        "stop_loss_pct": sl_pct,
        "take_profit_t1": tp1,
        "take_profit_t2": tp2,
        "tp_basis": tp_basis,
        "position_pct": position_pct,
        "position_basis": position_basis,
        "trigger_conditions": triggers,
    }


def _generate_outlook(trend_direction, momentum_status, price_targets,
                       volatility_level, current_price, adx, rsi,
                       fundamental_score=0.0,
                       fund_interpretation="",
                       analyst_data=None,
                       news_themes=None,
                       industry_risks=None,
                       stock_name=""):
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

    # 從 news_themes / industry_risks 提取具體催化劑和風險
    _themes = news_themes or {}
    _risks = industry_risks or []
    _name = stock_name or "該股"

    # 正面催化劑（從新聞主題中提取）
    _catalysts = []
    for theme_key, theme_label in [
        ("營收財報", "財報利多"), ("專利技術", "技術突破"),
        ("合作擴張", "業務擴張"), ("法說活動", "法說利多"),
    ]:
        items = _themes.get(theme_key, [])
        if items:
            _catalysts.append(theme_label)

    # 主要風險（從產業風險中取前 2 個高嚴重度）
    _top_risks = [r["risk"] for r in _risks if r.get("severity") in ("high", "medium")][:2]

    def _catalyst_str():
        if _catalysts:
            return "，近期催化劑包括" + "、".join(_catalysts[:2])
        return ""

    def _risk_str():
        if _top_risks:
            return "，主要風險為" + "、".join(_top_risks[:2])
        return ""

    def make_outlook(tf, tf_label):
        b, m, e = probs[tf]
        bt = get_target(tf, "bull")
        mt = get_target(tf, "base")
        et = get_target(tf, "bear")
        ctx = _fund_context(tf)

        if "上漲" in trend_direction:
            cat = _catalyst_str() if tf in ("3M", "6M") else ""
            rsk = _risk_str() if tf in ("6M", "1Y") else ""
            bull_desc = (
                f"{_name}延續上升趨勢，突破近期壓力後挑戰 ${bt:.2f}"
                f"{cat}{ctx}"
            )
            base_desc = (
                f"漲勢放緩進入震盪整理，預期在 ${et:.2f}～${bt:.2f} 區間波動"
                f"{rsk}"
            )
            bear_desc = (
                f"趨勢反轉跌破關鍵支撐，回落至 ${et:.2f} 附近"
                f"{'，' + '、'.join(_top_risks[:1]) + '可能加速下行' if _top_risks else '，主要風險來自獲利回吐及系統性風險'}"
            )
        elif "下跌" in trend_direction:
            cat = _catalyst_str() if tf in ("3M", "6M") else ""
            rsk = _risk_str() if tf in ("3M", "6M") else ""
            bull_desc = (
                f"{_name}出現技術面反轉訊號，反彈至 ${bt:.2f}，需確認量能配合"
                f"{cat}{ctx}"
            )
            base_desc = (
                f"延續弱勢整理，預期在 ${et:.2f}～${mt:.2f} 之間波動"
                f"{rsk}"
            )
            bear_desc = (
                f"空方趨勢延續，進一步下探 ${et:.2f}"
                f"{'，' + '、'.join(_top_risks[:1]) + '構成額外壓力' if _top_risks else '，須留意支撐失守的連鎖效應'}"
            )
        else:
            cat = _catalyst_str() if tf in ("3M", "6M") else ""
            rsk = _risk_str() if tf in ("6M", "1Y") else ""
            bull_desc = (
                f"{_name}突破盤整區間上緣，啟動新一輪上漲至 ${bt:.2f}"
                f"{cat}{ctx}"
            )
            base_desc = (
                f"維持區間盤整，預期在 ${et:.2f}～${bt:.2f} 之間震盪"
                f"{rsk}"
            )
            bear_desc = (
                f"跌破盤整區間下緣，轉為空方走勢下探 ${et:.2f}"
                f"{'，' + '、'.join(_top_risks[:1]) + '為主要下行風險' if _top_risks else ''}"
            )

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


def _generate_summary(data: dict) -> str:
    """產生決策導向的專業中文摘要（Gemini 項目 6: 摘要說服力）

    新結構：投資論點 → 催化劑與風險 → 交易計畫 → 觀察重點 → 基本面/消息面濃縮
    """
    code = data["stock_code"]
    name = data["stock_name"]
    price = data["current_price"]
    perf = data["performance"]
    trend = data["trend"]
    risk = data["risk"]
    targets = data["targets"]
    supports = data["supports"]
    resistances = data["resistances"]
    rating = data["overall_rating"]

    # 取得新增的分析結果
    rec = data.get("recommendation", {})
    industry_risks = data.get("industry_risks", [])
    news_data = data.get("news_analysis", {})
    tech_conflicts = data.get("technical_conflicts", [])
    tech_bias = data.get("technical_bias", "")
    peer_ctx = data.get("peer_context", {})

    action = rec.get("action", "HOLD")
    thesis = rec.get("thesis", "")
    action_map = {"BUY": "買入", "SELL": "賣出", "HOLD": "觀望", "AVOID": "避開"}
    action_zh = action_map.get(action, "觀望")

    # ===== 第一段：投資論點（30 秒決策） =====
    perf_parts = []
    for label, key in [("一週", "price_change_1w"), ("一個月", "price_change_1m"),
                       ("三個月", "price_change_3m")]:
        val = perf[key]
        perf_parts.append(f"{label}{val:+.1%}")

    p1 = (
        f"【{action_zh}】{name}（{code}）收盤 ${price:.2f}，"
        f"綜合評等「{rating}」，技術偏向「{tech_bias}」。"
        f"投資論點：{thesis}"
        f"近期走勢：{', '.join(perf_parts)}，距 52 週高點 {perf['pct_from_52w_high']:.1%}。"
    )

    # ===== 第二段：催化劑與風險 =====
    catalysts = []
    risk_points = []

    # 從新聞主題提取催化劑（用主題概述，非原始標題）
    themes = news_data.get("themes", {})
    _theme_catalyst_map = {
        "營收財報": "近期有財報/營收面利多消息",
        "專利技術": "技術或專利面有正向進展",
        "合作擴張": "業務合作或產能擴張動向",
        "獎項榮譽": "品牌/品質獲得市場認可",
        "法說會議": "法說會或公司治理有新動態",
    }
    for theme_name, titles in themes.items():
        if titles and theme_name in _theme_catalyst_map:
            catalysts.append(f"{_theme_catalyst_map[theme_name]}（{len(titles)} 則相關報導）")
    if not catalysts:
        if "上漲" in trend["trend_direction"]:
            catalysts.append("技術面趨勢偏多，均線支撐有效")

    # 從產業風險提取重點（含 medium 嚴重度）
    for r in industry_risks[:3]:
        risk_points.append(r["risk"])
    if risk["risk_reward_ratio"] < 0.8:
        risk_points.append(f"風險報酬比僅 {risk['risk_reward_ratio']:.1f}:1")
    if not risk_points:
        risk_points.append(f"最大回撤 {risk['max_drawdown_1y']:.1%}")

    p2 = f"潛在催化劑：{'、'.join(catalysts[:3])}。主要風險：{'、'.join(risk_points[:3])}。"

    # 消息面矛盾
    contradictions = news_data.get("contradictions", [])
    if contradictions:
        p2 += f"注意矛盾：{contradictions[0]}"

    # ===== 第三段：交易計畫（僅 BUY/SELL，含計算依據） =====
    p3 = ""
    if action in ("BUY", "SELL"):
        parts = []
        if rec.get("entry_low") and rec.get("entry_high"):
            parts.append(f"進場區間 ${rec['entry_low']:.2f}～${rec['entry_high']:.2f}")
        if rec.get("stop_loss"):
            sl_pct = rec.get("stop_loss_pct", 0)
            parts.append(f"停損 ${rec['stop_loss']:.2f}（{sl_pct:+.1%}）")
        if rec.get("take_profit_t1"):
            tp_str = f"${rec['take_profit_t1']:.2f}"
            if rec.get("take_profit_t2") and rec["take_profit_t2"] != rec["take_profit_t1"]:
                tp_str += f" / ${rec['take_profit_t2']:.2f}"
            parts.append(f"目標 {tp_str}")
        parts.append(f"建議部位 {rec.get('position_pct', 'N/A')}")
        p3 = "交易計畫：" + "，".join(parts) + "。"

        # 計算依據
        basis_parts = []
        if rec.get("entry_basis"):
            basis_parts.append(f"進場依據：{rec['entry_basis']}")
        if rec.get("stop_loss_basis"):
            basis_parts.append(f"停損依據：{rec['stop_loss_basis']}")
        if rec.get("tp_basis"):
            basis_parts.append(f"目標依據：{rec['tp_basis']}")
        if rec.get("position_basis"):
            basis_parts.append(f"部位依據：{rec['position_basis']}")
        if basis_parts:
            p3 += "\n（" + "；".join(basis_parts) + "）"

    # ===== 第四段：觀察重點 =====
    watch_points = []
    if tech_conflicts:
        watch_points.append(f"技術面矛盾：{tech_conflicts[0]}")
    triggers = rec.get("trigger_conditions", [])
    if triggers:
        watch_points.append(triggers[0])
    if not watch_points:
        s_str = f"${supports[0].price:.2f}" if supports else "N/A"
        r_str = f"${resistances[0].price:.2f}" if resistances else "N/A"
        watch_points.append(f"關鍵支撐 {s_str}，壓力 {r_str}")
    p4 = "觀察重點：" + "；".join(watch_points[:2]) + "。"

    # ===== 第五段：基本面 + 估值 + 產業定位 =====
    fund_interp = data.get("fundamental_interpretation", "")
    p5 = ""
    if fund_interp:
        first_sent = fund_interp.split("。")[0] + "。"
        p5 = f"基本面：{first_sent}"

    if peer_ctx.get("positioning"):
        p5 += "產業定位：" + "；".join(peer_ctx["positioning"][:2]) + "。"

    # 估值模型（Gemini R10 要求）
    valuation = data.get("valuation", {})
    val_summary = valuation.get("summary", "")
    val_methods = valuation.get("methods", [])
    if val_summary and val_methods:
        method_names = "、".join(m["name"] for m in val_methods[:3])
        p5 += f"\n估值分析（{method_names}）：{val_summary}"

    # ===== 第六段：消息面濃縮 =====
    p_news = ""
    credible_count = news_data.get("credible_count", 0)
    insights = news_data.get("insights", [])
    if credible_count > 0:
        # 用解讀 + 來源，去重複解讀，優先選具體解讀
        news_summaries = []
        seen_interps = set()
        for i in insights[:5]:  # 看更多以找到不重複的
            interp = i.get("interpretation", "")
            src = i.get("source", "")
            senti = i.get("sentiment", "")
            if interp and interp not in seen_interps:
                seen_interps.add(interp)
                news_summaries.append(f"{senti}：{interp}（{src}）")
            if len(news_summaries) >= 3:
                break
        if news_summaries:
            p_news = f"消息面（{credible_count} 則可信來源）：{'；'.join(news_summaries)}。"
        else:
            p_news = f"消息面（{credible_count} 則可信來源），整體情緒{data.get('news_sentiment_label', '中性')}。"
        # 情緒趨勢（Gemini R10 要求）
        sentiment_trend = news_data.get("sentiment_trend", "")
        if sentiment_trend and sentiment_trend != "持平":
            p_news += f"情緒趨勢：近期新聞情緒{sentiment_trend}。"
        # 熱點議題
        hotspot = news_data.get("hotspot", "")
        if hotspot:
            p_news += f"熱點議題：{hotspot}。"
        # 低品質來源說明
        forum_note = news_data.get("forum_note", "")
        if forum_note:
            p_news += forum_note

    # ===== 組裝 =====
    sections = [p1, p2]
    if p3:
        sections.append(p3)
    sections.append(p4)
    if p5:
        sections.append(p5)
    if p_news:
        sections.append(p_news)
    sections.append("（以上分析僅供參考，不構成投資建議。）")

    return "\n\n".join(sections)

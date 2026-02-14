"""頁面共用輔助函式"""

import pandas as pd


def explain_signal(analysis: dict, buy_threshold: float, sell_threshold: float) -> str:
    """根據各指標評分產生訊號原因的中文說明（v2 策略用）"""
    scores = analysis["scores"]
    indicators = analysis["indicators"]
    signal = analysis["signal"]
    composite = analysis["composite_score"]

    bullish = []
    bearish = []
    neutral = []

    # MA
    ma_score = scores["MA"]
    if ma_score > 0:
        bullish.append("MA 均線多頭排列（MA5 > MA20），短期趨勢向上")
    elif ma_score < 0:
        bearish.append("MA 均線空頭排列（MA5 < MA20），短期趨勢向下")
    else:
        neutral.append("MA 均線方向不明")

    # RSI
    rsi_score = scores["RSI"]
    rsi_val = indicators.get("RSI", 0)
    if rsi_val and not pd.isna(rsi_val):
        if rsi_score > 0.5:
            bullish.append(f"RSI = {rsi_val:.1f}，處於超賣區（< 30），有反彈空間")
        elif rsi_score > 0:
            bullish.append(f"RSI = {rsi_val:.1f}，偏低但未超賣，仍有上漲動能")
        elif rsi_score < -0.5:
            bearish.append(f"RSI = {rsi_val:.1f}，處於超買區（> 70），注意回檔風險")
        elif rsi_score < 0:
            bearish.append(f"RSI = {rsi_val:.1f}，偏高，上漲動能趨緩")
        else:
            neutral.append(f"RSI = {rsi_val:.1f}，處於中性區間")

    # MACD
    macd_score = scores["MACD"]
    if macd_score > 0:
        bullish.append("MACD 多頭訊號，DIF 在 MACD 之上且柱狀體為正")
    elif macd_score < 0:
        bearish.append("MACD 空頭訊號，DIF 在 MACD 之下且柱狀體為負")
    else:
        neutral.append("MACD 訊號不明確")

    # KD
    kd_score = scores["KD"]
    k_val = indicators.get("K", 0)
    d_val = indicators.get("D", 0)
    if k_val and d_val and not pd.isna(k_val):
        if kd_score > 0:
            bullish.append(f"KD 指標 K={k_val:.1f} D={d_val:.1f}，K > D 黃金交叉偏多")
        elif kd_score < 0:
            bearish.append(f"KD 指標 K={k_val:.1f} D={d_val:.1f}，K < D 死亡交叉偏空")

    # 布林通道
    bb_score = scores["布林通道"]
    if bb_score > 0.3:
        bullish.append("股價靠近布林通道下軌，有反彈機會")
    elif bb_score < -0.3:
        bearish.append("股價靠近布林通道上軌，注意壓力")

    # 成交量
    vol_score = scores["成交量"]
    if vol_score > 0:
        bullish.append("成交量配合（量增價漲或量縮整理）")
    elif vol_score < 0:
        bearish.append("量增價跌，可能為出貨訊號")

    # 組合說明
    lines = []

    if signal == "BUY":
        lines.append(f"**建議買入** — 綜合評分 {composite:+.3f}（超過買入閾值 {buy_threshold}）")
    elif signal == "SELL":
        lines.append(f"**建議賣出** — 綜合評分 {composite:+.3f}（低於賣出閾值 {sell_threshold}）")
    else:
        lines.append(f"**建議持有/觀望** — 綜合評分 {composite:+.3f}（介於賣出閾值 {sell_threshold} 與買入閾值 {buy_threshold} 之間，訊號不夠強烈）")

    if bullish:
        lines.append("\n**偏多因素：**")
        for b in bullish:
            lines.append(f"- {b}")

    if bearish:
        lines.append("\n**偏空因素：**")
        for b in bearish:
            lines.append(f"- {b}")

    if neutral:
        lines.append("\n**中性因素：**")
        for n in neutral:
            lines.append(f"- {n}")

    return "\n".join(lines)

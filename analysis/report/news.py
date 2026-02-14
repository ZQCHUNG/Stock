"""新聞分析模組 — 新聞可信度、情緒分析、消息洞察"""

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


def _extract_news_insights(scored_news: list, fundamentals: dict,
                           stock_name: str) -> dict:
    """消息面增強：過濾噪音、主題分類、交叉比對矛盾（Gemini 項目 4: 消息面品質）"""
    # 1) 品質過濾
    credible = [n for n in scored_news if n.get("credibility_score", 0) > 0]
    low_quality = [n for n in scored_news if n.get("credibility_score", 0) <= 0]

    # 2) 主題分類 (keyword matching)
    theme_keywords = {
        "營收財報": ["營收", "獲利", "財報", "EPS", "revenue", "earnings", "profit", "轉盈", "虧損", "淨利"],
        "專利技術": ["專利", "patent", "技術", "研發", "R&D", "認證", "通過", "臨床", "FDA", "核准"],
        "合作擴張": ["合作", "合資", "簽約", "授權", "partnership", "deal", "擴產", "併購", "IPO", "上市"],
        "法說會議": ["法說", "股東會", "董事會", "增資", "減資", "現金增資"],
        "獎項榮譽": ["得獎", "獲獎", "勇奪", "榮獲", "award", "品質獎"],
        "法規監理": ["法規", "監理", "處罰", "調查", "違規", "訴訟", "regulatory"],
    }
    themes = {k: [] for k in theme_keywords}
    for n in credible:
        title = n.get("title", "")
        for theme, keywords in theme_keywords.items():
            if any(kw in title for kw in keywords):
                themes[theme].append(title)
                break  # 每篇只歸一個主題

    # 移除空主題
    themes = {k: v for k, v in themes.items() if v}

    # 3) 交叉比對矛盾：新聞 vs 基本面數據
    contradictions = []
    rg = fundamentals.get("revenue_growth")

    for n in credible:
        title = n.get("title", "")
        # 新聞說營收雙增但實際營收衰退
        if rg is not None and rg < -0.10:
            if any(kw in title for kw in ["營收成長", "營收雙增", "獲利雙增", "營收新高"]):
                contradictions.append(
                    f"新聞提及「{title[:50]}」，但最新營收數據為 {rg:.0%}，"
                    f"存在預期與現實落差，需關注後續財報是否兌現"
                )
        # 新聞說虧損但實際有獲利
        eg = fundamentals.get("earnings_growth")
        if eg is not None and eg > 0.10:
            if any(kw in title for kw in ["虧損", "衰退", "利空"]):
                contradictions.append(
                    f"新聞提及「{title[:50]}」，但最新獲利成長率為 {eg:.0%}，"
                    f"消息可能已過時或被市場消化"
                )

    # 4) 洞察提取（僅高可信度新聞，附帶含義解讀）
    insights = []
    high_cred = [n for n in scored_news if n.get("credibility_score", 0) >= 2]
    # 解讀規則（由具體到通用，確保大部分新聞都能匹配）
    _interp_rules = [
        (["專利", "patent", "認證", "通過", "FDA", "核准", "研發", "R&D"],
         "技術/專利進展有助提升公司競爭壁壘與市場評價"),
        (["營收", "獲利", "EPS", "轉盈", "revenue", "earnings", "profit", "財報", "淨利", "毛利"],
         "財務面消息直接影響估值與市場信心"),
        (["合作", "合資", "簽約", "授權", "partnership", "deal", "擴產", "併購"],
         "業務拓展可帶來新營收來源與市場擴張機會"),
        (["目標價", "看好", "按讚", "推薦", "升評", "目標"],
         "法人觀點可能影響市場預期與短期股價動能"),
        (["得獎", "獲獎", "勇奪", "品質獎", "award"],
         "品牌與品質認可有助提升市場信任度"),
        (["增資", "募資", "IPO", "上市"],
         "資本市場活動影響股本與每股價值，需留意稀釋效應"),
        (["虧損", "衰退", "裁員", "訴訟", "減產", "下修"],
         "負面事件可能影響營運與投資人信心"),
        (["人事", "資深副總", "董事", "總經理", "CEO"],
         "管理層異動可能影響公司策略方向"),
        (["產能", "擴廠", "新廠", "建廠", "投資"],
         "產能擴張反映長期成長佈局，但須關注資本支出效益"),
        (["ETF", "成分股", "指數", "0050", "0052"],
         "指數/ETF相關消息可影響被動資金流向"),
    ]
    for n in high_cred[:5]:
        title = n.get("title", "")
        sentiment = n.get("sentiment", "中性")
        s_icon = {"正面": "利多", "負面": "利空", "中性": "中性"}.get(sentiment, "中性")
        interpretation = ""
        for keywords, interp in _interp_rules:
            if any(kw in title for kw in keywords):
                interpretation = interp
                break
        if not interpretation:
            # 通用解讀：依 sentiment 給出方向
            if sentiment == "正面":
                interpretation = "正面消息有助提振市場信心"
            elif sentiment == "負面":
                interpretation = "負面消息可能壓抑短期表現"
            else:
                interpretation = "需結合其他指標綜合判斷影響"
        insights.append({
            "title": title, "sentiment": s_icon,
            "source": n.get("source", ""),
            "interpretation": interpretation,
        })

    # 低品質新聞統計（供市場情緒參考）
    forum_note = ""
    if low_quality:
        forum_note = f"另有 {len(low_quality)} 則低品質來源（社群/論壇），僅供市場情緒參考，不納入分析"

    return {
        "insights": insights,
        "themes": themes,
        "contradictions": contradictions,
        "credible_count": len(credible),
        "low_quality_count": len(low_quality),
        "forum_note": forum_note,
    }

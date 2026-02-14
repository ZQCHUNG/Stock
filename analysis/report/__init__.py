"""專業股票分析報告模組

產生證券研究等級的技術分析報告，包含：
公司概況、價格績效、技術面評估、支撐壓力、費氏回檔、
目標價、動能分析、成交量分析、波動度、風險評估、展望、500字摘要

拆分自原 analysis/report.py (2519 行)：
- technical.py — 價格、趨勢、動能、量能、波動度、支撐壓力、目標價
- fundamental.py — 基本面評估、產業風險、產業對照
- news.py — 新聞可信度、情緒分析、消息洞察
- recommendation.py — 評等、矛盾偵測、行動建議、展望、摘要
"""

from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from data.fetcher import (
    get_stock_data, get_stock_info_and_fundamentals,
    get_stock_news, get_google_news,
)
from data.stock_list import get_stock_name, get_all_stocks
from analysis.indicators import calculate_all_indicators
from analysis.strategy import get_latest_analysis
from analysis.strategy_v4 import get_v4_analysis

# 從 report_models 匯入所有資料結構（保持向下相容）
from analysis.report_models import (  # noqa: F401
    SupportResistanceLevel,
    FibonacciLevels,
    PriceTarget,
    OutlookScenario,
    ReportResult,
    _safe,
)

# 從子模組匯入所有函式（保持向下相容：from analysis.report import _xxx）
from analysis.report.technical import (  # noqa: F401
    _calculate_price_performance,
    _detect_swing_points,
    _get_round_numbers,
    _calculate_support_resistance,
    _calculate_fibonacci,
    _assess_trend,
    _assess_momentum,
    _assess_volume,
    _assess_volatility,
    _assess_risk,
    _calculate_price_targets,
)
from analysis.report.fundamental import (  # noqa: F401
    _SECTOR_PROFILES,
    _get_sector_profile,
    _assess_fundamentals,
    _assess_industry_risks,
    _get_peer_context,
)
from analysis.report.news import (  # noqa: F401
    _assess_news,
    _analyze_news_sentiment,
    _extract_news_insights,
)
from analysis.report.recommendation import (  # noqa: F401
    _calculate_overall_rating,
    _resolve_technical_conflicts,
    _generate_actionable_recommendation,
    _generate_outlook,
    _generate_summary,
)


def generate_report(stock_code: str, period_days: int = 730) -> ReportResult:
    """產生完整專業分析報告"""
    # 中文名稱（用於報告標題、Google News 搜尋）—— 純本地查表，無網路
    cn_name = get_stock_name(stock_code, get_all_stocks())

    # 1. 並行取得資料（4 個獨立網路請求同時跑）
    def _fetch_stock_data():
        return get_stock_data(stock_code, period_days=period_days)

    def _fetch_info_and_fundamentals():
        return get_stock_info_and_fundamentals(stock_code)

    def _fetch_google_news_cn():
        return get_google_news(stock_code, cn_name)

    def _fetch_stock_news():
        return get_stock_news(stock_code)

    raw_df = None
    company_info = None
    fundamentals_raw = {}
    google_news_cn = []
    yf_news = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        fut_data = executor.submit(_fetch_stock_data)
        fut_info = executor.submit(_fetch_info_and_fundamentals)
        fut_gnews = executor.submit(_fetch_google_news_cn)
        fut_yfnews = executor.submit(_fetch_stock_news)

        # 收集結果
        try:
            raw_df = fut_data.result()
        except Exception:
            raise  # 股價資料是必要的，失敗就拋出

        try:
            company_info, fundamentals_raw = fut_info.result()
        except Exception:
            company_info = {"name": cn_name or stock_code, "sector": "N/A",
                           "industry": "N/A", "market_cap": 0, "currency": "TWD"}
            fundamentals_raw = {}

        try:
            google_news_cn = fut_gnews.result()
        except Exception:
            google_news_cn = []

        try:
            yf_news = fut_yfnews.result()
        except Exception:
            yf_news = []

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

    # 3b. 消息面：合併 + 英文新聞（依賴 company_info 的英文名）
    # 優先使用中文名；若 stock_list 無此股則用 yfinance 英文名
    display_name = cn_name if cn_name and cn_name != stock_code else company_info["name"]

    raw_news = list(google_news_cn)

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

    # yfinance 新聞去重合併
    existing_titles = {n["title"].lower() for n in raw_news}
    for n in yf_news:
        if n["title"].lower() not in existing_titles:
            raw_news.append(n)

    sector = company_info.get("sector", "")
    industry = company_info.get("industry", "")
    fund_result = _assess_fundamentals(fundamentals_raw, current_price, sector=sector, industry=industry)
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
    risk = _assess_risk(df, supports, resistances)

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

    # 5. 新增分析模組（Gemini 審核項目 1-7）
    tech_conflicts_result = _resolve_technical_conflicts(
        momentum, trend, risk, df,
    )
    industry_risks = _assess_industry_risks(
        sector, industry, fundamentals_raw, volatility,
        volume, current_price, company_info,
    )
    news_analysis = _extract_news_insights(scored_news, fundamentals_raw, display_name)

    outlook_3m, outlook_6m, outlook_1y = _generate_outlook(
        trend["trend_direction"], momentum["momentum_status"],
        targets, volatility["volatility_level"],
        current_price, momentum["adx_value"], momentum["rsi_value"],
        fundamental_score=fund_result["fundamental_score"],
        fund_interpretation=fund_result["fundamental_interpretation"],
        analyst_data=fund_result.get("analyst_data"),
        news_themes=news_analysis.get("themes", {}),
        industry_risks=industry_risks,
        stock_name=display_name,
    )

    peer_context = _get_peer_context(
        sector, industry, fundamentals_raw, current_price, perf,
    )
    recommendation = _generate_actionable_recommendation(
        overall_rating, risk, momentum, trend, volatility,
        supports, resistances, current_price,
        industry_risks, tech_conflicts_result["technical_bias"],
        fundamentals_raw,
    )

    # 評等與行動建議一致性修正：避免「中性」評等卻建議「避開」的矛盾
    if recommendation.get("action") == "AVOID" and overall_rating == "中性":
        overall_rating = "賣出"
    elif recommendation.get("action") == "BUY" and overall_rating in ("中性", "賣出"):
        overall_rating = "買進"

    # 6. 摘要
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
        # 新增
        "recommendation": recommendation,
        "industry_risks": industry_risks,
        "news_analysis": news_analysis,
        "technical_conflicts": tech_conflicts_result["conflicts"],
        "technical_bias": tech_conflicts_result["technical_bias"],
        "peer_context": peer_context,
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
        # 新增欄位
        actionable_recommendation=recommendation,
        industry_risks=industry_risks,
        news_insights=news_analysis.get("insights", []),
        news_themes=news_analysis.get("themes", {}),
        news_contradictions=news_analysis.get("contradictions", []),
        technical_conflicts=tech_conflicts_result["conflicts"],
        technical_bias=tech_conflicts_result["technical_bias"],
        peer_context=peer_context,
    )

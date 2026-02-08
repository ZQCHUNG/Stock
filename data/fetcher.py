"""台股資料抓取模組 - 使用 yfinance

支援上市 (.TW) 與上櫃 (.TWO) 股票，自動判斷。
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta


def _resolve_ticker(stock_code: str) -> str:
    """自動判斷股票是上市 (.TW) 或上櫃 (.TWO)

    先嘗試 .TW，若無資料再嘗試 .TWO
    """
    for suffix in [".TW", ".TWO"]:
        ticker = f"{stock_code}{suffix}"
        try:
            df = yf.download(
                ticker,
                period="5d",
                auto_adjust=True,
                progress=False,
            )
            if not df.empty:
                return ticker
        except Exception:
            continue
    return f"{stock_code}.TW"  # fallback


# 快取已解析過的 ticker，避免重複查詢
_ticker_cache: dict[str, str] = {}


def get_ticker(stock_code: str) -> str:
    """取得 yfinance ticker 字串（含快取）"""
    if stock_code not in _ticker_cache:
        _ticker_cache[stock_code] = _resolve_ticker(stock_code)
    return _ticker_cache[stock_code]


def get_stock_data(
    stock_code: str,
    period_days: int = 365,
    end_date: datetime | None = None,
) -> pd.DataFrame:
    """抓取台股歷史資料

    自動支援上市 (.TW) 與上櫃 (.TWO) 股票。
    優先從 Redis 快取讀取，快取未命中才打 yfinance。

    Args:
        stock_code: 台股代碼（純數字，如 '2330' 或 '6748'）
        period_days: 抓取天數（預設 365 天）
        end_date: 結束日期（預設今天）

    Returns:
        DataFrame with columns: open, high, low, close, volume
    """
    from data.cache import get_cached_stock_data, set_cached_stock_data

    # 嘗試 Redis 快取
    cached = get_cached_stock_data(stock_code, period_days)
    if cached is not None:
        return cached

    ticker = get_ticker(stock_code)
    if end_date is None:
        end_date = datetime.now()
    start_date = end_date - timedelta(days=period_days)

    df = yf.download(
        ticker,
        start=start_date.strftime("%Y-%m-%d"),
        end=end_date.strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=False,
    )

    if df.empty:
        raise ValueError(
            f"無法取得 {stock_code} 的資料，請確認股票代碼是否正確"
            f"（已嘗試 {ticker}）"
        )

    # yfinance 回傳的 columns 可能是 MultiIndex，統一處理
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # 確保欄位名稱一致
    df = df.rename(columns={
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    })

    # 只保留需要的欄位
    df = df[["open", "high", "low", "close", "volume"]].copy()
    df.index.name = "date"

    # 寫入 Redis 快取（5 分鐘）
    set_cached_stock_data(stock_code, period_days, df, ttl=300)

    return df


def get_stock_info(stock_code: str) -> dict:
    """取得股票基本資訊

    Args:
        stock_code: 台股代碼

    Returns:
        包含股票名稱等基本資訊的 dict
    """
    ticker_str = get_ticker(stock_code)
    ticker = yf.Ticker(ticker_str)
    info = ticker.info
    return {
        "name": info.get("longName", info.get("shortName", stock_code)),
        "sector": info.get("sector", "N/A"),
        "industry": info.get("industry", "N/A"),
        "market_cap": info.get("marketCap", 0),
        "shares_outstanding": info.get("sharesOutstanding", 0),
        "currency": info.get("currency", "TWD"),
    }


def get_stock_fundamentals(stock_code: str) -> dict:
    """取得股票基本面數據

    Returns:
        包含估值、獲利、成長、股利、財務健全等指標的 dict，缺值為 None
    """
    ticker_str = get_ticker(stock_code)
    ticker = yf.Ticker(ticker_str)
    info = ticker.info
    return {
        # 估值
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "price_to_book": info.get("priceToBook"),
        # 獲利
        "trailing_eps": info.get("trailingEps"),
        "forward_eps": info.get("forwardEps"),
        "earnings_growth": info.get("earningsGrowth"),
        # 營收
        "total_revenue": info.get("totalRevenue"),
        "revenue_growth": info.get("revenueGrowth"),
        # 利潤率
        "profit_margins": info.get("profitMargins"),
        "gross_margins": info.get("grossMargins"),
        "operating_margins": info.get("operatingMargins"),
        # 股利
        "dividend_yield": info.get("dividendYield"),
        "dividend_rate": info.get("dividendRate"),
        # 財務健全
        "debt_to_equity": info.get("debtToEquity"),
        "current_ratio": info.get("currentRatio"),
        # 報酬率
        "return_on_equity": info.get("returnOnEquity"),
        "return_on_assets": info.get("returnOnAssets"),
        # 風險
        "beta": info.get("beta"),
        # 現金流
        "free_cashflow": info.get("freeCashflow"),
        "operating_cashflow": info.get("operatingCashflow"),
        # 法人
        "analyst_rating": info.get("averageAnalystRating"),
        "target_mean_price": info.get("targetMeanPrice"),
        "target_median_price": info.get("targetMedianPrice"),
        "target_high_price": info.get("targetHighPrice"),
        "target_low_price": info.get("targetLowPrice"),
        "number_of_analysts": info.get("numberOfAnalystOpinions"),
        # 現價（供 screener 免呼叫 get_stock_data）
        "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
    }


def get_stock_news(stock_code: str) -> list:
    """取得股票近期新聞

    Returns:
        list of dict，每項含 title, summary, date, source, url
    """
    ticker_str = get_ticker(stock_code)
    ticker = yf.Ticker(ticker_str)
    raw_news = ticker.news or []

    results = []
    for item in raw_news:
        # yfinance news 結構可能是巢狀 content 或扁平
        content = item.get("content", item)
        title = content.get("title", item.get("title", ""))
        summary = content.get("summary", item.get("summary", ""))
        pub_date = content.get("pubDate", item.get("pubDate", ""))

        provider = content.get("provider", item.get("provider", {}))
        if isinstance(provider, dict):
            source = provider.get("displayName", "Unknown")
        else:
            source = str(provider) if provider else "Unknown"

        canon = content.get("canonicalUrl", item.get("canonicalUrl", {}))
        if isinstance(canon, dict):
            url = canon.get("url", "")
        else:
            url = str(canon) if canon else ""

        if title:
            results.append({
                "title": title,
                "summary": summary,
                "date": pub_date,
                "source": source,
                "url": url,
            })
    return results


def get_google_news(stock_code: str, stock_name: str = "", lang: str = "zh-TW") -> list:
    """從 Google News RSS 取得新聞

    Args:
        stock_code: 股票代碼（如 "6748"）
        stock_name: 股票名稱（如 "亞果生醫"），提升搜尋精確度
        lang: 語系，"zh-TW"（預設）或 "en"

    Returns:
        list of dict，每項含 title, summary, date, source, url
    """
    import feedparser
    from html import unescape
    from urllib.parse import quote
    import re

    keyword = f"{stock_name} {stock_code}" if stock_name else stock_code
    if lang == "en":
        locale_params = "hl=en&gl=US&ceid=US:en"
    else:
        locale_params = "hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    url = (
        f"https://news.google.com/rss/search?"
        f"q={quote(keyword)}&{locale_params}"
    )

    feed = feedparser.parse(url)
    results = []
    for entry in feed.entries[:20]:  # 最多 20 則
        # summary 是 HTML，需清理
        raw_summary = entry.get("summary", "")
        clean_summary = re.sub(r"<[^>]+>", "", unescape(raw_summary)).strip()

        source_obj = entry.get("source", {})
        source_name = source_obj.get("title", "Unknown") if isinstance(source_obj, dict) else str(source_obj)

        results.append({
            "title": entry.get("title", ""),
            "summary": clean_summary,
            "date": entry.get("published", ""),
            "source": source_name,
            "url": entry.get("link", ""),
        })
    return results


def populate_ticker_cache(stock_dict: dict[str, dict]) -> None:
    """從股票清單預填 ticker 快取，避免逐一 resolve

    Args:
        stock_dict: {code: {"name": ..., "market": "上市"|"上櫃"}}
    """
    for code, info in stock_dict.items():
        if code in _ticker_cache:
            continue
        if isinstance(info, dict):
            market = info.get("market", "")
            suffix = ".TWO" if market == "上櫃" else ".TW"
        else:
            suffix = ".TW"
        _ticker_cache[code] = f"{code}{suffix}"


def get_stock_fundamentals_safe(stock_code: str) -> dict | None:
    """取得股票基本面數據（安全版本）

    批次掃描用，失敗時回傳 None 而非拋出例外。
    """
    try:
        return get_stock_fundamentals(stock_code)
    except Exception:
        return None


def validate_stock_code(stock_code: str) -> bool:
    """驗證台股代碼是否有效"""
    try:
        df = get_stock_data(stock_code, period_days=7)
        return not df.empty
    except Exception:
        return False

"""台股資料抓取模組 - 使用 yfinance（主），FinMind（備援）

支援上市 (.TW) 與上櫃 (.TWO) 股票，自動判斷。
yfinance 失敗時自動切換 FinMind API 作為備援數據源。
"""

import json as _json_mod
from pathlib import Path

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)

_TICKER_CACHE_FILE = Path(__file__).parent.parent / ".cache" / "ticker_cache.json"


def _resolve_ticker(stock_code: str) -> str:
    """自動判斷股票是上市 (.TW) 或上櫃 (.TWO)

    先嘗試 .TW，若無資料再嘗試 .TWO
    """
    for suffix in [".TW", ".TWO"]:
        ticker = f"{stock_code}{suffix}"
        try:
            df = yf.download(
                ticker,
                period="2d",
                auto_adjust=True,
                progress=False,
            )
            if not df.empty:
                return ticker
        except Exception:
            continue
    return f"{stock_code}.TW"  # fallback


# 快取已解析過的 ticker，避免重複查詢（含磁碟持久化）
_ticker_cache: dict[str, str] = {}


def _load_ticker_cache():
    """從磁碟載入 ticker 快取"""
    global _ticker_cache
    try:
        if _TICKER_CACHE_FILE.exists():
            _ticker_cache = _json_mod.loads(_TICKER_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        _ticker_cache = {}


def _save_ticker_cache():
    """將 ticker 快取寫入磁碟"""
    try:
        _TICKER_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TICKER_CACHE_FILE.write_text(
            _json_mod.dumps(_ticker_cache, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


# 啟動時載入
_load_ticker_cache()


def get_ticker(stock_code: str) -> str:
    """取得 yfinance ticker 字串（含快取 + 磁碟持久化）"""
    if stock_code not in _ticker_cache:
        _ticker_cache[stock_code] = _resolve_ticker(stock_code)
        _save_ticker_cache()
    return _ticker_cache[stock_code]


def _fetch_from_finmind(stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """從 FinMind API 取得台股歷史資料（備援數據源）

    FinMind 回傳未調整股價（不含除權息調整），作為 yfinance 失敗時的備援。

    Args:
        stock_code: 台股代碼（純數字）
        start_date: 開始日期 YYYY-MM-DD
        end_date: 結束日期 YYYY-MM-DD

    Returns:
        DataFrame with columns: open, high, low, close, volume
    """
    import urllib.request
    import json as _json
    from urllib.parse import urlencode

    params = urlencode({
        "dataset": "TaiwanStockPrice",
        "data_id": stock_code,
        "start_date": start_date,
        "end_date": end_date,
    })
    url = f"https://api.finmindtrade.com/api/v4/data?{params}"

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=15)
    data = _json.loads(resp.read().decode("utf-8"))

    if data.get("status") != 200 or not data.get("data"):
        raise ValueError(f"FinMind: no data for {stock_code}")

    df = pd.DataFrame(data["data"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df = df.rename(columns={
        "max": "high",
        "min": "low",
        "Trading_Volume": "volume",
    })
    df = df[["open", "high", "low", "close", "volume"]].copy()
    df.index.name = "date"

    # 確保數值型別
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def get_stock_data(
    stock_code: str,
    period_days: int = 365,
    end_date: datetime | None = None,
) -> pd.DataFrame:
    """抓取台股歷史資料

    優先從 Redis 快取讀取，再嘗試 yfinance（調整後股價），
    yfinance 失敗時自動切換 FinMind API（未調整股價）作為備援。

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

    if end_date is None:
        end_date = datetime.now()
    start_date = end_date - timedelta(days=period_days)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    # 主要數據源：yfinance（調整後股價）
    df = None
    try:
        ticker = get_ticker(stock_code)
        df = yf.download(
            ticker,
            start=start_str,
            end=end_str,
            auto_adjust=True,
            progress=False,
        )
        if df.empty:
            df = None
    except Exception as e:
        _logger.warning("yfinance failed for %s: %s", stock_code, e)
        df = None

    # 備援數據源：FinMind API（未調整股價）
    if df is None:
        try:
            _logger.info("Falling back to FinMind for %s", stock_code)
            df = _fetch_from_finmind(stock_code, start_str, end_str)
            if df.empty:
                df = None
        except Exception as e:
            _logger.warning("FinMind also failed for %s: %s", stock_code, e)
            df = None

    if df is None or df.empty:
        raise ValueError(
            f"無法取得 {stock_code} 的資料（yfinance 與 FinMind 皆失敗），"
            f"請確認股票代碼是否正確"
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

    # 寫入 Redis 快取（市場感知 TTL）
    set_cached_stock_data(stock_code, period_days, df)

    return df


def get_taiex_data(period_days: int = 365) -> pd.DataFrame:
    """取得台灣加權指數 (TAIEX) 歷史資料

    Args:
        period_days: 抓取天數

    Returns:
        DataFrame with columns: open, high, low, close, volume
    """
    from data.cache import get_cached_stock_data, set_cached_stock_data

    cached = get_cached_stock_data("^TWII", period_days)
    if cached is not None:
        return cached

    end_date = datetime.now()
    start_date = end_date - timedelta(days=period_days)

    df = yf.download(
        "^TWII",
        start=start_date.strftime("%Y-%m-%d"),
        end=end_date.strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=False,
    )

    if df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })
    df = df[["open", "high", "low", "close", "volume"]].copy()
    df.index.name = "date"

    set_cached_stock_data("^TWII", period_days, df)
    return df


def get_dividend_data(stock_code: str) -> pd.Series:
    """取得股票歷史除權息資料

    Args:
        stock_code: 台股代碼

    Returns:
        pd.Series，index 為除息日、值為每股股利（TWD）
    """
    ticker_str = get_ticker(stock_code)
    ticker = yf.Ticker(ticker_str)
    dividends = ticker.dividends
    if dividends is not None and not dividends.empty:
        # 移除時區資訊（統一為 tz-naive）以利日期比對
        if dividends.index.tz is not None:
            dividends.index = dividends.index.tz_localize(None)
    return dividends if dividends is not None else pd.Series(dtype=float)


def _t86_find_col(fields: list, keywords: list[str]) -> int | None:
    """在 T86 欄位列表中用關鍵字搜尋欄位索引"""
    for i, f in enumerate(fields):
        if all(kw in f for kw in keywords):
            return i
    return None


def get_institutional_data(stock_code: str, days: int = 30) -> pd.DataFrame:
    """取得三大法人買賣超資料（TWSE API），含 Redis 快取

    Args:
        stock_code: 台股代碼
        days: 抓取最近幾天的資料

    Returns:
        DataFrame with columns: date, foreign_net, trust_net, dealer_net, total_net
        買賣超單位：股
    """
    from data.cache import get_cached_institutional_data, set_cached_institutional_data

    # 嘗試 Redis 快取
    cached = get_cached_institutional_data(stock_code)
    if cached is not None and len(cached) >= min(days, 5):
        return cached.tail(days)

    import urllib.request
    import json as _json
    from datetime import datetime, timedelta

    results = []
    _checked = 0
    _date = datetime.now()
    _col_map = None  # 延遲初始化，從第一個成功回應的 fields 建立

    while len(results) < days and _checked < days * 2:
        _date_str = _date.strftime("%Y%m%d")
        _checked += 1
        _date -= timedelta(days=1)

        try:
            url = (f"https://www.twse.com.tw/rwd/zh/fund/T86"
                   f"?date={_date_str}&selectType=ALL&response=json")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            data = _json.loads(resp.read().decode("utf-8"))

            if not data.get("data"):
                continue

            # 用欄位名稱動態定位，避免固定索引
            if _col_map is None:
                fields = data.get("fields", [])
                if fields:
                    _col_map = {
                        "foreign": _t86_find_col(fields, ["外", "買賣超"]),
                        "trust": _t86_find_col(fields, ["投信", "買賣超"]),
                        "dealer": _t86_find_col(fields, ["自營商", "買賣超", "合計"]),
                        "total": _t86_find_col(fields, ["三大法人", "買賣超"]),
                    }
                # 找不到欄位時降級為固定索引
                if not _col_map or None in _col_map.values():
                    _col_map = {"foreign": 4, "trust": 10, "dealer": 11, "total": 18}

            for row in data["data"]:
                if row[0].strip() == stock_code:
                    _parse_int = lambda s: int(s.replace(",", "")) if s.strip() else 0
                    results.append({
                        "date": pd.Timestamp(_date_str),
                        "foreign_net": _parse_int(row[_col_map["foreign"]]),
                        "trust_net": _parse_int(row[_col_map["trust"]]),
                        "dealer_net": _parse_int(row[_col_map["dealer"]]),
                        "total_net": _parse_int(row[_col_map["total"]]),
                    })
                    break
        except Exception:
            continue

        # TWSE rate limit
        import time
        time.sleep(0.3)

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results).sort_values("date").set_index("date")

    # 寫入 Redis 快取（60 分鐘）
    set_cached_institutional_data(stock_code, df, ttl=3600)

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


def get_stock_info_and_fundamentals(stock_code: str) -> tuple[dict, dict]:
    """取得股票基本資訊 + 基本面數據（單次 HTTP 請求）

    合併 get_stock_info() 和 get_stock_fundamentals() 的功能，
    只呼叫一次 yf.Ticker().info，省掉一次完整的 HTTP roundtrip。

    Returns:
        (company_info_dict, fundamentals_dict)
    """
    ticker_str = get_ticker(stock_code)
    ticker = yf.Ticker(ticker_str)
    info = ticker.info

    company_info = {
        "name": info.get("longName", info.get("shortName", stock_code)),
        "sector": info.get("sector", "N/A"),
        "industry": info.get("industry", "N/A"),
        "market_cap": info.get("marketCap", 0),
        "shares_outstanding": info.get("sharesOutstanding", 0),
        "currency": info.get("currency", "TWD"),
    }

    fundamentals = {
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
        # 規模
        "market_cap": info.get("marketCap"),
        # 現價（供 screener 免呼叫 get_stock_data）
        "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
    }

    return company_info, fundamentals


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
        # 規模
        "market_cap": info.get("marketCap"),
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
    _changed = False
    for code, info in stock_dict.items():
        if code in _ticker_cache:
            continue
        if isinstance(info, dict):
            market = info.get("market", "")
            suffix = ".TWO" if market == "上櫃" else ".TW"
        else:
            suffix = ".TW"
        _ticker_cache[code] = f"{code}{suffix}"
        _changed = True
    if _changed:
        _save_ticker_cache()


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

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
        "currency": info.get("currency", "TWD"),
    }


def validate_stock_code(stock_code: str) -> bool:
    """驗證台股代碼是否有效"""
    try:
        df = get_stock_data(stock_code, period_days=7)
        return not df.empty
    except Exception:
        return False

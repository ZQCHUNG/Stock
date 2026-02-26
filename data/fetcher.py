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
    使用 yf.Ticker().history() 而非 yf.download()，確保 thread-safety。
    """
    for suffix in [".TW", ".TWO"]:
        ticker = f"{stock_code}{suffix}"
        try:
            df = yf.Ticker(ticker).history(period="2d", auto_adjust=True)
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

    優先順序（R63 資料整合）：
    1. Redis 快取
    2. TWSE/TPEX 官方 SQLite（前復權調整後）
    3. yfinance（調整後股價，fallback）
    4. FinMind API（未調整股價，最後備援）

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

    df = None

    # --- Primary: TWSE/TPEX 官方 SQLite (R63) ---
    try:
        from data.twse_provider import get_stock_data_from_db, sync_stock
        df = get_stock_data_from_db(
            stock_code, start_str, end_str, adjusted=True,
        )
        if df.empty or len(df) < max(period_days * 0.5, 10):
            # Insufficient data in DB — try syncing from TWSE API
            _logger.info("TWSE DB insufficient for %s (%d rows), syncing...",
                         stock_code, len(df))
            months_needed = max(period_days // 30 + 1, 3)
            sync_stock(stock_code, months_back=months_needed)
            df = get_stock_data_from_db(
                stock_code, start_str, end_str, adjusted=True,
            )
        if not df.empty:
            _logger.debug("Using TWSE data for %s: %d rows", stock_code, len(df))
    except Exception as e:
        _logger.warning("TWSE provider failed for %s: %s", stock_code, e)
        df = None

    if df is not None and not df.empty:
        # TWSE data available — cache and return
        set_cached_stock_data(stock_code, period_days, df)
        return df

    # --- Fallback 1: yfinance（調整後股價）---
    # 使用 yf.Ticker().history() 而非 yf.download()，確保 thread-safety
    try:
        ticker = get_ticker(stock_code)
        df = yf.Ticker(ticker).history(
            start=start_str,
            end=end_str,
            auto_adjust=True,
        )
        if df.empty:
            df = None
        else:
            _logger.info("Using yfinance fallback for %s", stock_code)
    except Exception as e:
        _logger.warning("yfinance failed for %s: %s", stock_code, e)
        df = None

    # --- Fallback 2: FinMind API（未調整股價）---
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
            f"無法取得 {stock_code} 的資料（TWSE、yfinance、FinMind 皆失敗），"
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

    優先順序（R63）：
    1. Redis 快取
    2. TWSE MI_5MINS_HIST（官方加權指數）
    3. yfinance ^TWII（fallback）

    Args:
        period_days: 抓取天數

    Returns:
        DataFrame with columns: open, high, low, close, volume
    """
    from data.cache import get_cached_stock_data, set_cached_stock_data

    cached = get_cached_stock_data("^TWII", period_days)
    if cached is not None:
        return cached

    df = None

    # --- Primary: TWSE 官方加權指數 ---
    try:
        from data.twse_provider import get_taiex_from_db, sync_taiex
        df = get_taiex_from_db(period_days=period_days)
        if df.empty or len(df) < max(period_days * 0.5, 10):
            _logger.info("TAIEX DB insufficient (%d rows), syncing...", len(df))
            months_needed = max(period_days // 30 + 1, 3)
            sync_taiex(months_back=months_needed)
            df = get_taiex_from_db(period_days=period_days)
        if not df.empty:
            _logger.debug("Using TWSE TAIEX data: %d rows", len(df))
    except Exception as e:
        _logger.warning("TWSE TAIEX failed: %s", e)
        df = None

    if df is not None and not df.empty:
        set_cached_stock_data("^TWII", period_days, df)
        return df

    # --- Fallback: yfinance ^TWII ---
    end_date = datetime.now()
    start_date = end_date - timedelta(days=period_days)

    try:
        df = yf.Ticker("^TWII").history(
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            auto_adjust=True,
        )
    except Exception as e:
        _logger.warning("yfinance ^TWII failed: %s", e)
        return pd.DataFrame()

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

    R63: 優先從 TWSE SQLite 讀取，fallback yfinance。

    Args:
        stock_code: 台股代碼

    Returns:
        pd.Series，index 為除息日、值為每股股利（TWD）
    """
    # Primary: TWSE SQLite (R63)
    try:
        from data.twse_provider import _get_conn
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT ex_date, cash_dividend FROM corporate_actions "
                "WHERE ticker=? AND cash_dividend>0 ORDER BY ex_date",
                (stock_code,),
            ).fetchall()
        if rows:
            dates = pd.to_datetime([r[0] for r in rows])
            values = [r[1] for r in rows]
            return pd.Series(values, index=dates, name="Dividends")
    except Exception:
        pass

    # Fallback: yfinance
    ticker_str = get_ticker(stock_code)
    ticker = yf.Ticker(ticker_str)
    dividends = ticker.dividends
    if dividends is not None and not dividends.empty:
        # 移除時區資訊（統一為 tz-naive）以利日期比對
        if dividends.index.tz is not None:
            dividends.index = dividends.index.tz_localize(None)
    return dividends if dividends is not None else pd.Series(dtype=float)


def get_splits_data(stock_code: str) -> pd.Series:
    """取得股票歷史分割（拆股/合股）資料

    Args:
        stock_code: 台股代碼

    Returns:
        pd.Series，index 為分割日、值為分割比率（e.g. 5.0 表示 1 拆 5）
    """
    ticker_str = get_ticker(stock_code)
    ticker = yf.Ticker(ticker_str)
    splits = ticker.splits
    if splits is not None and not splits.empty:
        if splits.index.tz is not None:
            splits.index = splits.index.tz_localize(None)
        return splits
    return pd.Series(dtype=float)


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
        # T86 沒有資料（可能是 OTC 股票）
        # R63: 優先嘗試 TPEX 官方 API，再 fallback FinMind
        try:
            from data.twse_provider import fetch_tpex_institutional
            _tpex_date = datetime.now()
            for _tpex_i in range(days * 2):
                _tpex_str = _tpex_date.strftime("%Y-%m-%d")
                _tpex_date -= timedelta(days=1)
                inst = fetch_tpex_institutional(stock_code, _tpex_str)
                if inst:
                    results.append({
                        "date": pd.Timestamp(_tpex_str),
                        **inst,
                    })
                    if len(results) >= days:
                        break
        except Exception as e:
            _logger.warning("TPEX institutional failed for %s: %s", stock_code, e)

        if not results:
            # Final fallback: FinMind
            df = _fetch_institutional_from_finmind(stock_code, days)
            if not df.empty:
                set_cached_institutional_data(stock_code, df, ttl=3600)
            return df

    df = pd.DataFrame(results).sort_values("date").set_index("date")

    # 寫入 Redis 快取（60 分鐘）
    set_cached_institutional_data(stock_code, df, ttl=3600)

    return df


def _fetch_institutional_from_finmind(stock_code: str, days: int = 20) -> pd.DataFrame:
    """FinMind 備援：取得三大法人買賣超（涵蓋 OTC/上櫃股票）

    FinMind 的 TaiwanStockInstitutionalInvestorsBuySell 同時涵蓋
    上市（TWSE）和上櫃（TPEX）股票，作為 T86 API 的備援。

    Returns:
        DataFrame with columns: foreign_net, trust_net, dealer_net, total_net
        Index: date (DatetimeIndex)
    """
    import requests

    start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params={
                "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
                "data_id": stock_code,
                "start_date": start,
            },
            timeout=15,
        )
        raw = resp.json().get("data", [])
    except Exception:
        return pd.DataFrame()

    if not raw:
        return pd.DataFrame()

    # FinMind 格式：每日多筆（每個法人類型一筆），需 pivot
    # name: Foreign_Investor, Investment_Trust, Dealer_self, Dealer_Hedging, Foreign_Dealer_Self
    rows_by_date: dict[str, dict] = {}
    for r in raw:
        d = r["date"]
        if d not in rows_by_date:
            rows_by_date[d] = {"foreign_net": 0, "trust_net": 0, "dealer_net": 0, "total_net": 0}

        net = (r.get("buy", 0) or 0) - (r.get("sell", 0) or 0)
        name = r.get("name", "")

        if name in ("Foreign_Investor", "Foreign_Dealer_Self"):
            rows_by_date[d]["foreign_net"] += net
        elif name == "Investment_Trust":
            rows_by_date[d]["trust_net"] += net
        elif name in ("Dealer_self", "Dealer_Hedging"):
            rows_by_date[d]["dealer_net"] += net

    for d in rows_by_date:
        rows_by_date[d]["total_net"] = (
            rows_by_date[d]["foreign_net"]
            + rows_by_date[d]["trust_net"]
            + rows_by_date[d]["dealer_net"]
        )

    if not rows_by_date:
        return pd.DataFrame()

    df = pd.DataFrame.from_dict(rows_by_date, orient="index")
    df.index = pd.to_datetime(df.index)
    df.index.name = "date"
    df = df.sort_index().tail(days)
    return df


# ===== Financial Statements Cache (TTL=4hr, 財報不常更新) =====
import time as _time_mod
_financial_cache: dict[str, tuple[float, dict]] = {}  # code → (expiry_ts, result)
_FINANCIAL_CACHE_TTL = 4 * 3600  # 4 hours


def get_financial_statements(stock_code: str, start_date: str = "") -> dict:
    """取得財務報表資料（FinMind API）— 資產負債表 + 現金流量表

    主要用於生技股 Cash Runway 計算。內建 4 小時 in-memory 快取。

    Args:
        stock_code: 台股代碼（純數字，例如 "6748"）
        start_date: 起始日期（YYYY-MM-DD），預設最近 3 年

    Returns:
        dict: {
            "balance_sheet": [{date, type, value}, ...],
            "cash_flows": [{date, type, value}, ...],
            "cash_runway": {
                "cash": float,  # 最新現金及約當現金
                "quarterly_burn": float,  # 季度營業現金流出（正數=燒錢）
                "runway_quarters": float,  # 現金可撐季數
                "runway_label": str,  # "極高風險" / "高風險" / "安全"
                "latest_date": str,  # 最新報表日期
                "total_quarterly_burn": float,  # 含投資活動的總燒錢
                "total_runway_quarters": float,  # 含投資活動的總跑道
            } | None,
        }
    """
    import requests

    # 快取檢查（4 小時 TTL）
    cache_key = stock_code
    cached = _financial_cache.get(cache_key)
    if cached is not None:
        expiry, data = cached
        if _time_mod.time() < expiry:
            return data
        else:
            del _financial_cache[cache_key]

    if not start_date:
        start_date = (datetime.now() - timedelta(days=365 * 3)).strftime("%Y-%m-%d")

    base_url = "https://api.finmindtrade.com/api/v4/data"
    result = {"balance_sheet": [], "cash_flows": [], "cash_runway": None}

    # --- 1. 資產負債表 ---
    try:
        resp = requests.get(base_url, params={
            "dataset": "TaiwanStockBalanceSheet",
            "data_id": stock_code,
            "start_date": start_date,
        }, timeout=15)
        bs_data = resp.json().get("data", [])
        result["balance_sheet"] = bs_data
    except Exception as e:
        _logger.warning("FinMind balance sheet failed for %s: %s", stock_code, e)
        bs_data = []

    # --- 2. 現金流量表 ---
    try:
        resp = requests.get(base_url, params={
            "dataset": "TaiwanStockCashFlowsStatement",
            "data_id": stock_code,
            "start_date": start_date,
        }, timeout=15)
        cf_data = resp.json().get("data", [])
        result["cash_flows"] = cf_data
    except Exception as e:
        _logger.warning("FinMind cash flows failed for %s: %s", stock_code, e)
        cf_data = []

    # --- 3. 計算 Cash Runway ---
    result["cash_runway"] = _calculate_cash_runway(bs_data, cf_data)

    # 快取存入（4 小時 TTL）
    _financial_cache[cache_key] = (_time_mod.time() + _FINANCIAL_CACHE_TTL, result)
    # 限制快取大小（最多 50 支股票）
    if len(_financial_cache) > 50:
        oldest_key = min(_financial_cache, key=lambda k: _financial_cache[k][0])
        del _financial_cache[oldest_key]

    return result


def _calculate_cash_runway(bs_data: list, cf_data: list) -> dict | None:
    """從 FinMind 原始資料計算 Cash Runway

    使用報表日期區間（BeginningOfPeriod → EndOfPeriod）天數來標準化
    季度消耗率，避免硬編碼半年報/年報邏輯。

    Quarterly_Burn = Total_Flow / Days_In_Period * 90
    """
    if not bs_data or not cf_data:
        return None

    # 取得最新現金
    cash_items = [r for r in bs_data if r["type"] == "CashAndCashEquivalents"]
    if not cash_items:
        return None
    cash_items.sort(key=lambda r: r["date"])
    latest_cash = cash_items[-1]["value"]
    latest_date = cash_items[-1]["date"]

    # 短期投資（可能沒有）
    short_term = [r for r in bs_data
                  if r["type"] in ("CurrentFinancialAssetsAtFairvalueThroughProfitOrLoss",
                                   "ShortTermInvestments")
                  and r["date"] == latest_date]
    short_term_val = sum(r["value"] for r in short_term)

    total_liquid = latest_cash + short_term_val

    # 取得營業現金流（各期）
    op_cf_items = [r for r in cf_data
                   if r["type"] in ("CashFlowsFromOperatingActivities",
                                    "NetCashInflowFromOperatingActivities")]
    if not op_cf_items:
        return None

    # 按日期分組，取每個日期的營業現金流
    op_cf_by_date: dict[str, float] = {}
    for r in op_cf_items:
        d = r["date"]
        if d not in op_cf_by_date or r["type"] == "CashFlowsFromOperatingActivities":
            op_cf_by_date[d] = r["value"]

    dates = sorted(op_cf_by_date.keys())
    if not dates:
        return None

    latest_cf_date = dates[-1]
    latest_cf = op_cf_by_date[latest_cf_date]

    # 用報表起迄日期計算覆蓋天數，再標準化為季度（90 天）
    days_in_period = _get_report_period_days(cf_data, latest_cf_date)

    if latest_cf < 0 and days_in_period > 0:
        quarterly_burn = abs(latest_cf) / days_in_period * 90
    else:
        quarterly_burn = 0.0

    if quarterly_burn > 0:
        runway_q = total_liquid / quarterly_burn
    else:
        runway_q = 99  # 營業現金流為正，無需擔心

    # 總現金消耗（含投資活動）
    cf_end_items = [r for r in cf_data
                    if r["type"] == "CashBalancesEndOfPeriod"
                    and r["date"] == latest_cf_date]
    cf_begin_items = [r for r in cf_data
                      if r["type"] == "CashBalancesBeginningOfPeriod"
                      and r["date"] == latest_cf_date]

    total_quarterly_burn = 0.0
    total_runway_q = 99.0
    if cf_end_items and cf_begin_items:
        total_change = cf_end_items[0]["value"] - cf_begin_items[0]["value"]
        if total_change < 0 and days_in_period > 0:
            total_quarterly_burn = abs(total_change) / days_in_period * 90
            total_runway_q = total_liquid / total_quarterly_burn

    # 風險標籤
    effective_runway = min(runway_q, total_runway_q)
    if effective_runway < 4:
        label = "極高風險"
    elif effective_runway < 8:
        label = "高風險"
    else:
        label = "安全"

    return {
        "cash": float(total_liquid),
        "quarterly_burn": float(quarterly_burn),
        "runway_quarters": round(float(runway_q), 1),
        "runway_label": label,
        "latest_date": latest_date,
        "total_quarterly_burn": round(float(total_quarterly_burn), 1),
        "total_runway_quarters": round(float(total_runway_q), 1),
    }


def _get_report_period_days(cf_data: list, report_date: str) -> int:
    """從現金流量表的起迄餘額日期推算報表涵蓋天數

    優先使用 CashBalancesBeginningOfPeriod 日期推算。
    Fallback: 根據報表日期月份判斷（06-30→182天, 12-31→365天, 其他→90天）
    """
    from datetime import datetime as _dt

    # 嘗試從 Beginning/End 推算
    begin_items = [r for r in cf_data
                   if r["type"] == "CashBalancesBeginningOfPeriod"
                   and r["date"] == report_date]

    if begin_items:
        # FinMind 的 BeginningOfPeriod.date = 報表截止日，
        # 但 BeginningOfPeriod.value 對應的是期初日期的餘額。
        # 我們需要比對前一期的 EndOfPeriod 來推算期間天數。
        # 更可靠的方法：用報表日期的月份推算
        pass

    # Fallback: 用報表截止日期的月份推算覆蓋天數
    try:
        dt = _dt.strptime(report_date, "%Y-%m-%d")
        month = dt.month
        if month <= 3:
            return 90   # Q1 (1/1 - 3/31)
        elif month <= 6:
            return 182  # H1 (1/1 - 6/30)
        elif month <= 9:
            return 273  # Q1-Q3 (1/1 - 9/30)
        else:
            return 365  # Full year (1/1 - 12/31)
    except ValueError:
        return 182  # Safe default: half-year


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
        # 股利 (clamp: yfinance dividendYield sometimes returns absurd values)
        "dividend_yield": min(info.get("dividendYield") or 0, 0.15),
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
        # 股利 (clamp: yfinance dividendYield sometimes returns absurd values)
        "dividend_yield": min(info.get("dividendYield") or 0, 0.15),
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

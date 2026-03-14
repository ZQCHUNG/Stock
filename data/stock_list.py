"""台股完整股票清單模組

資料來源（優先順序）：
1. TWSE/TPEX 公開 API（線上，最即時）
2. twstock 內建清單（離線，約 2000+ 隻）
3. 內建熱門股清單（最小備援）
"""

import requests
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
import logging
logger = logging.getLogger(__name__)


# 快取檔案路徑（存在專案根目錄下）
CACHE_DIR = Path(__file__).parent.parent / ".cache"
CACHE_FILE = CACHE_DIR / "stock_list.json"
CACHE_TTL_HOURS = 24  # 快取 24 小時


def _fetch_twse_stocks() -> dict[str, dict]:
    """從 TWSE 抓取上市股票清單"""
    stocks = {}
    try:
        r = requests.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
            timeout=10,
        )
        r.raise_for_status()
        for item in r.json():
            code = item.get("Code", "")
            name = item.get("Name", "")
            if code and name:
                stocks[code] = {"name": name, "market": "上市"}
    except Exception as e:
        logger.debug(f"Optional data load failed: {e}")
    return stocks


def _fetch_tpex_stocks() -> dict[str, dict]:
    """從 TPEX 抓取上櫃股票清單"""
    stocks = {}
    try:
        r = requests.get(
            "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
            timeout=10,
        )
        r.raise_for_status()
        for item in r.json():
            code = item.get("SecuritiesCompanyCode", "")
            name = item.get("CompanyName", "")
            if code and name:
                stocks[code] = {"name": name, "market": "上櫃"}
    except Exception as e:
        logger.debug(f"Optional data load failed: {e}")
    return stocks


def _fetch_twstock_codes() -> dict[str, dict]:
    """從 twstock 套件取得離線股票清單"""
    stocks = {}
    try:
        import twstock
        for code, info in twstock.codes.items():
            # 只要股票、ETF、ETN、特別股（排除權證）
            if hasattr(info, "type") and "權證" not in info.type:
                # 只要 4 碼數字或 4 碼+英文（如 ETF）
                if len(code) <= 6:
                    market = "上市" if "上市" in str(getattr(info, "market", "")) else "上櫃"
                    stocks[code] = {
                        "name": getattr(info, "name", code),
                        "market": market,
                    }
    except Exception as e:
        logger.debug(f"Optional operation failed: {e}")
    return stocks


# 內建最小備援清單
_BUILTIN_STOCKS = {
    "2330": {"name": "台積電", "market": "上市"},
    "2317": {"name": "鴻海", "market": "上市"},
    "2454": {"name": "聯發科", "market": "上市"},
    "2881": {"name": "富邦金", "market": "上市"},
    "2882": {"name": "國泰金", "market": "上市"},
    "2891": {"name": "中信金", "market": "上市"},
    "2303": {"name": "聯電", "market": "上市"},
    "2412": {"name": "中華電", "market": "上市"},
    "3711": {"name": "日月光投控", "market": "上市"},
    "2308": {"name": "台達電", "market": "上市"},
    "1301": {"name": "台塑", "market": "上市"},
    "2886": {"name": "兆豐金", "market": "上市"},
    "2884": {"name": "玉山金", "market": "上市"},
    "2603": {"name": "長榮", "market": "上市"},
    "3008": {"name": "大立光", "market": "上市"},
    "2357": {"name": "華碩", "market": "上市"},
    "2382": {"name": "廣達", "market": "上市"},
    "2395": {"name": "研華", "market": "上市"},
    "3034": {"name": "聯詠", "market": "上市"},
    "6505": {"name": "台塑化", "market": "上市"},
    "0050": {"name": "元大台灣50", "market": "上市"},
    "0056": {"name": "元大高股息", "market": "上市"},
    "00878": {"name": "國泰永續高股息", "market": "上市"},
    "00919": {"name": "群益台灣精選高息", "market": "上市"},
    "6748": {"name": "亞果生醫", "market": "上櫃"},
    "6547": {"name": "高端疫苗", "market": "上櫃"},
    "3293": {"name": "鉅祥", "market": "上櫃"},
    "5876": {"name": "上海商銀", "market": "上市"},
    "2345": {"name": "智邦", "market": "上市"},
    "3037": {"name": "欣興", "market": "上市"},
    # twstock 可能缺少的較新上櫃股
    "6618": {"name": "永虹", "market": "上櫃"},
    "6869": {"name": "雲豹能源", "market": "上櫃"},
    "6863": {"name": "永道-KY", "market": "上櫃"},
    "6903": {"name": "亞信電子", "market": "上櫃"},
    "6957": {"name": "東碩資訊", "market": "上櫃"},
    "6873": {"name": "泓德能源", "market": "上櫃"},
    "6916": {"name": "博晟生醫", "market": "上櫃"},
    "4966": {"name": "譜瑞-KY", "market": "上櫃"},
    "5347": {"name": "世界", "market": "上櫃"},
    "6488": {"name": "環球晶", "market": "上櫃"},
    "6533": {"name": "晶心科", "market": "上櫃"},
    "6472": {"name": "閎康", "market": "上櫃"},
    "3105": {"name": "穩懋", "market": "上櫃"},
    "5269": {"name": "祥碩", "market": "上櫃"},
    "6409": {"name": "旭隼", "market": "上櫃"},
    "8069": {"name": "元太", "market": "上櫃"},
    "3529": {"name": "力旺", "market": "上櫃"},
    "6510": {"name": "精測", "market": "上櫃"},
}


def _load_cache() -> dict[str, dict] | None:
    """嘗試從快取讀取"""
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            cached_time = datetime.fromisoformat(data.get("timestamp", "2000-01-01"))
            if datetime.now() - cached_time < timedelta(hours=CACHE_TTL_HOURS):
                return data.get("stocks", {})
    except Exception as e:
        logger.debug(f"Optional cache operation failed: {e}")
    return None


def _save_cache(stocks: dict[str, dict]) -> None:
    """儲存快取"""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "timestamp": datetime.now().isoformat(),
            "count": len(stocks),
            "stocks": stocks,
        }
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug(f"Optional cache operation failed: {e}")


def get_all_stocks(force_refresh: bool = False) -> dict[str, dict]:
    """取得完整台股清單

    Returns:
        dict: {stock_code: {"name": str, "market": "上市"|"上櫃"}}
    """
    # 1. 嘗試讀取快取（本地檔案優先，避免 Redis 連線延遲）
    if not force_refresh:
        cached = _load_cache()
        if cached and len(cached) > 100:
            return cached

        # 本地快取 miss 才嘗試 Redis
        try:
            from data.cache import get_cached_stock_list
            redis_cached = get_cached_stock_list()
            if redis_cached and len(redis_cached) > 100:
                _save_cache(redis_cached)  # 回填本地（下次更快）
                return redis_cached
        except Exception as e:
            logger.debug(f"Optional cache operation failed: {e}")

    # 2. 線上 API
    stocks = {}
    twse = _fetch_twse_stocks()
    tpex = _fetch_tpex_stocks()
    stocks.update(twse)
    stocks.update(tpex)

    # 3. twstock 補充
    twstock_codes = _fetch_twstock_codes()
    for code, info in twstock_codes.items():
        if code not in stocks:
            stocks[code] = info

    # 4. 內建備援
    for code, info in _BUILTIN_STOCKS.items():
        if code not in stocks:
            stocks[code] = info

    # 儲存快取（本地檔案 + Redis）
    if len(stocks) > 100:
        _save_cache(stocks)
        try:
            from data.cache import set_cached_stock_list
            set_cached_stock_list(stocks)
        except Exception as e:
            logger.debug(f"Optional cache operation failed: {e}")

    # 至少回傳內建清單
    if not stocks:
        return dict(_BUILTIN_STOCKS)

    return stocks


def search_stocks(query: str, all_stocks: dict[str, dict] | None = None) -> list[tuple[str, str, str]]:
    """搜尋股票（支援代碼或名稱模糊搜尋）

    Args:
        query: 搜尋關鍵字
        all_stocks: 完整股票清單（若為 None 會自動載入）

    Returns:
        list of (code, name, market) 排序後的搜尋結果
    """
    if all_stocks is None:
        all_stocks = get_all_stocks()

    query = query.strip().lower()
    if not query:
        return []

    results = []
    for code, info in all_stocks.items():
        name = info.get("name", "")
        market = info.get("market", "")
        # 代碼完全匹配優先
        if code.lower() == query:
            results.insert(0, (code, name, market))
        # 代碼前綴匹配
        elif code.lower().startswith(query):
            results.append((code, name, market))
        # 名稱包含匹配
        elif query in name.lower():
            results.append((code, name, market))

    return results[:50]  # 最多回傳 50 筆


def _lookup_stock_name_online(code: str) -> tuple[str, str] | None:
    """從 TWSE/TPEX 或 yfinance 查詢單一股票名稱

    Returns:
        (name, market) 或 None
    """
    # 嘗試 TWSE 查詢
    try:
        r = requests.get(
            f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{code}.tw",
            timeout=5,
        )
        data = r.json()
        if data.get("msgArray"):
            name = data["msgArray"][0].get("n", "")
            if name:
                return (name, "上市")
    except Exception as e:
        logger.debug(f"Optional data load failed: {e}")

    # 嘗試 TPEX 查詢
    try:
        r = requests.get(
            f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=otc_{code}.tw",
            timeout=5,
        )
        data = r.json()
        if data.get("msgArray"):
            name = data["msgArray"][0].get("n", "")
            if name:
                return (name, "上櫃")
    except Exception as e:
        logger.debug(f"Optional data load failed: {e}")

    # fallback: yfinance（可能只有英文名）
    try:
        from data.fetcher import get_ticker
        import yfinance as yf

        ticker_str = get_ticker(code)
        ticker = yf.Ticker(ticker_str)
        yf_info = ticker.info
        name = yf_info.get("longName", yf_info.get("shortName", ""))
        if name:
            market = "上櫃" if ".TWO" in ticker_str else "上市"
            return (name, market)
    except Exception as e:
        logger.debug(f"Optional data fetch failed: {e}")

    return None


def get_stock_name(code: str, all_stocks: dict[str, dict] | None = None) -> str:
    """取得股票名稱，若不在清單中會嘗試線上查詢並自動補進快取"""
    if all_stocks is None:
        all_stocks = get_all_stocks()
    info = all_stocks.get(code, {})
    if info:
        return info.get("name", code)

    # 不在清單中，線上查詢
    result = _lookup_stock_name_online(code)
    if result:
        name, market = result
        all_stocks[code] = {"name": name, "market": market}
        _save_cache(all_stocks)
        return name

    return code

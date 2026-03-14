"""股票資料路由"""

import logging
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/list")
def stock_list():
    """取得完整台股清單"""
    from data.stock_list import get_all_stocks
    stocks = get_all_stocks()
    # 回傳 [{code, name, market}] 格式
    return [
        {"code": code, "name": info["name"], "market": info.get("market", "")}
        for code, info in stocks.items()
    ]


@router.get("/search")
def stock_search(q: str = Query(..., min_length=1)):
    """搜尋股票（代碼或名稱）"""
    from data.stock_list import search_stocks
    results = search_stocks(q)
    return [{"code": r[0], "name": r[1], "market": r[2]} for r in results]


@router.get("/{code}/data")
def stock_data(code: str, period_days: int = Query(365, ge=7, le=3650)):
    """取得股價歷史資料"""
    from data.fetcher import get_stock_data
    from backend.dependencies import df_to_response
    try:
        df = get_stock_data(code, period_days=period_days)
        return df_to_response(df)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{code}/info")
def stock_info(code: str):
    """取得股票基本資訊"""
    from data.fetcher import get_stock_info
    try:
        return get_stock_info(code)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{code}/name")
def stock_name(code: str):
    """取得股票名稱"""
    from data.stock_list import get_stock_name
    name = get_stock_name(code)
    return {"code": code, "name": name}


@router.get("/{code}/fundamentals")
def stock_fundamentals(code: str):
    """取得基本面數據"""
    from data.fetcher import get_stock_fundamentals
    from backend.dependencies import make_serializable
    try:
        data = get_stock_fundamentals(code)
        return make_serializable(data)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{code}/news")
def stock_news(code: str):
    """取得 Google News"""
    from data.fetcher import get_google_news
    from data.stock_list import get_stock_name
    name = get_stock_name(code)
    return get_google_news(code, name)


@router.get("/{code}/institutional")
def stock_institutional(code: str, days: int = Query(20, ge=1, le=60)):
    """取得三大法人買賣超"""
    from data.fetcher import get_institutional_data
    from backend.dependencies import df_to_response
    try:
        df = get_institutional_data(code, days=days)
        return df_to_response(df)
    except Exception as e:
        logger.debug(f"Institutional data fetch failed for {code}: {e}")
        return {"dates": [], "columns": {}}


@router.get("/{code}/dividends")
def stock_dividends(code: str):
    """取得除權息資料"""
    from data.fetcher import get_dividend_data
    from backend.dependencies import series_to_response
    try:
        s = get_dividend_data(code)
        return series_to_response(s)
    except Exception as e:
        logger.debug(f"Dividend data fetch failed for {code}: {e}")
        return {"dates": [], "values": []}


@router.get("/taiex/data")
def taiex_data(period_days: int = Query(365, ge=7, le=3650)):
    """取得台灣加權指數"""
    from data.fetcher import get_taiex_data
    from backend.dependencies import df_to_response
    try:
        df = get_taiex_data(period_days=period_days)
        return df_to_response(df)
    except Exception as e:
        logger.debug(f"TAIEX data fetch failed: {e}")
        return {"dates": [], "columns": {}}

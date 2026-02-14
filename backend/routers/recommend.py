"""推薦掃描路由"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ScanRequest(BaseModel):
    stock_codes: list[str] | None = None
    params: dict | None = None


@router.post("/scan-v4")
def scan_v4(req: ScanRequest):
    """v4 策略掃描 — 尋找 BUY 訊號"""
    from data.fetcher import get_stock_data
    from data.stock_list import get_stock_name
    from analysis.strategy_v4 import get_v4_analysis
    from data.cache import get_cached_scan_results, set_cached_scan_results
    from config import SCAN_STOCKS
    from backend.dependencies import make_serializable

    # 嘗試快取
    cached = get_cached_scan_results()
    if cached and not req.stock_codes:
        return make_serializable(cached)

    stock_pool = req.stock_codes or list(SCAN_STOCKS.keys())
    results = []

    for code in stock_pool:
        try:
            df = get_stock_data(code, period_days=365)
            analysis = get_v4_analysis(df)
            name = get_stock_name(code)
            latest_price = float(df["close"].iloc[-1])
            price_change = float(df["close"].pct_change().iloc[-1]) if len(df) > 1 else 0

            item = {
                "code": code,
                "name": name,
                "price": latest_price,
                "price_change": price_change,
                "signal": analysis["signal"],
                "entry_type": analysis.get("entry_type", ""),
                "uptrend_days": analysis.get("uptrend_days", 0),
                "dist_ma20": analysis.get("dist_ma20", 0),
                "indicators": analysis.get("indicators", {}),
            }
            results.append(item)
        except Exception:
            continue

    # 只快取預設股票池結果
    if not req.stock_codes:
        set_cached_scan_results(results, ttl=600)

    # 排序：BUY 訊號排前面
    signal_order = {"BUY": 0, "HOLD": 1, "SELL": 2}
    results.sort(key=lambda x: signal_order.get(x["signal"], 1))

    return make_serializable(results)

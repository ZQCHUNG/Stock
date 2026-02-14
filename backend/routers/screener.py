"""條件選股路由"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class ScreenerFilter(BaseModel):
    """選股條件"""
    # 價格
    min_price: float | None = None
    max_price: float | None = None
    # 漲跌幅
    min_change_pct: float | None = None
    max_change_pct: float | None = None
    # 成交量
    min_volume: float | None = None  # 張
    # 技術指標
    min_rsi: float | None = None
    max_rsi: float | None = None
    min_adx: float | None = None
    # 趨勢
    ma20_above_ma60: bool | None = None
    min_uptrend_days: int | None = None
    # v4 訊號
    signal_filter: str | None = None  # "BUY" / "SELL"
    # 基本面
    min_pe: float | None = None
    max_pe: float | None = None
    min_dividend_yield: float | None = None
    min_roe: float | None = None
    # 市場
    market_filter: str | None = None  # "上市" / "上櫃"
    # 股票池
    stock_codes: list[str] | None = None


def _run_screener_logic(filters: ScreenerFilter, progress_callback=None):
    """共用篩選邏輯，支援進度回報"""
    from data.stock_list import get_all_stocks
    from data.fetcher import get_stock_data, get_stock_fundamentals_safe
    from analysis.strategy_v4 import get_v4_analysis
    from backend.dependencies import make_serializable

    all_stocks = get_all_stocks()

    if filters.stock_codes:
        stock_pool = {c: all_stocks.get(c, {"name": c, "market": ""}) for c in filters.stock_codes}
    else:
        stock_pool = all_stocks

    if filters.market_filter:
        stock_pool = {c: v for c, v in stock_pool.items() if v.get("market") == filters.market_filter}

    pool_list = list(stock_pool.items())[:200]
    total = len(pool_list)
    results = []

    for i, (code, info) in enumerate(pool_list):
        if progress_callback:
            progress_callback(i + 1, total, code)
        try:
            df = get_stock_data(code, period_days=120)
            if df.empty or len(df) < 20:
                continue

            latest = df.iloc[-1]
            price = float(latest["close"])
            volume_lots = float(latest["volume"]) / 1000
            change_pct = float(df["close"].pct_change().iloc[-1]) if len(df) > 1 else 0

            if filters.min_price and price < filters.min_price:
                continue
            if filters.max_price and price > filters.max_price:
                continue
            if filters.min_change_pct and change_pct < filters.min_change_pct:
                continue
            if filters.max_change_pct and change_pct > filters.max_change_pct:
                continue
            if filters.min_volume and volume_lots < filters.min_volume:
                continue

            v4 = None
            if any([filters.min_rsi, filters.max_rsi, filters.min_adx,
                     filters.ma20_above_ma60, filters.min_uptrend_days,
                     filters.signal_filter]):
                try:
                    v4 = get_v4_analysis(df)
                    indicators = v4.get("indicators", {})

                    rsi = indicators.get("RSI")
                    if filters.min_rsi and (rsi is None or rsi < filters.min_rsi):
                        continue
                    if filters.max_rsi and (rsi is None or rsi > filters.max_rsi):
                        continue

                    adx = indicators.get("ADX")
                    if filters.min_adx and (adx is None or adx < filters.min_adx):
                        continue

                    if filters.ma20_above_ma60:
                        ma20 = indicators.get("MA20")
                        ma60 = indicators.get("MA60")
                        if ma20 is None or ma60 is None or ma20 <= ma60:
                            continue

                    if filters.min_uptrend_days:
                        ut = v4.get("uptrend_days", 0)
                        if ut < filters.min_uptrend_days:
                            continue

                    if filters.signal_filter and v4["signal"] != filters.signal_filter:
                        continue
                except Exception:
                    continue

            fundamentals = None
            if any([filters.min_pe, filters.max_pe, filters.min_dividend_yield, filters.min_roe]):
                fundamentals = get_stock_fundamentals_safe(code)
                if fundamentals is None:
                    continue

                pe = fundamentals.get("trailing_pe")
                if filters.min_pe and (pe is None or pe < filters.min_pe):
                    continue
                if filters.max_pe and (pe is None or pe > filters.max_pe):
                    continue

                dy = fundamentals.get("dividend_yield")
                if filters.min_dividend_yield and (dy is None or dy < filters.min_dividend_yield):
                    continue

                roe = fundamentals.get("return_on_equity")
                if filters.min_roe and (roe is None or roe < filters.min_roe):
                    continue

            item = {
                "code": code,
                "name": info.get("name", code),
                "market": info.get("market", ""),
                "price": price,
                "change_pct": change_pct,
                "volume_lots": volume_lots,
            }

            if v4:
                item["signal"] = v4["signal"]
                item["entry_type"] = v4.get("entry_type", "")
                item["uptrend_days"] = v4.get("uptrend_days", 0)
                item["indicators"] = v4.get("indicators", {})

            if fundamentals:
                item["pe"] = fundamentals.get("trailing_pe")
                item["dividend_yield"] = fundamentals.get("dividend_yield")
                item["roe"] = fundamentals.get("return_on_equity")

            results.append(item)
        except Exception:
            continue

    return make_serializable(results)


@router.post("/run")
def run_screener(filters: ScreenerFilter):
    """執行條件選股"""
    return _run_screener_logic(filters)


@router.post("/run-stream")
def run_screener_stream(filters: ScreenerFilter):
    """執行條件選股 — SSE 串流進度"""
    from backend.sse import sse_progress, sse_done

    progress_events = []

    def on_progress(current, total, code):
        progress_events.append(sse_progress(current, total, f"篩選 {code}..."))

    def generate():
        # 用 generator 串流：先送進度，最後送結果
        from data.stock_list import get_all_stocks
        from data.fetcher import get_stock_data, get_stock_fundamentals_safe
        from analysis.strategy_v4 import get_v4_analysis
        from backend.dependencies import make_serializable

        all_stocks = get_all_stocks()

        if filters.stock_codes:
            stock_pool = {c: all_stocks.get(c, {"name": c, "market": ""}) for c in filters.stock_codes}
        else:
            stock_pool = all_stocks

        if filters.market_filter:
            stock_pool = {c: v for c, v in stock_pool.items() if v.get("market") == filters.market_filter}

        pool_list = list(stock_pool.items())[:200]
        total = len(pool_list)
        results = []

        for i, (code, info) in enumerate(pool_list):
            yield sse_progress(i + 1, total, f"篩選 {code}...")
            try:
                df = get_stock_data(code, period_days=120)
                if df.empty or len(df) < 20:
                    continue

                latest = df.iloc[-1]
                price = float(latest["close"])
                volume_lots = float(latest["volume"]) / 1000
                change_pct = float(df["close"].pct_change().iloc[-1]) if len(df) > 1 else 0

                if filters.min_price and price < filters.min_price:
                    continue
                if filters.max_price and price > filters.max_price:
                    continue
                if filters.min_volume and volume_lots < filters.min_volume:
                    continue

                v4 = None
                if any([filters.min_rsi, filters.max_rsi, filters.min_adx,
                         filters.ma20_above_ma60, filters.min_uptrend_days,
                         filters.signal_filter]):
                    try:
                        v4 = get_v4_analysis(df)
                        indicators = v4.get("indicators", {})

                        rsi = indicators.get("RSI")
                        if filters.min_rsi and (rsi is None or rsi < filters.min_rsi):
                            continue
                        if filters.max_rsi and (rsi is None or rsi > filters.max_rsi):
                            continue

                        adx = indicators.get("ADX")
                        if filters.min_adx and (adx is None or adx < filters.min_adx):
                            continue

                        if filters.ma20_above_ma60:
                            ma20 = indicators.get("MA20")
                            ma60 = indicators.get("MA60")
                            if ma20 is None or ma60 is None or ma20 <= ma60:
                                continue

                        if filters.min_uptrend_days:
                            ut = v4.get("uptrend_days", 0)
                            if ut < filters.min_uptrend_days:
                                continue

                        if filters.signal_filter and v4["signal"] != filters.signal_filter:
                            continue
                    except Exception:
                        continue

                fundamentals = None
                if any([filters.min_pe, filters.max_pe, filters.min_dividend_yield, filters.min_roe]):
                    fundamentals = get_stock_fundamentals_safe(code)
                    if fundamentals is None:
                        continue

                    pe = fundamentals.get("trailing_pe")
                    if filters.min_pe and (pe is None or pe < filters.min_pe):
                        continue
                    if filters.max_pe and (pe is None or pe > filters.max_pe):
                        continue

                    dy = fundamentals.get("dividend_yield")
                    if filters.min_dividend_yield and (dy is None or dy < filters.min_dividend_yield):
                        continue

                    roe = fundamentals.get("return_on_equity")
                    if filters.min_roe and (roe is None or roe < filters.min_roe):
                        continue

                item = {
                    "code": code,
                    "name": info.get("name", code),
                    "market": info.get("market", ""),
                    "price": price,
                    "change_pct": change_pct,
                    "volume_lots": volume_lots,
                }

                if v4:
                    item["signal"] = v4["signal"]
                    item["entry_type"] = v4.get("entry_type", "")
                    item["uptrend_days"] = v4.get("uptrend_days", 0)
                    item["indicators"] = v4.get("indicators", {})

                if fundamentals:
                    item["pe"] = fundamentals.get("trailing_pe")
                    item["dividend_yield"] = fundamentals.get("dividend_yield")
                    item["roe"] = fundamentals.get("return_on_equity")

                results.append(item)
            except Exception:
                continue

        yield sse_done(make_serializable(results))

    return StreamingResponse(generate(), media_type="text/event-stream")

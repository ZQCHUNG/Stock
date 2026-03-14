"""條件選股路由 — Phase 1: 財報狗級篩選系統"""

import logging
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# Phase 1: Snapshot-based Screening (instant queries)
# ═══════════════════════════════════════════════════════════════════


class ScreenerFilterV2(BaseModel):
    """V2 篩選條件 — supports any column from screening_latest."""
    filters: dict = {}  # {column: {"op": ">=", "value": 30}}
    sort_by: str = "rs_rating"
    sort_desc: bool = True
    limit: int = 100
    offset: int = 0


@router.post("/v2/filter")
def run_screener_v2(req: ScreenerFilterV2):
    """V2 篩選：Snapshot-based, <100ms response."""
    from analysis.financial_screener import screen_stocks
    filters = dict(req.filters)
    filters["sort_by"] = req.sort_by
    filters["sort_desc"] = req.sort_desc
    filters["limit"] = req.limit
    filters["offset"] = req.offset
    results = screen_stocks(filters)
    return {"count": len(results), "results": results}


@router.get("/v2/rankings/{metric}")
def get_rankings_v2(
    metric: str,
    top_n: int = Query(50, ge=1, le=200),
    ascending: bool = Query(False),
):
    """排行榜：Top/Bottom by any metric."""
    from analysis.financial_screener import get_rankings
    allowed = {
        "pe", "pb", "dividend_yield", "roe", "roa", "gross_margin",
        "operating_margin", "revenue_yoy", "eps_yoy", "rs_rating",
        "rs_rank_pct", "change_pct", "volume_avg_20d", "market_cap",
        "revenue_consecutive_up", "debt_ratio", "current_ratio",
    }
    if metric not in allowed:
        raise HTTPException(400, f"Invalid metric: {metric}. Allowed: {sorted(allowed)}")
    results = get_rankings(metric, top_n, ascending)
    return {"metric": metric, "ascending": ascending, "count": len(results), "results": results}


@router.get("/v2/stock/{code}")
def get_stock_snapshot_v2(code: str):
    """Single stock full metrics snapshot."""
    from analysis.financial_screener import get_stock_snapshot
    result = get_stock_snapshot(code)
    if not result:
        raise HTTPException(404, f"Stock {code} not found in screening data")
    return result


@router.get("/v2/indicators")
def get_filter_definitions():
    """Return available filter categories and their conditions."""
    from analysis.financial_screener import FILTER_DEFINITIONS
    return FILTER_DEFINITIONS


@router.get("/v2/stats")
def get_screening_stats():
    """Get screening database stats."""
    from analysis.financial_screener import get_screening_stats
    return get_screening_stats()


@router.post("/v2/refresh")
def refresh_screening():
    """Trigger screening data refresh (call after market close)."""
    from analysis.financial_screener import refresh_screening_data
    result = refresh_screening_data()
    return result


# ═══════════════════════════════════════════════════════════════════
# Legacy V1 Screener (kept for backward compatibility)
# ═══════════════════════════════════════════════════════════════════


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
    min_market_cap: float | None = None  # R52 P1: e.g. 10_000_000_000
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
                except Exception as e:
                    logger.debug(f"Screener: V4 analysis failed for {code}: {e}")
                    continue

            fundamentals = None
            if any([filters.min_pe, filters.max_pe, filters.min_dividend_yield,
                    filters.min_roe, filters.min_market_cap]):
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

                mcap = fundamentals.get("market_cap")
                if filters.min_market_cap and (mcap is None or mcap < filters.min_market_cap):
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
                item["market_cap"] = fundamentals.get("market_cap")

            results.append(item)
        except Exception as e:
            logger.debug(f"Screener: stock processing failed for {code}: {e}")
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
                    except Exception as e:
                        logger.debug(f"Screener SSE: V4 analysis failed for {code}: {e}")
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
            except Exception as e:
                logger.debug(f"Screener SSE: processing failed for {code}: {e}")
                continue

        yield sse_done(make_serializable(results))

    return StreamingResponse(generate(), media_type="text/event-stream")


# === Phase 8B: Sniper Scanner Dashboard (CTO R14.18) ===


class BoldScanRequest(BaseModel):
    """Bold Sniper 掃描參數"""
    min_rs: float = 60          # Minimum RS percentile (default: Gold+)
    min_volume_lots: float = 50  # Minimum avg volume (張)
    include_no_signal: bool = False  # Include stocks without active Bold signal


@router.post("/bold-scan")
def run_bold_scan(req: BoldScanRequest | None = None):
    """Phase 8B: Sniper Target List — 每日收盤後掃描全市場

    Combines Bold signal + RS Rating + VCP Score + SQS into a ranked
    Sniper Target List. Uses SCAN_STOCKS (108 stocks) as the universe.

    Sniper Score = RS_120D × 0.5 + SQS × 0.3 + RS_Mom × 0.2
    (CTO R14.18 formula)
    """
    from config import SCAN_STOCKS
    from data.fetcher import get_stock_data
    from data.sector_mapping import get_stock_sector
    from analysis.strategy_bold import get_bold_analysis, compute_rs_ratio, compute_rs_momentum
    from analysis.rs_scanner import get_stock_rs_rating
    from analysis.vcp_detector import detect_vcp
    from analysis.liquidity import calculate_market_impact
    from backend.dependencies import make_serializable
    import numpy as np

    if req is None:
        req = BoldScanRequest()

    results = []
    errors = []

    for code, info in SCAN_STOCKS.items():
        try:
            df = get_stock_data(code, period_days=300)
            if df.empty or len(df) < 60:
                continue

            latest = df.iloc[-1]
            price = float(latest["close"])
            volume_lots = float(latest["volume"]) / 1000

            # Volume filter
            avg_vol = float(df["volume"].iloc[-20:].mean()) / 1000
            if avg_vol < req.min_volume_lots:
                continue

            # 1. Bold signal
            bold = get_bold_analysis(df)
            has_signal = bold.get("signal") == "BUY"

            if not has_signal and not req.include_no_signal:
                continue

            # 2. RS Rating (from cached rankings first, fallback to compute)
            rs_info = get_stock_rs_rating(code)
            rs_rating = None
            rs_grade = "unknown"
            if rs_info:
                rs_rating = rs_info.get("rs_rating")
                rs_grade = rs_info.get("grade", "unknown")
            else:
                rs_ratio = compute_rs_ratio(df)
                rs_rating = rs_ratio * 100 if rs_ratio else None

            if rs_rating is not None and rs_rating < req.min_rs:
                continue

            # RS Momentum (20d slope)
            rs_mom = compute_rs_momentum(df, period=20)

            # 3. VCP detection
            vcp_result = detect_vcp(df)
            vcp_score = vcp_result.vcp_score if vcp_result else 0

            # 4. SQS — lightweight inline (avoid heavy computation)
            sqs_score = None
            try:
                from analysis.scoring import compute_sqs_for_signal
                sqs_data = compute_sqs_for_signal(code, signal_strategy="V4")
                if sqs_data:
                    sqs_score = sqs_data.get("sqs")
            except Exception as e:
                logger.debug(f"Sniper scan: SQS failed for {code}: {e}")

            # 5. Compute Sniper Score (CTO formula)
            rs_norm = (rs_rating / 100.0) if rs_rating else 0
            sqs_norm = (sqs_score / 100.0) if sqs_score else 0
            rs_mom_norm = min(max(rs_mom * 10, 0), 1) if rs_mom else 0  # Scale ~0.1 → 1.0
            sniper_score = round(
                rs_norm * 0.5 + sqs_norm * 0.3 + rs_mom_norm * 0.2, 4
            )

            # 5b. Phase 9A: Liquidity Stress Alert (CTO directive)
            # Predict slippage via Kyle Lambda for a 1M NTD position
            # If predicted slippage > 1%, deduct from Sniper Score
            predicted_slippage_pct = 0.0
            liquidity_stress = False
            try:
                adv_20_shares = float(df["volume"].iloc[-20:].mean())
                vol_20 = float(df["close"].pct_change().iloc[-20:].std() * np.sqrt(252))
                # Position size: 1M NTD worth of shares
                pos_shares = 1_000_000 / price if price > 0 else 0
                if adv_20_shares > 0 and pos_shares > 0:
                    kyle_slip = calculate_market_impact(pos_shares, adv_20_shares, vol_20)
                    predicted_slippage_pct = round(kyle_slip * 100, 2)
                    if predicted_slippage_pct > 1.0:
                        liquidity_stress = True
                        # Deduction: proportional penalty above 1%
                        # e.g., 2% slippage → (2-1)/100 = 0.01 deducted from sniper_score
                        penalty = (predicted_slippage_pct - 1.0) / 100.0
                        sniper_score = max(0, sniper_score - penalty)
            except Exception as e:
                logger.debug(f"Sniper scan: liquidity check failed for {code}: {e}")

            # 6. Sector
            sector = get_stock_sector(code, level=1)

            # 7. Entry details
            entry_type = bold.get("entry_type", "")
            confidence = bold.get("confidence", 0)

            results.append({
                "code": code,
                "name": info.get("name", code),
                "sector": sector,
                "price": round(price, 2),
                "change_pct": round(float(df["close"].pct_change().iloc[-1]) * 100, 2),
                "avg_volume_lots": round(avg_vol, 0),
                "has_signal": has_signal,
                "entry_type": entry_type,
                "confidence": round(confidence, 2) if confidence else 0,
                "rs_rating": round(rs_rating, 1) if rs_rating else None,
                "rs_grade": rs_grade,
                "rs_momentum": round(rs_mom, 4) if rs_mom else None,
                "vcp_score": vcp_score,
                "vcp_breakout": vcp_result.is_breakout if vcp_result else False,
                "sqs_score": round(sqs_score, 1) if sqs_score else None,
                "sniper_score": round(sniper_score * 100, 1),
                "predicted_slippage_pct": predicted_slippage_pct,
                "liquidity_stress": liquidity_stress,
            })

        except Exception as e:
            errors.append({"code": code, "error": str(e)})
            continue

    # Sort by sniper_score descending
    results.sort(key=lambda x: x["sniper_score"], reverse=True)

    return make_serializable({
        "scan_date": __import__("datetime").date.today().isoformat(),
        "total_scanned": len(SCAN_STOCKS),
        "results_count": len(results),
        "error_count": len(errors),
        "results": results,
    })

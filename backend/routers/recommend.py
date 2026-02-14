"""推薦掃描路由"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class FundamentalFilter(BaseModel):
    """R52 P1: Optional fundamental filters for scan."""
    min_roe: float | None = None       # e.g. 0.15
    max_pe: float | None = None        # e.g. 20
    min_market_cap: float | None = None # e.g. 10_000_000_000


class ScanRequest(BaseModel):
    stock_codes: list[str] | None = None
    params: dict | None = None
    fundamental_filter: FundamentalFilter | None = None


@router.post("/scan-v4")
def scan_v4(req: ScanRequest):
    """v4 策略掃描 — 尋找 BUY 訊號"""
    from data.fetcher import get_stock_data, get_stock_fundamentals_safe
    from data.stock_list import get_stock_name
    from analysis.strategy_v4 import get_v4_analysis
    from data.cache import get_cached_scan_results, set_cached_scan_results
    from config import SCAN_STOCKS
    from backend.dependencies import make_serializable

    ff = req.fundamental_filter
    has_ff = ff and any([ff.min_roe, ff.max_pe, ff.min_market_cap])

    # 嘗試快取（只在無基本面過濾時）
    cached = get_cached_scan_results()
    if cached and not req.stock_codes and not has_ff:
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

            # R52 P1: Apply fundamental filter on BUY signals
            if has_ff and analysis["signal"] == "BUY":
                fundamentals = get_stock_fundamentals_safe(code)
                if fundamentals:
                    roe = fundamentals.get("return_on_equity")
                    pe = fundamentals.get("trailing_pe")
                    mcap = fundamentals.get("market_cap")

                    if ff.min_roe and (roe is None or roe < ff.min_roe):
                        item["signal"] = "HOLD"
                        item["filter_reason"] = f"ROE {(roe or 0)*100:.1f}% < {ff.min_roe*100:.0f}%"
                    elif ff.max_pe and pe is not None and pe > ff.max_pe:
                        item["signal"] = "HOLD"
                        item["filter_reason"] = f"PE {pe:.1f} > {ff.max_pe:.0f}"
                    elif ff.min_market_cap and (mcap is None or mcap < ff.min_market_cap):
                        item["signal"] = "HOLD"
                        item["filter_reason"] = f"市值不足 ({(mcap or 0)/1e8:.0f}億)"
                    else:
                        item["roe"] = roe
                        item["pe"] = pe
                        item["market_cap"] = mcap
                else:
                    item["signal"] = "HOLD"
                    item["filter_reason"] = "基本面資料不可用"

            results.append(item)
        except Exception:
            continue

    # 只快取預設股票池結果（無基本面過濾時）
    if not req.stock_codes and not has_ff:
        set_cached_scan_results(results, ttl=600)

    # 排序：BUY 訊號排前面
    signal_order = {"BUY": 0, "HOLD": 1, "SELL": 2}
    results.sort(key=lambda x: signal_order.get(x["signal"], 1))

    return make_serializable(results)


@router.post("/scan-v4-stream")
def scan_v4_stream(req: ScanRequest):
    """v4 策略掃描 — SSE 串流進度"""
    from data.fetcher import get_stock_data, get_stock_fundamentals_safe
    from data.stock_list import get_stock_name
    from analysis.strategy_v4 import get_v4_analysis
    from data.cache import get_cached_scan_results, set_cached_scan_results
    from config import SCAN_STOCKS
    from backend.dependencies import make_serializable
    from backend.sse import sse_progress, sse_done, sse_error

    ff = req.fundamental_filter
    has_ff = ff and any([ff.min_roe, ff.max_pe, ff.min_market_cap])

    def generate():
        # 嘗試快取（只在無基本面過濾時）
        cached = get_cached_scan_results()
        if cached and not req.stock_codes and not has_ff:
            yield sse_done(make_serializable(cached))
            return

        stock_pool = req.stock_codes or list(SCAN_STOCKS.keys())
        total = len(stock_pool)
        results = []

        for i, code in enumerate(stock_pool):
            yield sse_progress(i + 1, total, f"掃描 {code}...")
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

                # R52 P1: Apply fundamental filter on BUY signals
                if has_ff and analysis["signal"] == "BUY":
                    fundamentals = get_stock_fundamentals_safe(code)
                    if fundamentals:
                        roe = fundamentals.get("return_on_equity")
                        pe = fundamentals.get("trailing_pe")
                        mcap = fundamentals.get("market_cap")

                        if ff.min_roe and (roe is None or roe < ff.min_roe):
                            item["signal"] = "HOLD"
                            item["filter_reason"] = f"ROE {(roe or 0)*100:.1f}% < {ff.min_roe*100:.0f}%"
                        elif ff.max_pe and pe is not None and pe > ff.max_pe:
                            item["signal"] = "HOLD"
                            item["filter_reason"] = f"PE {pe:.1f} > {ff.max_pe:.0f}"
                        elif ff.min_market_cap and (mcap is None or mcap < ff.min_market_cap):
                            item["signal"] = "HOLD"
                            item["filter_reason"] = f"市值不足 ({(mcap or 0)/1e8:.0f}億)"
                        else:
                            item["roe"] = roe
                            item["pe"] = pe
                            item["market_cap"] = mcap
                    else:
                        item["signal"] = "HOLD"
                        item["filter_reason"] = "基本面資料不可用"

                results.append(item)
            except Exception:
                continue

        if not req.stock_codes and not has_ff:
            set_cached_scan_results(results, ttl=600)

        signal_order = {"BUY": 0, "HOLD": 1, "SELL": 2}
        results.sort(key=lambda x: signal_order.get(x["signal"], 1))

        yield sse_done(make_serializable(results))

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/alpha-hunter")
def alpha_hunter():
    """Alpha Hunter — 高信心推薦清單（Gemini R24）

    Enriches BUY stocks from sector_heat with confidence multiplier,
    sector momentum, leader status. Pre-computed from worker cache.
    Returns data grouped by sector for "battle briefing" display.
    """
    from data.cache import get_cached_sector_heat, get_transition_events
    from backend.dependencies import make_serializable

    cached = get_cached_sector_heat()
    if not cached:
        return {"sectors": [], "high_confidence": [], "transitions": []}

    sectors = cached.get("sectors", [])

    # Build enriched BUY stock list with sector context
    MATURITY_RANK = {"Speculative Spike": 1, "Trend Formation": 2, "Structural Shift": 3}
    MOMENTUM_RANK = {"surge": 4, "heating": 3, "stable": 2, "cooling": 1, "new": 0}

    # Confidence matrix (same as analysis.py)
    MATRIX = {
        "Structural Shift": {"surge": 1.3, "heating": 1.2, "stable": 0.9, "cooling": 0.6},
        "Trend Formation": {"surge": 1.1, "heating": 0.9, "stable": 0.7, "cooling": 0.4},
        "Speculative Spike": {"surge": 0.6, "heating": 0.6, "stable": 0.4, "cooling": 0.1},
    }

    sector_groups = []
    all_buy = []

    for sec in sectors:
        if not sec.get("buy_stocks"):
            continue

        momentum = sec.get("momentum", "stable")
        weighted_heat = sec.get("weighted_heat", 0)
        leader = sec.get("leader")

        enriched_stocks = []
        for bs in sec["buy_stocks"]:
            maturity = bs.get("maturity", "N/A")
            is_leader = leader and leader.get("code") == bs["code"]
            leader_score = bs.get("leader_score", 0)

            # Quick confidence estimate (without LF — that needs per-stock data)
            mat_row = MATRIX.get(maturity, MATRIX["Speculative Spike"])
            base_c = mat_row.get(momentum, mat_row.get("stable", 0.5))
            c = base_c + (0.2 if is_leader else 0)
            # Overheat decay
            if weighted_heat > 0.8:
                decay = max(0.7, 1.0 - (weighted_heat - 0.8) * 1.5)
                c *= decay
            c = max(0.1, min(1.5, round(c, 2)))

            stock_data = {
                "code": bs["code"],
                "name": bs["name"],
                "maturity": maturity,
                "maturity_rank": MATURITY_RANK.get(maturity, 0),
                "is_leader": bool(is_leader),
                "leader_score": leader_score,
                "confidence": c,
                "sector": sec["sector"],
                "momentum": momentum,
                "weighted_heat": weighted_heat,
            }
            enriched_stocks.append(stock_data)
            all_buy.append(stock_data)

        # Sort stocks within sector: leaders first, then confidence desc
        enriched_stocks.sort(key=lambda x: (-x["is_leader"], -x["confidence"]))

        sector_groups.append({
            "sector": sec["sector"],
            "momentum": momentum,
            "weighted_heat": weighted_heat,
            "momentum_rank": MOMENTUM_RANK.get(momentum, 0),
            "leader": leader,
            "buy_count": len(enriched_stocks),
            "total": sec.get("total", 0),
            "stocks": enriched_stocks,
            "is_crowded": weighted_heat > 0.8,
        })

    # Sort sector groups: hot sectors first
    sector_groups.sort(key=lambda x: (-x["momentum_rank"], -x["weighted_heat"]))

    # High confidence picks: C >= 1.0
    high_confidence = sorted(
        [s for s in all_buy if s["confidence"] >= 1.0],
        key=lambda x: (-x["confidence"], -x["leader_score"]),
    )

    # Recent transitions
    transitions = get_transition_events(limit=10)

    return make_serializable({
        "sectors": sector_groups,
        "high_confidence": high_confidence,
        "transitions": list(reversed(transitions)),
        "total_buy": len(all_buy),
        "updated_at": cached.get("_updated_at"),
    })

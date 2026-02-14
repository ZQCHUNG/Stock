"""自選股路由"""

import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()

WATCHLIST_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "watchlist.json"


def _load_watchlist() -> list[str]:
    try:
        if WATCHLIST_FILE.exists():
            return json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save_watchlist(codes: list[str]):
    WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST_FILE.write_text(json.dumps(codes, ensure_ascii=False), encoding="utf-8")


@router.get("/")
def get_watchlist():
    """取得自選股清單"""
    from data.stock_list import get_stock_name
    codes = _load_watchlist()
    return [{"code": c, "name": get_stock_name(c)} for c in codes]


@router.post("/{code}")
def add_to_watchlist(code: str):
    """新增自選股"""
    codes = _load_watchlist()
    if code not in codes:
        codes.append(code)
        _save_watchlist(codes)
    return {"ok": True, "watchlist": codes}


@router.delete("/{code}")
def remove_from_watchlist(code: str):
    """移除自選股"""
    codes = _load_watchlist()
    if code in codes:
        codes.remove(code)
        _save_watchlist(codes)
    return {"ok": True, "watchlist": codes}


class BatchAddRequest(BaseModel):
    codes: list[str]


@router.post("/batch-add")
def batch_add(req: BatchAddRequest):
    """批次新增自選股"""
    codes = _load_watchlist()
    for c in req.codes:
        if c not in codes:
            codes.append(c)
    _save_watchlist(codes)
    return {"ok": True, "watchlist": codes}


@router.get("/overview")
def watchlist_overview():
    """自選股總覽（並行載入所有股票最新資料）"""
    from concurrent.futures import ThreadPoolExecutor
    from data.fetcher import get_stock_data
    from data.stock_list import get_stock_name
    from analysis.strategy_v4 import get_v4_analysis
    from backend.dependencies import make_serializable

    codes = _load_watchlist()
    if not codes:
        return []

    def _load_stock(code):
        try:
            df = get_stock_data(code, period_days=120)
            v4 = get_v4_analysis(df)
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest
            change = (latest["close"] - prev["close"]) / prev["close"]

            return {
                "code": code,
                "name": get_stock_name(code),
                "price": float(latest["close"]),
                "change_pct": float(change),
                "volume_lots": float(latest["volume"]) / 1000,
                "signal": v4["signal"],
                "entry_type": v4.get("entry_type", ""),
                "uptrend_days": v4.get("uptrend_days", 0),
                "rsi": v4["indicators"].get("RSI"),
                "adx": v4["indicators"].get("ADX"),
            }
        except Exception:
            return {"code": code, "name": get_stock_name(code), "error": True}

    # yf.Ticker().history() 是 thread-safe（已從 yf.download 遷移）
    # 可安全並行載入
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(_load_stock, codes))

    return make_serializable(results)


class BatchBacktestRequest(BaseModel):
    period_days: int = 1095
    initial_capital: float = 1_000_000
    params: dict | None = None


@router.post("/batch-backtest")
def batch_backtest(req: BatchBacktestRequest):
    """批次回測所有自選股"""
    from concurrent.futures import ThreadPoolExecutor
    from data.fetcher import get_stock_data
    from data.stock_list import get_stock_name
    from backtest.engine import run_backtest_v4
    from backend.dependencies import make_serializable

    codes = _load_watchlist()
    if not codes:
        return []

    def _bt_stock(code):
        try:
            df = get_stock_data(code, period_days=req.period_days)
            result = run_backtest_v4(df, initial_capital=req.initial_capital, params=req.params)
            return {
                "code": code,
                "name": get_stock_name(code),
                "total_return": result.total_return,
                "annual_return": result.annual_return,
                "max_drawdown": result.max_drawdown,
                "sharpe_ratio": result.sharpe_ratio,
                "win_rate": result.win_rate,
                "total_trades": result.total_trades,
                "profit_factor": result.profit_factor,
            }
        except Exception:
            return {"code": code, "name": get_stock_name(code), "error": True}

    # yf.Ticker().history() 是 thread-safe（已從 yf.download 遷移）
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(_bt_stock, codes))

    return make_serializable(results)


@router.post("/batch-backtest-stream")
def batch_backtest_stream(req: BatchBacktestRequest):
    """批次回測 — SSE 串流進度"""
    from data.fetcher import get_stock_data
    from data.stock_list import get_stock_name
    from backtest.engine import run_backtest_v4
    from backend.dependencies import make_serializable
    from backend.sse import sse_progress, sse_done

    def generate():
        codes = _load_watchlist()
        if not codes:
            yield sse_done([])
            return

        total = len(codes)
        results = []

        for i, code in enumerate(codes):
            yield sse_progress(i + 1, total, f"回測 {code}...")
            try:
                df = get_stock_data(code, period_days=req.period_days)
                result = run_backtest_v4(df, initial_capital=req.initial_capital, params=req.params)
                results.append({
                    "code": code,
                    "name": get_stock_name(code),
                    "total_return": result.total_return,
                    "annual_return": result.annual_return,
                    "max_drawdown": result.max_drawdown,
                    "sharpe_ratio": result.sharpe_ratio,
                    "win_rate": result.win_rate,
                    "total_trades": result.total_trades,
                    "profit_factor": result.profit_factor,
                })
            except Exception:
                results.append({"code": code, "name": get_stock_name(code), "error": True})

        yield sse_done(make_serializable(results))

    return StreamingResponse(generate(), media_type="text/event-stream")

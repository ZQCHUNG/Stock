"""自選股路由"""

import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
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

    # 注意：yf.download 非 thread-safe，並行呼叫會導致資料混淆
    # 因此使用循序載入
    results = [_load_stock(code) for code in codes]

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

    # yf.download 非 thread-safe，循序載入避免資料混淆
    results = [_bt_stock(code) for code in codes]

    return make_serializable(results)

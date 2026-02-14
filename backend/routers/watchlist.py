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

            # Sector/Industry info (best-effort, cached in yfinance)
            sector = ""
            industry = ""
            try:
                from data.fetcher import get_stock_info
                info = get_stock_info(code)
                sector = info.get("sector", "")
                industry = info.get("industry", "")
            except Exception:
                pass

            return {
                "code": code,
                "name": get_stock_name(code),
                "price": float(latest["close"]),
                "change_pct": float(change),
                "volume_lots": float(latest["volume"]) / 1000,
                "signal": v4["signal"],
                "entry_type": v4.get("entry_type", ""),
                "signal_maturity": v4.get("signal_maturity", "N/A"),
                "uptrend_days": v4.get("uptrend_days", 0),
                "rsi": v4["indicators"].get("RSI"),
                "adx": v4["indicators"].get("ADX"),
                "sector": sector,
                "industry": industry,
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


@router.get("/risk-audit")
def risk_audit(capital: float = 1_000_000, risk_pct: float = 2.0):
    """全自選股風險審計（Gemini R21: Risk Audit Export）

    並行載入每支股票的技術訊號 + 風險因子，
    返回結構化 JSON 供前端 CSV 下載。
    """
    from concurrent.futures import ThreadPoolExecutor
    from data.fetcher import (
        get_stock_data, get_stock_info_and_fundamentals,
        get_institutional_data, get_financial_statements,
    )
    from data.stock_list import get_stock_name
    from analysis.strategy_v4 import get_v4_analysis
    from analysis.report.recommendation import (
        _is_biotech_industry, _calculate_institutional_score,
    )
    from backend.dependencies import make_serializable

    codes = _load_watchlist()
    if not codes:
        return {"stocks": [], "summary": {}}

    def _audit_stock(code):
        try:
            # 並行取得所有資料
            with ThreadPoolExecutor(max_workers=4) as ex:
                fut_data = ex.submit(get_stock_data, code, period_days=365)
                fut_info = ex.submit(get_stock_info_and_fundamentals, code)
                fut_inst = ex.submit(get_institutional_data, code, days=20)
                fut_fin = ex.submit(get_financial_statements, code)

                df = fut_data.result()
                try:
                    company_info, _ = fut_info.result()
                except Exception:
                    company_info = {"industry": "", "sector": ""}
                try:
                    inst_df = fut_inst.result()
                except Exception:
                    inst_df = None
                try:
                    fin_data = fut_fin.result()
                except Exception:
                    fin_data = None

            # V4 分析
            v4 = get_v4_analysis(df)
            latest = df.iloc[-1]
            current_price = float(latest["close"])

            # 風險因子
            sector = company_info.get("sector", "")
            industry = company_info.get("industry", "")
            is_biotech = _is_biotech_industry(industry, sector)
            inst_result = _calculate_institutional_score(inst_df)
            cash_runway = fin_data.get("cash_runway") if fin_data else None

            op_runway = 99.0
            total_runway = 99.0
            if cash_runway:
                op_runway = cash_runway.get("runway_quarters", 99)
                total_runway = cash_runway.get("total_runway_quarters", 99)
            eff_runway = min(op_runway, total_runway) if is_biotech else op_runway

            avg_volume_20d = float(df["volume"].tail(20).mean()) if len(df) >= 20 else 0

            # Liquidity Factor 計算（與 risk-factors API 一致）
            lf = 1.0
            warnings = []
            if is_biotech:
                lf *= 0.5
                warnings.append("生技股 ×0.5")
            if eff_runway < 4:
                lf *= 0.25
                warnings.append(f"跑道 {eff_runway:.1f}Q ×0.25")
            elif eff_runway < 8:
                lf *= 0.5
                warnings.append(f"跑道 {eff_runway:.1f}Q ×0.5")
            if not is_biotech and total_runway < 8:
                warnings.append(f"Capital Strain {total_runway:.1f}Q")
            if inst_result.get("visibility") == "ghost_town":
                lf = 0
                warnings.append("Ghost Town")
            elif avg_volume_20d < 500_000:
                vol_f = max(0.1, avg_volume_20d / 500_000)
                lf *= vol_f
                warnings.append(f"低量 ×{vol_f:.2f}")

            # 建議張數 + 停損價 + 最大虧損
            risk_amount = capital * (risk_pct / 100) * lf
            stop_loss_pct = 0.07
            stop_loss_price = round(current_price * (1 - stop_loss_pct), 2)
            loss_per_share = current_price * stop_loss_pct
            suggested_lots = int(risk_amount / (loss_per_share * 1000)) if loss_per_share > 0 and lf > 0 else 0
            max_loss = round(suggested_lots * 1000 * loss_per_share, 0)

            return {
                "code": code,
                "name": get_stock_name(code),
                "price": current_price,
                "signal": v4["signal"],
                "entry_type": v4.get("entry_type", ""),
                "signal_maturity": v4.get("signal_maturity", "N/A"),
                "rsi": v4["indicators"].get("RSI"),
                "adx": v4["indicators"].get("ADX"),
                "uptrend_days": v4.get("uptrend_days", 0),
                "sector": sector,
                "industry": industry,
                "is_biotech": is_biotech,
                "visibility": inst_result.get("visibility", "active"),
                "inst_score": inst_result.get("score", 0),
                "op_runway": round(op_runway, 1),
                "total_runway": round(total_runway, 1),
                "eff_runway": round(eff_runway, 1),
                "liquidity_factor": round(lf, 4),
                "suggested_lots": suggested_lots,
                "stop_loss_price": stop_loss_price,
                "max_loss": max_loss,
                "avg_volume_lots": round(avg_volume_20d / 1000, 0),
                "warnings": warnings,
            }
        except Exception as e:
            return {"code": code, "name": get_stock_name(code), "error": str(e)}

    with ThreadPoolExecutor(max_workers=4) as executor:
        stocks = list(executor.map(_audit_stock, codes))

    # 組合層級摘要
    valid = [s for s in stocks if "error" not in s]
    sector_counts: dict[str, int] = {}
    for s in valid:
        sec = s.get("sector") or "未分類"
        sector_counts[sec] = sector_counts.get(sec, 0) + 1
    top_sector = max(sector_counts, key=sector_counts.get) if sector_counts else ""  # type: ignore[arg-type]
    top_sector_pct = (sector_counts.get(top_sector, 0) / len(valid) * 100) if valid else 0

    ghost_count = sum(1 for s in valid if s.get("visibility") == "ghost_town")
    avg_lf = sum(s.get("liquidity_factor", 0) for s in valid) / len(valid) if valid else 0
    buy_count = sum(1 for s in valid if s.get("signal") == "BUY")
    biotech_count = sum(1 for s in valid if s.get("is_biotech"))
    biotech_pct = (biotech_count / len(valid) * 100) if valid else 0

    # 組合風險警告
    portfolio_warnings = []
    if biotech_pct >= 30:
        portfolio_warnings.append(f"生技板塊曝險過高：{biotech_pct:.0f}%（{biotech_count}/{len(valid)}）")
    if top_sector_pct >= 50:
        portfolio_warnings.append(f"產業集中度過高：{top_sector} 佔 {top_sector_pct:.0f}%")
    if ghost_count > 0:
        portfolio_warnings.append(f"{ghost_count} 檔標的無流動性（Ghost Town），建議移除")

    summary = {
        "total_stocks": len(codes),
        "valid_stocks": len(valid),
        "top_sector": top_sector,
        "top_sector_pct": round(top_sector_pct, 1),
        "biotech_count": biotech_count,
        "biotech_pct": round(biotech_pct, 1),
        "avg_liquidity_factor": round(avg_lf, 2),
        "ghost_town_count": ghost_count,
        "buy_signal_count": buy_count,
        "portfolio_warnings": portfolio_warnings,
        "audit_time": __import__("datetime").datetime.now().isoformat(),
        "capital": capital,
        "risk_pct": risk_pct,
    }

    return make_serializable({"stocks": stocks, "summary": summary})

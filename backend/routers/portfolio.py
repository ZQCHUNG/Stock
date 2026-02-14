"""模擬倉位管理路由（Gemini R25: Portfolio Commander）

JSON-file-backed simulated position management.
Supports open/close positions, live P&L tracking, portfolio health audit.
"""

import json
import uuid
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

PORTFOLIO_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "portfolio.json"


def _load_portfolio() -> dict:
    try:
        if PORTFOLIO_FILE.exists():
            return json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"positions": [], "closed": []}


def _save_portfolio(data: dict):
    PORTFOLIO_FILE.parent.mkdir(parents=True, exist_ok=True)
    PORTFOLIO_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class OpenPositionRequest(BaseModel):
    code: str
    name: str = ""
    entry_price: float
    lots: int
    stop_loss: float
    trailing_stop: float | None = None
    confidence: float = 0.7
    sector: str = ""
    note: str = ""


class ClosePositionRequest(BaseModel):
    exit_price: float
    exit_reason: str = "manual"


class UpdateStopRequest(BaseModel):
    stop_loss: float | None = None
    trailing_stop: float | None = None
    note: str | None = None


@router.get("/")
def list_positions():
    """列出所有模擬倉位（含即時損益）"""
    from concurrent.futures import ThreadPoolExecutor
    from data.fetcher import get_stock_data
    from backend.dependencies import make_serializable

    portfolio = _load_portfolio()
    positions = portfolio.get("positions", [])

    if not positions:
        return make_serializable({
            "positions": [],
            "closed": portfolio.get("closed", [])[-20:],
            "summary": _empty_summary(),
        })

    # Parallel fetch current prices
    codes = list({p["code"] for p in positions})

    def _get_price(code):
        try:
            df = get_stock_data(code, period_days=5)
            return code, float(df["close"].iloc[-1])
        except Exception:
            return code, None

    with ThreadPoolExecutor(max_workers=6) as ex:
        price_results = list(ex.map(_get_price, codes))

    price_map = {code: price for code, price in price_results}

    # Enrich positions with live data
    enriched = []
    for p in positions:
        current = price_map.get(p["code"])
        if current is not None:
            shares = p["lots"] * 1000
            cost = p["entry_price"] * shares
            value = current * shares
            pnl = value - cost
            pnl_pct = (current / p["entry_price"] - 1) if p["entry_price"] > 0 else 0
            # Exit signal checks
            exit_signals = []
            if current <= p.get("stop_loss", 0):
                exit_signals.append("觸及停損")
            trailing = p.get("trailing_stop")
            if trailing and current <= trailing:
                exit_signals.append("觸及移動停利")
            if pnl_pct >= 0.10:
                exit_signals.append("達停利 +10%")
            days_held = (datetime.now() - datetime.fromisoformat(p["entry_date"])).days

            p["current_price"] = current
            p["pnl"] = round(pnl, 0)
            p["pnl_pct"] = round(pnl_pct, 4)
            p["market_value"] = round(value, 0)
            p["exit_signals"] = exit_signals
            p["days_held"] = days_held
        enriched.append(p)

    # Sort: exit signals first, then by P&L
    enriched.sort(key=lambda x: (-len(x.get("exit_signals", [])), x.get("pnl", 0)))

    summary = _calculate_summary(enriched, portfolio.get("closed", []))

    return make_serializable({
        "positions": enriched,
        "closed": portfolio.get("closed", [])[-20:],
        "summary": summary,
    })


@router.post("/open")
def open_position(req: OpenPositionRequest):
    """開啟模擬倉位"""
    if req.lots <= 0 or req.entry_price <= 0:
        raise HTTPException(400, "張數和買入價必須大於 0")

    portfolio = _load_portfolio()

    # Check if already has open position for same code
    existing = [p for p in portfolio["positions"] if p["code"] == req.code]
    if existing:
        raise HTTPException(400, f"已有 {req.code} 的未平倉部位，請先平倉")

    position = {
        "id": str(uuid.uuid4())[:8],
        "code": req.code,
        "name": req.name,
        "entry_date": datetime.now().strftime("%Y-%m-%d"),
        "entry_price": req.entry_price,
        "lots": req.lots,
        "stop_loss": req.stop_loss,
        "trailing_stop": req.trailing_stop,
        "confidence": req.confidence,
        "sector": req.sector,
        "note": req.note,
    }

    portfolio["positions"].append(position)
    _save_portfolio(portfolio)
    return {"ok": True, "position": position}


@router.post("/{position_id}/close")
def close_position(position_id: str, req: ClosePositionRequest):
    """平倉模擬倉位"""
    portfolio = _load_portfolio()

    pos = None
    for i, p in enumerate(portfolio["positions"]):
        if p["id"] == position_id:
            pos = portfolio["positions"].pop(i)
            break

    if not pos:
        raise HTTPException(404, f"找不到倉位 {position_id}")

    shares = pos["lots"] * 1000
    entry_cost = pos["entry_price"] * shares
    exit_value = req.exit_price * shares
    pnl = exit_value - entry_cost
    # Transaction costs: commission 0.1425% × 2 + tax 0.3% + slippage already in prices
    commission = (entry_cost + exit_value) * 0.001425
    tax = exit_value * 0.003
    net_pnl = pnl - commission - tax

    closed = {
        **pos,
        "exit_date": datetime.now().strftime("%Y-%m-%d"),
        "exit_price": req.exit_price,
        "exit_reason": req.exit_reason,
        "pnl": round(pnl, 0),
        "net_pnl": round(net_pnl, 0),
        "return_pct": round((req.exit_price / pos["entry_price"] - 1), 4),
        "commission": round(commission, 0),
        "tax": round(tax, 0),
        "days_held": (datetime.now() - datetime.fromisoformat(pos["entry_date"])).days,
    }

    portfolio["closed"].append(closed)
    _save_portfolio(portfolio)
    return {"ok": True, "closed": closed}


@router.put("/{position_id}")
def update_position(position_id: str, req: UpdateStopRequest):
    """更新倉位停損/停利"""
    portfolio = _load_portfolio()

    for p in portfolio["positions"]:
        if p["id"] == position_id:
            if req.stop_loss is not None:
                p["stop_loss"] = req.stop_loss
            if req.trailing_stop is not None:
                p["trailing_stop"] = req.trailing_stop
            if req.note is not None:
                p["note"] = req.note
            _save_portfolio(portfolio)
            return {"ok": True, "position": p}

    raise HTTPException(404, f"找不到倉位 {position_id}")


@router.delete("/{position_id}")
def delete_position(position_id: str):
    """刪除倉位（不計入已平倉記錄）"""
    portfolio = _load_portfolio()

    for i, p in enumerate(portfolio["positions"]):
        if p["id"] == position_id:
            portfolio["positions"].pop(i)
            _save_portfolio(portfolio)
            return {"ok": True}

    raise HTTPException(404, f"找不到倉位 {position_id}")


@router.get("/health")
def portfolio_health():
    """組合健康檢查（Gemini R25: Risk Audit）

    Returns sector concentration, momentum divergence, and risk warnings.
    """
    from data.cache import get_cached_sector_heat
    from backend.dependencies import make_serializable

    portfolio = _load_portfolio()
    positions = portfolio.get("positions", [])

    if not positions:
        return make_serializable({"warnings": [], "sector_allocation": [], "total_positions": 0})

    # Sector concentration
    sector_counts: dict[str, int] = {}
    sector_lots: dict[str, int] = {}
    for p in positions:
        sec = p.get("sector") or "未分類"
        sector_counts[sec] = sector_counts.get(sec, 0) + 1
        sector_lots[sec] = sector_lots.get(sec, 0) + p["lots"]

    total_lots = sum(p["lots"] for p in positions)
    sector_allocation = [
        {
            "sector": sec,
            "count": sector_counts[sec],
            "lots": sector_lots[sec],
            "pct": round(sector_lots[sec] / total_lots * 100, 1) if total_lots > 0 else 0,
        }
        for sec in sorted(sector_counts, key=lambda s: -sector_lots[s])
    ]

    warnings = []

    # Concentration warning: any sector > 40%
    for sa in sector_allocation:
        if sa["pct"] > 40:
            warnings.append({
                "type": "concentration",
                "severity": "high",
                "message": f"板塊集中風險：{sa['sector']} 佔 {sa['pct']}%（建議 < 40%）",
            })

    # Momentum divergence: check if held sectors are cooling
    sector_heat = get_cached_sector_heat()
    if sector_heat:
        heat_sectors = {s["sector"]: s for s in sector_heat.get("sectors", [])}
        for p in positions:
            sec = p.get("sector", "")
            heat_info = heat_sectors.get(sec)
            if heat_info and heat_info.get("momentum") == "cooling":
                warnings.append({
                    "type": "momentum_divergence",
                    "severity": "medium",
                    "message": f"{p['code']} {p['name']}：所屬板塊 {sec} 動能降溫 (Cooling)，留意趨勢反轉",
                })
            if heat_info and heat_info.get("weighted_heat", 0) > 0.8:
                warnings.append({
                    "type": "crowded_trade",
                    "severity": "medium",
                    "message": f"{p['code']}：板塊 {sec} 擁擠交易 (Hw={heat_info['weighted_heat']:.0%})，留意回調風險",
                })

    # Over-diversification
    if len(positions) > 10:
        warnings.append({
            "type": "over_diversification",
            "severity": "low",
            "message": f"持有 {len(positions)} 檔，過度分散可能稀釋績效（建議 5-10 檔）",
        })

    return make_serializable({
        "warnings": warnings,
        "sector_allocation": sector_allocation,
        "total_positions": len(positions),
        "total_lots": total_lots,
    })


def _calculate_summary(positions: list, closed: list) -> dict:
    """Calculate portfolio summary metrics."""
    if not positions:
        return _empty_summary()

    total_cost = sum(p["entry_price"] * p["lots"] * 1000 for p in positions)
    total_value = sum(p.get("market_value", 0) for p in positions)
    total_pnl = sum(p.get("pnl", 0) for p in positions)
    total_pnl_pct = (total_value / total_cost - 1) if total_cost > 0 else 0

    exit_alert_count = sum(1 for p in positions if p.get("exit_signals"))

    # Closed trade stats
    closed_pnl = sum(c.get("net_pnl", 0) for c in closed)
    wins = [c for c in closed if c.get("net_pnl", 0) > 0]
    win_rate = len(wins) / len(closed) if closed else 0

    return {
        "total_positions": len(positions),
        "total_cost": round(total_cost, 0),
        "total_value": round(total_value, 0),
        "unrealized_pnl": round(total_pnl, 0),
        "unrealized_pnl_pct": round(total_pnl_pct, 4),
        "exit_alert_count": exit_alert_count,
        "closed_trades": len(closed),
        "closed_pnl": round(closed_pnl, 0),
        "win_rate": round(win_rate, 4),
    }


def _empty_summary() -> dict:
    return {
        "total_positions": 0,
        "total_cost": 0,
        "total_value": 0,
        "unrealized_pnl": 0,
        "unrealized_pnl_pct": 0,
        "exit_alert_count": 0,
        "closed_trades": 0,
        "closed_pnl": 0,
        "win_rate": 0,
    }

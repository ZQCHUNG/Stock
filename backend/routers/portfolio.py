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

    # L1 Hidden Exposure (Gemini R26: Correlation Audit)
    # Even if L2 subsectors differ, high L1 concentration = correlated risk
    if total_lots > 0:
        max_sector = max(sector_allocation, key=lambda x: x["pct"])
        if max_sector["pct"] >= 60 and max_sector["count"] >= 2:
            warnings.append({
                "type": "hidden_exposure",
                "severity": "high",
                "message": (
                    f"🔴 隱藏曝險過高：{max_sector['sector']} 佔 {max_sector['pct']}% "
                    f"({max_sector['count']}檔)，即使子板塊不同，L1 相關性仍高，大盤輪動時可能集體下跌"
                ),
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


@router.get("/exit-alerts")
def get_exit_alerts():
    """Worker 自動偵測的出場警報（Gemini R25）"""
    from data.cache import get_portfolio_exit_alerts
    return get_portfolio_exit_alerts()


@router.get("/equity-ledger")
def get_equity_ledger():
    """每日資產快照歷史（Gemini R25）"""
    from data.cache import get_equity_ledger as _get_ledger
    from backend.dependencies import make_serializable

    ledger = _get_ledger()
    if not ledger:
        return {"ledger": [], "delta_equity": None}

    # Delta equity: today vs yesterday
    delta = None
    if len(ledger) >= 2:
        today = ledger[-1]
        yesterday = ledger[-2]
        delta = {
            "today": today.get("total_equity", 0),
            "yesterday": yesterday.get("total_equity", 0),
            "change": round(today.get("total_equity", 0) - yesterday.get("total_equity", 0), 0),
            "change_pct": round(
                (today.get("total_equity", 0) / yesterday.get("total_equity", 1) - 1), 4
            ) if yesterday.get("total_equity", 0) > 0 else 0,
        }

    return make_serializable({"ledger": ledger, "delta_equity": delta})


@router.get("/analytics")
def get_analytics():
    """勝率與賠率統計 — Win-Loss Analytics（Gemini R26）

    Validates whether our Confidence Multiplier actually works:
    - Win rate, Profit Factor, Expectancy
    - Confidence Accuracy: avg return by C-value bracket
    - Best/worst trades
    """
    from backend.dependencies import make_serializable

    portfolio = _load_portfolio()
    closed = portfolio.get("closed", [])

    if not closed:
        return make_serializable({"has_data": False})

    wins = [c for c in closed if c.get("net_pnl", 0) > 0]
    losses = [c for c in closed if c.get("net_pnl", 0) <= 0]
    total_gain = sum(c.get("net_pnl", 0) for c in wins)
    total_loss = abs(sum(c.get("net_pnl", 0) for c in losses))

    win_rate = len(wins) / len(closed) if closed else 0
    profit_factor = total_gain / total_loss if total_loss > 0 else float("inf")
    avg_win = total_gain / len(wins) if wins else 0
    avg_loss = total_loss / len(losses) if losses else 0

    # Expectancy = (Win% × Avg Win) - (Loss% × Avg Loss)
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    # Confidence Accuracy: group by C-value brackets
    c_brackets = {
        "C >= 1.2 (高信心)": [],
        "1.0 <= C < 1.2 (中高)": [],
        "0.5 <= C < 1.0 (中)": [],
        "C < 0.5 (低信心)": [],
    }
    for c in closed:
        cv = c.get("confidence", 0.7)
        ret = c.get("return_pct", 0)
        if cv >= 1.2:
            c_brackets["C >= 1.2 (高信心)"].append(ret)
        elif cv >= 1.0:
            c_brackets["1.0 <= C < 1.2 (中高)"].append(ret)
        elif cv >= 0.5:
            c_brackets["0.5 <= C < 1.0 (中)"].append(ret)
        else:
            c_brackets["C < 0.5 (低信心)"].append(ret)

    confidence_accuracy = []
    for bracket, returns in c_brackets.items():
        if returns:
            avg_ret = sum(returns) / len(returns)
            w = sum(1 for r in returns if r > 0)
            confidence_accuracy.append({
                "bracket": bracket,
                "count": len(returns),
                "avg_return": round(avg_ret, 4),
                "win_rate": round(w / len(returns), 4),
            })

    # Best/worst trades
    sorted_by_pnl = sorted(closed, key=lambda x: x.get("net_pnl", 0))
    best = sorted_by_pnl[-1] if sorted_by_pnl else None
    worst = sorted_by_pnl[0] if sorted_by_pnl else None

    # Avg holding days
    avg_days = sum(c.get("days_held", 0) for c in closed) / len(closed) if closed else 0

    return make_serializable({
        "has_data": True,
        "total_trades": len(closed),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999,
        "expectancy": round(expectancy, 0),
        "avg_win": round(avg_win, 0),
        "avg_loss": round(avg_loss, 0),
        "total_gain": round(total_gain, 0),
        "total_loss": round(total_loss, 0),
        "avg_days_held": round(avg_days, 1),
        "confidence_accuracy": confidence_accuracy,
        "best_trade": {
            "code": best["code"], "name": best.get("name", ""),
            "net_pnl": best.get("net_pnl", 0), "return_pct": best.get("return_pct", 0),
        } if best else None,
        "worst_trade": {
            "code": worst["code"], "name": worst.get("name", ""),
            "net_pnl": worst.get("net_pnl", 0), "return_pct": worst.get("return_pct", 0),
        } if worst else None,
    })


@router.get("/briefing")
def get_briefing():
    """今日戰略簡報 — AI Briefing（Gemini R26）

    Aggregates: sector heat, transitions, health warnings, exit alerts
    into top 3 actionable insights.
    """
    from data.cache import (
        get_cached_sector_heat, get_transition_events,
        get_portfolio_exit_alerts,
    )
    from backend.dependencies import make_serializable

    insights = []

    # 1. Hottest sector from sector heat
    heat = get_cached_sector_heat()
    if heat:
        sectors = heat.get("sectors", [])
        surge_sectors = [s for s in sectors if s.get("momentum") == "surge"]
        heating_sectors = [s for s in sectors if s.get("momentum") == "heating"]

        if surge_sectors:
            top = surge_sectors[0]
            leader_info = ""
            if top.get("leader"):
                leader_info = f"，Leader {top['leader']['code']} {top['leader']['name']}"
            insights.append({
                "type": "sector_surge",
                "severity": "high",
                "icon": "🔥",
                "message": f"板塊爆發：{top['sector']} 熱度急升 (Hw={top['weighted_heat']:.0%}){leader_info}",
            })
        elif heating_sectors:
            top = heating_sectors[0]
            insights.append({
                "type": "sector_heating",
                "severity": "medium",
                "icon": "📈",
                "message": f"板塊升溫：{top['sector']} 動能增強 (Hw={top['weighted_heat']:.0%})",
            })

    # 2. Exit alerts
    exit_alerts = get_portfolio_exit_alerts()
    if exit_alerts:
        codes = [f"{a['code']} {a['name']}" for a in exit_alerts[:3]]
        insights.append({
            "type": "exit_alert",
            "severity": "high",
            "icon": "🔴",
            "message": f"出場警報：{', '.join(codes)} 已觸發停損/停利條件，請評估撤退",
        })

    # 3. Maturity transitions (high-value only)
    transitions = get_transition_events(limit=5)
    high_value = [t for t in transitions if t.get("is_high_value")]
    if high_value:
        t = high_value[0]
        insights.append({
            "type": "transition",
            "severity": "medium",
            "icon": "⭐",
            "message": f"成熟度躍遷：{t['code']} {t.get('name', '')} 從 {t['from_maturity']} 升級至 {t['to_maturity']}（{t.get('sector', '')} Leader）",
        })

    # 4. Portfolio health warnings
    portfolio = _load_portfolio()
    positions = portfolio.get("positions", [])
    if positions:
        sectors = {}
        for p in positions:
            sec = p.get("sector") or "未分類"
            sectors[sec] = sectors.get(sec, 0) + p["lots"]
        total_lots = sum(sectors.values())
        for sec, lots in sectors.items():
            pct = lots / total_lots * 100 if total_lots > 0 else 0
            if pct > 50:
                insights.append({
                    "type": "concentration",
                    "severity": "medium",
                    "icon": "⚠️",
                    "message": f"集中風險：{sec} 佔組合 {pct:.0f}%，建議分散至其他板塊避險",
                })
                break

    # 5. If no insights, add a neutral one
    if not insights:
        insights.append({
            "type": "neutral",
            "severity": "low",
            "icon": "📋",
            "message": "目前無重大警報，市場穩定運行中",
        })

    # Keep top 3
    insights = insights[:3]

    return make_serializable({"insights": insights, "generated_at": datetime.now().isoformat()})


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

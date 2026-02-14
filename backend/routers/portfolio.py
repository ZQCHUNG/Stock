"""模擬倉位管理路由（Gemini R25→R27: SQLite-backed）

SQLite-backed simulated position management.
Supports open/close positions, live P&L tracking, portfolio health audit,
win-loss analytics, and AI strategic briefing.
"""

from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import db

router = APIRouter()


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
    tags: str = ""


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

    positions = db.get_open_positions()
    closed = db.get_closed_positions(limit=20)

    if not positions:
        return make_serializable({
            "positions": [],
            "closed": closed,
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

    summary = _calculate_summary(enriched, closed)

    return make_serializable({
        "positions": enriched,
        "closed": closed,
        "summary": summary,
    })


@router.post("/open")
def open_position(req: OpenPositionRequest):
    """開啟模擬倉位"""
    if req.lots <= 0 or req.entry_price <= 0:
        raise HTTPException(400, "張數和買入價必須大於 0")

    try:
        position = db.create_position({
            "code": req.code,
            "name": req.name,
            "entry_price": req.entry_price,
            "lots": req.lots,
            "stop_loss": req.stop_loss,
            "trailing_stop": req.trailing_stop,
            "confidence": req.confidence,
            "sector": req.sector,
            "note": req.note,
            "tags": req.tags,
        })
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {"ok": True, "position": position}


@router.post("/{position_id}/close")
def close_position(position_id: str, req: ClosePositionRequest):
    """平倉模擬倉位"""
    result = db.close_position(position_id, req.exit_price, req.exit_reason)
    if not result:
        raise HTTPException(404, f"找不到倉位 {position_id}")
    return {"ok": True, "closed": result}


@router.put("/{position_id}")
def update_position(position_id: str, req: UpdateStopRequest):
    """更新倉位停損/停利"""
    updates = {}
    if req.stop_loss is not None:
        updates["stop_loss"] = req.stop_loss
    if req.trailing_stop is not None:
        updates["trailing_stop"] = req.trailing_stop
    if req.note is not None:
        updates["note"] = req.note

    result = db.update_position(position_id, updates)
    if not result:
        raise HTTPException(404, f"找不到倉位 {position_id}")
    return {"ok": True, "position": result}


@router.delete("/{position_id}")
def delete_position(position_id: str):
    """刪除倉位（不計入已平倉記錄）"""
    if not db.delete_position(position_id):
        raise HTTPException(404, f"找不到倉位 {position_id}")
    return {"ok": True}


@router.get("/health")
def portfolio_health():
    """組合健康檢查（Gemini R25-R26: Risk Audit + Correlation Audit）"""
    from data.cache import get_cached_sector_heat
    from backend.dependencies import make_serializable

    positions = db.get_open_positions()

    if not positions:
        return make_serializable({"warnings": [], "sector_allocation": [], "total_positions": 0})

    # Sector concentration — market-value based (Gemini R30: Cluster Audit)
    sector_counts: dict[str, int] = {}
    sector_value: dict[str, float] = {}
    sector_codes: dict[str, list[str]] = {}
    for p in positions:
        sec = p.get("sector") or "未分類"
        mv = p["lots"] * 1000 * (p.get("current_price") or p["entry_price"])
        sector_counts[sec] = sector_counts.get(sec, 0) + 1
        sector_value[sec] = sector_value.get(sec, 0) + mv
        sector_codes.setdefault(sec, []).append(p["code"])

    total_value = sum(sector_value.values())
    total_lots = sum(p["lots"] for p in positions)
    sector_allocation = [
        {
            "sector": sec,
            "count": sector_counts[sec],
            "value": round(sector_value[sec]),
            "codes": sector_codes[sec],
            "pct": round(sector_value[sec] / total_value * 100, 1) if total_value > 0 else 0,
        }
        for sec in sorted(sector_counts, key=lambda s: -sector_value[s])
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
    """每日資產快照歷史（Gemini R25→R27: from SQLite）"""
    from backend.dependencies import make_serializable

    ledger = db.get_equity_snapshots()

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


@router.get("/performance")
def get_performance():
    """資產淨值曲線 + 最大回撤（Gemini R28: Visual Intelligence）

    Returns equity curve, daily returns, HWM, and drawdown from SQLite snapshots.
    """
    from backend.dependencies import make_serializable

    snapshots = db.get_equity_snapshots()
    if len(snapshots) < 2:
        return make_serializable({"has_data": False})

    dates = []
    equities = []
    hwm_line = []
    drawdown_line = []
    daily_returns = []

    hwm = 0
    max_dd = 0
    max_dd_date = ""
    prev_equity = None

    for s in snapshots:
        eq = s.get("total_equity", 0)
        dates.append(s["date"])
        equities.append(eq)

        # HWM
        if eq > hwm:
            hwm = eq
        hwm_line.append(hwm)

        # Drawdown
        dd = (hwm - eq) / hwm if hwm > 0 else 0
        drawdown_line.append(round(-dd, 4))
        if dd > max_dd:
            max_dd = dd
            max_dd_date = s["date"]

        # Daily return
        if prev_equity is not None and prev_equity > 0:
            dr = (eq - prev_equity) / prev_equity
            daily_returns.append(round(dr, 4))
        else:
            daily_returns.append(0)
        prev_equity = eq

    # Summary stats
    first_eq = equities[0] if equities else 0
    last_eq = equities[-1] if equities else 0
    total_return = (last_eq / first_eq - 1) if first_eq > 0 else 0

    # Shadow portfolio overlay (Gemini R30)
    shadow_snaps = db.get_shadow_snapshots()
    shadow_equity = None
    shadow_dates = None
    if len(shadow_snaps) >= 2:
        shadow_dates = [s["date"] for s in shadow_snaps]
        shadow_equity = [s.get("total_equity", 0) for s in shadow_snaps]

    return make_serializable({
        "has_data": True,
        "dates": dates,
        "equity": equities,
        "hwm": hwm_line,
        "drawdown": drawdown_line,
        "daily_returns": daily_returns,
        "shadow_dates": shadow_dates,
        "shadow_equity": shadow_equity,
        "summary": {
            "total_return": round(total_return, 4),
            "max_drawdown": round(max_dd, 4),
            "max_dd_date": max_dd_date,
            "current_equity": last_eq,
            "peak_equity": hwm,
            "data_points": len(snapshots),
        },
    })


@router.get("/analytics")
def get_analytics():
    """勝率與賠率統計 — Win-Loss Analytics（Gemini R26→R27: SQL-powered）"""
    from backend.dependencies import make_serializable

    stats = db.get_closed_stats()

    if stats["total"] == 0:
        return make_serializable({"has_data": False})

    confidence_accuracy = db.get_confidence_accuracy()
    best, worst = db.get_best_worst_trades()
    discipline = db.get_discipline_score()

    return make_serializable({
        "has_data": True,
        "total_trades": stats["total"],
        "win_rate": stats["win_rate"],
        "profit_factor": stats["profit_factor"],
        "expectancy": stats["expectancy"],
        "avg_win": stats["avg_win"],
        "avg_loss": stats["avg_loss"],
        "total_gain": stats["total_gain"],
        "total_loss": stats["total_loss"],
        "avg_days_held": stats["avg_days"],
        "confidence_accuracy": confidence_accuracy,
        "best_trade": best,
        "worst_trade": worst,
        "discipline": discipline,
    })


@router.get("/briefing")
def get_briefing():
    """今日戰略簡報 — AI Briefing（Gemini R26-R27: with self-correction）"""
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

    # 4. Portfolio health warnings — market-value based (Gemini R30: Cluster Audit)
    positions = db.get_open_positions()
    if positions:
        sector_mv: dict[str, float] = {}
        for p in positions:
            sec = p.get("sector") or "未分類"
            mv = p["lots"] * 1000 * (p.get("current_price") or p["entry_price"])
            sector_mv[sec] = sector_mv.get(sec, 0) + mv
        total_mv = sum(sector_mv.values())
        for sec, mv in sector_mv.items():
            pct = mv / total_mv * 100 if total_mv > 0 else 0
            if pct > 50:
                insights.append({
                    "type": "concentration",
                    "severity": "medium",
                    "icon": "⚠️",
                    "message": f"集中風險：{sec} 佔組合市值 {pct:.0f}%，建議分散至其他板塊避險",
                })
                break

    # 5. Self-correction advice from Analytics (Gemini R27)
    confidence_accuracy = db.get_confidence_accuracy()
    for ca in confidence_accuracy:
        if "低信心" in ca["bracket"] and ca["count"] >= 2 and ca["win_rate"] < 0.35:
            insights.append({
                "type": "self_correction",
                "severity": "high",
                "icon": "🧠",
                "message": (
                    f"自我修正：低信心標的 ({ca['bracket']}) 勝率僅 {ca['win_rate']:.0%}，"
                    f"建議嚴格執行低信心不開倉策略"
                ),
            })
            break

    # 6. Post-mortem: analyze recent closed trades (Gemini R29)
    recent_closed = db.get_recent_closed(limit=5)
    if len(recent_closed) >= 3:
        manual_exits = [c for c in recent_closed if c.get("exit_reason") == "manual" and (c.get("net_pnl") or 0) < 0]
        if len(manual_exits) >= 2:
            insights.append({
                "type": "post_mortem",
                "severity": "high",
                "icon": "📝",
                "message": (
                    f"戰後檢討：最近 {len(manual_exits)} 筆虧損為手動出場（非系統停損），"
                    f"可能過早恐慌出場，建議信任移動停利邏輯"
                ),
            })

    # 7. Shadow portfolio comparison (Gemini R30)
    shadow_snaps = db.get_shadow_snapshots()
    user_snaps = db.get_equity_snapshots()
    if len(shadow_snaps) >= 5 and len(user_snaps) >= 5:
        shadow_first = shadow_snaps[0].get("total_equity", 0)
        shadow_last = shadow_snaps[-1].get("total_equity", 0)
        user_first = user_snaps[0].get("total_equity", 0)
        user_last = user_snaps[-1].get("total_equity", 0)
        if shadow_first > 0 and user_first > 0:
            shadow_ret = (shadow_last / shadow_first - 1) * 100
            user_ret = (user_last / user_first - 1) * 100
            delta = user_ret - shadow_ret
            if delta < -3:
                insights.append({
                    "type": "shadow_comparison",
                    "severity": "high",
                    "icon": "🤖",
                    "message": (
                        f"影子組合對比：AI 純系統推薦 {shadow_ret:+.1f}% vs 你的操作 {user_ret:+.1f}%，"
                        f"主觀干預拖累 {abs(delta):.1f}%，建議減少偏離系統信號的交易"
                    ),
                })
            elif delta > 3:
                insights.append({
                    "type": "shadow_comparison",
                    "severity": "low",
                    "icon": "🏆",
                    "message": f"超越影子組合：你的操作 {user_ret:+.1f}% 優於 AI 推薦 {shadow_ret:+.1f}%，主觀判斷加值 {delta:.1f}%",
                })

    # 8. If no insights, add a neutral one
    if not insights:
        insights.append({
            "type": "neutral",
            "severity": "low",
            "icon": "📋",
            "message": "目前無重大警報，市場穩定運行中",
        })

    # Keep top 4
    insights = insights[:4]

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

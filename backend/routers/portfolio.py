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

    # Alpha/Beta attribution (Gemini R31)
    benchmark_prices = [s.get("benchmark_price", 0) for s in snapshots]
    has_benchmark = any(p > 0 for p in benchmark_prices)
    alpha_beta = None
    if has_benchmark and len(equities) >= 10:
        # Simple return-based attribution
        port_rets = []
        bench_rets = []
        for i in range(1, len(equities)):
            if equities[i - 1] > 0 and benchmark_prices[i] > 0 and benchmark_prices[i - 1] > 0:
                port_rets.append(equities[i] / equities[i - 1] - 1)
                bench_rets.append(benchmark_prices[i] / benchmark_prices[i - 1] - 1)
        if len(port_rets) >= 5:
            import numpy as np
            pr = np.array(port_rets)
            br = np.array(bench_rets)
            # Simple OLS: Rp = alpha + beta * Rm
            cov = np.cov(pr, br)
            beta_val = float(cov[0, 1] / cov[1, 1]) if cov[1, 1] > 0 else 1.0
            alpha_val = float(pr.mean() - beta_val * br.mean()) * 252  # Annualized
            correlation = float(np.corrcoef(pr, br)[0, 1]) if len(pr) >= 3 else 0
            alpha_beta = {
                "alpha_annual": round(alpha_val, 4),
                "beta": round(beta_val, 3),
                "correlation": round(correlation, 3),
                "data_points": len(port_rets),
            }

    # Sortino & Calmar Ratios (Gemini R34: Downside Risk Metrics)
    sortino = None
    calmar = None
    actual_daily = [r for r in daily_returns[1:] if r != 0]  # Skip first zero
    if len(actual_daily) >= 10:
        import numpy as np
        rf_daily = 0.015 / 252  # Taiwan 1-year rate ~1.5%
        excess = [r - rf_daily for r in actual_daily]
        downside = [min(0, r) for r in excess]
        downside_sq = [d ** 2 for d in downside]
        downside_dev = (sum(downside_sq) / len(downside_sq)) ** 0.5
        mean_excess = sum(excess) / len(excess)

        # Annualize
        sortino = float(mean_excess * 252 ** 0.5 / downside_dev) if downside_dev > 0 else 0

        # Calmar: annualized return / max drawdown
        n_days = len(actual_daily)
        annual_return = (1 + total_return) ** (252 / n_days) - 1 if n_days > 0 else 0
        calmar = float(annual_return / max_dd) if max_dd > 0 else 0

    return make_serializable({
        "has_data": True,
        "dates": dates,
        "equity": equities,
        "hwm": hwm_line,
        "drawdown": drawdown_line,
        "daily_returns": daily_returns,
        "shadow_dates": shadow_dates,
        "shadow_equity": shadow_equity,
        "alpha_beta": alpha_beta,
        "risk_ratios": {
            "sortino": round(sortino, 3) if sortino is not None else None,
            "calmar": round(calmar, 3) if calmar is not None else None,
        },
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


@router.get("/correlation")
def get_portfolio_correlation():
    """持倉統計相關性矩陣 — Pearson 60 天日報酬率（Gemini R33）

    Returns correlation matrix + high-correlation pairs for portfolio positions.
    """
    from concurrent.futures import ThreadPoolExecutor
    from data.fetcher import get_stock_data
    from backend.dependencies import make_serializable
    import numpy as np
    import pandas as pd

    positions = db.get_open_positions()
    if len(positions) < 2:
        return make_serializable({"has_data": False})

    codes = [p["code"] for p in positions]
    code_name_map = {p["code"]: p.get("name", "") for p in positions}

    def _get_returns(code):
        try:
            df = get_stock_data(code, period_days=90)
            if len(df) < 30:
                return code, None
            returns = df["close"].pct_change().dropna().tail(60)
            return code, returns
        except Exception:
            return code, None

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(_get_returns, codes))

    # Filter out failed fetches
    valid = [(code, ret) for code, ret in results if ret is not None and len(ret) >= 20]
    if len(valid) < 2:
        return make_serializable({"has_data": False})

    # Align returns to common dates
    ret_df = pd.DataFrame({code: ret for code, ret in valid})
    ret_df = ret_df.dropna()

    if len(ret_df) < 20:
        return make_serializable({"has_data": False})

    corr_matrix = ret_df.corr().values
    valid_codes = list(ret_df.columns)
    valid_names = [code_name_map.get(c, "") for c in valid_codes]

    # Find high correlation pairs (|ρ| > 0.7)
    high_corr_pairs = []
    n = len(valid_codes)
    for i in range(n):
        for j in range(i + 1, n):
            rho = float(corr_matrix[i][j])
            if abs(rho) > 0.7:
                high_corr_pairs.append({
                    "code_a": valid_codes[i],
                    "name_a": valid_names[i],
                    "code_b": valid_codes[j],
                    "name_b": valid_names[j],
                    "correlation": round(rho, 3),
                })

    # R52 P2: Detect high-correlation groups (|ρ| > 0.8, 3+ stocks)
    high_corr_group_alert = False
    high_corr_group_stocks = set()
    for pair in high_corr_pairs:
        if abs(pair["correlation"]) > 0.8:
            high_corr_group_stocks.add(pair["code_a"])
            high_corr_group_stocks.add(pair["code_b"])
    if len(high_corr_group_stocks) >= 3:
        high_corr_group_alert = True

    return make_serializable({
        "has_data": True,
        "codes": valid_codes,
        "names": valid_names,
        "matrix": [[round(float(v), 3) for v in row] for row in corr_matrix],
        "high_corr_pairs": sorted(high_corr_pairs, key=lambda x: -abs(x["correlation"])),
        "data_points": len(ret_df),
        # R52 P2: Correlation alert
        "high_corr_alert": high_corr_group_alert,
        "high_corr_group": sorted(high_corr_group_stocks) if high_corr_group_alert else [],
    })


@router.get("/stress-test")
def get_stress_test():
    """組合壓力測試 — 3 情境模擬（Gemini R32）

    Scenarios:
    1. Base: market -3%
    2. Black Swan: market -7%
    3. Sector Crash: top sector -2×ATR
    """
    from data.fetcher import get_stock_data
    from backend.dependencies import make_serializable

    positions = db.get_open_positions()
    if not positions:
        return make_serializable({"has_data": False, "scenarios": []})

    # Collect per-position data
    pos_data = []
    for p in positions:
        shares = p["lots"] * 1000
        entry = p["entry_price"]
        current = p.get("current_price") or entry
        market_value = current * shares
        sector = p.get("sector", "未分類")

        # Fetch ATR for sector crash scenario
        atr = current * 0.03  # Default 3% if data unavailable
        try:
            df = get_stock_data(p["code"], period_days=30)
            if len(df) >= 15:
                high = df["high"]
                low = df["low"]
                close = df["close"]
                tr = (high - low).combine(abs(high - close.shift(1)), max).combine(abs(low - close.shift(1)), max)
                atr = float(tr.tail(14).mean())
                current = float(close.iloc[-1])
                market_value = current * shares
        except Exception:
            pass

        pos_data.append({
            "code": p["code"],
            "name": p.get("name", ""),
            "lots": p["lots"],
            "current_price": current,
            "market_value": round(market_value),
            "sector": sector,
            "atr": round(atr, 2),
        })

    total_value = sum(pd["market_value"] for pd in pos_data)

    # Scenario 1: Base — market -3%, each stock drops 3% × estimated beta (assume 1.0)
    base_loss = sum(-pd["market_value"] * 0.03 for pd in pos_data)

    # Scenario 2: Black Swan — market -7%
    swan_loss = sum(-pd["market_value"] * 0.07 for pd in pos_data)

    # Scenario 3: Sector Crash — top sector drops 2×ATR per share
    sector_values: dict[str, float] = {}
    for pd in pos_data:
        sector_values[pd["sector"]] = sector_values.get(pd["sector"], 0) + pd["market_value"]
    top_sector = max(sector_values, key=sector_values.get) if sector_values else ""

    sector_crash_loss = 0
    for pd in pos_data:
        if pd["sector"] == top_sector:
            sector_crash_loss -= pd["lots"] * 1000 * pd["atr"] * 2
        else:
            # Other sectors drop 1.5% (sympathetic sell-off)
            sector_crash_loss -= pd["market_value"] * 0.015

    scenarios = [
        {
            "name": "基準回調 (Base)",
            "description": "大盤下跌 3%",
            "estimated_loss": round(base_loss),
            "loss_pct": round(base_loss / total_value, 4) if total_value > 0 else 0,
            "severity": "medium",
        },
        {
            "name": "黑天鵝 (Black Swan)",
            "description": "大盤暴跌 7%",
            "estimated_loss": round(swan_loss),
            "loss_pct": round(swan_loss / total_value, 4) if total_value > 0 else 0,
            "severity": "high",
        },
        {
            "name": f"板塊殺盤 ({top_sector})",
            "description": f"{top_sector} 集體下跌 2×ATR",
            "estimated_loss": round(sector_crash_loss),
            "loss_pct": round(sector_crash_loss / total_value, 4) if total_value > 0 else 0,
            "severity": "high",
        },
    ]

    return make_serializable({
        "has_data": True,
        "total_value": round(total_value),
        "position_count": len(positions),
        "top_sector": top_sector,
        "top_sector_pct": round(sector_values.get(top_sector, 0) / total_value * 100, 1) if total_value > 0 else 0,
        "scenarios": scenarios,
        "positions": pos_data,
    })


@router.get("/optimal-exposure")
def get_optimal_exposure():
    """Kelly Criterion 建議最佳曝險比例（Gemini R34）

    Half-Kelly with market breadth multiplier for Taiwan stock retail context.
    """
    from data.cache import get_cached_sector_heat
    from backend.dependencies import make_serializable

    stats = db.get_closed_stats()
    shadow_stats = db.get_shadow_stats_recent(days=30)

    # Prefer shadow stats (pure system), fall back to user stats
    if shadow_stats["total"] >= 5:
        win_rate = shadow_stats["win_rate"]
    elif stats["total"] >= 5:
        win_rate = stats["win_rate"]
    else:
        return make_serializable({"has_data": False, "reason": "需至少 5 筆已平倉交易"})

    avg_win = stats["avg_win"] if stats["avg_win"] > 0 else 1
    avg_loss = stats["avg_loss"] if stats["avg_loss"] > 0 else 1
    payoff_ratio = avg_win / avg_loss

    # Kelly formula: f* = (p*b - q) / b
    p = win_rate
    b = payoff_ratio
    q = 1 - p
    kelly_full = (p * b - q) / b if b > 0 else 0

    # Half-Kelly for safety (industry standard)
    kelly_half = max(0, min(1, kelly_full * 0.5))

    # Market breadth adjustment
    heat = get_cached_sector_heat()
    breadth = heat.get("market_breadth", 0.5) if heat else 0.5

    if breadth > 0.40:
        breadth_mult = 1.0
        regime = "攻擊"
    elif breadth > 0.20:
        breadth_mult = 0.6
        regime = "盤整"
    else:
        breadth_mult = 0.3
        regime = "防禦"

    suggested_exposure = min(0.95, kelly_half * breadth_mult)
    suggested_cash = 1 - suggested_exposure

    # Current actual exposure
    positions = db.get_open_positions()
    pos_value = sum(
        p["lots"] * 1000 * (p.get("current_price") or p["entry_price"])
        for p in positions
    )
    snapshots = db.get_equity_snapshots(limit=1)
    total_eq = snapshots[-1].get("total_equity", 0) if snapshots else 0
    current_exposure = pos_value / total_eq if total_eq > 0 else 0

    # Over/under-exposed
    delta = current_exposure - suggested_exposure
    if delta > 0.15:
        advice = f"過度曝險 {delta:.0%}，建議減倉至 {suggested_exposure:.0%}"
    elif delta < -0.15:
        advice = f"低於最佳曝險 {abs(delta):.0%}，可適度加碼至 {suggested_exposure:.0%}"
    else:
        advice = "曝險水位適當"

    return make_serializable({
        "has_data": True,
        "kelly_full": round(kelly_full, 4),
        "kelly_half": round(kelly_half, 4),
        "win_rate": round(win_rate, 4),
        "payoff_ratio": round(payoff_ratio, 2),
        "market_breadth": round(breadth, 4),
        "breadth_multiplier": breadth_mult,
        "regime": regime,
        "suggested_exposure": round(suggested_exposure, 4),
        "suggested_cash": round(suggested_cash, 4),
        "current_exposure": round(current_exposure, 4),
        "total_equity": round(total_eq, 0),
        "position_value": round(pos_value, 0),
        "advice": advice,
    })


class ImportCsvRequest(BaseModel):
    """CSV 匯入 — 台灣券商對帳單格式（Gemini R36）"""
    csv_text: str  # Raw CSV content as text


@router.post("/import-csv")
def import_csv(req: ImportCsvRequest):
    """匯入券商 CSV 交易記錄（Gemini R36）

    支援格式（台灣主流券商對帳單）：
    - 日期, 股票代號, 股票名稱, 買賣別, 成交股數, 成交價格
    - 或：date, code, name, action, shares, price
    - 自動偵測欄位名稱（中/英文）
    - 買入→open position, 賣出→close matching position
    """
    import csv
    import io
    from backend.dependencies import make_serializable

    lines = req.csv_text.strip().split("\n")
    if len(lines) < 2:
        return make_serializable({"ok": False, "error": "CSV 至少需要標題列 + 1 筆資料"})

    reader = csv.DictReader(io.StringIO(req.csv_text.strip()))
    fieldnames = reader.fieldnames or []

    # Auto-detect column mapping
    col_map = _detect_csv_columns(fieldnames)
    if not col_map.get("date") or not col_map.get("code"):
        return make_serializable({
            "ok": False,
            "error": f"無法辨識 CSV 欄位: {fieldnames}。需要至少「日期」和「股票代號」欄位",
        })

    # Parse all rows into buy/sell actions
    actions = []
    parse_errors = []
    for i, row in enumerate(reader):
        try:
            date = row.get(col_map["date"], "").strip()
            code = row.get(col_map["code"], "").strip()
            # Normalize date format: 民國年 → 西元年
            date = _normalize_date(date)
            if not date or not code:
                continue

            # Remove .TW suffix if present
            code = code.replace(".TW", "").replace(".tw", "")

            name = row.get(col_map.get("name", ""), "").strip() if col_map.get("name") else ""
            action = row.get(col_map.get("action", ""), "").strip() if col_map.get("action") else "買"

            shares_str = row.get(col_map.get("shares", ""), "0").strip()
            shares = int(shares_str.replace(",", "")) if shares_str else 0

            price_str = row.get(col_map.get("price", ""), "0").strip()
            price = float(price_str.replace(",", "")) if price_str else 0

            if shares <= 0 or price <= 0:
                continue

            lots = max(1, shares // 1000)  # Convert shares to lots (round down, min 1)

            is_buy = any(k in action for k in ("買", "buy", "Buy", "B"))
            is_sell = any(k in action for k in ("賣", "sell", "Sell", "S"))

            actions.append({
                "date": date,
                "code": code,
                "name": name,
                "lots": lots,
                "price": price,
                "is_buy": is_buy,
                "is_sell": is_sell,
            })
        except Exception as e:
            parse_errors.append(f"Row {i+2}: {e}")

    if not actions:
        return make_serializable({"ok": False, "error": "無法解析任何有效交易記錄", "parse_errors": parse_errors})

    # Match buy/sell pairs → create position records
    trades = _match_buy_sell_pairs(actions)

    # Import into DB
    result = db.import_csv_trades(trades)
    result["ok"] = True
    result["total_rows"] = len(actions)
    result["parse_errors"] = parse_errors

    return make_serializable(result)


def _detect_csv_columns(fieldnames: list[str]) -> dict:
    """Auto-detect CSV column mapping (supports 中/英文)."""
    mapping = {}
    for f in fieldnames:
        fl = f.lower().strip()
        if any(k in fl for k in ("日期", "date", "交易日")):
            mapping["date"] = f
        elif any(k in fl for k in ("代號", "代碼", "code", "股號", "證券代號")):
            mapping["code"] = f
        elif any(k in fl for k in ("名稱", "name", "股名", "證券名稱")):
            mapping["name"] = f
        elif any(k in fl for k in ("買賣", "action", "交易", "買賣別")):
            mapping["action"] = f
        elif any(k in fl for k in ("股數", "shares", "成交股數", "數量")):
            mapping["shares"] = f
        elif any(k in fl for k in ("價格", "price", "成交價", "單價", "成交價格")):
            mapping["price"] = f
    return mapping


def _normalize_date(date_str: str) -> str:
    """Normalize date string to YYYY-MM-DD format.

    Supports:
    - 2024-01-15 (already ISO)
    - 2024/01/15
    - 113/01/15 (民國年)
    - 20240115
    """
    import re
    date_str = date_str.strip()
    if not date_str:
        return ""

    # ISO format: 2024-01-15
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str

    # Slash format: 2024/01/15
    if re.match(r"^\d{4}/\d{2}/\d{2}$", date_str):
        return date_str.replace("/", "-")

    # ROC year: 113/01/15 or 113-01-15
    m = re.match(r"^(\d{2,3})[/-](\d{1,2})[/-](\d{1,2})$", date_str)
    if m:
        year = int(m.group(1)) + 1911
        return f"{year}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # Compact: 20240115
    if re.match(r"^\d{8}$", date_str):
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

    return date_str  # Return as-is, let downstream handle


def _match_buy_sell_pairs(actions: list[dict]) -> list[dict]:
    """Match buy and sell actions into position records.

    Gemini R37: Weighted Average Cost accounting.
    For each code:
    1. Sort by date
    2. Accumulate buys into a single aggregate position with weighted average cost:
       C_avg = Σ(Price_i × Lots_i) / Σ(Lots_i)
    3. Sell → close from the aggregate position at C_avg entry price
    """
    from collections import defaultdict

    by_code: dict[str, list] = defaultdict(list)
    for a in actions:
        by_code[a["code"]].append(a)

    trades = []

    for code, code_actions in by_code.items():
        code_actions.sort(key=lambda x: x["date"])

        # Weighted average cost accumulator
        agg_lots = 0
        agg_cost = 0.0  # total cost = Σ(price × lots)
        first_buy_date = ""
        last_name = ""

        for a in code_actions:
            if a["is_buy"]:
                if agg_lots == 0:
                    first_buy_date = a["date"]
                agg_lots += a["lots"]
                agg_cost += a["price"] * a["lots"]
                last_name = a.get("name") or last_name
            elif a["is_sell"] and agg_lots > 0:
                # Weighted average entry price
                avg_price = agg_cost / agg_lots if agg_lots > 0 else a["price"]
                sell_lots = min(a["lots"], agg_lots)

                trades.append({
                    "code": code,
                    "name": last_name or a.get("name", ""),
                    "entry_date": first_buy_date,
                    "entry_price": round(avg_price, 2),
                    "lots": sell_lots,
                    "exit_date": a["date"],
                    "exit_price": a["price"],
                })

                # Reduce aggregate position
                agg_lots -= sell_lots
                agg_cost = avg_price * agg_lots  # Remaining cost at avg price

                if agg_lots <= 0:
                    agg_lots = 0
                    agg_cost = 0.0
                    first_buy_date = ""

        # Remaining unmatched buys → open position at weighted average cost
        if agg_lots > 0:
            avg_price = agg_cost / agg_lots if agg_lots > 0 else 0
            trades.append({
                "code": code,
                "name": last_name,
                "entry_date": first_buy_date,
                "entry_price": round(avg_price, 2),
                "lots": agg_lots,
            })

    return trades


class SimulateRebalanceRequest(BaseModel):
    codes: list[str]


@router.post("/simulate-rebalance")
def simulate_rebalance(req: SimulateRebalanceRequest):
    """模擬重組預覽 — 計算假設持倉的相關性與壓力測試（Gemini R34）

    Takes a list of stock codes and returns what-if correlation matrix + stress test.
    """
    from concurrent.futures import ThreadPoolExecutor
    from data.fetcher import get_stock_data
    from backend.dependencies import make_serializable
    import numpy as np
    import pandas as pd

    codes = list(dict.fromkeys(req.codes))  # dedupe preserving order
    if len(codes) < 2:
        return make_serializable({"has_data": False, "reason": "至少需要 2 檔標的"})

    def _fetch(code):
        try:
            df = get_stock_data(code, period_days=90)
            if len(df) < 30:
                return code, None, None, None
            returns = df["close"].pct_change().dropna().tail(60)
            current = float(df["close"].iloc[-1])
            # ATR for stress test
            high, low, close = df["high"], df["low"], df["close"]
            tr = (high - low).combine(abs(high - close.shift(1)), max).combine(abs(low - close.shift(1)), max)
            atr = float(tr.tail(14).mean())
            return code, returns, current, atr
        except Exception:
            return code, None, None, None

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(_fetch, codes))

    valid = [(c, r, p, a) for c, r, p, a in results if r is not None and len(r) >= 20]
    if len(valid) < 2:
        return make_serializable({"has_data": False, "reason": "數據不足"})

    # Correlation matrix
    ret_df = pd.DataFrame({c: r for c, r, _, _ in valid}).dropna()
    if len(ret_df) < 20:
        return make_serializable({"has_data": False, "reason": "共同交易日不足"})

    corr = ret_df.corr().values
    v_codes = list(ret_df.columns)

    high_corr = []
    n = len(v_codes)
    for i in range(n):
        for j in range(i + 1, n):
            rho = float(corr[i][j])
            if abs(rho) > 0.7:
                high_corr.append({"code_a": v_codes[i], "code_b": v_codes[j], "correlation": round(rho, 3)})

    # Simple stress test (equal-weight 1 lot each)
    prices = {c: p for c, _, p, _ in valid}
    atrs = {c: a for c, _, _, a in valid}
    total_value = sum(prices[c] * 1000 for c in v_codes)
    base_loss = -total_value * 0.03
    swan_loss = -total_value * 0.07
    atr_loss = sum(-atrs[c] * 2 * 1000 for c in v_codes)

    return make_serializable({
        "has_data": True,
        "codes": v_codes,
        "matrix": [[round(float(v), 3) for v in row] for row in corr],
        "high_corr_pairs": sorted(high_corr, key=lambda x: -abs(x["correlation"])),
        "data_points": len(ret_df),
        "stress_test": {
            "total_value": round(total_value),
            "base_loss": round(base_loss),
            "base_pct": round(base_loss / total_value, 4) if total_value > 0 else 0,
            "swan_loss": round(swan_loss),
            "swan_pct": round(swan_loss / total_value, 4) if total_value > 0 else 0,
            "atr_loss": round(atr_loss),
            "atr_pct": round(atr_loss / total_value, 4) if total_value > 0 else 0,
        },
    })


@router.get("/market-regime")
def get_market_regime():
    """市場狀態分類器 — ADX + ATR% 判斷趨勢/震盪（Gemini R35）

    Uses 0050.TW as proxy for Taiwan market.
    ADX > 25 = trending, < 20 = ranging.
    ATR% > median = high volatility, else low.
    """
    from data.fetcher import get_stock_data
    from backend.dependencies import make_serializable

    try:
        df = get_stock_data("0050", period_days=120)
    except Exception:
        return make_serializable({"has_data": False})

    if len(df) < 60:
        return make_serializable({"has_data": False})

    import numpy as np

    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    # True Range
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))

    # ATR14
    atr_vals = []
    atr = np.mean(tr[:14])
    for i in range(14, len(tr)):
        atr = (atr * 13 + tr[i]) / 14
        atr_vals.append(atr)

    # +DM / -DM
    plus_dm = np.maximum(high[1:] - high[:-1], 0)
    minus_dm = np.maximum(low[:-1] - low[1:], 0)
    # Zero out when opposite is larger
    mask = plus_dm > minus_dm
    minus_dm[mask & (plus_dm > minus_dm)] = 0
    mask2 = minus_dm > plus_dm
    plus_dm[mask2 & (minus_dm > plus_dm)] = 0

    # Smoothed DI
    def _smooth(arr, period=14):
        result = []
        s = np.mean(arr[:period])
        for i in range(period, len(arr)):
            s = (s * (period - 1) + arr[i]) / period
            result.append(s)
        return np.array(result)

    smooth_tr = _smooth(tr)
    smooth_plus = _smooth(plus_dm)
    smooth_minus = _smooth(minus_dm)

    n = min(len(smooth_tr), len(smooth_plus), len(smooth_minus))
    plus_di = smooth_plus[:n] / smooth_tr[:n] * 100
    minus_di = smooth_minus[:n] / smooth_tr[:n] * 100

    # DX → ADX
    dx = np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10) * 100
    adx_vals = []
    if len(dx) >= 14:
        adx = np.mean(dx[:14])
        for i in range(14, len(dx)):
            adx = (adx * 13 + dx[i]) / 14
            adx_vals.append(adx)

    current_adx = float(adx_vals[-1]) if adx_vals else 20
    current_atr = float(atr_vals[-1]) if atr_vals else 0
    current_close = float(close[-1])
    atr_pct = current_atr / current_close if current_close > 0 else 0.02
    median_atr_pct = float(np.median([a / c for a, c in zip(atr_vals[-30:], close[-30:])]))

    # Classify regime
    is_trending = current_adx >= 25
    is_high_vol = atr_pct > median_atr_pct

    if is_trending and is_high_vol:
        regime = "趨勢噴發"
        regime_en = "trend_explosive"
        description = "趨勢明確+波動大，V4 策略最佳環境"
        kelly_mult = 1.0
    elif is_trending and not is_high_vol:
        regime = "溫和趨勢"
        regime_en = "trend_mild"
        description = "趨勢明確但波動收斂，適合加碼"
        kelly_mult = 0.9
    elif not is_trending and is_high_vol:
        regime = "震盪劇烈"
        regime_en = "range_volatile"
        description = "無趨勢+高波動，V4 易被洗盤，建議減碼"
        kelly_mult = 0.4
    else:
        regime = "低波盤整"
        regime_en = "range_quiet"
        description = "無趨勢+低波動，等待突破，輕倉觀望"
        kelly_mult = 0.5

    return make_serializable({
        "has_data": True,
        "regime": regime,
        "regime_en": regime_en,
        "description": description,
        "kelly_multiplier": kelly_mult,
        "adx": round(current_adx, 2),
        "atr": round(current_atr, 2),
        "atr_pct": round(atr_pct, 4),
        "median_atr_pct": round(median_atr_pct, 4),
        "close": round(current_close, 2),
        "is_trending": is_trending,
        "is_high_vol": is_high_vol,
    })


@router.get("/efficient-frontier")
def get_efficient_frontier():
    """效率前緣分析 — Markowitz 均值-變異數優化（Gemini R35）

    Monte Carlo simulation with 3000 random portfolios.
    Returns scatter data, current portfolio point, and max Sharpe point.
    """
    from concurrent.futures import ThreadPoolExecutor
    from data.fetcher import get_stock_data
    from backend.dependencies import make_serializable
    import numpy as np

    positions = db.get_open_positions()
    if len(positions) < 2:
        return make_serializable({"has_data": False})

    codes = [p["code"] for p in positions]
    lots = {p["code"]: p["lots"] for p in positions}

    def _get_returns(code):
        try:
            df = get_stock_data(code, period_days=120)
            if len(df) < 60:
                return code, None
            return code, df["close"].pct_change().dropna().tail(60)
        except Exception:
            return code, None

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(_get_returns, codes))

    import pandas as pd
    valid = [(c, r) for c, r in results if r is not None and len(r) >= 30]
    if len(valid) < 2:
        return make_serializable({"has_data": False})

    ret_df = pd.DataFrame({c: r for c, r in valid}).dropna()
    if len(ret_df) < 30:
        return make_serializable({"has_data": False})

    v_codes = list(ret_df.columns)
    mean_returns = ret_df.mean().values * 252  # Annualized
    cov_matrix = ret_df.cov().values * 252  # Annualized
    n = len(v_codes)
    rf = 0.015

    # Current portfolio weights (by market value)
    total_lots = sum(lots.get(c, 1) for c in v_codes)
    current_weights = np.array([lots.get(c, 1) / total_lots for c in v_codes])

    # Current portfolio stats
    cur_ret = float(current_weights @ mean_returns)
    cur_vol = float(np.sqrt(current_weights @ cov_matrix @ current_weights))
    cur_sharpe = (cur_ret - rf) / cur_vol if cur_vol > 0 else 0

    # Monte Carlo: 3000 random portfolios
    n_sim = 3000
    sim_returns = []
    sim_vols = []
    sim_sharpes = []
    best_sharpe = -999
    best_weights = current_weights.copy()

    rng = np.random.default_rng(42)
    for _ in range(n_sim):
        w = rng.random(n)
        w = w / w.sum()
        ret = float(w @ mean_returns)
        vol = float(np.sqrt(w @ cov_matrix @ w))
        sharpe = (ret - rf) / vol if vol > 0 else 0
        sim_returns.append(round(ret, 4))
        sim_vols.append(round(vol, 4))
        sim_sharpes.append(round(sharpe, 3))
        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_weights = w.copy()

    # Max Sharpe portfolio
    max_ret = float(best_weights @ mean_returns)
    max_vol = float(np.sqrt(best_weights @ cov_matrix @ best_weights))

    return make_serializable({
        "has_data": True,
        "codes": v_codes,
        "sim_returns": sim_returns,
        "sim_vols": sim_vols,
        "sim_sharpes": sim_sharpes,
        "current": {
            "return": round(cur_ret, 4),
            "volatility": round(cur_vol, 4),
            "sharpe": round(cur_sharpe, 3),
            "weights": {c: round(float(w), 4) for c, w in zip(v_codes, current_weights)},
        },
        "max_sharpe": {
            "return": round(max_ret, 4),
            "volatility": round(max_vol, 4),
            "sharpe": round(best_sharpe, 3),
            "weights": {c: round(float(w), 4) for c, w in zip(v_codes, best_weights)},
        },
        "data_points": len(ret_df),
    })


@router.post("/rebalance-plan")
def generate_rebalance_plan():
    """自動重組交易計劃 — 根據效率前緣最佳權重產生買賣指令（Gemini R36）

    比較目前持倉與 Max Sharpe 最佳組合，產生具體買/賣張數建議。
    """
    from data.fetcher import get_stock_data
    from backend.dependencies import make_serializable

    positions = db.get_open_positions()
    if len(positions) < 2:
        return make_serializable({"has_data": False, "reason": "至少需 2 檔持倉"})

    # Get efficient frontier optimal weights
    ef_data = get_efficient_frontier()
    if not ef_data.get("has_data"):
        return make_serializable({"has_data": False, "reason": "效率前緣計算失敗"})

    optimal_weights = ef_data["max_sharpe"]["weights"]
    current_weights = ef_data["current"]["weights"]
    codes = ef_data["codes"]

    # Get current prices and position details
    pos_map = {}
    for p in positions:
        if p["code"] in codes:
            current_price = p.get("current_price") or p["entry_price"]
            pos_map[p["code"]] = {
                "code": p["code"],
                "name": p.get("name", ""),
                "lots": p["lots"],
                "entry_price": p["entry_price"],
                "current_price": current_price,
                "market_value": current_price * p["lots"] * 1000,
            }

    total_value = sum(pm["market_value"] for pm in pos_map.values())

    # Calculate target lots vs current lots
    orders = []
    for code in codes:
        if code not in pos_map:
            continue

        current_lots = pos_map[code]["lots"]
        current_price = pos_map[code]["current_price"]
        optimal_w = optimal_weights.get(code, 0)
        current_w = current_weights.get(code, 0)

        target_value = total_value * optimal_w
        target_lots = round(target_value / (current_price * 1000)) if current_price > 0 else current_lots
        delta_lots = target_lots - current_lots

        if delta_lots == 0:
            continue

        action = "買入" if delta_lots > 0 else "賣出"
        est_amount = abs(delta_lots) * current_price * 1000

        orders.append({
            "code": code,
            "name": pos_map[code]["name"],
            "action": action,
            "current_lots": current_lots,
            "target_lots": target_lots,
            "delta_lots": abs(delta_lots),
            "current_weight": round(current_w, 4),
            "target_weight": round(optimal_w, 4),
            "estimated_amount": round(est_amount, 0),
            "price": round(current_price, 2),
        })

    # Sort: sells first (free up capital), then buys
    orders.sort(key=lambda x: (0 if x["action"] == "賣出" else 1, -x["estimated_amount"]))

    total_buy = sum(o["estimated_amount"] for o in orders if o["action"] == "買入")
    total_sell = sum(o["estimated_amount"] for o in orders if o["action"] == "賣出")
    net_cash_flow = total_sell - total_buy

    return make_serializable({
        "has_data": True,
        "orders": orders,
        "total_value": round(total_value, 0),
        "total_buy": round(total_buy, 0),
        "total_sell": round(total_sell, 0),
        "net_cash_flow": round(net_cash_flow, 0),
        "optimal_sharpe": ef_data["max_sharpe"]["sharpe"],
        "current_sharpe": ef_data["current"]["sharpe"],
    })


@router.get("/behavioral-audit")
def get_behavioral_audit():
    """AI 行為鏡像 — 交易標籤績效分析（Gemini R35）"""
    from backend.dependencies import make_serializable

    tag_stats = db.get_tag_performance()
    if not tag_stats:
        return make_serializable({"has_data": False})

    # Identify worst behavioral pattern
    worst = None
    for ts in tag_stats:
        if ts["count"] >= 2 and ts["win_rate"] < 0.35:
            if worst is None or ts["win_rate"] < worst["win_rate"]:
                worst = ts

    # Identify best pattern
    best = None
    for ts in tag_stats:
        if ts["count"] >= 2 and ts["win_rate"] >= 0.60:
            if best is None or ts["win_rate"] > best["win_rate"]:
                best = ts

    return make_serializable({
        "has_data": True,
        "tag_stats": tag_stats,
        "worst_pattern": worst,
        "best_pattern": best,
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

    # 7. Market breadth regime diagnosis (Gemini R31)
    if heat:
        breadth = heat.get("market_breadth", 0)
        total_buy = heat.get("total_buy", 0)
        scanned = heat.get("scanned", 0)
        if breadth <= 0.20:
            insights.append({
                "type": "market_regime",
                "severity": "high",
                "icon": "🛡️",
                "message": (
                    f"防禦模式：市場寬度僅 {breadth:.0%}（{total_buy}/{scanned} 檔 BUY），"
                    f"影子組合已停止開倉，請減少主觀交易"
                ),
            })
        elif breadth <= 0.40:
            insights.append({
                "type": "market_regime",
                "severity": "medium",
                "icon": "⚖️",
                "message": f"盤整模式：市場寬度 {breadth:.0%}，影子組合限縮至 2 檔，謹慎操作",
            })

    # 8. Shadow portfolio comparison (Gemini R30)
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

    # 9. Strategy drift monitor: check shadow trade win rate (Gemini R33)
    shadow_stats = db.get_shadow_stats_recent(days=30)
    if shadow_stats["total"] >= 5 and shadow_stats["win_rate"] < 0.40:
        insights.append({
            "type": "strategy_drift",
            "severity": "high",
            "icon": "⚠️",
            "message": (
                f"策略適應性下降：過去 30 天影子組合勝率僅 {shadow_stats['win_rate']:.0%}"
                f"（{shadow_stats['wins']}/{shadow_stats['total']} 筆），"
                f"目前市場可能不適合趨勢追蹤，建議縮減信心乘數 (C) 至 0.7x"
            ),
        })

    # 10. Rotation suggestions: held cooling → new surge leader (Gemini R32)
    if positions and heat:
        sector_lookup = {s["sector"]: s for s in heat.get("sectors", [])}
        for p in positions:
            p_sector = p.get("sector", "")
            sector_info = sector_lookup.get(p_sector, {})
            p_momentum = sector_info.get("momentum", "stable")
            # Check if held stock is in cooling sector
            if p_momentum in ("cooling",):
                # Find a surge sector with a leader in a different L1 sector
                for s_data in heat.get("sectors", []):
                    if s_data.get("momentum") == "surge" and s_data.get("leader"):
                        leader = s_data["leader"]
                        if leader["code"] != p["code"]:
                            insights.append({
                                "type": "rotation",
                                "severity": "medium",
                                "icon": "🔄",
                                "message": (
                                    f"換股建議：{p['code']} {p.get('name', '')} 所屬 {p_sector} 動能降溫 → "
                                    f"轉進 {leader['code']} {leader['name']} ({s_data['sector']} Surge, Score={leader['score']:.2f})"
                                ),
                            })
                            break  # One rotation per cooling position
                if len(insights) >= 5:
                    break

    # 11. Kelly exposure advice (Gemini R34)
    stats = db.get_closed_stats()
    if stats["total"] >= 5:
        from data.cache import get_cached_sector_heat as _gsh
        _heat = _gsh()
        _breadth = _heat.get("market_breadth", 0.5) if _heat else 0.5
        _wr = shadow_stats["win_rate"] if shadow_stats["total"] >= 5 else stats["win_rate"]
        _avg_w = stats["avg_win"] if stats["avg_win"] > 0 else 1
        _avg_l = stats["avg_loss"] if stats["avg_loss"] > 0 else 1
        _b = _avg_w / _avg_l
        _kelly = max(0, (_wr * _b - (1 - _wr)) / _b * 0.5) if _b > 0 else 0
        _bm = 1.0 if _breadth > 0.40 else (0.6 if _breadth > 0.20 else 0.3)
        _sug = min(0.95, _kelly * _bm)
        _pos_val = sum(p["lots"] * 1000 * (p.get("current_price") or p["entry_price"]) for p in positions) if positions else 0
        _snaps = db.get_equity_snapshots(limit=1)
        _teq = _snaps[-1].get("total_equity", 0) if _snaps else 0
        _cur_exp = _pos_val / _teq if _teq > 0 else 0
        if _cur_exp > _sug + 0.15:
            insights.append({
                "type": "kelly_overexposed",
                "severity": "high",
                "icon": "💰",
                "message": (
                    f"現金管理：目前曝險 {_cur_exp:.0%} 超出 Kelly 建議 {_sug:.0%}，"
                    f"建議提高現金儲備（勝率 {_wr:.0%}，賠率 {_b:.1f}x，寬度 {_breadth:.0%}）"
                ),
            })

    # 12. Behavioral mirror: worst-performing tag pattern (Gemini R35)
    tag_stats = db.get_tag_performance()
    for ts in tag_stats:
        if ts["count"] >= 3 and ts["win_rate"] < 0.30:
            insights.append({
                "type": "behavioral",
                "severity": "high",
                "icon": "🪞",
                "message": (
                    f"行為鏡像：帶有「{ts['tag']}」標籤的交易勝率僅 {ts['win_rate']:.0%}"
                    f"（{ts['count']} 筆，淨損益 ${ts['total_pnl']:,.0f}），"
                    f"建議在此類交易前強制執行冷靜期"
                ),
            })
            break  # Only the worst pattern

    # 13. If no insights, add a neutral one
    if not insights:
        insights.append({
            "type": "neutral",
            "severity": "low",
            "icon": "📋",
            "message": "目前無重大警報，市場穩定運行中",
        })

    # --- Action Hub: Top 3 Priority Actions (Gemini R33) ---
    # Assign weights for priority sorting
    _ACTION_WEIGHTS = {
        "exit_alert": 100,
        "strategy_drift": 95,
        "post_mortem": 90,
        "hidden_exposure": 85,
        "concentration": 80,
        "market_regime": 75,
        "kelly_overexposed": 72,
        "shadow_comparison": 70,
        "behavioral": 68,
        "self_correction": 65,
        "sector_surge": 55,
        "rotation": 50,
        "sector_heating": 40,
        "transition": 30,
        "neutral": 0,
    }

    # Map insight types to action verbs
    _ACTION_LABELS = {
        "exit_alert": "緊急平倉",
        "strategy_drift": "策略調整",
        "post_mortem": "交易紀律",
        "hidden_exposure": "曝險警告",
        "concentration": "組合優化",
        "market_regime": "風險防禦",
        "kelly_overexposed": "現金管理",
        "shadow_comparison": "績效檢視",
        "behavioral": "行為修正",
        "self_correction": "自我修正",
        "sector_surge": "進場機會",
        "rotation": "換股建議",
        "sector_heating": "關注板塊",
        "transition": "成熟度變化",
        "neutral": "持續觀察",
    }

    # Sort all insights by weight, pick top 3
    sorted_insights = sorted(insights, key=lambda x: -_ACTION_WEIGHTS.get(x["type"], 0))
    priority_actions = []
    for ins in sorted_insights[:3]:
        priority_actions.append({
            "label": _ACTION_LABELS.get(ins["type"], "注意"),
            "icon": ins["icon"],
            "severity": ins["severity"],
            "message": ins["message"],
            "type": ins["type"],
        })

    # Keep top 5 for regular insights
    insights = insights[:5]

    return make_serializable({
        "insights": insights,
        "priority_actions": priority_actions,
        "generated_at": datetime.now().isoformat(),
    })


def _calculate_summary(positions: list, closed: list) -> dict:
    """Calculate portfolio summary metrics."""
    if not positions:
        return _empty_summary()

    total_cost = sum(p["entry_price"] * p["lots"] * 1000 for p in positions)
    total_value = sum((p.get("market_value") or 0) for p in positions)
    total_pnl = sum((p.get("pnl") or 0) for p in positions)
    total_pnl_pct = (total_value / total_cost - 1) if total_cost > 0 else 0

    exit_alert_count = sum(1 for p in positions if p.get("exit_signals"))

    # Closed trade stats
    closed_pnl = sum((c.get("net_pnl") or 0) for c in closed)
    wins = [c for c in closed if (c.get("net_pnl") or 0) > 0]
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

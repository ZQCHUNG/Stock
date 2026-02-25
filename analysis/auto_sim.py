"""Auto-Sim Pipeline — Screener → find_similar_dual → LINE Notify.

P2-B: CTO Gemini directive — 全自動化決策鏈條
Daily at 20:30 after screener refresh:
  1. Query screener for RS > 80 stocks
  2. Run find_similar_dual on candidates
  3. Rank by sniper_assessment + confidence
  4. Diversify: max 2 per L1 industry
  5. Send LINE Notify with CTO-mandated format

[HYPOTHESIS: AUTOSIM_RS_THRESHOLD = 80, MAX_PER_INDUSTRY = 2, TOP_N = 5]
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Configurable thresholds
RS_THRESHOLD = 80          # [HYPOTHESIS] Screener RS Rating minimum
TOP_N = 5                  # Max signals per notification
MAX_PER_INDUSTRY = 2       # Industry diversification cap
SIM_TOP_K = 20             # find_similar_dual top_k

# Position Sizing V1 (Phase 5)
# [HYPOTHESIS: RISK_PER_TRADE = 0.02, MAX_POSITION_PCT = 0.20]
ASSUMED_EQUITY = 3_000_000   # [PLACEHOLDER] Joe's assumed equity (TWD)
RISK_PER_TRADE = 0.02        # [HYPOTHESIS] 2% of equity per trade
MAX_POSITION_PCT = 0.20      # Max 20% of equity in single stock


def _tier_score(tier: str) -> int:
    """Convert sniper tier to numeric score for sorting."""
    return {"sniper": 3, "tactical": 2, "avoid": 1}.get(tier, 0)


def _format_advice(confidence_score: int) -> str:
    """CTO-mandated auto advice based on confidence score."""
    if confidence_score >= 70:
        return "強力買入 (High Confidence)"
    elif confidence_score >= 40:
        return "謹慎嘗試 (Medium Confidence)"
    return "觀望 (Low Confidence)"


def run_auto_sim(
    rs_threshold: int = RS_THRESHOLD,
    top_n: int = TOP_N,
    max_per_industry: int = MAX_PER_INDUSTRY,
) -> dict:
    """Run the full Auto-Sim Pipeline.

    Returns:
        {
            "candidates_found": int,
            "simulated": int,
            "top_signals": [{stock_code, name, rs_rating, tier, similarity,
                             confidence_score, d21_stats, industry}, ...],
            "message": str,  # Formatted LINE message
            "elapsed_s": float,
        }
    """
    t0 = time.time()

    # Step 1: Query screener for high RS stocks
    from analysis.financial_screener import screen_stocks
    from data.sector_mapping import get_stock_sector

    candidates = screen_stocks({
        "rs_rating": {"op": ">=", "value": rs_threshold},
        "sort_by": "rs_rating",
        "sort_desc": True,
        "limit": 50,
    })

    if not candidates:
        elapsed = round(time.time() - t0, 1)
        return {
            "candidates_found": 0,
            "simulated": 0,
            "top_signals": [],
            "message": "",
            "elapsed_s": elapsed,
        }

    logger.info("Auto-Sim: %d candidates with RS >= %d", len(candidates), rs_threshold)

    # Step 2: Run find_similar_dual for each candidate
    from analysis.cluster_search import find_similar_dual
    from analysis.pattern_simulator import _compute_confidence

    sim_results = []
    for stock in candidates:
        code = stock.get("code", "")
        name = stock.get("name", "")
        rs = stock.get("rs_rating", 0)
        industry = get_stock_sector(code, level=1) or "其他"

        try:
            dual = find_similar_dual(
                stock_code=code,
                top_k=SIM_TOP_K,
            )
        except Exception as e:
            logger.debug("Sim failed for %s: %s", code, e)
            continue

        sniper = dual.get("sniper_assessment", {})
        tier = sniper.get("tier", "avoid")
        mean_sim = sniper.get("mean_similarity", 0)

        # Extract d21 stats from raw block
        raw_stats = dual.get("raw", {}).get("statistics", {})
        d21 = raw_stats.get("d21", {})

        # Compute confidence from raw cases
        raw_cases = dual.get("raw", {}).get("similar_cases", [])
        # Build enriched cases for confidence (need returns dict)
        enriched = []
        for case in raw_cases:
            fwd = case.get("forward_returns", {})
            enriched.append({"returns": fwd})

        conf = _compute_confidence(enriched, {"d21": d21})
        conf_score = conf.get("score", 0)
        conf_range = conf.get("expected_return_range", {})

        # Worst case from spaghetti (if available)
        raw_paths = dual.get("raw", {}).get("forward_paths", [])
        worst_return = None
        if raw_paths:
            finals = [p["path"][-1]["value"] if p["path"] else 1.0 for p in raw_paths]
            if finals:
                worst_return = round((min(finals) - 1.0) * 100, 1)

        sim_results.append({
            "stock_code": code,
            "name": name,
            "rs_rating": rs,
            "industry": industry,
            "tier": tier,
            "tier_score": _tier_score(tier),
            "mean_similarity": round(mean_sim, 3),
            "confidence_score": conf_score,
            "confidence_grade": conf.get("grade", "LOW"),
            "d21_win_rate": d21.get("win_rate"),
            "d21_mean": d21.get("mean"),
            "d21_expectancy": d21.get("expectancy"),
            "ci_low": conf_range.get("low"),
            "ci_high": conf_range.get("high"),
            "worst_case_pct": worst_return,
            "sample_count": raw_stats.get("sample_count", 0),
            "divergence_warning": dual.get("divergence_warning", False),
        })

    logger.info("Auto-Sim: %d/%d stocks simulated", len(sim_results), len(candidates))

    # Step 2.5: Market Context Factor (Phase 4 Scoring V2)
    # CTO directive: "在空頭市場頻繁開火是多頭策略最容易死掉的地方"
    # TAIEX < MA20 → Score -10, TAIEX > MA20 + RS > 90 → Score +5
    market_adj = _get_market_context_adjustment()
    if market_adj != 0:
        for s in sim_results:
            adj = market_adj
            # Extra bonus for RS > 90 in bull market
            if market_adj > 0 and s["rs_rating"] >= 90:
                adj += 5
            s["confidence_score"] = max(0, min(100, s["confidence_score"] + adj))
            # Re-grade
            score = s["confidence_score"]
            s["confidence_grade"] = "HIGH" if score >= 70 else "MEDIUM" if score >= 40 else "LOW"
        logger.info("Auto-Sim: Market Context adjustment=%+d applied", market_adj)

    # Step 3: Sort by tier_score desc → confidence_score desc
    sim_results.sort(key=lambda x: (x["tier_score"], x["confidence_score"]), reverse=True)

    # Step 4: Industry diversification
    industry_count: dict[str, int] = {}
    top_signals = []
    for s in sim_results:
        ind = s["industry"]
        if industry_count.get(ind, 0) >= max_per_industry:
            continue
        industry_count[ind] = industry_count.get(ind, 0) + 1
        top_signals.append(s)
        if len(top_signals) >= top_n:
            break

    # Step 4.5: Compute position sizing (Phase 5)
    for s in top_signals:
        try:
            from analysis.signal_log import _get_closing_price
            price = _get_closing_price(s["stock_code"])
            if price:
                sizing = _compute_position_size(
                    entry_price=price,
                    worst_case_pct=s.get("worst_case_pct"),
                    confidence_score=s.get("confidence_score", 0),
                )
                s["entry_price"] = price
                s["position_pct"] = sizing["position_pct"]
                s["position_lots"] = sizing["lots"]
                s["position_rationale"] = sizing["rationale"]
        except Exception:
            pass

    # Step 5: Format LINE message
    message = _format_line_message(top_signals)

    # Step 6: Log signals to trade log (P3: signal accountability)
    signals_logged = 0
    if top_signals:
        try:
            from analysis.signal_log import log_signals_batch
            signals_logged = log_signals_batch(top_signals)
            logger.info("Auto-Sim: %d signals logged to trade log", signals_logged)
        except Exception as e:
            logger.warning("Auto-Sim: Failed to log signals: %s", e)

    # Step 7: Check risk flag — suppress recommendations if risk-off
    risk_suppressed = False
    try:
        from analysis.drift_detector import get_risk_flag
        flag = get_risk_flag()
        if not flag.get("global_risk_on", True):
            message = _format_risk_off_message(flag)
            risk_suppressed = True
            logger.info("Auto-Sim: Risk flag OFF — suppressing recommendations")
    except Exception:
        pass

    elapsed = round(time.time() - t0, 1)
    return {
        "candidates_found": len(candidates),
        "simulated": len(sim_results),
        "top_signals": top_signals,
        "message": message,
        "elapsed_s": elapsed,
        "signals_logged": signals_logged,
        "risk_suppressed": risk_suppressed,
    }


def _compute_position_size(
    entry_price: float,
    worst_case_pct: float,
    confidence_score: int,
    equity: float = ASSUMED_EQUITY,
) -> dict:
    """Phase 5: Risk-based position sizing.

    Formula: PositionSize = (Equity * RiskPerTrade) / (Entry - WorstCasePrice)
    Capped at MAX_POSITION_PCT of equity.

    CTO directive: "不要讓 Joe 每次都買一樣多"

    Returns:
        {"position_pct": float, "shares": int, "lots": int, "rationale": str}
    """
    if not entry_price or entry_price <= 0:
        return {"position_pct": 0, "shares": 0, "lots": 0, "rationale": "No entry price"}

    # Compute worst case price from percentage
    if worst_case_pct is not None and worst_case_pct < 0:
        worst_case_price = entry_price * (1 + worst_case_pct / 100.0)
    else:
        # Default: assume 7% stop loss
        worst_case_price = entry_price * 0.93

    risk_per_share = entry_price - worst_case_price
    if risk_per_share <= 0:
        return {"position_pct": 0, "shares": 0, "lots": 0, "rationale": "Invalid risk"}

    # Risk amount = equity * risk_per_trade
    risk_amount = equity * RISK_PER_TRADE

    # Shares from risk sizing
    shares = int(risk_amount / risk_per_share)

    # Position value
    position_value = shares * entry_price
    position_pct = position_value / equity if equity > 0 else 0

    # Cap at MAX_POSITION_PCT
    if position_pct > MAX_POSITION_PCT:
        position_pct = MAX_POSITION_PCT
        position_value = equity * MAX_POSITION_PCT
        shares = int(position_value / entry_price)

    # Round to lots (1 lot = 1000 shares in TW)
    lots = max(1, shares // 1000)
    shares = lots * 1000
    position_pct = (shares * entry_price) / equity if equity > 0 else 0

    # Confidence adjustment: HIGH=full, MEDIUM=70%, LOW=50%
    if confidence_score < 40:
        lots = max(1, lots // 2)
        shares = lots * 1000
        position_pct = (shares * entry_price) / equity
    elif confidence_score < 70:
        lots = max(1, int(lots * 0.7))
        shares = lots * 1000
        position_pct = (shares * entry_price) / equity

    return {
        "position_pct": round(position_pct, 4),
        "shares": shares,
        "lots": lots,
        "rationale": f"Risk {RISK_PER_TRADE:.0%}, Stop {worst_case_pct or -7:.1f}%",
    }


def _get_market_context_adjustment() -> int:
    """Phase 4 Scoring V2: Market Context Factor.

    CTO directive:
    - TAIEX < MA20 → all scores -10 (bear filter)
    - TAIEX > MA20 → base +0 (neutral, RS>90 gets extra +5 in caller)

    [HYPOTHESIS: MARKET_CONTEXT_PENALTY = -10, MARKET_CONTEXT_BONUS = 0]
    """
    try:
        from data.fetcher import get_taiex_data
        import pandas as pd

        taiex = get_taiex_data(period_days=60)
        if taiex is None or len(taiex) < 25:
            return 0

        close = taiex["close"]
        ma20 = close.rolling(20).mean()
        latest_close = float(close.iloc[-1])
        latest_ma20 = float(ma20.iloc[-1])

        if latest_close < latest_ma20:
            return -10  # Bear filter
        return 0  # Neutral (RS>90 bonus handled by caller)
    except Exception:
        return 0  # Default: no adjustment


def _format_line_message(signals: list[dict]) -> str:
    """Format CTO-mandated LINE Notify message.

    Format per CTO directive:
    🚀 Bold Strategy Signal [2330 台積電]
    Score: 73 (HIGH)
    🔹 機率預測: CI 95% (-7.6% ~ -1.7%)
    🔹 預期路徑: Mean Path -4.6% (T+21)
    ⚠️ 風險警告: Worst Case -15%
    💡 建議: 強力買入 / 謹慎嘗試 / 觀望
    """
    if not signals:
        return ""

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [f"\n📊 Auto-Sim Daily Report ({now})"]
    lines.append(f"共 {len(signals)} 檔高信心標的:\n")

    for s in signals:
        tier_icon = "🎯" if s["tier"] == "sniper" else "🔶" if s["tier"] == "tactical" else "⚪"
        grade = s.get("confidence_grade", "LOW")

        lines.append(f"{tier_icon} [{s['stock_code']} {s['name']}]")
        lines.append(f"  Score: {s['confidence_score']} ({grade}) | RS: {s['rs_rating']:.0f}")

        # CI range
        ci_low = s.get("ci_low")
        ci_high = s.get("ci_high")
        if ci_low is not None and ci_high is not None:
            lines.append(f"  CI 95%: {ci_low*100:.1f}% ~ {ci_high*100:.1f}% (T+21)")

        # Mean return
        d21_mean = s.get("d21_mean")
        if d21_mean is not None:
            lines.append(f"  Mean Path: {d21_mean*100:.1f}% (T+21)")

        # Risk
        worst = s.get("worst_case_pct")
        if worst is not None:
            lines.append(f"  ⚠️ Worst Case: {worst:+.1f}%")

        # Advice
        advice = _format_advice(s["confidence_score"])
        lines.append(f"  💡 {advice}")

        # Position sizing (Phase 5)
        pos_pct = s.get("position_pct")
        pos_lots = s.get("position_lots")
        if pos_pct is not None and pos_lots:
            lines.append(f"  📊 建議倉位: {pos_pct:.0%} ({pos_lots} 張)")

        # Divergence warning
        if s.get("divergence_warning"):
            lines.append("  ⚠️ Block Divergence Warning")

        lines.append("")  # blank separator

    lines.append(f"(n={signals[0].get('sample_count', '?')} similar cases)")
    return "\n".join(lines)


def _format_risk_off_message(flag: dict) -> str:
    """Format risk-off message when global_risk_on is False."""
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    reason = flag.get("reason", "模型信心不足")
    return (
        f"\n⚠️ 系統維護中 ({now})\n"
        f"模型信心不足，建議觀望\n"
        f"原因: {reason}\n"
        f"待週報確認模型恢復後自動重啟"
    )


def send_auto_sim_notification(result: dict) -> bool:
    """Send Auto-Sim results via LINE Notify.

    Returns True if sent successfully.
    """
    message = result.get("message", "")
    if not message:
        logger.info("Auto-Sim: No signals to send")
        return False

    try:
        from backend.scheduler import _send_notification
        _send_notification(message)
        logger.info("Auto-Sim: LINE notification sent (%d signals)", len(result.get("top_signals", [])))
        return True
    except Exception as e:
        logger.warning("Auto-Sim: Notification failed: %s", e)
        return False

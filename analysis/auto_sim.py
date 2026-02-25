"""Auto-Sim Pipeline — Screener → find_similar_dual → LINE Notify.

P2-B: CTO Gemini directive — 全自動化決策鏈條
Daily at 20:30 after screener refresh:
  1. Query screener for RS > 80 stocks
  2. Run find_similar_dual on candidates
  2.3. Energy Quality Filter (Phase 7 P0)
  2.4. Sector RS Bonus (Phase 8 P1)
  2.6. History Success Rate Back-weighting (Phase 9 P0)
  2.5. Market Context adjustment
  3. Rank by sniper_assessment + confidence
  4. Diversify: max 2 per L1 industry
  5. Send LINE Notify with CTO-mandated format

[HYPOTHESIS: AUTOSIM_RS_THRESHOLD = 80, MAX_PER_INDUSTRY = 2, TOP_N = 5]
[HYPOTHESIS: SIGNAL_QUALITY_V1 — TR>2.5xATR=overheat, Vol<1.5xAvg=weak]
[HYPOTHESIS: INDUSTRY_EXPERIENCE_WEIGHTS_V1 — WinRate>70%=+3, <40%=-5]
"""

import logging
import time
from pathlib import Path
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

# Energy Score (Phase 7 P0) — [HYPOTHESIS: SIGNAL_QUALITY_V1]
# Architect approved: "動能與波動平衡器"
ENERGY_OVERHEAT_TR_MULT = 2.5   # TR > 2.5x ATR20 → climax / momentum exhaustion
ENERGY_WEAK_VOL_MULT = 1.5      # Vol < 1.5x 5-day avg → weak breakout
ENERGY_OVERHEAT_PENALTY = 0.8   # Confidence × 0.8
ENERGY_WEAK_VOL_PENALTY = 0.9   # Confidence × 0.9

# History Success Rate (Phase 9 P0) — [HYPOTHESIS: INDUSTRY_EXPERIENCE_WEIGHTS_V1]
# Architect approved: "避開陷阱比追逐更高勝率對淨值貢獻更直接"
SUCCESS_RATE_HIGH_THRESHOLD = 0.70  # In-Bounds Rate > 70% → bonus
SUCCESS_RATE_LOW_THRESHOLD = 0.40   # In-Bounds Rate < 40% → penalty
SUCCESS_RATE_BONUS = 3              # +3 for high-success industries
SUCCESS_RATE_PENALTY = -5           # -5 for low-success industries
SUCCESS_RATE_MIN_SAMPLES = 3        # Minimum signals to compute rate


def _tier_score(tier: str) -> int:
    """Convert sniper tier to numeric score for sorting."""
    return {"sniper": 3, "tactical": 2, "avoid": 1}.get(tier, 0)


def _compute_energy_score(stock_code: str) -> dict:
    """Phase 7 P0: Energy Quality assessment for a signal.

    Architect approved: "動能與波動平衡器"
    Checks:
      1. TR > 2.5x ATR20 → "overheat" (climax bar, momentum exhaustion)
      2. Vol < 1.5x 5-day avg → "weak_volume" (breakout without conviction)

    [HYPOTHESIS: SIGNAL_QUALITY_V1]

    Returns:
        {
            "penalty_factor": float,  # 1.0 = no penalty, <1.0 = penalized
            "overheat": bool,
            "weak_volume": bool,
            "tr_ratio": float | None,   # TR / ATR20
            "vol_ratio": float | None,  # today_vol / 5d_avg_vol
            "warnings": list[str],
        }
    """
    result = {
        "penalty_factor": 1.0,
        "overheat": False,
        "weak_volume": False,
        "tr_ratio": None,
        "vol_ratio": None,
        "warnings": [],
    }

    try:
        import pandas as pd
        from data.fetcher import get_stock_data

        df = get_stock_data(stock_code, period_days=60)
        if df is None or len(df) < 25:
            return result

        high = df["high"]
        low = df["low"]
        close = df["close"]
        volume = df["volume"]

        # True Range series
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)

        # ATR20 (20-day rolling average of TR)
        atr20 = tr.rolling(20).mean()

        latest_tr = float(tr.iloc[-1])
        latest_atr20 = float(atr20.iloc[-1])
        latest_vol = float(volume.iloc[-1])
        avg_vol_5d = float(volume.iloc[-5:].mean())

        # Check 1: Energy Overheat (climax bar)
        if latest_atr20 > 0:
            tr_ratio = latest_tr / latest_atr20
            result["tr_ratio"] = round(tr_ratio, 2)
            if tr_ratio > ENERGY_OVERHEAT_TR_MULT:
                result["overheat"] = True
                result["penalty_factor"] *= ENERGY_OVERHEAT_PENALTY
                result["warnings"].append(
                    f"過熱 TR={latest_tr:.1f} > {ENERGY_OVERHEAT_TR_MULT}x ATR20={latest_atr20:.1f}"
                )

        # Check 2: Weak Volume breakout
        if avg_vol_5d > 0:
            vol_ratio = latest_vol / avg_vol_5d
            result["vol_ratio"] = round(vol_ratio, 2)
            if vol_ratio < ENERGY_WEAK_VOL_MULT:
                result["weak_volume"] = True
                result["penalty_factor"] *= ENERGY_WEAK_VOL_PENALTY
                result["warnings"].append(
                    f"量縮 Vol={latest_vol:.0f} < {ENERGY_WEAK_VOL_MULT}x Avg5d={avg_vol_5d:.0f}"
                )

    except Exception as e:
        logger.debug("Energy score failed for %s: %s", stock_code, e)

    return result


def _compute_industry_success_rates(days_back: int = 90) -> dict:
    """Phase 9 P0: Industry-level In-Bounds Rate from signal history.

    Architect approved: "成功往往吸引更多資金 (Positive Feedback)，90天回看窗口
    能有效過濾雜訊並捕捉板塊強弱轉換"

    [HYPOTHESIS: INDUSTRY_EXPERIENCE_WEIGHTS_V1]

    Returns:
        {industry_name: {"rate": float, "count": int, "adjustment": int}, ...}
    """
    result = {}
    try:
        from analysis.signal_log import get_realized_signals

        realized = get_realized_signals(days_back=days_back)
        if not realized:
            return result

        # Group by industry
        industry_signals: dict[str, list] = {}
        for sig in realized:
            ind = sig.get("industry") or "其他"
            industry_signals.setdefault(ind, []).append(sig)

        for ind, sigs in industry_signals.items():
            # Only count signals with in_bounds_d21 data
            bounded = [s for s in sigs if s.get("in_bounds_d21") is not None]
            count = len(bounded)

            if count < SUCCESS_RATE_MIN_SAMPLES:
                result[ind] = {"rate": None, "count": count, "adjustment": 0}
                continue

            in_bounds = sum(1 for s in bounded if s["in_bounds_d21"] == 1)
            rate = in_bounds / count

            if rate > SUCCESS_RATE_HIGH_THRESHOLD:
                adj = SUCCESS_RATE_BONUS
            elif rate < SUCCESS_RATE_LOW_THRESHOLD:
                adj = SUCCESS_RATE_PENALTY
            else:
                adj = 0

            result[ind] = {"rate": round(rate, 3), "count": count, "adjustment": adj}

    except Exception as e:
        logger.debug("Industry success rate computation failed: %s", e)

    return result


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

    # Step 2.3: Energy Quality Filter (Phase 7 P0)
    # Architect approved: [HYPOTHESIS: SIGNAL_QUALITY_V1]
    # "把這兩個 check 實作為 Penalty Factors"
    energy_penalized = 0
    for s in sim_results:
        energy = _compute_energy_score(s["stock_code"])
        s["energy_overheat"] = energy["overheat"]
        s["energy_weak_volume"] = energy["weak_volume"]
        s["energy_tr_ratio"] = energy["tr_ratio"]
        s["energy_vol_ratio"] = energy["vol_ratio"]
        s["energy_warnings"] = energy["warnings"]

        if energy["penalty_factor"] < 1.0:
            original_score = s["confidence_score"]
            s["confidence_score"] = max(0, int(s["confidence_score"] * energy["penalty_factor"]))
            # Re-grade after penalty
            score = s["confidence_score"]
            s["confidence_grade"] = "HIGH" if score >= 70 else "MEDIUM" if score >= 40 else "LOW"
            energy_penalized += 1
            logger.info(
                "Energy penalty %s: %d → %d (TR_ratio=%.1f, Vol_ratio=%.1f, %s)",
                s["stock_code"], original_score, s["confidence_score"],
                energy.get("tr_ratio") or 0, energy.get("vol_ratio") or 0,
                ", ".join(energy["warnings"]),
            )
            # Phase 7 P2: Log to Missed Opportunities for post-mortem
            try:
                from analysis.signal_log import log_filtered_signal
                log_filtered_signal(
                    signal=s,
                    raw_score=original_score,
                    final_score=s["confidence_score"],
                    reason="; ".join(energy["warnings"]),
                )
            except Exception:
                pass

    if energy_penalized:
        logger.info("Auto-Sim: Energy Score penalized %d/%d signals", energy_penalized, len(sim_results))

    # Step 2.4: Sector RS Bonus (Phase 8 P1)
    # Architect approved: [HYPOTHESIS: SECTOR_MOMENTUM_BONUS_V1]
    # "Top 3 強勢產業 → Confidence +5"
    sector_bonus_applied = 0
    try:
        from analysis.sector_rs import compute_sector_rs_table
        sector_table = compute_sector_rs_table()
        if sector_table:
            # Get top 3 sectors by median_rs
            sorted_sectors = sorted(sector_table.items(), key=lambda x: x[1].get("median_rs", 0), reverse=True)
            top3_sectors = {name for name, _ in sorted_sectors[:3]}
            logger.info("Auto-Sim: Top 3 sectors = %s", top3_sectors)

            for s in sim_results:
                if s["industry"] in top3_sectors:
                    s["confidence_score"] = min(100, s["confidence_score"] + 5)
                    # Re-grade
                    score = s["confidence_score"]
                    s["confidence_grade"] = "HIGH" if score >= 70 else "MEDIUM" if score >= 40 else "LOW"
                    s["sector_bonus"] = True
                    sector_bonus_applied += 1
                else:
                    s["sector_bonus"] = False

            if sector_bonus_applied:
                logger.info("Auto-Sim: Sector RS bonus +5 applied to %d signals", sector_bonus_applied)
    except Exception as e:
        logger.debug("Sector RS bonus skipped: %s", e)

    # Step 2.6: History Success Rate Back-weighting (Phase 9 P0)
    # Architect approved: [HYPOTHESIS: INDUSTRY_EXPERIENCE_WEIGHTS_V1]
    # "避開陷阱比追逐更高勝率對淨值貢獻更直接" — +3 bonus / -5 penalty
    success_rate_applied = 0
    industry_rates = _compute_industry_success_rates(days_back=90)
    if industry_rates:
        for s in sim_results:
            ind = s["industry"]
            ind_data = industry_rates.get(ind, {})
            adj = ind_data.get("adjustment", 0)
            if adj != 0:
                s["confidence_score"] = max(0, min(100, s["confidence_score"] + adj))
                # Re-grade
                score = s["confidence_score"]
                s["confidence_grade"] = "HIGH" if score >= 70 else "MEDIUM" if score >= 40 else "LOW"
                s["success_rate_adj"] = adj
                success_rate_applied += 1
            else:
                s["success_rate_adj"] = 0

            # Store rate for display
            s["industry_success_rate"] = ind_data.get("rate")
            s["industry_signal_count"] = ind_data.get("count", 0)

        if success_rate_applied:
            logger.info(
                "Auto-Sim: Success Rate adjusted %d signals (rates: %s)",
                success_rate_applied,
                {k: v for k, v in industry_rates.items() if v.get("adjustment", 0) != 0},
            )

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

    # Step 5: Format LINE message (ai_comments added in Step 6.5 below)
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

    # Step 6.5: AI Signal Commentator (Phase 14 Task 1)
    # CTO: "讓 AI 用一句話戳穿信號的本質"
    ai_comments: dict[str, str] = {}
    if top_signals:
        try:
            from analysis.ai_commentator import get_ai_comments, update_signal_comments
            ai_comments = get_ai_comments(top_signals)
            if ai_comments:
                update_signal_comments(ai_comments)
                logger.info("Auto-Sim: AI comments generated for %d signals", len(ai_comments))
        except Exception as e:
            logger.warning("Auto-Sim: AI Commentator failed: %s", e)

    # Step 6.8: Append AI comments to LINE message (Phase 14)
    if ai_comments:
        ai_lines = ["\n💬 AI 戰友點評"]
        for s in top_signals:
            code = s.get("stock_code", "")
            comment = ai_comments.get(code, "")
            if comment:
                ai_lines.append(f"  {code}: {comment}")
        if len(ai_lines) > 1:
            message += "\n" + "\n".join(ai_lines)

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

    # V1.1 P1: Save daily report snapshot for Energy Score sparkline
    _save_daily_report_snapshot(top_signals)

    return {
        "candidates_found": len(candidates),
        "simulated": len(sim_results),
        "top_signals": top_signals,
        "message": message,
        "elapsed_s": elapsed,
        "signals_logged": signals_logged,
        "risk_suppressed": risk_suppressed,
        "ai_comments": ai_comments,
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


def _get_aggressive_index_summary() -> tuple:
    """Phase 10 P1: Quick Aggressive Index for LINE message header.

    Returns: (score: int, advice: str)
    """
    score = 0

    # 1. Market Context (max 30)
    try:
        from data.fetcher import get_taiex_data
        taiex = get_taiex_data(period_days=60)
        if taiex is not None and len(taiex) >= 25:
            close = taiex["close"]
            ma20 = close.rolling(20).mean()
            if float(close.iloc[-1]) > float(ma20.iloc[-1]):
                score += 30
            else:
                score += 10
        else:
            score += 15
    except Exception:
        score += 15

    # 2. Sector RS (max 25)
    try:
        from analysis.sector_rs import compute_sector_rs_table
        table = compute_sector_rs_table()
        if table:
            sorted_s = sorted(table.items(), key=lambda x: x[1].get("median_rs", 0), reverse=True)
            top3 = [v.get("median_rs", 0) for _, v in sorted_s[:3]]
            avg = sum(top3) / len(top3) if top3 else 0
            score += 25 if avg > 70 else 15 if avg > 50 else 5
        else:
            score += 10
    except Exception:
        score += 10

    # 3. In-Bounds Rate (max 25)
    try:
        from analysis.drift_detector import compute_in_bounds_rate
        ib = compute_in_bounds_rate(days_back=90)
        rate = ib.get("in_bounds_rate")
        if rate is None:
            score += 15
        elif rate > 0.70:
            score += 25
        elif rate > 0.60:
            score += 20
        elif rate > 0.50:
            score += 15
        else:
            score += 5
    except Exception:
        score += 10

    # 4. Signal Quality (max 20)
    try:
        from analysis.signal_log import get_all_signals
        recent = get_all_signals(limit=5)
        if recent:
            avg_conf = sum(s.get("sim_score", 0) for s in recent) / len(recent)
            score += 20 if avg_conf >= 60 else 12 if avg_conf >= 40 else 5
        else:
            score += 10
    except Exception:
        score += 10

    if score >= 70:
        return (score, "建議積極")
    elif score >= 40:
        return (score, "正常操作")
    else:
        return (score, "建議防禦")


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

    # Phase 10 P1: Aggressive Index header
    try:
        agg_score, agg_advice = _get_aggressive_index_summary()
        if agg_score is not None:
            icon = "🔥" if agg_score >= 70 else "🌡️" if agg_score >= 40 else "🧊"
            lines.append(f"{icon} 今日市場熱度：{agg_score} ({agg_advice})")
    except Exception:
        pass

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

        # Sector RS bonus (Phase 8 P1)
        if s.get("sector_bonus"):
            lines.append(f"  🔥 強勢產業加成 (+5)")

        # Success Rate adjustment (Phase 9 P0)
        sr_adj = s.get("success_rate_adj", 0)
        sr_rate = s.get("industry_success_rate")
        if sr_adj > 0 and sr_rate is not None:
            lines.append(f"  📈 產業勝率加成 (+{sr_adj}, {sr_rate:.0%} In-Bounds)")
        elif sr_adj < 0 and sr_rate is not None:
            lines.append(f"  ⚠️ 產業勝率警示 ({sr_adj}, {sr_rate:.0%} In-Bounds)")

        # Energy quality warnings (Phase 7 P0)
        energy_warns = s.get("energy_warnings", [])
        if energy_warns:
            lines.append(f"  ⚠️ 訊號品質警示: {'; '.join(energy_warns)}")

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


# ============================================================
# V1.1 P1: Daily Report Snapshots for Energy Score Sparkline
# Architect APPROVED: File-based, NO new DB table
# ============================================================

_DAILY_REPORTS_DIR = Path(__file__).resolve().parent.parent / "data" / "daily_reports"


def _save_daily_report_snapshot(top_signals: list[dict]):
    """Save daily Auto-Sim snapshot for Energy Score sparkline.

    Writes a lightweight JSON file per day containing signal energy data.
    Architect mandate: file-based, no heavy DB writes.
    """
    import json
    from datetime import datetime

    if not top_signals:
        return

    _DAILY_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    snapshot = {
        "date": today,
        "signals": [
            {
                "stock_code": s.get("stock_code", ""),
                "stock_name": s.get("name", ""),
                "energy_tr_ratio": s.get("energy_tr_ratio"),
                "energy_vol_ratio": s.get("energy_vol_ratio"),
                "energy_overheat": s.get("energy_overheat", False),
                "energy_weak_volume": s.get("energy_weak_volume", False),
                "confidence_score": s.get("confidence_score", 0),
                "rs_rating": s.get("rs_rating", 0),
                "tier": s.get("tier", ""),
            }
            for s in top_signals
        ],
    }

    filepath = _DAILY_REPORTS_DIR / f"{today}.json"
    try:
        filepath.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.debug("Daily report snapshot saved: %s (%d signals)", filepath.name, len(top_signals))
    except Exception as e:
        logger.warning("Failed to save daily report snapshot: %s", e)

    # Cleanup: keep only last 30 days of reports
    try:
        reports = sorted(_DAILY_REPORTS_DIR.glob("*.json"))
        if len(reports) > 30:
            for old in reports[:-30]:
                old.unlink()
    except Exception:
        pass


def get_energy_trend(stock_code: str, days_back: int = 3) -> list[dict]:
    """Read Energy Score trend for a stock from daily report snapshots.

    Returns list of {date, energy_tr_ratio, energy_vol_ratio, confidence_score}
    for the last N days. Used by the Sparkline UI component.

    Architect mandate: read from daily_reports/*.json, no DB queries.
    """
    import json
    from datetime import datetime, timedelta

    result = []
    if not _DAILY_REPORTS_DIR.exists():
        return result

    today = datetime.now().date()
    for i in range(days_back):
        date = today - timedelta(days=i)
        filepath = _DAILY_REPORTS_DIR / f"{date.isoformat()}.json"
        if not filepath.exists():
            continue
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            for s in data.get("signals", []):
                if s.get("stock_code") == stock_code:
                    result.append({
                        "date": date.isoformat(),
                        "energy_tr_ratio": s.get("energy_tr_ratio"),
                        "energy_vol_ratio": s.get("energy_vol_ratio"),
                        "confidence_score": s.get("confidence_score", 0),
                    })
                    break
        except Exception:
            continue

    # Sort oldest first
    result.sort(key=lambda x: x["date"])
    return result

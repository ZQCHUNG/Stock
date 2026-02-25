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

    # Step 5: Format LINE message
    message = _format_line_message(top_signals)

    elapsed = round(time.time() - t0, 1)
    return {
        "candidates_found": len(candidates),
        "simulated": len(sim_results),
        "top_signals": top_signals,
        "message": message,
        "elapsed_s": elapsed,
    }


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

        # Divergence warning
        if s.get("divergence_warning"):
            lines.append("  ⚠️ Block Divergence Warning")

        lines.append("")  # blank separator

    lines.append(f"(n={signals[0].get('sample_count', '?')} similar cases)")
    return "\n".join(lines)


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

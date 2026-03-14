"""Phase 14 Task 3: Parameter Recommendation Engine — Read-Only Monthly Scan.

CTO: "系統應該能告訴 Joe 哪些參數可能需要調整，但不自動修改"
Architect APPROVED: Read-only suggestions, no auto-modify.

Scans recent trade performance and suggests parameter adjustments:
1. Stop-loss tightness vs recent volatility regime
2. Position sizing vs recent win rate trend
3. Entry threshold vs recent signal quality
4. Trailing stop aggressiveness vs recent exit efficiency

Output: List of recommendations with confidence + evidence.
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# [HYPOTHESIS: PARAM_RECOMMENDER_THRESHOLDS_V1]
# These thresholds trigger recommendations
MIN_RECENT_TRADES = 10  # Need at least 10 trades in lookback
LOOKBACK_DAYS = 90      # 3-month performance window

# Stop-loss
STOP_TIGHTENING_WR_THRESHOLD = 0.55   # Win rate > 55% → consider tightening stops
STOP_LOOSENING_MDD_THRESHOLD = 0.05   # MDD > 5% → consider loosening stops

# Sizing
SIZING_BOOST_WR_THRESHOLD = 0.60      # Win rate > 60% for 3 months → suggest sizing increase
SIZING_CUT_WR_THRESHOLD = 0.40        # Win rate < 40% → suggest sizing decrease
SIZING_CUT_CONSEC_LOSS = 5            # 5 consecutive losses → immediate sizing cut

# Signal quality
ENTRY_TIGHTEN_THRESHOLD = 0.35        # If <35% of recent signals are profitable → tighten entry
ENTRY_LOOSEN_THRESHOLD = 0.65         # If >65% of recent signals are profitable → can loosen entry

# Exit efficiency
EXIT_SHAKE_OUT_THRESHOLD = 0.30       # If >30% stops are shake-outs → suggest wider trail


def generate_recommendations(days_back: int = LOOKBACK_DAYS) -> dict:
    """Generate parameter recommendations based on recent performance.

    Returns:
        {
            "recommendations": [
                {
                    "category": str,       # stop_loss | position_sizing | entry | trailing
                    "severity": str,       # info | warning | critical
                    "title": str,
                    "detail": str,
                    "evidence": dict,
                    "suggestion": str,
                },
                ...
            ],
            "summary": str,
            "trade_count": int,
            "analysis_period": str,
            "generated_at": str,
        }
    """
    recommendations = []
    trade_count = 0

    # --- 1. Load recent realized signals ---
    try:
        from analysis.signal_log import get_realized_signals, get_active_signals
        realized = get_realized_signals(days_back=days_back)
        active = get_active_signals(days_back=days_back)
        trade_count = len(realized)
    except Exception as e:
        logger.warning("Param recommender: failed to load signals: %s", e)
        return _empty_result("Failed to load signal data")

    if trade_count < MIN_RECENT_TRADES:
        return _empty_result(
            f"Insufficient data ({trade_count} trades, need {MIN_RECENT_TRADES})"
        )

    # --- 2. Compute basic metrics ---
    winners = [s for s in realized if (s.get("actual_return_d21") or 0) > 0]
    losers = [s for s in realized if (s.get("actual_return_d21") or 0) <= 0]
    win_rate = len(winners) / trade_count if trade_count > 0 else 0

    avg_win = (
        sum(s["actual_return_d21"] for s in winners) / len(winners)
        if winners else 0
    )
    avg_loss = (
        sum(s["actual_return_d21"] for s in losers) / len(losers)
        if losers else 0
    )

    in_bounds = [s for s in realized if s.get("in_bounds_d21") == 1]
    in_bounds_rate = len(in_bounds) / trade_count if trade_count > 0 else 0

    # Check consecutive losses (most recent first)
    sorted_trades = sorted(realized, key=lambda s: s.get("realized_date", ""), reverse=True)
    consec_losses = 0
    for s in sorted_trades:
        if (s.get("actual_return_d21") or 0) <= 0:
            consec_losses += 1
        else:
            break

    # --- 3. Stop-Loss Analysis ---
    if win_rate > STOP_TIGHTENING_WR_THRESHOLD and avg_win > abs(avg_loss) * 1.5:
        recommendations.append({
            "category": "stop_loss",
            "severity": "info",
            "title": "Stop-loss 可考慮收緊",
            "detail": f"近期勝率 {win_rate:.0%}，平均獲利 {avg_win*100:.1f}% 遠大於平均虧損 {avg_loss*100:.1f}%。"
                      "可考慮收緊停損以保護更多利潤。",
            "evidence": {
                "win_rate": round(win_rate, 3),
                "avg_win": round(avg_win, 4),
                "avg_loss": round(avg_loss, 4),
                "win_loss_ratio": round(avg_win / abs(avg_loss), 2) if avg_loss != 0 else None,
            },
            "suggestion": "worst_case_pct: 從 -7% 考慮收緊至 -5%",
        })

    # --- 4. Position Sizing Analysis ---
    if win_rate > SIZING_BOOST_WR_THRESHOLD and trade_count >= 20:
        recommendations.append({
            "category": "position_sizing",
            "severity": "info",
            "title": "倉位可考慮微幅加碼",
            "detail": f"連續 {days_back} 天勝率 {win_rate:.0%}（{len(winners)}/{trade_count}），"
                      "表現穩定。可考慮從 1.5% 提高至 1.8% risk per trade。",
            "evidence": {
                "win_rate": round(win_rate, 3),
                "trade_count": trade_count,
                "consecutive_losses": consec_losses,
            },
            "suggestion": "risk_per_trade: 0.015 → 0.018 (觀察 1 個月)",
        })
    elif win_rate < SIZING_CUT_WR_THRESHOLD:
        recommendations.append({
            "category": "position_sizing",
            "severity": "warning",
            "title": "建議降低倉位",
            "detail": f"近期勝率僅 {win_rate:.0%}，低於 {SIZING_CUT_WR_THRESHOLD:.0%} 門檻。"
                      "建議降低 risk per trade 直到系統恢復。",
            "evidence": {
                "win_rate": round(win_rate, 3),
                "trade_count": trade_count,
            },
            "suggestion": "risk_per_trade: 0.015 → 0.010 (防禦模式)",
        })

    if consec_losses >= SIZING_CUT_CONSEC_LOSS:
        recommendations.append({
            "category": "position_sizing",
            "severity": "critical",
            "title": f"連續 {consec_losses} 筆虧損",
            "detail": "連續虧損已達警戒線。系統可能處於不利環境。"
                      "建議暫停新進場或減半倉位。",
            "evidence": {
                "consecutive_losses": consec_losses,
                "last_loss_dates": [s.get("realized_date", "") for s in sorted_trades[:consec_losses]],
            },
            "suggestion": "暫停新進場 1 週，或 risk_per_trade 減半",
        })

    # --- 5. Entry Threshold Analysis ---
    profitable_rate = len(winners) / trade_count if trade_count > 0 else 0
    if profitable_rate < ENTRY_TIGHTEN_THRESHOLD:
        recommendations.append({
            "category": "entry",
            "severity": "warning",
            "title": "進場條件建議收緊",
            "detail": f"只有 {profitable_rate:.0%} 的信號最終獲利。"
                      "建議提高 Confidence Score 門檻或增加過濾條件。",
            "evidence": {
                "profitable_rate": round(profitable_rate, 3),
                "in_bounds_rate": round(in_bounds_rate, 3),
            },
            "suggestion": "confidence_threshold: 從 40 提高至 50",
        })
    elif profitable_rate > ENTRY_LOOSEN_THRESHOLD:
        recommendations.append({
            "category": "entry",
            "severity": "info",
            "title": "進場條件可適度放寬",
            "detail": f"{profitable_rate:.0%} 信號獲利，模型準確度高。"
                      "可考慮降低門檻以捕捉更多機會。",
            "evidence": {
                "profitable_rate": round(profitable_rate, 3),
                "in_bounds_rate": round(in_bounds_rate, 3),
            },
            "suggestion": "confidence_threshold: 從 40 降至 35（觀察 2 週）",
        })

    # --- 6. Trailing Stop / Exit Analysis ---
    try:
        from analysis.signal_log import detect_shake_outs
        shake_out_data = detect_shake_outs()
        shake_rate = shake_out_data.get("shake_out_rate")
        if shake_rate is not None and shake_rate > EXIT_SHAKE_OUT_THRESHOLD:
            recommendations.append({
                "category": "trailing",
                "severity": "warning",
                "title": "Trailing Stop 被洗出比例偏高",
                "detail": f"洗盤率 {shake_rate:.0%}，超過 {EXIT_SHAKE_OUT_THRESHOLD:.0%} 門檻。"
                          "Trailing stop 可能過緊，考慮加寬 ATR 倍數。",
                "evidence": {
                    "shake_out_rate": shake_rate,
                    "shake_out_count": shake_out_data.get("shake_out_count", 0),
                    "total_stopped": shake_out_data.get("total_stopped_out", 0),
                },
                "suggestion": "trailing_atr_multiplier: 從 2.0 提高至 2.5",
            })
    except Exception as e:
        logger.debug(f"Optional operation failed: {e}")

    # --- 7. In-Bounds Rate Health ---
    if in_bounds_rate < 0.50 and trade_count >= 15:
        recommendations.append({
            "category": "entry",
            "severity": "warning",
            "title": "模型校準度下降",
            "detail": f"In-Bounds Rate 僅 {in_bounds_rate:.0%}（正常應 >60%）。"
                      "信號的預測區間可能需要重新校準。",
            "evidence": {
                "in_bounds_rate": round(in_bounds_rate, 3),
                "total_in_bounds": len(in_bounds),
                "total_realized": trade_count,
            },
            "suggestion": "考慮執行 Weekly Audit 並檢查 CI 區間設定",
        })

    # --- Summary ---
    severity_counts = {"critical": 0, "warning": 0, "info": 0}
    for r in recommendations:
        severity_counts[r["severity"]] = severity_counts.get(r["severity"], 0) + 1

    if severity_counts["critical"] > 0:
        summary = f"有 {severity_counts['critical']} 項緊急建議需要關注"
    elif severity_counts["warning"] > 0:
        summary = f"有 {severity_counts['warning']} 項警告建議"
    elif recommendations:
        summary = f"系統健康，有 {len(recommendations)} 項優化建議"
    else:
        summary = "系統表現良好，暫無調整建議"

    return {
        "recommendations": recommendations,
        "summary": summary,
        "trade_count": trade_count,
        "win_rate": round(win_rate, 3),
        "in_bounds_rate": round(in_bounds_rate, 3),
        "analysis_period": f"last {days_back} days",
        "generated_at": datetime.now().isoformat(),
    }


def _empty_result(reason: str) -> dict:
    return {
        "recommendations": [],
        "summary": reason,
        "trade_count": 0,
        "win_rate": None,
        "in_bounds_rate": None,
        "analysis_period": "",
        "generated_at": datetime.now().isoformat(),
    }

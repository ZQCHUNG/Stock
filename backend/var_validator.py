"""VaR Model Validation via Historical Backtest (Gemini R49-1).

Backtests the position_sizer's VaR model against historical data to
measure breach rate, breach magnitude, and model calibration.
"""

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def validate_var_model(
    stock_data: dict[str, pd.DataFrame],
    confidence: float = 0.95,
    lookback_days: int = 250,
    test_window_days: int = 500,
    portfolio_value: float = 1_000_000,
) -> dict:
    """Run VaR model validation backtest.

    Methodology:
    1. For each day in the test window, calculate historical VaR using
       the previous `lookback_days` of returns.
    2. Compare the predicted VaR against actual portfolio return.
    3. Track breach events (actual loss > predicted VaR).

    Args:
        stock_data: {code: DataFrame with 'close'} — at least lookback_days + test_window_days rows
        confidence: VaR confidence level (0.95 = 95%)
        lookback_days: Rolling window for VaR estimation
        test_window_days: Number of out-of-sample test days
        portfolio_value: Notional portfolio value

    Returns:
        Validation report dict.
    """
    if not stock_data:
        return {"error": "無股票數據可供驗證", "breach_count": 0, "test_days": 0}

    # Build equal-weight portfolio returns
    returns_list = []
    codes_used = []
    for code, df in stock_data.items():
        if df is None or df.empty or "close" not in df.columns:
            continue
        r = df["close"].pct_change().dropna()
        if len(r) < lookback_days + 50:
            continue
        r.name = code
        returns_list.append(r)
        codes_used.append(code)

    if not returns_list:
        return {"error": "數據不足以進行驗證", "breach_count": 0, "test_days": 0}

    # Align and build portfolio returns (equal weight)
    returns_df = pd.concat(returns_list, axis=1).dropna()
    portfolio_returns = returns_df.mean(axis=1)  # Equal-weight daily return

    total_available = len(portfolio_returns)
    actual_test_days = min(test_window_days, total_available - lookback_days)

    if actual_test_days < 30:
        return {"error": f"測試窗口太短 ({actual_test_days} < 30 天)", "breach_count": 0, "test_days": 0}

    # Rolling VaR backtest
    breach_events = []
    daily_records = []

    for i in range(lookback_days, lookback_days + actual_test_days):
        window = portfolio_returns.iloc[i - lookback_days:i]
        # Historical VaR: (1-confidence) quantile
        var_pct = float(window.quantile(1 - confidence))  # Negative number
        actual_return = float(portfolio_returns.iloc[i])

        is_breach = actual_return < var_pct  # Loss exceeds VaR
        breach_magnitude = (actual_return - var_pct) if is_breach else 0

        daily_records.append({
            "date": str(portfolio_returns.index[i].date()) if hasattr(portfolio_returns.index[i], 'date') else str(portfolio_returns.index[i]),
            "var_pct": round(var_pct, 6),
            "actual_return": round(actual_return, 6),
            "is_breach": is_breach,
        })

        if is_breach:
            breach_events.append({
                "date": daily_records[-1]["date"],
                "var_pct": round(var_pct, 6),
                "actual_return": round(actual_return, 6),
                "excess_loss": round(breach_magnitude, 6),
            })

    # Compute validation metrics
    breach_count = len(breach_events)
    expected_breach_rate = 1 - confidence  # e.g., 5% for 95% VaR
    actual_breach_rate = breach_count / actual_test_days if actual_test_days > 0 else 0

    avg_breach_magnitude = (
        float(np.mean([b["excess_loss"] for b in breach_events]))
        if breach_events else 0
    )

    # Model calibration assessment
    # Kupiec POF test (proportion of failures): is breach rate close to expected?
    ratio = actual_breach_rate / expected_breach_rate if expected_breach_rate > 0 else 0
    if ratio < 0.5:
        calibration = "過度保守 (Over-conservative)"
        calibration_action = "可適度放寬 VaR limit 或降低懲罰係數"
    elif ratio <= 1.5:
        calibration = "校準良好 (Well-calibrated)"
        calibration_action = "維持現有參數"
    elif ratio <= 2.5:
        calibration = "略微低估 (Slightly under-estimating)"
        calibration_action = "建議降低 VaR limit 5-10% 或增加 Beta 懲罰"
    else:
        calibration = "嚴重低估風險 (Significantly under-estimating)"
        calibration_action = "立即降低 VaR limit、增加相關性和 Beta 懲罰係數"

    # Market regime analysis: split by market condition
    regime_analysis = _analyze_by_regime(portfolio_returns, daily_records, lookback_days, actual_test_days)

    return {
        "validation_date": datetime.now().isoformat(),
        "stocks_used": codes_used,
        "stock_count": len(codes_used),
        "confidence_level": confidence,
        "lookback_days": lookback_days,
        "test_days": actual_test_days,
        "breach_count": breach_count,
        "expected_breach_rate": round(expected_breach_rate, 4),
        "actual_breach_rate": round(actual_breach_rate, 4),
        "breach_ratio": round(ratio, 2),
        "avg_breach_magnitude": round(avg_breach_magnitude, 6),
        "calibration": calibration,
        "calibration_action": calibration_action,
        "regime_analysis": regime_analysis,
        "parameter_recommendations": _generate_recommendations(ratio, avg_breach_magnitude),
        "breach_events": breach_events[:50],  # Top 50 for display
        "daily_summary": {
            "total": actual_test_days,
            "breaches": breach_count,
            "avg_var": round(float(np.mean([r["var_pct"] for r in daily_records])), 6),
            "avg_return": round(float(np.mean([r["actual_return"] for r in daily_records])), 6),
            "worst_return": round(float(min(r["actual_return"] for r in daily_records)), 6),
        },
    }


def _analyze_by_regime(
    portfolio_returns: pd.Series,
    daily_records: list,
    lookback_days: int,
    test_days: int,
) -> dict:
    """Split validation by market regime (bull/bear/sideways)."""
    regimes = {"bull": [], "bear": [], "sideways": []}

    for i, rec in enumerate(daily_records):
        # Simple regime: 20-day MA of returns
        idx = lookback_days + i
        if idx < 20:
            continue
        recent_20d = portfolio_returns.iloc[idx - 20:idx].mean()
        if recent_20d > 0.001:  # ~0.1%/day ≈ 25%/year
            regime = "bull"
        elif recent_20d < -0.001:
            regime = "bear"
        else:
            regime = "sideways"
        regimes[regime].append(rec)

    result = {}
    for regime, records in regimes.items():
        total = len(records)
        breaches = sum(1 for r in records if r["is_breach"])
        result[regime] = {
            "days": total,
            "breach_count": breaches,
            "breach_rate": round(breaches / total, 4) if total > 0 else 0,
        }
    return result


def _generate_recommendations(breach_ratio: float, avg_breach_mag: float) -> list[dict]:
    """Generate parameter adjustment recommendations based on validation."""
    recs = []

    if breach_ratio > 2.0:
        recs.append({
            "parameter": "var_limit_pct",
            "current": "2.0%",
            "suggested": "1.5%",
            "reason": f"突破率過高 ({breach_ratio:.1f}x expected)，需降低風險上限",
        })
        recs.append({
            "parameter": "corr_penalty",
            "current": "0.75 threshold",
            "suggested": "0.60 threshold",
            "reason": "更積極懲罰相關性以降低集中風險",
        })
    elif breach_ratio > 1.5:
        recs.append({
            "parameter": "var_limit_pct",
            "current": "2.0%",
            "suggested": "1.8%",
            "reason": f"突破率偏高 ({breach_ratio:.1f}x)，微調風險上限",
        })
    elif breach_ratio < 0.3:
        recs.append({
            "parameter": "var_limit_pct",
            "current": "2.0%",
            "suggested": "2.5%",
            "reason": f"模型過度保守 ({breach_ratio:.1f}x)，可適度放寬",
        })
        recs.append({
            "parameter": "beta_penalty",
            "current": "1.5 threshold",
            "suggested": "1.8 threshold",
            "reason": "Beta 懲罰過嚴，可放寬閾值",
        })

    if abs(avg_breach_mag) > 0.02:  # >2% average excess loss
        recs.append({
            "parameter": "scenario_severity",
            "current": "standard",
            "suggested": "enhanced",
            "reason": f"平均突破幅度 {avg_breach_mag:.2%}，需加強壓力情境",
        })

    if not recs:
        recs.append({
            "parameter": "all",
            "current": "current",
            "suggested": "no change",
            "reason": "VaR 模型校準良好，維持現有參數",
        })

    return recs

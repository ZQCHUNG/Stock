"""Backtest Drift Monitor — V1.3 P1

CTO/Architect OFFICIALLY APPROVED.
Monitors deviation between live trading returns and backtest expectations.

Core Formula (CTO mandate):
  Drift = (Return_live - Return_backtest) / σ_backtest

Physical Meaning:
  Not just "are we making money?" but "is live performance within
  the statistical distribution predicted by backtesting?"
  If Drift > 1.5σ → regime has shifted, backtest no longer valid.

CTO Question Resolution — σ_backtest across different volatility stocks:
  Per-stock normalization → portfolio-weighted aggregation.
  Each stock's drift is normalized by its OWN backtest σ (not a global σ),
  then aggregated as equal-weight average across portfolio.
  This prevents high-vol stocks from dominating the drift signal.

Rolling Window: 20 signals (CTO: captures short-term sector rotation).
Alert Threshold: 15% absolute drift or Z-score > 1.5σ.
[CRITICAL]: Negative expanding drift → recommend lowering Aggressive Index.

[PLACEHOLDER: DRIFT_THRESHOLD_15] — 15% needs sensitivity test
[PLACEHOLDER: DRIFT_ZSCORE_1_5] — 1.5σ Z-score cutoff
"""

import json
import logging
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DRIFT_STATE_FILE = DATA_DIR / "drift_monitor_state.json"

# ─── Thresholds [PLACEHOLDER] ────────────────────────────────
DRIFT_THRESHOLD = 0.15      # [PLACEHOLDER: DRIFT_THRESHOLD_15] 15% absolute drift
ZSCORE_THRESHOLD = 1.5      # [PLACEHOLDER: DRIFT_ZSCORE_1_5] 1.5σ Z-score cutoff
ROLLING_WINDOW = 20         # CTO: 20-signal rolling window
MIN_SAMPLES = 5             # Minimum signals needed for valid drift calculation
EXPANDING_LOOKBACK = 3      # Consecutive worsening periods → "expanding" drift


# ─── Data Collection ──────────────────────────────────────────

def _get_realized_signals(days_back: int = 180) -> list[dict]:
    """Fetch realized signals with actual returns from signal_log."""
    try:
        from analysis.signal_log import get_realized_signals
        return get_realized_signals(days_back=days_back)
    except Exception as e:
        logger.warning("Failed to fetch realized signals: %s", e)
        return []


def _get_backtest_baseline() -> dict[str, dict]:
    """Get backtest expected returns per strategy.

    Returns dict keyed by strategy name:
    {
        "v4": {"mean_return": 0.035, "std_return": 0.08, "n": 150},
        "bold": {"mean_return": 0.042, "std_return": 0.10, "n": 85},
    }
    """
    try:
        from analysis.signal_tracker import get_strategy_stats
        stats = get_strategy_stats()
        baseline = {}
        for strat_data in stats:
            name = strat_data.get("strategy", "unknown")
            decay = strat_data.get("decay_curve", [])
            # Use d20 or d21 as the benchmark return horizon
            if decay:
                d20 = next(
                    (d for d in decay if d.get("day") in (20, 21)), None
                )
                if d20:
                    baseline[name] = {
                        "mean_return": d20.get("avg_return", 0),
                        "n": d20.get("n", 0),
                    }
        return baseline
    except Exception as e:
        logger.warning("Failed to get backtest baseline: %s", e)
        return {}


# ─── Per-Signal Drift Computation ─────────────────────────────

def compute_signal_drift(
    actual_return: float,
    expected_return: float,
    sigma: float,
) -> dict[str, float]:
    """Compute drift metrics for a single signal.

    Returns:
        {
            "raw_drift": float,      # actual - expected (in %)
            "z_score": float,        # (actual - expected) / σ
            "is_drifting": bool,     # |z_score| > threshold
        }
    """
    raw_drift = actual_return - expected_return

    if sigma and sigma > 0:
        z_score = raw_drift / sigma
    else:
        z_score = 0.0

    return {
        "raw_drift": raw_drift,
        "z_score": z_score,
        "is_drifting": abs(z_score) > ZSCORE_THRESHOLD,
    }


# ─── Portfolio-Level Drift Aggregation ────────────────────────

def compute_portfolio_drift(
    signals: list[dict] | None = None,
    days_back: int = 180,
) -> dict[str, Any]:
    """Compute rolling portfolio-level drift.

    CTO resolution: Per-stock normalization → equal-weight aggregation.
    Each signal's drift is normalized by its own strategy's σ_backtest,
    preventing high-vol stocks from dominating.

    Returns:
        {
            "total_signals": int,
            "eligible_signals": int,     # With actual returns
            "rolling_window": int,
            "portfolio_drift": float,    # Average raw drift across window
            "portfolio_zscore": float,   # Average Z-score across window
            "is_drifting": bool,
            "drift_direction": str,      # "POSITIVE" / "NEGATIVE" / "NEUTRAL"
            "expanding_negative": bool,  # CTO [CRITICAL]: worsening negative drift
            "signal_details": list,      # Per-signal drift data
            "alert_level": str,          # "NORMAL" / "WARNING" / "CRITICAL"
            "alert_message": str,
        }
    """
    if signals is None:
        signals = _get_realized_signals(days_back=days_back)

    if not signals:
        return _empty_result("無已實現信號")

    # Get backtest baselines per strategy
    baseline = _get_backtest_baseline()

    # Compute per-signal drift
    drift_entries = []
    for sig in signals:
        actual = sig.get("actual_return_d21")
        if actual is None:
            continue

        strategy = sig.get("strategy", sig.get("sniper_tier", "v4"))
        expected_mean = sig.get("expected_mean_return")

        # Fallback: use strategy baseline if no per-signal expected return
        if expected_mean is None and strategy in baseline:
            expected_mean = baseline[strategy].get("mean_return", 0)
        if expected_mean is None:
            expected_mean = 0

        # Per-signal σ from confidence interval, or strategy-level σ
        ci_upper = sig.get("ci_upper")
        ci_lower = sig.get("ci_lower")
        if ci_upper is not None and ci_lower is not None:
            # σ ≈ (ci_upper - ci_lower) / (2 × 1.96) for 95% CI
            sigma = (ci_upper - ci_lower) / 3.92
        else:
            sigma = 0.08  # Default 8% vol if no CI data

        drift = compute_signal_drift(actual, expected_mean, sigma)
        drift_entries.append({
            "code": sig.get("stock_code", ""),
            "name": sig.get("stock_name", ""),
            "signal_date": sig.get("signal_date", ""),
            "strategy": strategy,
            "actual_return": actual,
            "expected_return": expected_mean,
            "sigma": sigma,
            **drift,
        })

    if len(drift_entries) < MIN_SAMPLES:
        return _empty_result(
            f"樣本不足 ({len(drift_entries)}/{MIN_SAMPLES})"
        )

    # Sort by date descending and take rolling window
    drift_entries.sort(
        key=lambda x: x.get("signal_date", ""), reverse=True,
    )
    window = drift_entries[:ROLLING_WINDOW]

    # Portfolio aggregation (equal-weight average)
    raw_drifts = [d["raw_drift"] for d in window]
    z_scores = [d["z_score"] for d in window]

    portfolio_drift = statistics.mean(raw_drifts)
    portfolio_zscore = statistics.mean(z_scores)
    is_drifting = abs(portfolio_zscore) > ZSCORE_THRESHOLD

    # Drift direction
    if portfolio_drift > 0.01:
        direction = "POSITIVE"
    elif portfolio_drift < -0.01:
        direction = "NEGATIVE"
    else:
        direction = "NEUTRAL"

    # CTO [CRITICAL]: Expanding negative drift detection
    expanding_neg = _detect_expanding_negative(drift_entries)

    # Alert level
    alert_level, alert_msg = _classify_alert(
        portfolio_drift, portfolio_zscore, direction, expanding_neg,
    )

    return {
        "timestamp": datetime.now().isoformat(),
        "total_signals": len(signals),
        "eligible_signals": len(drift_entries),
        "rolling_window": len(window),
        "portfolio_drift": round(portfolio_drift, 4),
        "portfolio_drift_pct": round(portfolio_drift * 100, 2),
        "portfolio_zscore": round(portfolio_zscore, 2),
        "is_drifting": is_drifting,
        "drift_direction": direction,
        "expanding_negative": expanding_neg,
        "alert_level": alert_level,
        "alert_message": alert_msg,
        "signal_details": window,
    }


# ─── Expanding Negative Detection ─────────────────────────────

def _detect_expanding_negative(
    sorted_entries: list[dict],
) -> bool:
    """CTO [CRITICAL]: Detect if negative drift is expanding over time.

    Check if the most recent EXPANDING_LOOKBACK windows show
    progressively worsening (more negative) average Z-scores.
    """
    if len(sorted_entries) < ROLLING_WINDOW + EXPANDING_LOOKBACK:
        return False

    # Compute rolling Z-scores for consecutive windows
    window_zscores = []
    for offset in range(EXPANDING_LOOKBACK):
        start = offset * (ROLLING_WINDOW // 2)  # 50% overlap
        end = start + ROLLING_WINDOW
        if end > len(sorted_entries):
            break
        chunk = sorted_entries[start:end]
        avg_z = statistics.mean(d["z_score"] for d in chunk)
        window_zscores.append(avg_z)

    if len(window_zscores) < EXPANDING_LOOKBACK:
        return False

    # Check if each subsequent window is more negative
    # (window_zscores[0] = most recent, should be most negative)
    for i in range(len(window_zscores) - 1):
        if window_zscores[i] >= window_zscores[i + 1]:
            return False  # Not monotonically worsening

    # All recent → more negative than older
    return window_zscores[0] < -ZSCORE_THRESHOLD * 0.5


# ─── Alert Classification ────────────────────────────────────

def _classify_alert(
    drift: float,
    zscore: float,
    direction: str,
    expanding_neg: bool,
) -> tuple[str, str]:
    """Classify alert level and generate message.

    Returns: (alert_level, alert_message)
    """
    if expanding_neg:
        return (
            "CRITICAL",
            f"\u26a0\ufe0f \u7b56\u7565\u5074\u96e2\u8b66\u793a [CRITICAL]: "
            f"\u8ca0\u5411\u504f\u96e2\u6301\u7e8c\u64f4\u5927 "
            f"(Z:{zscore:+.2f}, Drift:{drift*100:+.1f}%) "
            f"\u2014 \u5efa\u8b70\u4e0b\u8abf Aggressive Index",
        )

    if abs(zscore) > ZSCORE_THRESHOLD or abs(drift) > DRIFT_THRESHOLD:
        return (
            "WARNING",
            f"\u26a0\ufe0f \u7b56\u7565\u504f\u96e2\u8b66\u793a: "
            f"Live \u8207\u56de\u6e2c\u504f\u96e2 "
            f"(Z:{zscore:+.2f}, Drift:{drift*100:+.1f}%)",
        )

    return ("NORMAL", "")


# ─── Empty Result Template ────────────────────────────────────

def _empty_result(reason: str) -> dict[str, Any]:
    return {
        "timestamp": datetime.now().isoformat(),
        "total_signals": 0,
        "eligible_signals": 0,
        "rolling_window": 0,
        "portfolio_drift": 0.0,
        "portfolio_drift_pct": 0.0,
        "portfolio_zscore": 0.0,
        "is_drifting": False,
        "drift_direction": "NEUTRAL",
        "expanding_negative": False,
        "alert_level": "NORMAL",
        "alert_message": reason,
        "signal_details": [],
    }


# ─── Integration: Morning Brief ──────────────────────────────

def get_drift_alert_for_brief() -> str | None:
    """Get drift alert message for Morning Brief integration.

    Returns None if no alert needed.
    """
    try:
        result = compute_portfolio_drift()
        if result["alert_level"] in ("WARNING", "CRITICAL"):
            return result["alert_message"]
    except Exception as e:
        logger.warning("Drift monitor failed: %s", e)
    return None


# ─── State Persistence (for trend detection) ──────────────────

def _load_drift_history() -> list[dict]:
    """Load historical drift snapshots for trend analysis."""
    if DRIFT_STATE_FILE.exists():
        try:
            return json.loads(
                DRIFT_STATE_FILE.read_text(encoding="utf-8")
            )
        except Exception:
            pass
    return []


def _save_drift_snapshot(snapshot: dict) -> None:
    """Append today's drift snapshot to history (keep last 60 days)."""
    try:
        history = _load_drift_history()
        history.append({
            "date": snapshot.get("timestamp", datetime.now().isoformat()),
            "drift_pct": snapshot.get("portfolio_drift_pct", 0),
            "zscore": snapshot.get("portfolio_zscore", 0),
            "alert_level": snapshot.get("alert_level", "NORMAL"),
            "eligible": snapshot.get("eligible_signals", 0),
        })
        # Keep last 60 entries
        history = history[-60:]
        DRIFT_STATE_FILE.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("Failed to save drift snapshot: %s", e)


# ─── Main Entry Point ────────────────────────────────────────

def generate_drift_report(
    save_snapshot: bool = True,
) -> dict[str, Any]:
    """Generate comprehensive drift report.

    Called daily by scheduler or on-demand via API.
    """
    result = compute_portfolio_drift()

    if save_snapshot and result["eligible_signals"] >= MIN_SAMPLES:
        _save_drift_snapshot(result)

    # Add trend data from history
    history = _load_drift_history()
    result["drift_history"] = history[-20:]  # Last 20 snapshots
    result["trend_direction"] = _compute_trend(history)

    return result


def _compute_trend(history: list[dict]) -> str:
    """Compute drift trend from historical snapshots."""
    if len(history) < 3:
        return "INSUFFICIENT_DATA"

    recent = [h["zscore"] for h in history[-5:]]
    older = [h["zscore"] for h in history[-10:-5]] if len(history) >= 10 else []

    if not older:
        return "INSUFFICIENT_DATA"

    recent_avg = statistics.mean(recent)
    older_avg = statistics.mean(older)

    delta = recent_avg - older_avg
    if delta > 0.3:
        return "IMPROVING"
    elif delta < -0.3:
        return "DETERIORATING"
    return "STABLE"

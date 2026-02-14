"""SQS Backtester — 驗證 Signal Quality Score 的選股能力（Gemini R43）

用歷史數據回測：SQS 過濾後的信號 vs 全部信號，績效是否有顯著提升？

方法：
1. 對每支股票用 V4 策略生成歷史 BUY 信號
2. 計算每個信號的實際 d5/d20 報酬
3. 為每個信號計算「簡化 SQS」（使用可回溯的維度）
4. 比較不同 SQS 閾值下的績效差異
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
import pandas as pd

from analysis.scoring import TRANSACTION_COST, calculate_sqs

logger = logging.getLogger(__name__)


def _estimate_regime_at_date(taiex_df: pd.DataFrame | None, date) -> str:
    """Estimate market regime at a specific date using TAIEX MA cross."""
    if taiex_df is None or len(taiex_df) < 120:
        return "sideways"
    try:
        loc = taiex_df.index.get_indexer([date], method="ffill")[0]
        if loc < 60:
            return "sideways"
        window = taiex_df["close"].iloc[max(0, loc - 120) : loc + 1]
        ma20 = window.rolling(20).mean().iloc[-1]
        ma60 = window.rolling(60).mean().iloc[-1]
        if pd.isna(ma20) or pd.isna(ma60):
            return "sideways"
        pct_diff = (ma20 - ma60) / ma60
        if pct_diff > 0.02:
            return "bull"
        elif pct_diff < -0.02:
            return "bear"
        return "sideways"
    except Exception:
        return "sideways"


def _compute_forward_returns(
    df: pd.DataFrame, signal_idx: int
) -> dict[str, float | None]:
    """Compute d5 and d20 forward returns from a signal index."""
    close = df["close"]
    high = df["high"] if "high" in df.columns else close
    low = df["low"] if "low" in df.columns else close
    signal_price = float(close.iloc[signal_idx])
    result: dict[str, Any] = {"signal_price": signal_price}

    for label, days in [("d5", 5), ("d20", 20)]:
        end = min(signal_idx + days, len(df) - 1)
        if end <= signal_idx:
            result[f"{label}_return"] = None
            result[f"{label}_max_gain"] = None
            result[f"{label}_max_dd"] = None
            continue
        slice_close = close.iloc[signal_idx + 1 : end + 1]
        slice_high = high.iloc[signal_idx + 1 : end + 1]
        slice_low = low.iloc[signal_idx + 1 : end + 1]
        ret = (float(slice_close.iloc[-1]) - signal_price) / signal_price
        max_gain = (float(slice_high.max()) - signal_price) / signal_price
        max_dd = (float(slice_low.min()) - signal_price) / signal_price
        result[f"{label}_return"] = round(ret, 5)
        result[f"{label}_max_gain"] = round(max_gain, 5)
        result[f"{label}_max_dd"] = round(max_dd, 5)

    return result


def _process_stock(
    code: str,
    period_days: int,
    fitness_map: dict[str, str],
    taiex_df: pd.DataFrame | None,
) -> list[dict]:
    """Generate V4 signals for one stock and compute SQS + forward returns."""
    signals = []
    try:
        from data.fetcher import get_stock_data
        from analysis.strategy_v4 import generate_v4_signals

        df = get_stock_data(code, period_days=period_days)
        if df is None or len(df) < 120:
            return signals

        sig_df = generate_v4_signals(df)

        # Find all BUY signal dates (skip last 20 bars for forward return calc)
        buy_mask = sig_df["v4_signal"] == "BUY"
        buy_indices = [i for i in range(len(sig_df)) if buy_mask.iloc[i]]

        fitness_tag = fitness_map.get(code, "")

        for idx in buy_indices:
            # Need at least 5 bars forward
            if idx >= len(df) - 5:
                continue

            signal_date = sig_df.index[idx]
            regime = _estimate_regime_at_date(taiex_df, signal_date)

            # Compute simplified SQS (no EV, no heat — only fitness + regime + maturity)
            uptrend_days = int(sig_df.iloc[idx].get("uptrend_days", 0))
            if uptrend_days >= 30:
                maturity = "Structural Shift"
            elif uptrend_days >= 10:
                maturity = "Trend Formation"
            else:
                maturity = "Speculative Spike"

            sqs_result = calculate_sqs(
                fitness_tag=fitness_tag,
                signal_strategy="V4",
                regime=regime,
                raw_ev_20d=None,  # Not available historically
                ev_sample_count=0,
                sector_weighted_heat=None,  # Not available historically
                sector_momentum="stable",
                signal_maturity=maturity,
            )

            # Forward returns
            fwd = _compute_forward_returns(df, idx)

            signals.append(
                {
                    "code": code,
                    "date": signal_date.strftime("%Y-%m-%d"),
                    "sqs": sqs_result["sqs"],
                    "grade": sqs_result["grade"],
                    "regime": regime,
                    "fitness_tag": fitness_tag,
                    "maturity": maturity,
                    "breakdown": sqs_result["breakdown"],
                    **fwd,
                }
            )

    except Exception as e:
        logger.warning(f"SQS backtest failed for {code}: {e}")

    return signals


def _compute_group_metrics(signals: list[dict]) -> dict:
    """Compute performance metrics for a group of signals."""
    if not signals:
        return {
            "count": 0,
            "win_rate_5d": None,
            "win_rate_20d": None,
            "avg_return_5d": None,
            "avg_return_20d": None,
            "net_return_5d": None,
            "net_return_20d": None,
            "avg_max_gain_5d": None,
            "avg_max_dd_5d": None,
            "profit_factor_5d": None,
        }

    d5 = [s["d5_return"] for s in signals if s.get("d5_return") is not None]
    d20 = [s["d20_return"] for s in signals if s.get("d20_return") is not None]
    mg5 = [s["d5_max_gain"] for s in signals if s.get("d5_max_gain") is not None]
    md5 = [s["d5_max_dd"] for s in signals if s.get("d5_max_dd") is not None]

    win5 = [r for r in d5 if r > 0]
    lose5 = [r for r in d5 if r <= 0]
    win20 = [r for r in d20 if r > 0]

    avg5 = sum(d5) / len(d5) if d5 else None
    avg20 = sum(d20) / len(d20) if d20 else None

    # Profit factor: sum of wins / abs(sum of losses)
    pf5 = None
    if win5 and lose5:
        total_loss = abs(sum(lose5))
        if total_loss > 0:
            pf5 = round(sum(win5) / total_loss, 2)

    return {
        "count": len(signals),
        "count_d5": len(d5),
        "count_d20": len(d20),
        "win_rate_5d": round(len(win5) / len(d5), 3) if d5 else None,
        "win_rate_20d": round(len(win20) / len(d20), 3) if d20 else None,
        "avg_return_5d": round(avg5, 4) if avg5 is not None else None,
        "avg_return_20d": round(avg20, 4) if avg20 is not None else None,
        "net_return_5d": round(avg5 - TRANSACTION_COST, 4) if avg5 is not None else None,
        "net_return_20d": round(avg20 - TRANSACTION_COST, 4) if avg20 is not None else None,
        "avg_max_gain_5d": round(sum(mg5) / len(mg5), 4) if mg5 else None,
        "avg_max_dd_5d": round(sum(md5) / len(md5), 4) if md5 else None,
        "profit_factor_5d": pf5,
    }


def run_sqs_backtest(
    stock_codes: list[str] | None = None,
    period_days: int = 730,
    max_workers: int = 4,
    thresholds: list[float] | None = None,
) -> dict:
    """Run SQS effectiveness backtest.

    Generates V4 signals historically, computes simplified SQS, and compares
    performance across different SQS threshold groups.

    Args:
        stock_codes: List of stock codes to test. Defaults to SCAN_STOCKS.
        period_days: Historical period in days.
        max_workers: Parallel workers for data fetching.
        thresholds: SQS threshold levels to test. Default [40, 60, 80].

    Returns:
        dict with all_signals metrics, per-threshold metrics, and distribution.
    """
    if thresholds is None:
        thresholds = [40, 60, 80]

    if stock_codes is None:
        from config import SCAN_STOCKS
        stock_codes = list(SCAN_STOCKS.keys())

    # Load fitness tags
    fitness_map: dict[str, str] = {}
    try:
        from analysis.strategy_fitness import get_fitness_tags
        tags = get_fitness_tags(stock_codes)
        for t in tags:
            fitness_map[t["code"]] = t.get("fitness_tag", "")
    except Exception:
        pass

    # Load TAIEX for regime estimation
    taiex_df = None
    try:
        from data.fetcher import get_taiex_data
        taiex_df = get_taiex_data(period_days=period_days + 120)
    except Exception:
        pass

    # Process all stocks in parallel
    all_signals: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _process_stock, code, period_days, fitness_map, taiex_df
            ): code
            for code in stock_codes
        }
        for future in futures:
            try:
                result = future.result(timeout=60)
                all_signals.extend(result)
            except Exception as e:
                logger.warning(f"Stock {futures[future]} timed out: {e}")

    if not all_signals:
        return {"error": "No signals generated", "total_signals": 0}

    # Sort by date
    all_signals.sort(key=lambda s: s["date"])

    # Compute metrics for all signals (baseline)
    baseline = _compute_group_metrics(all_signals)

    # Compute metrics for each threshold
    threshold_results = {}
    for thr in sorted(thresholds):
        filtered = [s for s in all_signals if s["sqs"] >= thr]
        metrics = _compute_group_metrics(filtered)
        # Compute lift vs baseline
        lift_wr5 = None
        lift_ret5 = None
        if metrics["win_rate_5d"] is not None and baseline["win_rate_5d"] is not None:
            lift_wr5 = round(metrics["win_rate_5d"] - baseline["win_rate_5d"], 3)
        if metrics["avg_return_5d"] is not None and baseline["avg_return_5d"] is not None:
            lift_ret5 = round(metrics["avg_return_5d"] - baseline["avg_return_5d"], 4)
        threshold_results[f"sqs_{int(thr)}"] = {
            **metrics,
            "threshold": thr,
            "pass_rate": round(len(filtered) / len(all_signals), 3),
            "lift_win_rate_5d": lift_wr5,
            "lift_avg_return_5d": lift_ret5,
        }

    # SQS distribution
    sqs_scores = [s["sqs"] for s in all_signals]
    distribution = {
        "min": round(min(sqs_scores), 1),
        "max": round(max(sqs_scores), 1),
        "mean": round(float(np.mean(sqs_scores)), 1),
        "median": round(float(np.median(sqs_scores)), 1),
        "p10": round(float(np.percentile(sqs_scores, 10)), 1),
        "p25": round(float(np.percentile(sqs_scores, 25)), 1),
        "p75": round(float(np.percentile(sqs_scores, 75)), 1),
        "p90": round(float(np.percentile(sqs_scores, 90)), 1),
        "histogram": _build_histogram(sqs_scores),
    }

    # Grade distribution
    grade_counts = {}
    for s in all_signals:
        g = s["grade"]
        grade_counts[g] = grade_counts.get(g, 0) + 1

    # Per-regime breakdown
    regime_metrics = {}
    for regime in ["bull", "sideways", "bear"]:
        regime_sigs = [s for s in all_signals if s["regime"] == regime]
        if regime_sigs:
            regime_metrics[regime] = _compute_group_metrics(regime_sigs)

    return {
        "total_signals": len(all_signals),
        "stock_count": len(set(s["code"] for s in all_signals)),
        "date_range": {
            "start": all_signals[0]["date"],
            "end": all_signals[-1]["date"],
        },
        "baseline": baseline,
        "thresholds": threshold_results,
        "distribution": distribution,
        "grade_counts": grade_counts,
        "regime_breakdown": regime_metrics,
        "transaction_cost": TRANSACTION_COST,
    }


def _build_histogram(scores: list[float], bins: int = 10) -> list[dict]:
    """Build histogram buckets for SQS score distribution."""
    counts, edges = np.histogram(scores, bins=bins, range=(0, 100))
    return [
        {
            "range": f"{int(edges[i])}-{int(edges[i + 1])}",
            "count": int(counts[i]),
        }
        for i in range(len(counts))
    ]

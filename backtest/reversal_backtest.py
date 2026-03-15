"""Reversal Detection Backtester — Phase 4

Walk-forward backtester for reversal signals. Scans historical data,
records signals when composite_score >= threshold, and tracks forward
returns at D5/D10/D20.

All thresholds tagged [PLACEHOLDER] per protocol.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_logger = logging.getLogger(__name__)

# ---------- Paths ----------

VALIDATION_STOCKS_PATH = Path(__file__).parent.parent / "data" / "reversal_validation_stocks.json"

# ---------- Parameters ----------

# [PLACEHOLDER: REVERSAL_BT_MIN_SCORE_001] — minimum composite score to trigger signal
DEFAULT_MIN_COMPOSITE_SCORE = 50.0

# [PLACEHOLDER: REVERSAL_BT_FORWARD_DAYS_001] — forward return horizons
DEFAULT_FORWARD_DAYS = (5, 10, 20)

# [PLACEHOLDER: REVERSAL_BT_WALK_STEP_001] — step size for walk-forward scan
DEFAULT_WALK_STEP = 1

# [PLACEHOLDER: REVERSAL_BT_MIN_HISTORY_001] — minimum bars before first signal check
MIN_HISTORY_BARS = 120

# [PLACEHOLDER: REVERSAL_BT_RANDOM_OFFSET_RANGE_001] — range for random benchmark offset
RANDOM_OFFSET_RANGE = 10

SIGNAL_TYPES = ["spring", "rsi_divergence", "bb_squeeze", "volume_exhaustion", "multiscale_accumulation"]


# ---------- Config ----------

@dataclass
class ReversalBacktestConfig:
    """Configuration for reversal backtest run."""
    universe: list[str] = field(default_factory=list)
    min_composite_score: float = DEFAULT_MIN_COMPOSITE_SCORE
    forward_days: tuple[int, ...] | list[int] = field(default_factory=lambda: list(DEFAULT_FORWARD_DAYS))
    walk_step: int = DEFAULT_WALK_STEP
    period_days: int = 500  # how many calendar days of history to fetch
    include_broker: bool = False  # whether to include F6 broker score


# ---------- Result ----------

@dataclass
class ReversalBacktestResult:
    """Aggregated result from reversal backtest."""

    # Summary
    total_stocks_scanned: int = 0
    total_signals: int = 0
    elapsed_sec: float = 0.0

    # Hit rates: {5: 0.65, 10: 0.70, 20: 0.72}
    hit_rates: dict[int, float] = field(default_factory=dict)

    # Average forward returns: {5: 0.012, 10: 0.025, 20: 0.04}
    avg_returns: dict[int, float] = field(default_factory=dict)

    # Median forward returns
    median_returns: dict[int, float] = field(default_factory=dict)

    # Max adverse excursion (worst drawdown after signal)
    avg_mae: float = 0.0

    # Per sub-signal attribution: {signal_type: {count, avg_score, win_contribution}}
    signal_attribution: dict[str, dict[str, float]] = field(default_factory=dict)

    # Random benchmark comparison: {5: avg_random_return, ...}
    benchmark_returns: dict[int, float] = field(default_factory=dict)

    # Per-stock breakdown: [{code, signal_count, hit_rate_d10, avg_return_d10}]
    per_stock: list[dict[str, Any]] = field(default_factory=list)

    # Individual signal records (for detailed analysis)
    signals: list[dict[str, Any]] = field(default_factory=list)

    # Phase distribution: {WATCH: N, ALERT: N, STRONG: N}
    phase_distribution: dict[str, int] = field(default_factory=dict)

    # Errors
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "total_stocks_scanned": self.total_stocks_scanned,
            "total_signals": self.total_signals,
            "elapsed_sec": round(self.elapsed_sec, 2),
            "hit_rates": {str(k): round(v, 4) for k, v in self.hit_rates.items()},
            "avg_returns": {str(k): round(v, 6) for k, v in self.avg_returns.items()},
            "median_returns": {str(k): round(v, 6) for k, v in self.median_returns.items()},
            "avg_mae": round(self.avg_mae, 6),
            "signal_attribution": self.signal_attribution,
            "benchmark_returns": {str(k): round(v, 6) for k, v in self.benchmark_returns.items()},
            "per_stock": self.per_stock,
            "phase_distribution": self.phase_distribution,
            "signal_count_detail": len(self.signals),
            "errors": self.errors,
        }


# ---------- Core Walk-Forward Scanner ----------

def _scan_stock(
    code: str,
    config: ReversalBacktestConfig,
) -> tuple[list[dict], str | None]:
    """Walk-forward scan a single stock for reversal signals.

    Returns:
        (list of signal dicts, error_msg or None)
    """
    from analysis.reversal_detector import detect_reversal, PHASE_ALERT_THRESHOLD
    from data.fetcher import get_stock_data

    try:
        df = get_stock_data(code, period_days=config.period_days)
    except Exception as e:
        return [], f"{code}: fetch failed - {e}"

    if df is None or len(df) < MIN_HISTORY_BARS:
        return [], f"{code}: insufficient data ({len(df) if df is not None else 0} bars)"

    close = df["close"].values
    n = len(df)
    max_forward = max(config.forward_days)
    signals = []

    # Walk forward: at each bar, run detection on data up to that bar
    # Start after MIN_HISTORY_BARS, stop max_forward days before end
    # to ensure we can measure forward returns
    scan_end = n - max_forward
    if scan_end <= MIN_HISTORY_BARS:
        return [], f"{code}: not enough data for walk-forward (n={n})"

    # To avoid generating duplicate signals on consecutive days for the
    # same event, enforce a cooldown after each signal.
    # [PLACEHOLDER: REVERSAL_BT_COOLDOWN_001]
    cooldown = 5
    last_signal_idx = -cooldown - 1

    for i in range(MIN_HISTORY_BARS, scan_end, config.walk_step):
        if i - last_signal_idx < cooldown:
            continue

        df_slice = df.iloc[:i + 1]
        result = detect_reversal(df_slice)

        if result.score >= config.min_composite_score:
            last_signal_idx = i
            signal_date = str(df.index[i].date()) if hasattr(df.index[i], 'date') else str(df.index[i])

            # Forward returns
            fwd_returns = {}
            mae = 0.0
            for d in config.forward_days:
                if i + d < n:
                    fwd_price = close[i + d]
                    entry_price = close[i]
                    if entry_price > 0:
                        fwd_returns[d] = float((fwd_price - entry_price) / entry_price)

            # Max Adverse Excursion: worst low in forward window
            forward_window_end = min(i + max_forward + 1, n)
            if forward_window_end > i + 1:
                forward_lows = df["low"].values[i + 1:forward_window_end]
                entry_price = close[i]
                if entry_price > 0 and len(forward_lows) > 0:
                    worst_low = np.min(forward_lows)
                    mae = float((worst_low - entry_price) / entry_price)

            # Random benchmark: entry N days before
            random_returns = {}
            np.random.seed(i)  # deterministic per position
            offset = np.random.randint(1, RANDOM_OFFSET_RANGE + 1)
            rand_idx = max(0, i - offset)
            rand_price = close[rand_idx]
            for d in config.forward_days:
                rand_fwd_idx = rand_idx + d
                if rand_fwd_idx < n and rand_price > 0:
                    random_returns[d] = float((close[rand_fwd_idx] - rand_price) / rand_price)

            # Sub-signal attribution
            active_signals = []
            for s in result.signals:
                if s.score > 0:
                    active_signals.append({
                        "type": s.signal_type,
                        "score": s.score,
                        "direction": s.direction,
                    })

            signals.append({
                "code": code,
                "date": signal_date,
                "bar_index": int(i),
                "composite_score": result.score,
                "phase": result.phase,
                "forward_returns": fwd_returns,
                "mae": mae,
                "random_returns": random_returns,
                "active_signals": active_signals,
            })

    return signals, None


def _aggregate_results(
    all_signals: list[dict],
    config: ReversalBacktestConfig,
    total_stocks: int,
    elapsed: float,
    errors: list[str],
) -> ReversalBacktestResult:
    """Aggregate individual signal records into summary metrics."""
    result = ReversalBacktestResult(
        total_stocks_scanned=total_stocks,
        total_signals=len(all_signals),
        elapsed_sec=elapsed,
        errors=errors,
    )

    if not all_signals:
        return result

    # Forward return arrays per horizon
    for d in config.forward_days:
        returns = [s["forward_returns"].get(d) for s in all_signals if d in s["forward_returns"]]
        if returns:
            returns_arr = np.array(returns, dtype=float)
            result.hit_rates[d] = float(np.mean(returns_arr > 0))
            result.avg_returns[d] = float(np.mean(returns_arr))
            result.median_returns[d] = float(np.median(returns_arr))

        # Benchmark
        rand_returns = [s["random_returns"].get(d) for s in all_signals if d in s.get("random_returns", {})]
        if rand_returns:
            result.benchmark_returns[d] = float(np.mean(rand_returns))

    # MAE
    mae_list = [s["mae"] for s in all_signals if s["mae"] != 0]
    if mae_list:
        result.avg_mae = float(np.mean(mae_list))

    # Phase distribution
    phase_counts: dict[str, int] = {}
    for s in all_signals:
        phase = s.get("phase", "NONE")
        phase_counts[phase] = phase_counts.get(phase, 0) + 1
    result.phase_distribution = phase_counts

    # Signal attribution
    attribution: dict[str, dict[str, Any]] = {}
    for sig_type in SIGNAL_TYPES:
        attribution[sig_type] = {"count": 0, "total_score": 0.0, "win_contribution": 0}

    for s in all_signals:
        d10_return = s["forward_returns"].get(10, s["forward_returns"].get(
            max(s["forward_returns"].keys()) if s["forward_returns"] else 10, None
        ))
        is_winner = d10_return is not None and d10_return > 0

        for sub in s.get("active_signals", []):
            sig_type = sub["type"]
            if sig_type in attribution:
                attribution[sig_type]["count"] += 1
                attribution[sig_type]["total_score"] += sub["score"]
                if is_winner:
                    attribution[sig_type]["win_contribution"] += 1

    # Compute averages
    for sig_type, data in attribution.items():
        if data["count"] > 0:
            data["avg_score"] = round(data["total_score"] / data["count"], 1)
            data["win_rate"] = round(data["win_contribution"] / data["count"], 4)
        else:
            data["avg_score"] = 0.0
            data["win_rate"] = 0.0
        del data["total_score"]

    result.signal_attribution = attribution

    # Per-stock breakdown
    by_stock: dict[str, list[dict]] = {}
    for s in all_signals:
        by_stock.setdefault(s["code"], []).append(s)

    per_stock_list = []
    for code, sigs in sorted(by_stock.items()):
        d10_rets = [s["forward_returns"].get(10) for s in sigs if 10 in s["forward_returns"]]
        d10_arr = np.array(d10_rets, dtype=float) if d10_rets else np.array([])
        stock_summary = {
            "code": code,
            "signal_count": len(sigs),
            "avg_score": round(float(np.mean([s["composite_score"] for s in sigs])), 1),
        }
        if len(d10_arr) > 0:
            stock_summary["hit_rate_d10"] = round(float(np.mean(d10_arr > 0)), 4)
            stock_summary["avg_return_d10"] = round(float(np.mean(d10_arr)), 6)
        per_stock_list.append(stock_summary)

    result.per_stock = per_stock_list
    result.signals = all_signals

    return result


# ---------- Public API ----------

def run_reversal_backtest(config: ReversalBacktestConfig) -> ReversalBacktestResult:
    """Run walk-forward reversal backtest across stock universe.

    Args:
        config: Backtest configuration.

    Returns:
        ReversalBacktestResult with all metrics.
    """
    if not config.universe:
        # Load default validation stocks
        if VALIDATION_STOCKS_PATH.exists():
            with open(VALIDATION_STOCKS_PATH, encoding="utf-8") as f:
                stocks = json.load(f)
            config.universe = [s["code"] for s in stocks]
        else:
            return ReversalBacktestResult(errors=["No universe specified and validation file not found"])

    _logger.info("Starting reversal backtest: %d stocks, threshold=%.1f",
                 len(config.universe), config.min_composite_score)

    start = time.time()
    all_signals: list[dict] = []
    errors: list[str] = []

    for i, code in enumerate(config.universe):
        _logger.info("[%d/%d] Scanning %s...", i + 1, len(config.universe), code)
        signals, err = _scan_stock(code, config)
        if err:
            errors.append(err)
            _logger.warning("  %s", err)
        if signals:
            all_signals.extend(signals)
            _logger.info("  %s: %d signals found", code, len(signals))

    elapsed = time.time() - start

    result = _aggregate_results(
        all_signals=all_signals,
        config=config,
        total_stocks=len(config.universe),
        elapsed=elapsed,
        errors=errors,
    )

    _logger.info("Backtest complete: %d signals from %d stocks in %.1fs",
                 result.total_signals, result.total_stocks_scanned, elapsed)

    return result


def run_quick_backtest(
    codes: list[str],
    days: int = 365,
    min_score: float = DEFAULT_MIN_COMPOSITE_SCORE,
) -> ReversalBacktestResult:
    """Simplified backtest for API endpoint — fewer stocks, shorter history.

    Args:
        codes: List of stock codes to scan.
        days: Number of days of history.
        min_score: Minimum composite score threshold.

    Returns:
        ReversalBacktestResult.
    """
    config = ReversalBacktestConfig(
        universe=codes,
        min_composite_score=min_score,
        forward_days=[5, 10, 20],
        period_days=days,
        walk_step=1,
    )
    return run_reversal_backtest(config)


def load_validation_stocks() -> list[dict]:
    """Load the 100 validation stocks from JSON."""
    if not VALIDATION_STOCKS_PATH.exists():
        return []
    with open(VALIDATION_STOCKS_PATH, encoding="utf-8") as f:
        return json.load(f)

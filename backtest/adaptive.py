"""Adaptive Strategy Backtester (Gemini R52 P0)

Simulates dynamic strategy switching over historical data based on ML market
regime classification. Compares adaptive performance vs fixed V4 baseline.

The backtester re-classifies the market regime every `rebalance_days` days
using a rolling window of `regime_lookback` bars, then selects V4 parameters
based on the regime-to-strategy mapping from strategy_adapter.py.
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine, BacktestResult
from config import STRATEGY_V4_PARAMS

logger = logging.getLogger(__name__)

# Regime -> parameter overrides (mirrors strategy_adapter.py logic)
REGIME_PARAM_MAP = {
    "bull_trending": {
        "adx_threshold": 15,
        "take_profit_pct": 0.15,
        "stop_loss_pct": 0.10,
        "trailing_stop_pct": 0.025,
        "max_position_pct": 0.95,
    },
    "bull_volatile": {
        "trailing_stop_pct": 0.015,
        "max_position_pct": 0.85,
    },
    "bear_trending": {
        "adx_threshold": 25,
        "stop_loss_pct": 0.05,
        "max_position_pct": 0.5,
        "min_hold_days": 3,
    },
    "bear_volatile": {
        "adx_threshold": 30,
        "stop_loss_pct": 0.04,
        "max_position_pct": 0.3,
        "min_hold_days": 3,
        "_pause_entries": True,  # skip new entries
    },
    "range_quiet": {
        "adx_threshold": 22,
        "max_position_pct": 0.7,
        "min_volume": 600,
    },
    "range_volatile": {
        "adx_threshold": 28,
        "stop_loss_pct": 0.05,
        "max_position_pct": 0.5,
        "min_hold_days": 3,
    },
}


@dataclass
class AdaptiveBacktestResult:
    """Result of adaptive vs fixed backtest comparison."""
    adaptive: BacktestResult = field(default_factory=BacktestResult)
    baseline: BacktestResult = field(default_factory=BacktestResult)

    # Per-regime performance breakdown
    regime_log: list[dict] = field(default_factory=list)
    regime_performance: list[dict] = field(default_factory=list)

    # Comparison metrics
    alpha: float = 0.0       # adaptive return - baseline return
    sharpe_delta: float = 0.0
    drawdown_delta: float = 0.0  # positive = adaptive is better


def run_adaptive_backtest(
    df: pd.DataFrame,
    initial_capital: float = 1_000_000,
    rebalance_days: int = 5,
    regime_lookback: int = 60,
) -> AdaptiveBacktestResult:
    """Run adaptive vs fixed V4 backtest.

    Args:
        df: OHLCV DataFrame (at least regime_lookback + 60 bars)
        initial_capital: Starting capital
        rebalance_days: Re-classify regime every N trading days
        regime_lookback: Number of bars for regime classification window

    Returns:
        AdaptiveBacktestResult with both equity curves and comparison
    """
    from backend.regime_classifier import classify_market_regime
    from analysis.strategy_v4 import generate_v4_signals
    from config import TRADE_UNIT

    n = len(df)
    if n < regime_lookback + 60:
        raise ValueError(f"Need at least {regime_lookback + 60} bars, got {n}")

    # --- Phase 1: Classify regime at each rebalance point ---
    regime_timeline = []  # list of (date_idx, regime, confidence, kelly)
    for i in range(regime_lookback, n, rebalance_days):
        window = df.iloc[max(0, i - regime_lookback):i]
        try:
            rd = classify_market_regime(
                close=window["close"].values,
                high=window["high"].values,
                low=window["low"].values,
                volume=window["volume"].values.astype(float),
            )
            regime_timeline.append({
                "idx": i,
                "date": df.index[i],
                "regime": rd["regime"],
                "label": rd.get("regime_label", ""),
                "confidence": rd.get("confidence", 0.5),
                "kelly": rd.get("kelly_multiplier", 0.5),
            })
        except Exception:
            regime_timeline.append({
                "idx": i, "date": df.index[i],
                "regime": "unknown", "label": "Unknown",
                "confidence": 0.3, "kelly": 0.3,
            })

    # --- Phase 2: Run adaptive V4 backtest ---
    # Build a day-to-regime map
    day_regime = {}
    for j, rt in enumerate(regime_timeline):
        end_idx = regime_timeline[j + 1]["idx"] if j + 1 < len(regime_timeline) else n
        for k in range(rt["idx"], end_idx):
            day_regime[k] = rt

    # Run adaptive: generate signals once with standard params, but apply
    # regime-specific exit params and entry filters during the trade loop
    base_params = dict(STRATEGY_V4_PARAMS)
    signals_df = generate_v4_signals(df, params=base_params)

    engine = BacktestEngine(initial_capital=initial_capital)
    rf_daily = engine._rf_daily

    tp_base = base_params.get("take_profit_pct", 0.10)
    sl_base = base_params.get("stop_loss_pct", 0.07)
    trailing_base = base_params.get("trailing_stop_pct", 0.02)
    max_pos_base = base_params.get("max_position_pct", 0.9)
    min_hold_base = base_params.get("min_hold_days", 5)

    cash = initial_capital
    position = 0
    trades = []
    current_trade = None
    equity_history = []
    hold_days = 0
    highest_since_entry = 0.0
    tp_price = sl_price = original_sl_price = 0.0

    # Active params (updated on regime changes)
    active_tp = tp_base
    active_sl = sl_base
    active_trailing = trailing_base
    active_max_pos = max_pos_base
    active_min_hold = min_hold_base
    active_pause = False
    current_regime_name = "unknown"

    _has_v4 = "v4_signal" in signals_df.columns
    _has_vol = "volume" in signals_df.columns

    for i, row in enumerate(signals_df.itertuples()):
        date = row.Index
        price = row.close
        high = row.high if hasattr(row, "high") else price
        low = row.low if hasattr(row, "low") else price
        signal = row.v4_signal if _has_v4 else "HOLD"

        # Update regime params if we're at a regime boundary
        rt = day_regime.get(i)
        if rt and rt["regime"] != current_regime_name:
            current_regime_name = rt["regime"]
            overrides = REGIME_PARAM_MAP.get(current_regime_name, {})

            active_tp = overrides.get("take_profit_pct", tp_base)
            active_sl = overrides.get("stop_loss_pct", sl_base)
            active_trailing = overrides.get("trailing_stop_pct", trailing_base)
            active_max_pos = overrides.get("max_position_pct", max_pos_base)
            active_min_hold = overrides.get("min_hold_days", min_hold_base)
            active_pause = overrides.get("_pause_entries", False)

            # Apply Kelly multiplier to position size
            kelly = rt.get("kelly", 0.5)
            if rt.get("confidence", 0.5) < 0.4:
                kelly *= 0.7
            active_max_pos = min(active_max_pos, active_max_pos * kelly / 0.5)

        # Holding: update tracking
        if position > 0:
            highest_since_entry = max(highest_since_entry, high)
            hold_days += 1

            if active_trailing > 0:
                new_sl = highest_since_entry * (1 - active_trailing)
                if new_sl > sl_price:
                    sl_price = new_sl

        # Exit checks
        force_sell = False
        exit_reason = ""
        exit_price = 0.0

        if position > 0 and current_trade is not None and hold_days >= active_min_hold:
            if active_tp > 0 and high >= tp_price and low <= sl_price:
                force_sell = True
                if price >= current_trade.price_open:
                    exit_reason, exit_price = "take_profit", tp_price
                else:
                    exit_reason = "trailing_stop" if sl_price > original_sl_price else "stop_loss"
                    exit_price = sl_price
            elif active_tp > 0 and high >= tp_price:
                force_sell, exit_reason, exit_price = True, "take_profit", tp_price
            elif low <= sl_price:
                force_sell = True
                exit_reason = "trailing_stop" if sl_price > original_sl_price else "stop_loss"
                exit_price = sl_price

        if force_sell and position > 0 and current_trade is not None:
            cash += engine._close_position(position, exit_price, current_trade, date, exit_reason)
            trades.append(current_trade)
            position, current_trade, hold_days = 0, None, 0

        # Cash earns risk-free
        if position == 0 and cash > 0:
            cash *= (1 + rf_daily)

        equity_history.append({"date": date, "equity": cash + position * price})

        # Entry
        if signal == "BUY" and position == 0 and not active_pause:
            volume = row.volume if _has_vol else 0
            trade, shares, cash = engine._open_position(
                price, high, volume, cash, active_max_pos, date)
            if trade is not None:
                position = shares
                current_trade = trade
                highest_since_entry = high
                hold_days = 0
                tp_price = trade.price_open * (1 + active_tp) if active_tp > 0 else float("inf")
                sl_price = trade.price_open * (1 - active_sl)
                original_sl_price = sl_price

    # End of period: close remaining position
    if position > 0 and current_trade is not None:
        last_price = signals_df.iloc[-1]["close"]
        cash += engine._close_position(position, last_price, current_trade,
                                       signals_df.index[-1], "end_of_period")
        trades.append(current_trade)

    adaptive_result = BacktestResult(
        trades=trades,
        equity_curve=BacktestEngine._build_equity_curve(equity_history),
    )
    engine._calculate_metrics(adaptive_result)

    # --- Phase 3: Run fixed V4 baseline ---
    baseline_result = BacktestEngine(initial_capital=initial_capital).run_v4(df)

    # --- Phase 4: Per-regime performance breakdown ---
    regime_performance = _compute_regime_performance(trades, regime_timeline, df)

    # --- Phase 5: Build comparison ---
    alpha = adaptive_result.total_return - baseline_result.total_return
    sharpe_delta = adaptive_result.sharpe_ratio - baseline_result.sharpe_ratio
    drawdown_delta = adaptive_result.max_drawdown - baseline_result.max_drawdown

    return AdaptiveBacktestResult(
        adaptive=adaptive_result,
        baseline=baseline_result,
        regime_log=regime_timeline,
        regime_performance=regime_performance,
        alpha=round(alpha, 4),
        sharpe_delta=round(sharpe_delta, 4),
        drawdown_delta=round(drawdown_delta, 4),
    )


def _compute_regime_performance(trades, regime_timeline, df):
    """Compute per-regime trade statistics."""
    # Map trade entry dates to regimes
    regime_map = {}
    for j, rt in enumerate(regime_timeline):
        end_date = regime_timeline[j + 1]["date"] if j + 1 < len(regime_timeline) else df.index[-1]
        regime_map[(rt["date"], end_date)] = rt["label"]

    def _get_regime_for_date(d):
        for (start, end), label in regime_map.items():
            if start <= d <= end:
                return label
        return "Unknown"

    # Group trades by regime
    from collections import defaultdict
    groups = defaultdict(list)
    for t in trades:
        if t.date_open:
            label = _get_regime_for_date(t.date_open)
            groups[label].append(t)

    results = []
    for label, group_trades in groups.items():
        pnls = [t.pnl for t in group_trades]
        returns = [t.return_pct for t in group_trades]
        wins = sum(1 for p in pnls if p > 0)
        results.append({
            "regime": label,
            "count": len(group_trades),
            "win_rate": round(wins / len(group_trades), 3) if group_trades else 0,
            "avg_return": round(float(np.mean(returns)), 4) if returns else 0,
            "total_pnl": round(sum(pnls), 0),
        })

    results.sort(key=lambda x: x["count"], reverse=True)
    return results

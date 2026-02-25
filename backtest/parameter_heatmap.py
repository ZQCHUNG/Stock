"""Parameter Sensitivity Heatmap — Grid search for Bold Strategy parameters.

P2-A: CTO Gemini directive — "我們需要知道 Entry D 的容錯空間"
Sweep two parameters across a grid, compute aggregate metrics per cell.

Identifies:
  - "Profit Plateau": stable region where metrics don't change much → robust
  - "Parameter Islands": isolated peaks → overfitting risk

Usage:
    result = run_heatmap(
        stock_codes=["2330", "2454", ...],
        x_param="momentum_high_pct",
        x_values=[0.93, 0.95, 0.97, 0.99],
        y_param="momentum_ma20_slope_days",
        y_values=[5, 10, 15, 20, 30, 40],
        period_days=1825,
    )
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import numpy as np
import pandas as pd

from analysis.strategy_bold import STRATEGY_BOLD_PARAMS
from backtest.engine import run_backtest_bold, BacktestResult

logger = logging.getLogger(__name__)

# Default Entry D parameter sweep ranges (CTO directive)
DEFAULT_PRESETS = {
    "entry_d_threshold_vs_lookback": {
        "x_param": "momentum_high_pct",
        "x_values": [0.93, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99],
        "x_label": "Near-High Threshold (%)",
        "y_param": "momentum_ma20_slope_days",
        "y_values": [5, 10, 15, 20, 25, 30, 35, 40],
        "y_label": "MA20 Slope Persistence (days)",
    },
    "entry_d_rsi_vs_volume": {
        "x_param": "momentum_rsi_min",
        "x_values": [45, 50, 55, 60, 65],
        "x_label": "RSI Lower Bound",
        "y_param": "momentum_vol_ratio",
        "y_values": [0.8, 1.0, 1.2, 1.5, 2.0],
        "y_label": "Volume Ratio (5d/20d)",
    },
}

# Metrics to compute per cell
METRICS = ["sharpe_ratio", "calmar_ratio", "win_rate", "profit_factor",
           "total_trades", "total_return", "max_drawdown", "avg_holding_days"]


def _run_single_backtest(
    code: str, df: pd.DataFrame, params: dict
) -> Optional[BacktestResult]:
    """Run a single Bold backtest, return result or None on failure."""
    try:
        result = run_backtest_bold(df, params=params)
        return result
    except Exception as e:
        logger.debug("Backtest failed for %s: %s", code, e)
        return None


def _extract_metrics(result: BacktestResult) -> dict:
    """Extract key metrics from a BacktestResult."""
    return {
        "sharpe_ratio": result.sharpe_ratio,
        "calmar_ratio": result.calmar_ratio,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "total_trades": result.total_trades,
        "total_return": result.total_return,
        "max_drawdown": result.max_drawdown,
        "avg_holding_days": result.avg_holding_days,
    }


def _aggregate_metrics(all_metrics: list[dict]) -> dict:
    """Aggregate metrics across multiple stocks.

    Returns mean for ratio metrics, sum for count metrics.
    """
    if not all_metrics:
        return {m: None for m in METRICS}

    agg = {}
    for m in METRICS:
        vals = [d[m] for d in all_metrics if d[m] is not None and np.isfinite(d[m])]
        if not vals:
            agg[m] = None
            continue
        if m == "total_trades":
            agg[m] = round(float(np.mean(vals)), 1)  # avg trades per stock
        elif m in ("max_drawdown",):
            agg[m] = round(float(np.mean(vals)), 4)  # avg MDD
        else:
            agg[m] = round(float(np.mean(vals)), 4)
    return agg


def _classify_cell(value: float, all_values: list[float]) -> str:
    """Classify a cell as plateau, island, or desert.

    - plateau: within 0.5 std of mean (robust)
    - island: > 1.5 std above mean (suspiciously good → overfit risk)
    - desert: < 0.5 std below mean (poor performance)
    """
    if not all_values or value is None:
        return "unknown"
    arr = np.array([v for v in all_values if v is not None and np.isfinite(v)])
    if len(arr) < 3:
        return "unknown"
    mean, std = float(np.mean(arr)), float(np.std(arr))
    if std < 1e-6:
        return "plateau"
    z = (value - mean) / std
    if z > 1.5:
        return "island"
    elif z < -0.5:
        return "desert"
    return "plateau"


def run_heatmap(
    stock_data: dict[str, pd.DataFrame],
    x_param: str,
    x_values: list,
    y_param: str,
    y_values: list,
    metric: str = "sharpe_ratio",
    max_workers: int = 4,
) -> dict:
    """Run parameter sensitivity heatmap.

    Args:
        stock_data: {code: DataFrame} pre-loaded stock data
        x_param: Parameter name for X-axis
        x_values: Values to sweep on X-axis
        y_param: Parameter name for Y-axis
        y_values: Values to sweep on Y-axis
        metric: Primary metric for heatmap coloring
        max_workers: Parallel workers for backtesting

    Returns:
        {
            "x_param": str, "x_values": [...],
            "y_param": str, "y_values": [...],
            "metric": str,
            "matrix": [[value, ...], ...],  # y_values × x_values
            "zones": [[zone_label, ...], ...],  # "plateau"/"island"/"desert"
            "all_metrics": {metric_name: [[...], ...]},
            "stocks_used": int,
            "compute_time_sec": float,
            "default_x": current_default_x,
            "default_y": current_default_y,
        }
    """
    t0 = time.time()
    codes = list(stock_data.keys())
    logger.info(
        "Heatmap: %s × %s, %d×%d grid, %d stocks",
        x_param, y_param, len(x_values), len(y_values), len(codes),
    )

    # Validate params exist
    base_params = STRATEGY_BOLD_PARAMS.copy()
    if x_param not in base_params:
        raise ValueError(f"Unknown parameter: {x_param}")
    if y_param not in base_params:
        raise ValueError(f"Unknown parameter: {y_param}")

    default_x = base_params[x_param]
    default_y = base_params[y_param]

    # Build grid: (y_idx, x_idx) → aggregated metrics
    grid = {}
    total_cells = len(x_values) * len(y_values)
    done = 0

    for yi, yv in enumerate(y_values):
        for xi, xv in enumerate(x_values):
            params = base_params.copy()
            params[x_param] = xv
            params[y_param] = yv

            # Run across all stocks in parallel
            cell_metrics = []
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {
                    pool.submit(_run_single_backtest, code, df, params): code
                    for code, df in stock_data.items()
                }
                for fut in as_completed(futures):
                    result = fut.result()
                    if result and result.total_trades > 0:
                        cell_metrics.append(_extract_metrics(result))

            grid[(yi, xi)] = _aggregate_metrics(cell_metrics)
            done += 1
            if done % 5 == 0:
                logger.info("Heatmap progress: %d/%d cells", done, total_cells)

    # Build output matrices
    all_metric_matrices = {}
    for m in METRICS:
        mat = []
        for yi in range(len(y_values)):
            row = []
            for xi in range(len(x_values)):
                val = grid.get((yi, xi), {}).get(m)
                row.append(val)
            mat.append(row)
        all_metric_matrices[m] = mat

    # Primary metric matrix
    primary_matrix = all_metric_matrices.get(metric, [])

    # Flatten for zone classification
    flat_values = [
        v for row in primary_matrix for v in row
        if v is not None and np.isfinite(v)
    ]

    # Zone classification
    zones = []
    for yi in range(len(y_values)):
        row = []
        for xi in range(len(x_values)):
            val = primary_matrix[yi][xi] if yi < len(primary_matrix) else None
            row.append(_classify_cell(val, flat_values))
        zones.append(row)

    elapsed = time.time() - t0
    logger.info("Heatmap complete: %.1fs", elapsed)

    return {
        "x_param": x_param,
        "x_values": x_values,
        "x_label": _param_label(x_param),
        "y_param": y_param,
        "y_values": y_values,
        "y_label": _param_label(y_param),
        "metric": metric,
        "matrix": primary_matrix,
        "zones": zones,
        "all_metrics": all_metric_matrices,
        "stocks_used": len(codes),
        "compute_time_sec": round(elapsed, 1),
        "default_x": default_x,
        "default_y": default_y,
    }


def _param_label(param: str) -> str:
    """Human-readable label for a parameter."""
    labels = {
        "momentum_high_pct": "Near-High Threshold",
        "momentum_ma20_slope_days": "MA20 Slope Persistence (days)",
        "momentum_rsi_min": "RSI Lower Bound",
        "momentum_rsi_max": "RSI Upper Bound",
        "momentum_vol_ratio": "Volume Ratio (5d/20d)",
        "momentum_min_volume_lots": "Min Volume (lots)",
        "trail_level1_pct": "Trail Level 1 (%)",
        "trail_level3_pct": "Trail Level 3 (%)",
        "stop_loss_pct": "Stop Loss (%)",
        "vcp_atr_tightness_max": "VCP ATR Tightness",
    }
    return labels.get(param, param)


def get_presets() -> dict:
    """Return available preset sweep configurations."""
    return DEFAULT_PRESETS

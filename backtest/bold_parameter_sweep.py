"""Bold 策略參數敏感度分析 — 用數據驗證參數，消滅「假精確」

背景（Joe 的 feedback.txt 批評）：
- conviction_hold_gain = 1.0 → 為什麼不是 0.8 或 1.2？沒有數據依據。
- trail_level3_pct = 0.25 → 為什麼不是 0.20 或 0.35？
- ATR multiplier = 3.0 → 為什麼不是 2.5 或 4.0？
- 所有數字都需要 backtest evidence 才能確定。

方法：
1. 在 3 檔歷史股票上 sweep 參數
2. 紀錄 Total Return, MDD, Sharpe, Win Rate, Max Hold Days
3. 輸出 heatmap 數據 + robustness band 分析
4. 如果最優區間不重疊 → 需要「分群治理」

參數標記規則：
- VALIDATED(n=X, period=Y) — 有 sweep 數據支持
- HYPOTHESIS — 有邏輯但無數據
- PLACEHOLDER_NEEDS_DATA — 純猜測
"""

import sys
import os
import itertools
import json
from datetime import datetime

import numpy as np
import pandas as pd

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import BacktestEngine


def fetch_stock_data(code: str, period_days: int = 2000) -> pd.DataFrame:
    """Fetch stock data directly via yfinance (bypass TWSE sync for speed)."""
    import yfinance as yf
    from data.fetcher import get_ticker
    from datetime import datetime, timedelta

    end = datetime.now()
    start = end - timedelta(days=period_days)
    ticker = get_ticker(code)
    df = yf.Ticker(ticker).history(
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        auto_adjust=True,
    )
    if df is None or df.empty:
        return pd.DataFrame()

    # Normalize columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]

    # Keep only needed columns
    cols = ["open", "high", "low", "close", "volume"]
    available = [c for c in cols if c in df.columns]
    df = df[available].copy()
    df.index.name = "date"
    return df


def run_single_sweep(
    df: pd.DataFrame,
    param_overrides: dict,
    ultra_wide: bool = True,
    initial_capital: int = 1_000_000,
) -> dict:
    """Run a single backtest with given parameter overrides.

    Returns dict with key metrics.
    """
    engine = BacktestEngine(initial_capital=initial_capital)
    try:
        result = engine.run_bold(df, params=param_overrides, ultra_wide=ultra_wide)
    except Exception as e:
        return {
            "total_return": np.nan,
            "max_drawdown": np.nan,
            "sharpe_ratio": np.nan,
            "win_rate": np.nan,
            "total_trades": 0,
            "max_hold_days": 0,
            "error": str(e),
        }

    # Calculate max hold days from trades
    max_hold = 0
    for t in result.trades:
        if t.date_close and t.date_open:
            days = (t.date_close - t.date_open).days
            max_hold = max(max_hold, days)

    return {
        "total_return": result.total_return,
        "max_drawdown": result.max_drawdown,
        "sharpe_ratio": result.sharpe_ratio,
        "win_rate": result.win_rate,
        "total_trades": result.total_trades,
        "max_hold_days": max_hold,
        "annual_return": result.annual_return,
        "profit_factor": getattr(result, 'profit_factor', np.nan),
    }


def sweep_conviction_vs_trail(
    df: pd.DataFrame,
    stock_code: str,
    conviction_gains: list[float] = None,
    trail_pcts: list[float] = None,
) -> pd.DataFrame:
    """Sweep conviction_hold_gain × trail_level3_pct grid.

    Returns DataFrame with all combinations and metrics.
    """
    if conviction_gains is None:
        conviction_gains = [0.3, 0.5, 0.8, 1.0, 1.2, 1.5]
    if trail_pcts is None:
        trail_pcts = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]

    rows = []
    total = len(conviction_gains) * len(trail_pcts)
    count = 0

    for cg, tp in itertools.product(conviction_gains, trail_pcts):
        count += 1
        print(f"  [{stock_code}] {count}/{total}: conviction_gain={cg}, trail_l3={tp}")

        overrides = {
            "conviction_hold_gain": cg,
            "trail_level3_pct": tp,
            "trail_ultra_wide_pct": tp + 0.05,  # ultra-wide always 5pp wider
        }

        metrics = run_single_sweep(df, overrides, ultra_wide=True)
        metrics["stock"] = stock_code
        metrics["conviction_hold_gain"] = cg
        metrics["trail_level3_pct"] = tp
        rows.append(metrics)

    return pd.DataFrame(rows)


def sweep_atr_multiplier(
    df: pd.DataFrame,
    stock_code: str,
    atr_mults: list[float] = None,
) -> pd.DataFrame:
    """Sweep ATR trail multiplier (standard mode, not ultra-wide)."""
    if atr_mults is None:
        atr_mults = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]

    rows = []
    for mult in atr_mults:
        print(f"  [{stock_code}] ATR mult={mult}")
        overrides = {"atr_trail_multiplier": mult}
        # Test in STANDARD mode (ATR matters more in standard)
        metrics = run_single_sweep(df, overrides, ultra_wide=False)
        metrics["stock"] = stock_code
        metrics["atr_multiplier"] = mult
        rows.append(metrics)

    return pd.DataFrame(rows)


def sweep_stop_loss(
    df: pd.DataFrame,
    stock_code: str,
    stop_losses: list[float] = None,
) -> pd.DataFrame:
    """Sweep disaster stop loss percentage."""
    if stop_losses is None:
        stop_losses = [0.10, 0.12, 0.15, 0.18, 0.20, 0.25]

    rows = []
    for sl in stop_losses:
        print(f"  [{stock_code}] stop_loss={sl}")
        overrides = {"stop_loss_pct": sl}
        metrics = run_single_sweep(df, overrides, ultra_wide=True)
        metrics["stock"] = stock_code
        metrics["stop_loss_pct"] = sl
        rows.append(metrics)

    return pd.DataFrame(rows)


def sweep_regime_trail(
    df: pd.DataFrame,
    stock_code: str,
    regime_trail_pcts: list[float] = None,
    base_trail_pcts: list[float] = None,
) -> pd.DataFrame:
    """Sweep trail_regime_wide_pct × trail_level3_pct grid (Conviction 2.0).

    Tests how regime-based dynamic trail width affects performance.
    - trail_level3_pct = base trail (bearish/flat market)
    - trail_regime_wide_pct = widened trail (bullish MA200 slope)
    """
    if regime_trail_pcts is None:
        regime_trail_pcts = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
    if base_trail_pcts is None:
        base_trail_pcts = [0.10, 0.15, 0.20]

    rows = []
    total = len(regime_trail_pcts) * len(base_trail_pcts)
    count = 0

    for rt, bt in itertools.product(regime_trail_pcts, base_trail_pcts):
        count += 1
        # regime trail must be >= base trail
        if rt < bt:
            continue
        print(f"  [{stock_code}] {count}/{total}: regime_trail={rt}, base_trail={bt}")

        overrides = {
            "trail_level3_pct": bt,
            "trail_regime_wide_pct": rt,
            "regime_trail_enabled": True,
        }

        metrics = run_single_sweep(df, overrides, ultra_wide=True)
        metrics["stock"] = stock_code
        metrics["trail_regime_wide_pct"] = rt
        metrics["trail_level3_pct"] = bt
        rows.append(metrics)

    # Also test with regime_trail disabled for comparison
    for bt in base_trail_pcts:
        print(f"  [{stock_code}] DISABLED: base_trail={bt} (no regime widening)")
        overrides = {
            "trail_level3_pct": bt,
            "regime_trail_enabled": False,
        }
        metrics = run_single_sweep(df, overrides, ultra_wide=True)
        metrics["stock"] = stock_code
        metrics["trail_regime_wide_pct"] = 0.0  # disabled
        metrics["trail_level3_pct"] = bt
        rows.append(metrics)

    return pd.DataFrame(rows)


def analyze_robustness(sweep_df: pd.DataFrame, param_col: str, metric_col: str = "total_return") -> dict:
    """Analyze robustness of optimal parameter.

    Returns:
        - optimal_value: best param value
        - optimal_metric: best metric value
        - robustness_band: range where metric stays within 80% of optimal
        - cliff_score: 0-1, higher = more cliff-like (less robust)
    """
    if sweep_df.empty or sweep_df[metric_col].isna().all():
        return {"optimal_value": None, "cliff_score": 1.0}

    best_idx = sweep_df[metric_col].idxmax()
    best_val = sweep_df.loc[best_idx, param_col]
    best_metric = sweep_df.loc[best_idx, metric_col]

    if best_metric <= 0:
        return {"optimal_value": best_val, "optimal_metric": best_metric, "cliff_score": 1.0}

    # 80% threshold band
    threshold = best_metric * 0.80
    in_band = sweep_df[sweep_df[metric_col] >= threshold]
    band_min = in_band[param_col].min()
    band_max = in_band[param_col].max()

    # Cliff score: how quickly metric drops off from optimal
    sorted_df = sweep_df.sort_values(param_col)
    values = sorted_df[metric_col].values
    if len(values) > 1:
        max_drop = max(abs(np.diff(values))) / max(abs(best_metric), 0.001)
        cliff_score = min(max_drop, 1.0)
    else:
        cliff_score = 0.0

    return {
        "optimal_value": float(best_val),
        "optimal_metric": float(best_metric),
        "robustness_band": [float(band_min), float(band_max)],
        "band_width": float(band_max - band_min),
        "cliff_score": round(float(cliff_score), 3),
    }


def format_heatmap(sweep_df: pd.DataFrame, row_param: str, col_param: str,
                   metric: str = "total_return") -> str:
    """Format sweep results as text heatmap."""
    pivot = sweep_df.pivot_table(
        values=metric, index=row_param, columns=col_param, aggfunc="first"
    )
    lines = [f"\n{'=' * 70}", f"Heatmap: {metric}", f"Rows: {row_param}, Cols: {col_param}", "=" * 70]

    # Header
    header = f"{'':>12}"
    for col in pivot.columns:
        header += f" {col:>10.2f}"
    lines.append(header)

    # Data rows
    for idx in pivot.index:
        row_str = f"{idx:>12.2f}"
        for col in pivot.columns:
            val = pivot.loc[idx, col]
            if np.isnan(val):
                row_str += f" {'N/A':>10}"
            else:
                row_str += f" {val:>10.1%}"
        lines.append(row_str)

    return "\n".join(lines)


def run_full_sweep(stocks: list[str] = None, period_days: int = 2000) -> dict:
    """Run complete parameter sweep on given stocks.

    Returns dict with all results and analysis.
    """
    if stocks is None:
        stocks = ["6748", "6139", "6442"]

    results = {
        "timestamp": datetime.now().isoformat(),
        "stocks": stocks,
        "conviction_trail_sweep": {},
        "atr_sweep": {},
        "stop_loss_sweep": {},
        "robustness": {},
        "cross_stock_overlap": {},
    }

    all_ct_dfs = []
    all_atr_dfs = []
    all_sl_dfs = []

    for code in stocks:
        print(f"\n{'=' * 60}")
        print(f"Fetching {code}.TW data...")
        print("=" * 60)

        df = fetch_stock_data(code, period_days=period_days)
        if df is None or df.empty:
            print(f"  SKIP: No data for {code}")
            continue

        print(f"  Got {len(df)} days, from {df.index[0]} to {df.index[-1]}")

        # --- Sweep 1: conviction_hold_gain × trail_level3_pct ---
        print(f"\n--- Sweep 1: Conviction × Trail (Ultra-Wide) ---")
        ct_df = sweep_conviction_vs_trail(df, code)
        all_ct_dfs.append(ct_df)
        results["conviction_trail_sweep"][code] = ct_df.to_dict(orient="records")

        # Print heatmap
        print(format_heatmap(ct_df, "conviction_hold_gain", "trail_level3_pct", "total_return"))
        print(format_heatmap(ct_df, "conviction_hold_gain", "trail_level3_pct", "max_drawdown"))

        # --- Sweep 2: ATR multiplier ---
        print(f"\n--- Sweep 2: ATR Multiplier (Standard) ---")
        atr_df = sweep_atr_multiplier(df, code)
        all_atr_dfs.append(atr_df)
        results["atr_sweep"][code] = atr_df.to_dict(orient="records")

        for _, row in atr_df.iterrows():
            print(f"  ATR {row['atr_multiplier']:.1f}x → Return {row['total_return']:.1%}, "
                  f"MDD {row['max_drawdown']:.1%}, Trades {row['total_trades']}")

        # --- Sweep 3: Stop loss ---
        print(f"\n--- Sweep 3: Stop Loss (Ultra-Wide) ---")
        sl_df = sweep_stop_loss(df, code)
        all_sl_dfs.append(sl_df)
        results["stop_loss_sweep"][code] = sl_df.to_dict(orient="records")

        for _, row in sl_df.iterrows():
            print(f"  SL {row['stop_loss_pct']:.0%} → Return {row['total_return']:.1%}, "
                  f"MDD {row['max_drawdown']:.1%}, Trades {row['total_trades']}")

    # --- Cross-stock robustness analysis ---
    print(f"\n{'=' * 60}")
    print("CROSS-STOCK ROBUSTNESS ANALYSIS")
    print("=" * 60)

    for code in stocks:
        if code not in results["conviction_trail_sweep"]:
            continue

        ct_df = pd.DataFrame(results["conviction_trail_sweep"][code])
        if ct_df.empty:
            continue

        # Find best trail_pct for each conviction_gain level
        rob_cg = analyze_robustness(ct_df.groupby("conviction_hold_gain")["total_return"].mean().reset_index(),
                                     "conviction_hold_gain", "total_return")
        rob_tp = analyze_robustness(ct_df.groupby("trail_level3_pct")["total_return"].mean().reset_index(),
                                     "trail_level3_pct", "total_return")

        results["robustness"][code] = {
            "conviction_gain": rob_cg,
            "trail_level3_pct": rob_tp,
        }
        print(f"\n{code}:")
        print(f"  conviction_hold_gain: optimal={rob_cg.get('optimal_value')}, "
              f"cliff={rob_cg.get('cliff_score')}, band={rob_cg.get('robustness_band')}")
        print(f"  trail_level3_pct:     optimal={rob_tp.get('optimal_value')}, "
              f"cliff={rob_tp.get('cliff_score')}, band={rob_tp.get('robustness_band')}")

    # --- Check cross-stock parameter overlap ---
    print(f"\n{'=' * 60}")
    print("PARAMETER OVERLAP CHECK")
    print("(If bands don't overlap → need cluster-based params)")
    print("=" * 60)

    for param_name in ["conviction_gain", "trail_level3_pct"]:
        bands = {}
        for code in stocks:
            if code in results["robustness"]:
                rob = results["robustness"][code].get(param_name, {})
                band = rob.get("robustness_band")
                if band:
                    bands[code] = band

        if len(bands) >= 2:
            # Check pairwise overlap
            codes = list(bands.keys())
            all_overlap = True
            for i in range(len(codes)):
                for j in range(i + 1, len(codes)):
                    b1, b2 = bands[codes[i]], bands[codes[j]]
                    overlap = max(0, min(b1[1], b2[1]) - max(b1[0], b2[0]))
                    total = max(b1[1], b2[1]) - min(b1[0], b2[0])
                    overlap_pct = overlap / total if total > 0 else 0
                    print(f"  {param_name}: {codes[i]} {b1} ∩ {codes[j]} {b2} → overlap {overlap_pct:.0%}")
                    if overlap_pct < 0.1:
                        all_overlap = False

            results["cross_stock_overlap"][param_name] = {
                "bands": bands,
                "all_overlap": all_overlap,
                "verdict": "ONE_SIZE_FITS_ALL" if all_overlap else "NEEDS_CLUSTERING",
            }
            print(f"  → Verdict: {'ONE_SIZE_FITS_ALL [OK]' if all_overlap else 'NEEDS_CLUSTERING [X]'}")

    # --- Final summary ---
    print(f"\n{'=' * 60}")
    print("PARAMETER VALIDATION SUMMARY")
    print("=" * 60)

    for code in stocks:
        if code not in results["robustness"]:
            continue
        rob = results["robustness"][code]
        cg = rob.get("conviction_gain", {})
        tp = rob.get("trail_level3_pct", {})
        print(f"\n{code}:")
        print(f"  conviction_hold_gain: {cg.get('optimal_value', 'N/A')}"
              f" [{'ROBUST' if cg.get('cliff_score', 1) < 0.5 else 'FRAGILE'}]")
        print(f"  trail_level3_pct:     {tp.get('optimal_value', 'N/A')}"
              f" [{'ROBUST' if tp.get('cliff_score', 1) < 0.5 else 'FRAGILE'}]")

    return results


def run_regime_sweep(stocks: list[str] = None, period_days: int = 2000) -> dict:
    """Run Conviction 2.0 regime trail sweep.

    Tests trail_regime_wide_pct vs trail_level3_pct combinations,
    plus disabled-regime baseline comparison.
    """
    if stocks is None:
        stocks = ["6748", "6139", "6442"]

    results = {
        "timestamp": datetime.now().isoformat(),
        "stocks": stocks,
        "regime_trail_sweep": {},
        "robustness": {},
    }

    for code in stocks:
        print(f"\n{'=' * 60}")
        print(f"Fetching {code}.TW data...")
        print("=" * 60)

        df = fetch_stock_data(code, period_days=period_days)
        if df is None or df.empty:
            print(f"  SKIP: No data for {code}")
            continue

        print(f"  Got {len(df)} days, from {df.index[0]} to {df.index[-1]}")

        # --- Regime Trail Sweep ---
        print(f"\n--- Regime Trail Sweep (Conviction 2.0) ---")
        rt_df = sweep_regime_trail(df, code)
        results["regime_trail_sweep"][code] = rt_df.to_dict(orient="records")

        # Print results table
        print(f"\n  {'regime_trail':>12} {'base_trail':>10} {'return':>10} {'MDD':>10} {'trades':>7} {'sharpe':>8}")
        print(f"  {'-'*12} {'-'*10} {'-'*10} {'-'*10} {'-'*7} {'-'*8}")
        for _, row in rt_df.sort_values(["trail_level3_pct", "trail_regime_wide_pct"]).iterrows():
            rt_label = f"{row['trail_regime_wide_pct']:.0%}" if row['trail_regime_wide_pct'] > 0 else "OFF"
            print(f"  {rt_label:>12} {row['trail_level3_pct']:>10.0%} "
                  f"{row['total_return']:>10.1%} {row['max_drawdown']:>10.1%} "
                  f"{row['total_trades']:>7.0f} {row.get('sharpe_ratio', 0):>8.2f}")

        # Robustness analysis for regime trail
        # Group by regime_trail_pct (with fixed base_trail=0.15)
        base15 = rt_df[rt_df["trail_level3_pct"] == 0.15]
        if not base15.empty:
            rob = analyze_robustness(base15, "trail_regime_wide_pct", "total_return")
            results["robustness"][code] = {
                "trail_regime_wide_pct": rob,
            }
            print(f"\n  Robustness (base=15%): optimal regime_trail={rob.get('optimal_value')}, "
                  f"cliff={rob.get('cliff_score')}, band={rob.get('robustness_band')}")

    # --- Summary ---
    print(f"\n{'=' * 60}")
    print("REGIME TRAIL VALIDATION SUMMARY")
    print("=" * 60)

    for code in stocks:
        if code not in results["robustness"]:
            continue
        rob = results["robustness"][code].get("trail_regime_wide_pct", {})
        print(f"\n{code}:")
        print(f"  trail_regime_wide_pct: optimal={rob.get('optimal_value', 'N/A')}, "
              f"cliff={rob.get('cliff_score', 'N/A')}")
        if rob.get("robustness_band"):
            print(f"  robustness band: {rob['robustness_band']}")

    return results


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, pd.Timestamp):
            return str(obj)
        return super().default(obj)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Bold Strategy Parameter Sweep")
    parser.add_argument("--stocks", nargs="+", default=["6748", "6139", "6442"])
    parser.add_argument("--period", type=int, default=2000)
    parser.add_argument("--output", type=str, default="data/bold_sweep_results.json")
    parser.add_argument("--mode", choices=["full", "regime"], default="regime",
                        help="full = original sweep, regime = Conviction 2.0 regime trail sweep")
    args = parser.parse_args()

    if args.mode == "regime":
        results = run_regime_sweep(stocks=args.stocks, period_days=args.period)
        output_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            args.output.replace(".json", "_regime.json"),
        )
    else:
        results = run_full_sweep(stocks=args.stocks, period_days=args.period)
        output_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            args.output,
        )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
    print(f"\nResults saved to {output_path}")

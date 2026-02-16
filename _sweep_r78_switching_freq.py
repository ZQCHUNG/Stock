"""R78: Mode Switching Frequency Analysis

Gemini CTO request: Find stocks that oscillate between Scalper/Trender modes.
High switching frequency near 1.8% threshold indicates instability.
Also tests hysteresis buffer (1.7%-1.9%) as proposed by Gemini.
"""
import sys, os, warnings, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from data.fetcher import get_stock_data
from config import SCAN_STOCKS

PERIOD_DAYS = 1095  # 3 years
THRESHOLD = 0.018


def compute_atr_pct_series(df: pd.DataFrame) -> pd.Series:
    """Compute rolling ATR% series (same as engine)."""
    if len(df) < 30:
        return pd.Series(dtype=float)
    h = df["high"] if "high" in df.columns else df["close"]
    lo = df["low"] if "low" in df.columns else df["close"]
    c = df["close"]
    tr = pd.concat([
        h - lo,
        (h - c.shift(1)).abs(),
        (lo - c.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr_14 = tr.rolling(14, min_periods=7).mean()
    atr_pct = atr_14 / c
    return atr_pct.rolling(60, min_periods=20).median()


def count_mode_switches(atr_pct_series: pd.Series, threshold: float, hysteresis: float = 0) -> dict:
    """Count how many times a stock switches between Scalper and Trender modes.

    With hysteresis=0: simple threshold crossing
    With hysteresis=0.001 (0.1%): upper=threshold+0.001, lower=threshold-0.001
    """
    upper = threshold + hysteresis
    lower = threshold - hysteresis

    values = atr_pct_series.dropna()
    if len(values) < 10:
        return {"switches": 0, "days_as_trender": 0, "days_as_scalper": 0, "pct_trender": 0}

    # Track mode and switches
    current_mode = "scalper" if values.iloc[0] >= threshold else "trender"
    switches = 0
    days_trender = 0
    days_scalper = 0

    for val in values:
        if hysteresis > 0:
            # Hysteresis: need to cross upper/lower to switch
            if current_mode == "trender" and val >= upper:
                current_mode = "scalper"
                switches += 1
            elif current_mode == "scalper" and val < lower:
                current_mode = "trender"
                switches += 1
        else:
            # Simple threshold
            new_mode = "scalper" if val >= threshold else "trender"
            if new_mode != current_mode:
                switches += 1
                current_mode = new_mode

        if current_mode == "trender":
            days_trender += 1
        else:
            days_scalper += 1

    total = days_trender + days_scalper
    return {
        "switches": switches,
        "days_as_trender": days_trender,
        "days_as_scalper": days_scalper,
        "pct_trender": days_trender / total * 100 if total > 0 else 0,
    }


def main():
    total = len(SCAN_STOCKS)
    print(f"R78: Mode Switching Frequency Analysis")
    print(f"Stocks: {total}, Period: {PERIOD_DAYS} days (~3 years)")
    print(f"Threshold: {THRESHOLD*100:.1f}%")
    print(f"{'='*100}\n")

    # Fetch data
    print("Fetching data...")
    stock_data = {}
    for i, code in enumerate(SCAN_STOCKS, 1):
        try:
            df = get_stock_data(code, period_days=PERIOD_DAYS)
            if df is not None and len(df) >= 60:
                stock_data[code] = df
        except:
            pass
        if i % 20 == 0:
            print(f"  [{i}/{total}]...", flush=True)
            time.sleep(1)

    print(f"  Fetched {len(stock_data)}/{total} stocks\n")

    # Analyze switching frequency
    results = []
    for code, df in stock_data.items():
        atr_pct_series = compute_atr_pct_series(df)
        if atr_pct_series.empty:
            continue

        current_atr_pct = float(atr_pct_series.iloc[-1]) * 100

        # No hysteresis (current behavior)
        r0 = count_mode_switches(atr_pct_series, THRESHOLD, hysteresis=0)
        # With 0.1% hysteresis (Gemini suggestion: 1.7%-1.9%)
        r1 = count_mode_switches(atr_pct_series, THRESHOLD, hysteresis=0.001)

        # Distance from threshold
        distance = abs(current_atr_pct - THRESHOLD * 100)

        results.append({
            "code": code,
            "atr_pct": round(current_atr_pct, 2),
            "mode": "Scalper" if current_atr_pct >= THRESHOLD * 100 else "Trender",
            "switches_raw": r0["switches"],
            "switches_hysteresis": r1["switches"],
            "pct_trender": round(r0["pct_trender"], 1),
            "distance_from_threshold": round(distance, 2),
        })

    # Sort by switching frequency (most unstable first)
    results.sort(key=lambda r: r["switches_raw"], reverse=True)

    # Report
    print(f"{'='*100}")
    print(f"SWITCHING FREQUENCY ANALYSIS")
    print(f"{'='*100}")
    print(f"{'Code':<8s} {'ATR%':>6s} {'Mode':<10s} {'Switches':>10s} {'W/ Hyst':>10s} {'%Trender':>10s} {'Dist':>8s} {'Stability':>12s}")
    print("-" * 80)

    high_switch = 0
    for r in results:
        stability = "UNSTABLE" if r["switches_raw"] >= 5 else ("MARGINAL" if r["switches_raw"] >= 2 else "STABLE")
        if r["switches_raw"] >= 5:
            high_switch += 1
        print(f"{r['code']:<8s} {r['atr_pct']:>5.2f}% {r['mode']:<10s} {r['switches_raw']:>10d} "
              f"{r['switches_hysteresis']:>10d} {r['pct_trender']:>9.1f}% {r['distance_from_threshold']:>7.2f}% {stability:>12s}")

    # Summary statistics
    print(f"\n{'='*100}")
    print("SUMMARY")
    print(f"{'='*100}")

    switch_counts = [r["switches_raw"] for r in results]
    switch_hyst = [r["switches_hysteresis"] for r in results]

    print(f"Total stocks: {len(results)}")
    print(f"\nRaw switching (no hysteresis):")
    print(f"  0 switches: {sum(1 for s in switch_counts if s == 0)} stocks (perfectly stable)")
    print(f"  1 switch:   {sum(1 for s in switch_counts if s == 1)} stocks")
    print(f"  2-4:        {sum(1 for s in switch_counts if 2 <= s <= 4)} stocks (marginal)")
    print(f"  5+:         {sum(1 for s in switch_counts if s >= 5)} stocks (UNSTABLE)")
    print(f"  Avg: {np.mean(switch_counts):.1f}, Median: {np.median(switch_counts):.0f}, Max: {max(switch_counts)}")

    print(f"\nWith hysteresis (±0.1%, i.e. 1.7%-1.9%):")
    print(f"  0 switches: {sum(1 for s in switch_hyst if s == 0)} stocks")
    print(f"  1 switch:   {sum(1 for s in switch_hyst if s == 1)} stocks")
    print(f"  2-4:        {sum(1 for s in switch_hyst if 2 <= s <= 4)} stocks")
    print(f"  5+:         {sum(1 for s in switch_hyst if s >= 5)} stocks")
    print(f"  Avg: {np.mean(switch_hyst):.1f}, Median: {np.median(switch_hyst):.0f}, Max: {max(switch_hyst)}")

    reduction = (1 - np.mean(switch_hyst) / max(np.mean(switch_counts), 0.001)) * 100
    print(f"\n  Hysteresis reduces avg switches by {reduction:.0f}%")

    # Distance distribution
    print(f"\n--- Distance from 1.8% Threshold ---")
    dists = [r["distance_from_threshold"] for r in results]
    print(f"  Within 0.2%: {sum(1 for d in dists if d < 0.2)} stocks (danger zone)")
    print(f"  0.2-0.5%:    {sum(1 for d in dists if 0.2 <= d < 0.5)} stocks")
    print(f"  0.5-1.0%:    {sum(1 for d in dists if 0.5 <= d < 1.0)} stocks")
    print(f"  >1.0%:       {sum(1 for d in dists if d >= 1.0)} stocks (safe)")

    # Most unstable stocks (for Gemini)
    unstable = [r for r in results if r["switches_raw"] >= 3]
    if unstable:
        print(f"\n--- Most Unstable Stocks (3+ switches) ---")
        for r in unstable:
            hyst_fix = "FIXED" if r["switches_hysteresis"] < r["switches_raw"] * 0.5 else "PARTIAL" if r["switches_hysteresis"] < r["switches_raw"] else "NO HELP"
            print(f"  {r['code']}: ATR%={r['atr_pct']:.2f}%, {r['switches_raw']} switches → {r['switches_hysteresis']} w/hysteresis [{hyst_fix}]")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\nRuntime: {time.time()-t0:.0f}s")

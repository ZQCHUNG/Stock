"""R82.2: Concentration-Cap Sensitivity Test (Protocol v2 — Empirical Validation)

Replaces the binary sector penalty (0.6x if any overlap) with a proportional
Concentration-Cap:

    R_sector = sum(same-sector market_value) / total_portfolio_value
    if R_sector < T_cap:  C = 1.0 (under cap)
    else:                 C = T_cap / R_sector (proportional reduction)

Sweep T_cap ∈ {0.20, 0.30, 0.40, 0.50, 0.60, 1.00(=disabled)}
Compare with the old binary k=0.6 as baseline.

All coefficients are [PLACEHOLDER_NEEDS_DATA] — this test provides the data.
"""

import sys
import os
import time
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from config import SCAN_STOCKS
from data.fetcher import get_stock_data
from data.sector_mapping import get_stock_sector
from backtest.engine import BacktestEngine


PERIOD_DAYS = 1095
INITIAL_CAPITAL = 1_000_000
RISK_FREE_ANNUAL = 0.015

# T_cap values to sweep + disabled (1.0) + old binary 0.6 for comparison
T_CAP_VALUES = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60]


def fetch_and_backtest_all():
    """Run V4 backtests and extract trade lists with entry prices."""
    results = {}
    codes = list(SCAN_STOCKS.keys())
    n = len(codes)

    print(f"Phase 1: Fetching data & running V4 backtests for {n} stocks...")
    print(f"  Period: {PERIOD_DAYS} days, Capital: ${INITIAL_CAPITAL:,}")
    print()

    t0 = time.time()
    total_trades = 0
    for i, code in enumerate(codes):
        name = SCAN_STOCKS[code]
        try:
            df = get_stock_data(code, period_days=PERIOD_DAYS)
            if df is None or len(df) < 60:
                continue

            engine = BacktestEngine(initial_capital=INITIAL_CAPITAL)
            bt = engine.run_v4(df)

            if bt.trades:
                sector = get_stock_sector(code, level=1)
                trades = []
                for t in bt.trades:
                    if t.date_close is not None and t.return_pct != 0:
                        # Estimate entry price from PnL and return
                        # pnl = shares * entry_price * return_pct
                        # We use capital * standard_position_pct as position size proxy
                        position_value = INITIAL_CAPITAL * 0.30  # ~30% position typical
                        trades.append({
                            "code": code,
                            "sector": sector,
                            "entry": pd.Timestamp(t.date_open),
                            "exit": pd.Timestamp(t.date_close),
                            "return_pct": t.return_pct,
                            "pnl": t.pnl,
                            "position_value": position_value,
                            "holding_days": (t.date_close - t.date_open).days,
                        })
                if trades:
                    results[code] = {
                        "name": name,
                        "sector": sector,
                        "trades": trades,
                        "total_return": bt.total_return,
                    }
                    total_trades += len(trades)

            if (i + 1) % 20 == 0 or i == 0 or i == n - 1:
                elapsed = time.time() - t0
                n_trades = len(bt.trades) if bt.trades else 0
                print(f"  [{i+1:3d}/{n}] {code} {name}... "
                      f"ret={bt.total_return:+.1%} trades={n_trades} ({elapsed:.0f}s)")
        except Exception as e:
            print(f"  [{i+1:3d}/{n}] {code} {name}... ERROR: {e}")

    elapsed = time.time() - t0
    print(f"\n  Done: {len(results)} stocks with trades, "
          f"{total_trades} total trades ({elapsed:.0f}s)")
    return results


def concentration_cap_multiplier(sector, active_positions, total_active_value, t_cap):
    """Concentration-Cap dynamic coefficient.

    Args:
        sector: L1 sector of the new trade
        active_positions: list of (sector, position_value) for currently held trades
        total_active_value: sum of all active position values
        t_cap: sector concentration cap threshold [PLACEHOLDER_NEEDS_DATA]

    Returns:
        C: multiplier (0.0 to 1.0)
    """
    if not active_positions or total_active_value <= 0 or t_cap >= 1.0:
        return 1.0

    # Calculate current sector exposure ratio
    sector_value = sum(pv for s, pv in active_positions if s == sector)
    r_sector = sector_value / total_active_value

    if r_sector < t_cap:
        return 1.0  # Under cap — full allocation
    else:
        return t_cap / r_sector  # Over cap — proportional reduction


def binary_penalty_multiplier(sector, active_positions, k=0.6):
    """Old R82 binary penalty for comparison."""
    if not active_positions:
        return 1.0
    active_sectors = set(s for s, _ in active_positions)
    if sector in active_sectors:
        return k
    return 1.0


def simulate_portfolio(results, t_cap=None, binary_k=None):
    """Simulate portfolio with sector-aware position sizing.

    If t_cap is set: use Concentration-Cap formula.
    If binary_k is set: use old binary penalty.
    If neither (or t_cap >= 1.0): no penalty.
    """
    # Flatten all trades and sort by entry date
    all_trades = []
    for code, info in results.items():
        for t in info["trades"]:
            all_trades.append(t)
    all_trades.sort(key=lambda t: t["entry"])

    if not all_trades:
        return None

    # Track active positions and compute weights at entry time
    trade_weights = []  # (trade_dict, weight)

    for trade in all_trades:
        entry_date = trade["entry"]
        sector = trade["sector"]

        # Find active positions at entry time
        active_positions = []
        total_active_value = 0
        for prev_trade, prev_weight in trade_weights:
            if prev_trade["entry"] <= entry_date and prev_trade["exit"] > entry_date:
                pv = prev_trade["position_value"] * prev_weight
                active_positions.append((prev_trade["sector"], pv))
                total_active_value += pv

        # Compute multiplier
        if binary_k is not None:
            weight = binary_penalty_multiplier(sector, active_positions, binary_k)
        elif t_cap is not None and t_cap < 1.0:
            weight = concentration_cap_multiplier(
                sector, active_positions, total_active_value, t_cap
            )
        else:
            weight = 1.0

        trade_weights.append((trade, weight))

    # Statistics
    weights = [w for _, w in trade_weights]
    n_penalized = sum(1 for w in weights if w < 1.0)
    n_full = sum(1 for w in weights if w >= 1.0)
    n_trades = len(trade_weights)
    avg_weight = np.mean(weights)

    # Weighted returns
    weighted_returns = [w * t["return_pct"] for t, w in trade_weights]

    # Win metrics
    wins = sum(1 for r in weighted_returns if r > 0)
    win_rate = wins / n_trades if n_trades > 0 else 0
    gains = sum(r for r in weighted_returns if r > 0)
    losses = abs(sum(r for r in weighted_returns if r < 0))
    pf = gains / losses if losses > 0 else float("inf")

    # Build equity curve from daily PnL
    all_dates = set()
    for t, _ in trade_weights:
        dates = pd.date_range(t["entry"], t["exit"], freq="B")
        all_dates.update(dates)
    all_dates = sorted(all_dates)

    if len(all_dates) < 10:
        return None

    daily_pnl = pd.Series(0.0, index=all_dates)
    concurrent = pd.Series(0, index=all_dates)

    for trade, weight in trade_weights:
        trade_dates = pd.date_range(trade["entry"], trade["exit"], freq="B")
        if len(trade_dates) <= 1:
            continue
        daily_trade_ret = trade["return_pct"] / len(trade_dates)
        weighted_daily = daily_trade_ret * weight
        for d in trade_dates:
            if d in daily_pnl.index:
                daily_pnl.loc[d] += weighted_daily
                concurrent.loc[d] += 1

    max_concurrent = int(concurrent.max()) if len(concurrent) > 0 else 1
    avg_concurrent = concurrent.mean() if len(concurrent) > 0 else 1
    norm_factor = max(avg_concurrent, 1)
    portfolio_daily = daily_pnl / norm_factor

    # Equity curve and metrics
    equity = (1 + portfolio_daily).cumprod()
    total_return = float(equity.iloc[-1]) - 1.0
    trading_days = len(equity)
    annual_return = (1 + total_return) ** (252 / trading_days) - 1 if trading_days > 1 else 0

    peak = equity.expanding().max()
    dd = (equity - peak) / peak
    max_dd = float(dd.min())

    rf_daily = RISK_FREE_ANNUAL / 252
    excess = portfolio_daily - rf_daily
    sharpe = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0 else 0
    calmar = annual_return / abs(max_dd) if max_dd < -0.001 else 0

    # Sector concentration at peak (what % was the largest sector?)
    # This measures whether the cap is actually reducing concentration
    sector_weights_over_time = {}
    for trade, weight in trade_weights:
        s = trade["sector"]
        if s not in sector_weights_over_time:
            sector_weights_over_time[s] = 0
        sector_weights_over_time[s] += weight

    total_weighted = sum(sector_weights_over_time.values())
    max_sector_pct = max(sector_weights_over_time.values()) / total_weighted if total_weighted > 0 else 0

    label = f"T_cap={t_cap:.2f}" if t_cap is not None and binary_k is None else (
        f"Binary k={binary_k}" if binary_k is not None else "Disabled"
    )

    return {
        "label": label,
        "t_cap": t_cap if t_cap is not None else (0.6 if binary_k else 1.0),
        "mode": "concentration_cap" if (t_cap is not None and binary_k is None) else (
            "binary" if binary_k is not None else "disabled"
        ),
        "total_return": total_return,
        "annual_return": annual_return,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "calmar": calmar,
        "win_rate": win_rate,
        "profit_factor": pf,
        "n_trades": n_trades,
        "n_penalized": n_penalized,
        "n_full": n_full,
        "penalty_rate": n_penalized / n_trades if n_trades > 0 else 0,
        "avg_weight": avg_weight,
        "max_sector_pct": max_sector_pct,
        "avg_concurrent": avg_concurrent,
        "max_concurrent": max_concurrent,
    }


def print_header():
    print(f"  {'Label':>16s} | {'Return':>8s} | {'Annual':>8s} | {'MDD':>8s} | "
          f"{'Sharpe':>7s} | {'Calmar':>7s} | {'WinR':>5s} | "
          f"{'PF':>5s} | {'Pen%':>5s} | {'AvgW':>5s} | {'MaxSec':>6s}")
    print(f"  {'-'*16}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*7}-+-{'-'*7}-+-"
          f"{'-'*5}-+-{'-'*5}-+-{'-'*5}-+-{'-'*5}-+-{'-'*6}")


def print_row(m):
    print(f"  {m['label']:>16s} | {m['total_return']:+7.1%} | "
          f"{m['annual_return']:+7.1%} | {m['max_dd']:+7.1%} | "
          f"{m['sharpe']:+6.2f} | {m['calmar']:6.2f} | "
          f"{m['win_rate']:4.0%} | {m['profit_factor']:5.2f} | "
          f"{m['penalty_rate']:4.0%} | {m['avg_weight']:5.2f} | "
          f"{m['max_sector_pct']:5.0%}")


def main():
    print("=" * 110)
    print("  R82.2: Concentration-Cap Sensitivity Test (Protocol v2 Empirical Validation)")
    print("  Compare: Disabled vs Binary(0.6x) vs Concentration-Cap(T_cap sweep)")
    print("=" * 110)
    print()

    # Phase 1: Backtests
    results = fetch_and_backtest_all()
    if len(results) < 10:
        print("ERROR: Too few stocks with trades. Aborting.")
        return

    # Sector summary
    sector_counts = {}
    for info in results.values():
        s = info["sector"]
        sector_counts[s] = sector_counts.get(s, 0) + 1

    print("\nSector Distribution (stocks with trades):")
    for sector, count in sorted(sector_counts.items(), key=lambda x: -x[1]):
        print(f"  {sector:12s}: {count:3d} stocks")

    # Phase 2: Full sweep
    print("\n" + "=" * 110)
    print("  Phase 2: Full Portfolio Comparison")
    print("  1) Disabled (no penalty)")
    print("  2) Old Binary (sector overlap → 0.6x)")
    print("  3) Concentration-Cap (proportional, sweep T_cap)")
    print("=" * 110)
    print()
    print_header()

    all_results = []

    # Baseline: disabled
    m = simulate_portfolio(results)
    if m:
        all_results.append(m)
        print_row(m)

    # Old binary 0.6x
    m = simulate_portfolio(results, binary_k=0.6)
    if m:
        all_results.append(m)
        print_row(m)

    # Separator
    print(f"  {'':>16s}-+-{'':>8s}-+-{'':>8s}-+-{'':>8s}-+-{'':>7s}-+-{'':>7s}-+-"
          f"{'':>5s}-+-{'':>5s}-+-{'':>5s}-+-{'':>5s}-+-{'':>6s}")

    # Concentration-Cap sweep
    for t in T_CAP_VALUES:
        m = simulate_portfolio(results, t_cap=t)
        if m:
            all_results.append(m)
            print_row(m)

    # Phase 3: Analysis
    print("\n" + "=" * 110)
    print("  Phase 3: Comparative Analysis")
    print("=" * 110)

    disabled = next((m for m in all_results if m["mode"] == "disabled"), None)
    binary = next((m for m in all_results if m["mode"] == "binary"), None)
    cap_results = [m for m in all_results if m["mode"] == "concentration_cap"]

    if disabled and binary and cap_results:
        best_cap = max(cap_results, key=lambda x: x["calmar"])

        print(f"\n  Disabled (baseline):")
        print(f"    Calmar={disabled['calmar']:.2f}, Sharpe={disabled['sharpe']:.2f}, "
              f"MDD={disabled['max_dd']:+.1%}")

        print(f"\n  Binary 0.6x (old R82):")
        print(f"    Calmar={binary['calmar']:.2f}, Sharpe={binary['sharpe']:.2f}, "
              f"MDD={binary['max_dd']:+.1%}")
        print(f"    vs Disabled: Calmar {binary['calmar'] - disabled['calmar']:+.2f}, "
              f"Sharpe {binary['sharpe'] - disabled['sharpe']:+.2f}")
        print(f"    Penalty rate: {binary['penalty_rate']:.0%} of trades penalized")

        print(f"\n  Best Concentration-Cap: {best_cap['label']}")
        print(f"    Calmar={best_cap['calmar']:.2f}, Sharpe={best_cap['sharpe']:.2f}, "
              f"MDD={best_cap['max_dd']:+.1%}")
        print(f"    vs Disabled: Calmar {best_cap['calmar'] - disabled['calmar']:+.2f}, "
              f"Sharpe {best_cap['sharpe'] - disabled['sharpe']:+.2f}")
        print(f"    vs Binary 0.6x: Calmar {best_cap['calmar'] - binary['calmar']:+.2f}, "
              f"Sharpe {best_cap['sharpe'] - binary['sharpe']:+.2f}")
        print(f"    Penalty rate: {best_cap['penalty_rate']:.0%}, "
              f"Avg weight: {best_cap['avg_weight']:.2f}")

    # Phase 4: Sector-focused
    print("\n" + "=" * 110)
    print("  Phase 4: Sector-Focused Tests (Top 3 Sectors)")
    print("=" * 110)

    for target_sector in ["半導體", "AI伺服器", "金融"]:
        sector_results = {
            code: info for code, info in results.items()
            if info["sector"] == target_sector
        }
        if len(sector_results) < 3:
            continue

        print(f"\n  [{target_sector}] ({len(sector_results)} stocks)")
        print_header()

        # Disabled
        m = simulate_portfolio(sector_results)
        if m:
            print_row(m)

        # Binary
        m = simulate_portfolio(sector_results, binary_k=0.6)
        if m:
            print_row(m)

        # Concentration-Cap sweep
        sector_caps = []
        for t in T_CAP_VALUES:
            m = simulate_portfolio(sector_results, t_cap=t)
            if m:
                sector_caps.append(m)
                print_row(m)

        if sector_caps:
            best = max(sector_caps, key=lambda x: x["calmar"])
            print(f"  >>> [{target_sector}] Best T_cap by Calmar: {best['label']} "
                  f"(Calmar={best['calmar']:.2f})")

    # Phase 5: Conclusion
    print("\n" + "=" * 110)
    print("  CONCLUSION")
    print("=" * 110)
    print()

    if disabled and binary and cap_results:
        best_cap = max(cap_results, key=lambda x: x["calmar"])

        # Check if Concentration-Cap improves over both disabled and binary
        cap_vs_disabled = best_cap["calmar"] - disabled["calmar"]
        cap_vs_binary = best_cap["calmar"] - binary["calmar"]
        binary_vs_disabled = binary["calmar"] - disabled["calmar"]

        print(f"  Binary 0.6x vs Disabled: Calmar {binary_vs_disabled:+.2f}")
        print(f"  Best Cap ({best_cap['label']}) vs Disabled: Calmar {cap_vs_disabled:+.2f}")
        print(f"  Best Cap ({best_cap['label']}) vs Binary: Calmar {cap_vs_binary:+.2f}")
        print()

        if cap_vs_disabled > 0.1 and cap_vs_binary > 0.1:
            print(f"  VERDICT: Concentration-Cap at {best_cap['label']} IMPROVES over both baselines.")
            print(f"  Recommend: Replace binary 0.6x with Concentration-Cap, "
                  f"T_cap={best_cap['t_cap']} [VERIFIED]")
        elif cap_vs_disabled > -0.05 and cap_vs_binary > 0.05:
            print(f"  VERDICT: Concentration-Cap at {best_cap['label']} is MARGINALLY better than binary,")
            print(f"  but similar to disabled. Consider using T_cap={best_cap['t_cap']} or disabling entirely.")
        elif binary_vs_disabled < -0.1:
            print(f"  VERDICT: Binary 0.6x is HARMFUL (confirmed again).")
            if cap_vs_disabled > -0.05:
                print(f"  Concentration-Cap at {best_cap['label']} is neutral — acceptable as risk control.")
            else:
                print(f"  All sector penalties appear to reduce performance. Consider removing entirely.")
        else:
            print(f"  VERDICT: No significant difference between methods.")
            print(f"  Concentration-Cap offers better theoretical properties but similar empirical results.")

    print()


if __name__ == "__main__":
    main()

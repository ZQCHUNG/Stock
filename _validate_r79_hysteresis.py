"""R79: Validate hysteresis implementation in engine.py

Tests:
1. Hysteresis ON vs OFF for the 12 UNSTABLE stocks from R78
2. Verifies trail_mode_info metadata is populated
3. Compares Sharpe impact
"""
import sys, os, warnings, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

from backtest.engine import run_backtest_v4
from data.fetcher import get_stock_data

# 12 most unstable stocks from R78 switching frequency analysis (5+ switches)
UNSTABLE_STOCKS = {
    "2609": "陽明",
    "2618": "長榮航",
    "2603": "長榮",
    "2615": "萬海",
    "1402": "遠東新",
    "2207": "和泰車",
    "2027": "大成鋼",
    "2377": "微星",
    "2353": "宏碁",
    "2409": "友達",
    "2344": "華邦電",
    "6770": "力積電",
}

# Also test a few stable stocks as control
STABLE_CONTROL = {
    "2330": "台積電",
    "2412": "中華電",
    "2891": "中信金",
}

PERIOD_DAYS = 1095
CAPITAL = 1_000_000

# Config: AUTO without hysteresis
CFG_NO_HYST = {
    "auto_trail_classifier": True,
    "auto_trail_threshold": 0.018,
    "auto_trail_hysteresis": 0,  # OFF
    "auto_trail_k": 1.0,
    "atr_trail_enabled": False,
    "dynamic_trail_enabled": False,
    "trailing_stop_pct": 0.02,
}

# Config: AUTO with hysteresis (new default)
CFG_HYST = {
    "auto_trail_classifier": True,
    "auto_trail_threshold": 0.018,
    "auto_trail_hysteresis": 0.001,  # ±0.1%
    "auto_trail_k": 1.0,
    "atr_trail_enabled": False,
    "dynamic_trail_enabled": False,
    "trailing_stop_pct": 0.02,
}


def run(df, cfg):
    try:
        bt = run_backtest_v4(df, initial_capital=CAPITAL, params=cfg)
        return bt
    except Exception as e:
        print(f"    ERROR: {e}")
        return None


def main():
    all_stocks = {**UNSTABLE_STOCKS, **STABLE_CONTROL}
    total = len(all_stocks)

    print(f"R79: Hysteresis Validation")
    print(f"Stocks: {len(UNSTABLE_STOCKS)} UNSTABLE + {len(STABLE_CONTROL)} control = {total}")
    print(f"{'='*110}\n")

    # Fetch data
    stock_data = {}
    for i, (code, name) in enumerate(all_stocks.items(), 1):
        print(f"  Fetching {code} {name}...", end=" ", flush=True)
        try:
            df = get_stock_data(code, period_days=PERIOD_DAYS)
            if df is not None and len(df) >= 60:
                stock_data[code] = df
                print(f"OK ({len(df)} rows)")
            else:
                print("SKIP (too short)")
        except Exception as e:
            print(f"FAIL: {e}")
        if i % 5 == 0:
            time.sleep(1)

    print(f"\n  Fetched {len(stock_data)}/{total} stocks\n")

    # Run backtests
    print(f"{'Code':<8s} {'Name':<8s} {'Group':<10s} {'No Hyst':>9s} {'W/ Hyst':>9s} {'Delta':>8s} "
          f"{'Mode':<10s} {'ATR%':>6s} {'Switches':>10s} {'Stability':<12s}")
    print("-" * 110)

    results = []
    for code, df in stock_data.items():
        name = all_stocks[code]
        group = "UNSTABLE" if code in UNSTABLE_STOCKS else "CONTROL"

        bt_no = run(df, CFG_NO_HYST)
        bt_yes = run(df, CFG_HYST)

        if bt_no and bt_yes:
            s_no = bt_no.sharpe_ratio
            s_yes = bt_yes.sharpe_ratio
            delta = s_yes - s_no
            info = bt_yes.trail_mode_info

            mode = info.get("mode", "?")
            atr_pct = info.get("atr_pct_median", 0)
            switches = info.get("switches", 0)
            stability = info.get("stability", "?")

            print(f"{code:<8s} {name:<8s} {group:<10s} {s_no:>+8.3f} {s_yes:>+8.3f} {delta:>+7.3f} "
                  f"{mode:<10s} {atr_pct:>5.2f}% {switches:>10d} {stability:<12s}")

            results.append({
                "code": code, "group": group,
                "sharpe_no_hyst": s_no, "sharpe_hyst": s_yes, "delta": delta,
                "mode": mode, "atr_pct": atr_pct, "switches": switches, "stability": stability,
            })
        else:
            print(f"{code:<8s} {name:<8s} {group:<10s} ERROR")

    # Summary
    print(f"\n{'='*110}")
    print("SUMMARY")
    print(f"{'='*110}")

    unstable_results = [r for r in results if r["group"] == "UNSTABLE"]
    control_results = [r for r in results if r["group"] == "CONTROL"]

    if unstable_results:
        print(f"\nUNSTABLE stocks ({len(unstable_results)}):")
        deltas = [r["delta"] for r in unstable_results]
        improved = sum(1 for d in deltas if d > 0.005)
        degraded = sum(1 for d in deltas if d < -0.005)
        neutral = len(deltas) - improved - degraded
        print(f"  Improved: {improved}, Neutral: {neutral}, Degraded: {degraded}")
        print(f"  Avg delta: {sum(deltas)/len(deltas):+.4f}")
        switches = [r["switches"] for r in unstable_results]
        print(f"  Avg switches (w/ hysteresis): {sum(switches)/len(switches):.1f}")

    if control_results:
        print(f"\nCONTROL stocks ({len(control_results)}):")
        deltas = [r["delta"] for r in control_results]
        print(f"  Avg delta: {sum(deltas)/len(deltas):+.4f}")
        print(f"  (Should be ~0 — stable stocks unaffected by hysteresis)")

    # Verify trail_mode_info is populated
    print(f"\n--- Trail Mode Info Verification ---")
    for r in results[:3]:
        print(f"  {r['code']}: mode={r['mode']}, ATR%={r['atr_pct']}%, switches={r['switches']}, stability={r['stability']}")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\nRuntime: {time.time()-t0:.0f}s")

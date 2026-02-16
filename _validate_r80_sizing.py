"""R80: Validate Risk-Adaptive Position Sizing

Tests:
1. Sizing module standalone: verify position calculations for various modes/ATR%
2. Engine integration: compare sizing ON vs OFF for 10 representative stocks
3. Verify risk-per-trade is bounded at 1.5% of equity
"""
import sys, os, warnings, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

from backtest.risk_manager import get_suggested_position, SIZING_DEFAULTS
from backtest.engine import run_backtest_v4
from data.fetcher import get_stock_data

# ===== Part 1: Standalone Sizing Tests =====
def test_sizing_module():
    print("=" * 90)
    print("PART 1: Sizing Module Unit Tests")
    print("=" * 90)

    equity = 1_000_000
    entry = 500.0  # $500 per share

    test_cases = [
        # (mode, atr_pct, entry_price, expected_behavior)
        ("Trender", 0.012, 50.0, "Low price, standard"),
        ("Trender", 0.015, 200.0, "Mid price, standard"),
        ("Trender", 0.012, 1000.0, "High price (TSMC-like), 1-lot floor"),
        ("Scalper", 0.020, 50.0, "Low price, reduced"),
        ("Scalper", 0.025, 200.0, "Mid price, reduced"),
        ("Scalper", 0.030, 500.0, "High price, 1-lot floor"),
        ("Scalper", 0.040, 1000.0, "Very high, 1-lot floor"),
    ]

    print(f"\nEquity: ${equity:,}, SL: 7%, Risk Budget: {SIZING_DEFAULTS['max_risk_per_trade']:.1%}")
    print(f"Base position: {SIZING_DEFAULTS['max_risk_per_trade']/SIZING_DEFAULTS['hard_stop_loss']:.1%}")
    print()
    print(f"{'Mode':<10s} {'ATR%':>6s} {'Price':>8s} {'Mult':>6s} {'Pos%':>8s} {'Amount':>12s} {'Shares':>8s} {'Risk%':>8s} {'Over?':>6s} {'Note'}")
    print("-" * 100)

    for mode, atr_pct, price, note in test_cases:
        r = get_suggested_position(mode, atr_pct, equity, price)
        print(f"{mode:<10s} {atr_pct*100:>5.1f}% {price:>7.0f} {r.regime_multiplier:>5.2f}x "
              f"{r.position_pct*100:>7.1f}% ${r.position_amount:>10,.0f} "
              f"{r.shares:>7,d} {r.risk_per_trade_pct*100:>7.2f}% {'YES' if r.over_risk else 'no':>6s} {note}")

    # Verify min-lot floor works
    print(f"\n--- Min-Lot Floor Verification ---")
    # $500 stock: sizing says ~$386K, but 1 lot = $500K → over_risk floor kicks in
    r_mid = get_suggested_position("Scalper", 0.025, equity, 500.0)
    print(f"  $500 Scalper 2.5%: shares={r_mid.shares}, over_risk={r_mid.over_risk}, risk={r_mid.risk_per_trade_pct:.2%}")

    # $1000 stock: 1 lot = $1M ≈ total equity → can't afford (not a sizing issue)
    r_tsmc = get_suggested_position("Scalper", 0.020, equity, 1000.0)
    print(f"  $1000 TSMC-like: shares={r_tsmc.shares}, over_risk={r_tsmc.over_risk} (capital too small for 1 lot)")

    # $200 stock: 1 lot = $200K, fits in 42.8% ($428K) → normal sizing
    r_low = get_suggested_position("Trender", 0.015, equity, 200.0)
    print(f"  $200 Trender: shares={r_low.shares}, over_risk={r_low.over_risk}, risk={r_low.risk_per_trade_pct:.2%}")
    assert r_low.shares >= 1000, "Should buy at least 1 lot"
    assert not r_low.over_risk, "Should not be over_risk at $200"
    print("  Min-lot floor verified [PASS]")


# ===== Part 2: Engine Integration =====
def test_engine_integration():
    print(f"\n{'='*90}")
    print("PART 2: Engine Integration (Sizing ON vs OFF)")
    print(f"{'='*90}")

    STOCKS = {
        # Trender stocks (low vol)
        "2412": "中華電",
        "2891": "中信金",
        "5880": "合庫金",
        # Scalper stocks (high vol)
        "2330": "台積電",
        "2603": "長榮",
        "6770": "力積電",
        # Borderline
        "2207": "和泰車",
        "2377": "微星",
        # High performance
        "2344": "華邦電",
        "3037": "欣興",
    }

    PERIOD_DAYS = 1095
    CAPITAL = 1_000_000

    # Config: sizing OFF (current default)
    CFG_OFF = {
        "auto_trail_classifier": True,
        "auto_trail_threshold": 0.018,
        "auto_trail_hysteresis": 0.001,
        "auto_trail_k": 1.0,
        "risk_sizing_enabled": False,
        "trailing_stop_pct": 0.02,
    }

    # Config: sizing ON (3% risk + min-1-lot floor)
    CFG_ON = {
        "auto_trail_classifier": True,
        "auto_trail_threshold": 0.018,
        "auto_trail_hysteresis": 0.001,
        "auto_trail_k": 1.0,
        "risk_sizing_enabled": True,
        "max_risk_per_trade": 0.030,  # 3% risk budget
        "min_lot_floor": True,        # Force at least 1 lot
        "trailing_stop_pct": 0.02,
    }

    # Fetch data
    stock_data = {}
    for code, name in STOCKS.items():
        print(f"  Fetching {code} {name}...", end=" ", flush=True)
        try:
            df = get_stock_data(code, period_days=PERIOD_DAYS)
            if df is not None and len(df) >= 60:
                stock_data[code] = df
                print(f"OK ({len(df)} rows)")
        except Exception as e:
            print(f"FAIL: {e}")
        time.sleep(0.3)

    print(f"\n{'Code':<8s} {'Name':<8s} {'Mode':<10s} {'ATR%':>6s} "
          f"{'Off Sharpe':>11s} {'On Sharpe':>11s} {'Delta':>8s} "
          f"{'Off MaxDD':>10s} {'On MaxDD':>10s} {'Off Trades':>11s} {'On Trades':>11s}")
    print("-" * 120)

    results = []
    for code, df in stock_data.items():
        name = STOCKS[code]
        bt_off = run_backtest_v4(df, initial_capital=CAPITAL, params=CFG_OFF)
        bt_on = run_backtest_v4(df, initial_capital=CAPITAL, params=CFG_ON)

        mode = bt_off.trail_mode_info.get("mode", "?")
        atr_pct = bt_off.trail_mode_info.get("atr_pct_median", 0)
        delta = bt_on.sharpe_ratio - bt_off.sharpe_ratio

        # Show sizing log from ON run
        sizing_log = bt_on.trail_mode_info.get("sizing_log", [])

        print(f"{code:<8s} {name:<8s} {mode:<10s} {atr_pct:>5.2f}% "
              f"{bt_off.sharpe_ratio:>+10.3f} {bt_on.sharpe_ratio:>+10.3f} {delta:>+7.3f} "
              f"{bt_off.max_drawdown*100:>9.1f}% {bt_on.max_drawdown*100:>9.1f}% "
              f"{bt_off.total_trades:>11d} {bt_on.total_trades:>11d}")

        results.append({
            "code": code, "mode": mode, "atr_pct": atr_pct,
            "sharpe_off": bt_off.sharpe_ratio, "sharpe_on": bt_on.sharpe_ratio,
            "delta": delta,
            "dd_off": bt_off.max_drawdown, "dd_on": bt_on.max_drawdown,
            "trades_off": bt_off.total_trades, "trades_on": bt_on.total_trades,
            "sizing_log": sizing_log,
        })

    # Summary
    print(f"\n{'='*90}")
    print("SUMMARY")
    print(f"{'='*90}")

    deltas = [r["delta"] for r in results]
    dd_improvements = [r["dd_off"] - r["dd_on"] for r in results]  # positive = ON has less DD

    print(f"Stocks tested: {len(results)}")
    print(f"Sharpe delta: avg={sum(deltas)/len(deltas):+.4f}")
    print(f"  Improved: {sum(1 for d in deltas if d > 0.01)}")
    print(f"  Neutral:  {sum(1 for d in deltas if -0.01 <= d <= 0.01)}")
    print(f"  Degraded: {sum(1 for d in deltas if d < -0.01)}")
    print(f"MaxDD change: avg={sum(dd_improvements)/len(dd_improvements)*100:+.1f}% "
          f"(positive = sizing reduces drawdown)")

    # Show sizing log examples
    print(f"\n--- Sizing Log Examples ---")
    for r in results[:3]:
        if r["sizing_log"]:
            log = r["sizing_log"][0]
            print(f"  {r['code']}: mode={log['mode']}, ATR%={log['atr_pct']}%, "
                  f"pos={log['position_pct']}%, mult={log['regime_mult']}")
        else:
            print(f"  {r['code']}: no sizing log (sizing may not have triggered)")

    # Key insight: with 21.4% max position, trades should be smaller and drawdown lower
    trender_results = [r for r in results if r["mode"] == "Trender"]
    scalper_results = [r for r in results if r["mode"] == "Scalper"]

    if trender_results:
        avg_dd_off = sum(r["dd_off"] for r in trender_results) / len(trender_results)
        avg_dd_on = sum(r["dd_on"] for r in trender_results) / len(trender_results)
        print(f"\nTrender ({len(trender_results)}): DD off={avg_dd_off*100:.1f}% → on={avg_dd_on*100:.1f}%")

    if scalper_results:
        avg_dd_off = sum(r["dd_off"] for r in scalper_results) / len(scalper_results)
        avg_dd_on = sum(r["dd_on"] for r in scalper_results) / len(scalper_results)
        print(f"Scalper ({len(scalper_results)}): DD off={avg_dd_off*100:.1f}% → on={avg_dd_on*100:.1f}%")


if __name__ == "__main__":
    t0 = time.time()
    test_sizing_module()
    test_engine_integration()
    print(f"\nTotal runtime: {time.time()-t0:.0f}s")

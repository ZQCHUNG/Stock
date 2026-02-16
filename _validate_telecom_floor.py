"""R78: Quick validation — does 1.5% floor fix Telecom failure?

Tests 3 Telecom stocks (2412, 4904, 3045) + a few other low-vol stocks
with the updated atr_trail_floor = 0.015.
"""
import sys, os, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

from backtest.engine import run_backtest_v4
from data.fetcher import get_stock_data

STOCKS = {
    # Telecom failures from R77
    "2412": "中華電",
    "4904": "遠傳",
    "3045": "台灣大",
    # Other low-vol stocks that failed or were marginal
    "2891": "台新金",
    "4938": "和碩",
    "2618": "長榮航",
    # Control: stocks that AUTO helped
    "2912": "統一超",
    "5880": "合庫金",
    "2834": "臺企銀",
}

PERIOD_DAYS = 1095
CAPITAL = 1_000_000

# Old config: floor=1%
CFG_FLAT = {
    "auto_trail_classifier": False,
    "atr_trail_enabled": False,
    "dynamic_trail_enabled": False,
    "trailing_stop_pct": 0.02,
}

# Old auto (floor=1%)
CFG_AUTO_OLD = {
    "auto_trail_classifier": True,
    "auto_trail_threshold": 0.018,
    "auto_trail_k": 1.0,
    "atr_trail_enabled": False,
    "dynamic_trail_enabled": False,
    "trailing_stop_pct": 0.02,
    "atr_trail_floor": 0.01,  # Old 1% floor
}

# New auto (floor=1.5%)
CFG_AUTO_NEW = {
    "auto_trail_classifier": True,
    "auto_trail_threshold": 0.018,
    "auto_trail_k": 1.0,
    "atr_trail_enabled": False,
    "dynamic_trail_enabled": False,
    "trailing_stop_pct": 0.02,
    "atr_trail_floor": 0.015,  # NEW 1.5% floor
}

def run(df, cfg):
    try:
        bt = run_backtest_v4(df, initial_capital=CAPITAL, params=cfg)
        return bt.sharpe_ratio
    except:
        return None

def main():
    print("R78: Telecom Floor Validation (1% → 1.5%)")
    print("=" * 80)

    stock_data = {}
    for code, name in STOCKS.items():
        print(f"  Fetching {code} {name}...", end=" ", flush=True)
        try:
            df = get_stock_data(code, period_days=PERIOD_DAYS)
            stock_data[code] = df
            print(f"OK ({len(df)} rows)")
        except Exception as e:
            print(f"FAIL: {e}")

    print(f"\n{'Code':<8s} {'Name':<10s} {'Flat 2%':>10s} {'Auto 1%':>10s} {'Auto 1.5%':>10s} {'Old Δ':>8s} {'New Δ':>8s} {'Fixed?':>8s}")
    print("-" * 75)

    for code, df in stock_data.items():
        name = STOCKS[code]
        s_flat = run(df, CFG_FLAT)
        s_old = run(df, CFG_AUTO_OLD)
        s_new = run(df, CFG_AUTO_NEW)

        if s_flat is not None and s_old is not None and s_new is not None:
            old_delta = s_old - s_flat
            new_delta = s_new - s_flat
            old_winner = "AUTO" if old_delta > 0.01 else ("FLAT" if old_delta < -0.01 else "TIE")
            new_winner = "AUTO" if new_delta > 0.01 else ("FLAT" if new_delta < -0.01 else "TIE")
            fixed = "YES" if old_winner == "FLAT" and new_winner != "FLAT" else ("N/A" if old_winner != "FLAT" else "NO")
            print(f"{code:<8s} {name:<10s} {s_flat:>+9.3f} {s_old:>+9.3f} {s_new:>+9.3f} {old_delta:>+7.3f} {new_delta:>+7.3f} {fixed:>8s}")
        else:
            print(f"{code:<8s} {name:<10s} ERROR")


if __name__ == "__main__":
    main()

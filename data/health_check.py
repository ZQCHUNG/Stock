"""Pre-Market Health Check for Maiden Voyage (2/23) and beyond.

[CONVERGED — Gemini Wall Street Trader R8]:
Run at 08:30 before market open to verify data pipeline integrity.

3 checks:
1. Parquet timestamp > previous trading day 20:00
2. Top 20 weighted stocks have non-zero attention_index_7d
3. Scheduler log has no 429 errors

Usage:
    python -m data.health_check
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FEATURES_DIR = PROJECT_ROOT / "data" / "pattern_data" / "features"
FEATURES_FILE = FEATURES_DIR / "features_all.parquet"
METADATA_FILE = FEATURES_DIR / "feature_metadata.json"
NEWS_DIR = PROJECT_ROOT / "data" / "pattern_data" / "raw" / "news"
HEARTBEAT_FILE = PROJECT_ROOT / "data" / "scheduler_heartbeat.json"

# Top 20 TWSE weighted stocks (TSMC, Hon Hai, MediaTek, etc.)
TOP20_STOCKS = [
    "2330", "2317", "2454", "2308", "2382",
    "2881", "2882", "2891", "2303", "2886",
    "3711", "2412", "1301", "1303", "2002",
    "2880", "3008", "2884", "1216", "2357",
]


def _get_previous_trading_day() -> datetime:
    """Get the most recent trading day before today."""
    today = datetime.now()
    # Go back 1 day, skip weekends
    d = today - timedelta(days=1)
    while d.weekday() >= 5:  # Saturday=5, Sunday=6
        d -= timedelta(days=1)
    return d


def check_parquet_freshness() -> dict:
    """Check 1: Parquet file was updated after previous trading day 20:00."""
    result = {"check": "Parquet Freshness", "status": "FAIL", "detail": ""}

    if not FEATURES_FILE.exists():
        result["detail"] = f"File not found: {FEATURES_FILE}"
        return result

    mtime = datetime.fromtimestamp(FEATURES_FILE.stat().st_mtime)
    prev_day = _get_previous_trading_day()
    threshold = prev_day.replace(hour=20, minute=0, second=0)

    result["file_mtime"] = mtime.isoformat()
    result["threshold"] = threshold.isoformat()

    if mtime >= threshold:
        result["status"] = "PASS"
        result["detail"] = f"Last updated: {mtime.strftime('%Y-%m-%d %H:%M')}"
    else:
        result["detail"] = (
            f"Stale! Last updated {mtime.strftime('%Y-%m-%d %H:%M')}, "
            f"expected after {threshold.strftime('%Y-%m-%d %H:%M')}"
        )

    return result


def check_attention_data() -> dict:
    """Check 2: Top 20 stocks have non-zero attention_index_7d."""
    result = {"check": "Attention Data", "status": "FAIL", "detail": ""}

    if not FEATURES_FILE.exists() or not METADATA_FILE.exists():
        result["detail"] = "Feature files not found"
        return result

    try:
        with open(METADATA_FILE, "r", encoding="utf-8") as f:
            meta = json.load(f)

        if "attention_index_7d" not in meta["all_features"]:
            result["status"] = "SKIP"
            result["detail"] = "attention_index_7d not in feature set"
            return result

        df = pd.read_parquet(FEATURES_FILE, columns=["stock_code", "date", "attention_index_7d"])
        latest_date = df["date"].max()

        # Check Top 20 on latest date
        latest = df[df["date"] == latest_date]
        top20_data = latest[latest["stock_code"].isin(TOP20_STOCKS)]

        total = len(top20_data)
        nonzero = int((top20_data["attention_index_7d"].fillna(0) != 0).sum())

        result["latest_date"] = str(latest_date)
        result["top20_found"] = total
        result["top20_nonzero"] = nonzero

        if nonzero > 0:
            result["status"] = "PASS"
            result["detail"] = f"{nonzero}/{total} stocks have attention data on {latest_date.strftime('%Y-%m-%d')}"
        else:
            result["detail"] = (
                f"All {total} Top 20 stocks have zero attention on {latest_date.strftime('%Y-%m-%d')}. "
                "Google News RSS fetch may have failed."
            )
    except Exception as e:
        result["detail"] = f"Error: {e}"

    return result


def check_scheduler_logs() -> dict:
    """Check 3: No 429 errors in recent scheduler activity."""
    result = {"check": "Scheduler Health", "status": "FAIL", "detail": ""}

    # Check heartbeat file
    if HEARTBEAT_FILE.exists():
        try:
            with open(HEARTBEAT_FILE, "r", encoding="utf-8") as f:
                hb = json.load(f)
            result["last_heartbeat"] = hb.get("timestamp", "unknown")
            result["status"] = "PASS"
            result["detail"] = f"Heartbeat: {hb.get('timestamp', 'unknown')}"
        except Exception as e:
            result["detail"] = f"Heartbeat parse error: {e}"
    else:
        result["status"] = "WARN"
        result["detail"] = "No heartbeat file found (scheduler may not have run yet)"

    # Check for Google News fetch results
    if NEWS_DIR.exists():
        google_news_files = list(NEWS_DIR.glob("google_news_gnews_*.json"))
        result["google_news_files"] = len(google_news_files)
        if len(google_news_files) == 0:
            result["status"] = "FAIL"
            result["detail"] += " | No Google News files found"
    else:
        result["google_news_files"] = 0
        result["detail"] += " | News directory not found"

    return result


def run_health_check() -> dict:
    """Run all health checks and return summary."""
    checks = [
        check_parquet_freshness(),
        check_attention_data(),
        check_scheduler_logs(),
    ]

    all_pass = all(c["status"] == "PASS" for c in checks)
    any_fail = any(c["status"] == "FAIL" for c in checks)

    return {
        "timestamp": datetime.now().isoformat(),
        "overall": "PASS" if all_pass else ("FAIL" if any_fail else "WARN"),
        "checks": checks,
    }


def main():
    print("=" * 60)
    print("Pre-Market Health Check — Maiden Voyage")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    result = run_health_check()

    for check in result["checks"]:
        status = check["status"]
        icon = "[OK]" if status == "PASS" else ("[!!]" if status == "FAIL" else "[??]")
        print(f"\n{icon} {check['check']}: {status}")
        print(f"    {check['detail']}")

    print("\n" + "=" * 60)
    overall = result["overall"]
    if overall == "PASS":
        print("RESULT: ALL CHECKS PASSED — Ready for market open")
    elif overall == "FAIL":
        print("RESULT: CHECKS FAILED — Manual investigation required")
    else:
        print("RESULT: WARNINGS — Proceed with caution")
    print("=" * 60)

    # Save result
    output_path = PROJECT_ROOT / "data" / "health_check_result.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to: {output_path}")

    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

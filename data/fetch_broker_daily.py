"""
券商分點進出 — 日頻資料抓取器 (Fubon DJhtm)
R88.7 Method C: Daily brokerage data for Sniper tier

- 來源: fubon-ebrokerdj.fbs.com.tw/z/zc/zco/
- 模式: 單日查詢 (e=f=same_date)
- 吞吐量: 10 workers, ~52 秒 / 1096 stocks [VALIDATED: Phase 1 test]

用法:
    python -m data.fetch_broker_daily                  # 抓最近交易日
    python -m data.fetch_broker_daily --date 20260210  # 指定日期
    python -m data.fetch_broker_daily --backfill 20    # 回補最近 20 個交易日
    python -m data.fetch_broker_daily --stats          # 顯示統計
    python -m data.fetch_broker_daily --time-check     # 時間滑塊測試

收斂參數 (R88.7):
    [CONVERGED] Fetch start time: 16:30 (avoid 15:30 trap)
    [CONVERGED] Timestamp validation: response.end_date == query_date
    [CONVERGED] Missing data: mark "data_unavailable" (NOT forward-fill)
"""
import requests
import time
import random
import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from data.pattern_store import (
    log_fetch, is_fetched, get_fetch_stats, RAW_DIR, get_trading_dates
)

SOURCE = "broker_daily"

HEADERS_POOL = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Referer": "https://fubon-ebrokerdj.fbs.com.tw/",
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-TW,zh;q=0.9",
        "Referer": "https://fubon-ebrokerdj.fbs.com.tw/",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8",
        "Referer": "https://fubon-ebrokerdj.fbs.com.tw/",
    },
]

FUBON_URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm"

ACTIVE_STOCKS_FILE = Path(__file__).parent / "active_stocks.json"

# Storage directory for daily broker data
DAILY_DIR = RAW_DIR / "broker_daily"
DAILY_DIR.mkdir(parents=True, exist_ok=True)


def get_stock_list() -> list[str]:
    """Read stock codes from active_stocks.json."""
    if ACTIVE_STOCKS_FILE.exists():
        with open(ACTIVE_STOCKS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        codes = [s["code"] for s in data.get("stocks", [])]
        return codes
    return ["2330", "2317", "2454", "2308", "2881", "2882"]


def _parse_broker_html(raw_bytes: bytes) -> dict | None:
    """Parse Fubon zco HTML (Big5) into structured data.

    Returns parsed data dict or None if no valid data found.
    """
    html = raw_bytes.decode("big5", errors="replace")

    # Extract date range from script variables
    date_vars = re.findall(
        r"var\s+(getYMD\d)\s*=\s*'([^']+)'", html
    )
    date_info = {name: val for name, val in date_vars}
    start_date = date_info.get("getYMD2", "")
    end_date = date_info.get("getYMD1", "")

    if not start_date and not end_date:
        return None

    # Extract data cells
    cells = re.findall(
        r'<[Tt][Dd][^>]*class="(t4t1|t3n1|t4t0|t3n0)"[^>]*>(.*?)</[Tt][Dd]>',
        html, re.DOTALL
    )
    if not cells:
        return None

    data_cells = [(cls, re.sub(r"<[^>]+>", "", val).strip())
                  for cls, val in cells
                  if cls in ("t4t1", "t3n1")]

    # Parse broker entries
    brokers = []
    i = 0
    while i < len(data_cells):
        cls, val = data_cells[i]
        if cls == "t4t1" and val:
            if i + 4 < len(data_cells):
                buy_lots = data_cells[i + 1][1]
                sell_lots = data_cells[i + 2][1]
                net = data_cells[i + 3][1]
                pct = data_cells[i + 4][1]
                brokers.append({
                    "broker": val,
                    "buy": buy_lots,
                    "sell": sell_lots,
                    "net": net,
                    "pct": pct,
                })
                i += 5
                continue
        i += 1

    if not brokers:
        return None

    # Split into buy/sell sections (interleaved layout)
    buy_brokers = brokers[::2]
    sell_brokers = brokers[1::2]

    # Extract broker codes
    broker_codes = re.findall(
        r'zco0\.djhtm\?a=\d+&(?:b|BHID)=(\d+)',
        html
    )

    return {
        "start_date": start_date.replace("/", "-"),
        "end_date": end_date.replace("/", "-"),
        "buy_top": buy_brokers,
        "sell_top": sell_brokers,
        "buy_count": len(buy_brokers),
        "sell_count": len(sell_brokers),
        "broker_codes": broker_codes[:30],
    }


def fetch_broker_daily(stock_code: str, date_str: str) -> dict | None:
    """Fetch single-day broker data from Fubon DJhtm.

    Args:
        stock_code: Stock code (e.g., '2330')
        date_str: Date in 'YYYY-M-D' format (e.g., '2026-2-10')

    Returns:
        Parsed data dict with timestamp validation, or None.
    """
    headers = random.choice(HEADERS_POOL)
    params = {
        "a": stock_code,
        "e": date_str,
        "f": date_str,  # Same day = daily query
    }
    try:
        resp = requests.get(
            FUBON_URL,
            params=params,
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()

        parsed = _parse_broker_html(resp.content)
        if not parsed:
            return None

        parsed["stock"] = stock_code
        return parsed

    except Exception as e:
        print(f"  [Fubon] {stock_code} error: {e}")
        return None


def _validate_timestamp(parsed: dict, expected_date: str) -> bool:
    """Validate that response date matches expected date.

    [CONVERGED] Trader requirement: timestamp校驗 — Fubon 15:30 trap protection.
    """
    end_date = parsed.get("end_date", "")
    return end_date == expected_date


def _format_date_for_fubon(yyyymmdd: str) -> str:
    """Convert YYYYMMDD to YYYY-M-D (Fubon format)."""
    y = int(yyyymmdd[:4])
    m = int(yyyymmdd[4:6])
    d = int(yyyymmdd[6:8])
    return f"{y}-{m}-{d}"


def _fetch_one_stock(stock: str, date_fubon: str, date_key: str,
                     max_retries: int = 3) -> tuple[str, str, dict | None]:
    """Fetch a single stock's daily broker data with retry logic.

    Returns:
        (status, stock_code, parsed_data)
        status: "ok", "skip", "stale", "fail"
    """
    # Check if already fetched
    if is_fetched(SOURCE, date_key, stock):
        return "skip", stock, None

    time.sleep(random.uniform(0.2, 0.4))

    for attempt in range(max_retries):
        result = fetch_broker_daily(stock, date_fubon)

        if result is None:
            # No data — could be holiday/weekend
            if attempt < max_retries - 1:
                time.sleep(1.0 * (attempt + 1))  # Exponential backoff
                continue
            return "fail", stock, None

        # Timestamp validation [CONVERGED]
        if _validate_timestamp(result, date_fubon):
            # Save to disk
            filepath = DAILY_DIR / f"{stock}_{date_key}.json"
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
            log_fetch(SOURCE, stock, date_key,
                      result["buy_count"] + result["sell_count"])
            return "ok", stock, result

        # Stale data: timestamp doesn't match
        if attempt < max_retries - 1:
            delay = 10 * (attempt + 1)  # 10s, 20s, 30s
            print(f"  [{stock}] Stale data (got {result['end_date']}, "
                  f"expected {date_fubon}), retry in {delay}s...")
            time.sleep(delay)
        else:
            # Mark as stale after all retries [CONVERGED: no forward-fill]
            log_fetch(SOURCE, stock, date_key, 0, "stale")
            return "stale", stock, None

    return "fail", stock, None


def run_daily_fetch(date_str: str = None, workers: int = 10,
                    batch_size: int = 0) -> dict:
    """Fetch daily broker data for all active stocks.

    Args:
        date_str: Date in YYYYMMDD format. Defaults to last trading day.
        workers: Number of parallel workers.
        batch_size: Limit stocks (0 = all).

    Returns:
        Summary dict with counts and timing.
    """
    stocks = get_stock_list()
    if batch_size > 0:
        stocks = stocks[:batch_size]

    if date_str is None:
        # Default to last trading day
        today = datetime.now()
        # Go back to find last weekday
        while today.weekday() >= 5:
            today -= timedelta(days=1)
        date_str = today.strftime("%Y%m%d")

    date_key = date_str  # YYYYMMDD for storage key
    date_fubon = _format_date_for_fubon(date_str)

    print(f"=== Daily Broker Fetch: {date_str} ===")
    print(f"Stocks: {len(stocks)}, Workers: {workers}")
    print(f"Fubon format: {date_fubon}")
    print()

    start_time = time.time()
    ok = 0
    skip = 0
    stale = 0
    fail = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_one_stock, stock, date_fubon, date_key): stock
            for stock in stocks
        }

        done = 0
        for future in as_completed(futures):
            status, stock, result = future.result()
            done += 1

            if status == "ok":
                ok += 1
            elif status == "skip":
                skip += 1
            elif status == "stale":
                stale += 1
            else:
                fail += 1

            if done % 200 == 0 or done == len(stocks):
                elapsed = time.time() - start_time
                print(f"  [{done}/{len(stocks)}] "
                      f"ok={ok} skip={skip} stale={stale} fail={fail} "
                      f"({elapsed:.1f}s)")

    elapsed = time.time() - start_time

    # Data quality assessment [CONVERGED]
    total_attempted = ok + stale + fail
    if total_attempted > 0:
        fail_rate = (stale + fail) / total_attempted
    else:
        fail_rate = 0

    quality = "good"
    if fail_rate > 0.5:
        quality = "data_insufficient"  # [CONVERGED] NaN dimension
    elif fail_rate > 0.1:
        quality = "partial"  # Warning but still usable

    summary = {
        "date": date_str,
        "stocks_total": len(stocks),
        "ok": ok,
        "skip": skip,
        "stale": stale,
        "fail": fail,
        "fail_rate": round(fail_rate, 4),
        "quality": quality,
        "elapsed_seconds": round(elapsed, 1),
    }

    print(f"\n=== Done: {date_str} ===")
    print(f"OK: {ok} | Skip: {skip} | Stale: {stale} | Fail: {fail}")
    print(f"Fail rate: {fail_rate:.1%} | Quality: {quality}")
    print(f"Time: {elapsed:.1f}s")

    return summary


def run_backfill(n_days: int = 20, workers: int = 10):
    """Backfill daily broker data for recent N trading days."""
    today = datetime.now().strftime("%Y%m%d")
    dates = get_trading_dates("20260101", today)

    # Take last N days
    dates = dates[-n_days:]
    print(f"Backfill: {len(dates)} trading days")
    print(f"Range: {dates[0]} ~ {dates[-1]}")
    print()

    for i, d in enumerate(dates):
        print(f"\n--- Day {i+1}/{len(dates)}: {d} ---")
        summary = run_daily_fetch(date_str=d, workers=workers)

        # Rate limit between days
        if i < len(dates) - 1:
            delay = random.uniform(2, 5)
            time.sleep(delay)


def run_time_check():
    """時間滑塊測試: Check if today's data is available at current time.

    [CONVERGED] Trader requirement: test 15:00/16:00/17:00 availability.
    """
    today = datetime.now()
    if today.weekday() >= 5:
        print("Weekend — no trading data expected.")
        return

    date_str = today.strftime("%Y%m%d")
    date_fubon = _format_date_for_fubon(date_str)
    current_time = today.strftime("%H:%M:%S")

    print(f"=== Time Check: {date_str} at {current_time} ===")
    print()

    test_stocks = ["2330", "2454", "1301"]
    for stock in test_stocks:
        result = fetch_broker_daily(stock, date_fubon)
        if result:
            is_today = _validate_timestamp(result, date_fubon)
            print(f"{stock}: DATA (date={result['end_date']}, "
                  f"is_today={is_today})")
        else:
            print(f"{stock}: NO DATA")
        time.sleep(0.5)


def show_stats():
    """Display daily broker data statistics."""
    stats = get_fetch_stats(SOURCE)
    if not stats:
        print("No daily broker data yet")
        return

    total_stocks = len(set(s["market"] for s in stats))
    total_records = sum(s["total_records"] for s in stats)
    print(f"Daily broker data: {total_stocks} stocks, "
          f"{total_records} total entries")
    for s in stats[:10]:
        print(f"  {s['market']}: {s['first']} ~ {s['last']}, "
              f"{s['days']} days")
    if len(stats) > 10:
        print(f"  ... and {len(stats) - 10} more")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Daily broker data fetcher (Fubon DJhtm) [R88.7]"
    )
    parser.add_argument("--date", type=str, default=None,
                        help="Target date YYYYMMDD (default: last trading day)")
    parser.add_argument("--backfill", type=int, default=0,
                        help="Backfill N recent trading days")
    parser.add_argument("--stats", action="store_true",
                        help="Show statistics")
    parser.add_argument("--time-check", action="store_true",
                        help="Time slider test (check data availability)")
    parser.add_argument("--workers", type=int, default=10,
                        help="Parallel workers (default 10)")
    parser.add_argument("--batch", type=int, default=0,
                        help="Batch size (0 = all)")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.time_check:
        run_time_check()
    elif args.backfill > 0:
        run_backfill(n_days=args.backfill, workers=args.workers)
    else:
        run_daily_fetch(date_str=args.date, workers=args.workers,
                        batch_size=args.batch)

"""產業熱度背景掃描 Worker（獨立進程）

Gemini R21: Independent background worker for sector heat scanning.
- Scans SCAN_STOCKS pool every 30 min during trading hours
- Stores results in Redis (with in-memory fallback)
- Keeps last successful data on failure (Stale > Empty)

Usage:
    python -m backend.worker          # Run as module
    python backend/worker.py          # Run directly

Schedule (台股):
    - Pre-open: 08:30
    - During trading: 09:00-13:30, every 30 min
    - After hours: skip (cache remains valid)
"""

import sys
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Ensure project root is in sys.path
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from config import SCAN_STOCKS
from data.cache import (
    set_cached_sector_heat,
    set_sector_heat_error,
    set_worker_heartbeat,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sector_heat_worker")

# Scan interval (seconds)
SCAN_INTERVAL = 1800  # 30 min

# Maturity weights for weighted heat scoring (Gemini R21)
MATURITY_WEIGHTS = {
    "Speculative Spike": 1.0,
    "Trend Formation": 1.5,
    "Structural Shift": 2.0,
}


def is_trading_hours() -> bool:
    """Check if current time is within Taiwan stock trading hours (with pre-open buffer).

    Returns True during:
    - Weekdays 08:30 - 14:00 (includes pre-open 08:30 and post-close buffer to 14:00)
    """
    now = datetime.now()
    weekday = now.weekday()  # 0=Mon, 6=Sun
    if weekday >= 5:
        return False
    time_val = now.hour * 60 + now.minute
    # 08:30 to 14:00 (13:30 close + 30 min buffer for final scan)
    return 8 * 60 + 30 <= time_val <= 14 * 60


def scan_sector_heat() -> dict:
    """Execute full sector heat scan across SCAN_STOCKS pool.

    Returns:
        dict with keys: sectors (list), scanned (int), total_buy (int)
    """
    from data.fetcher import get_stock_data, get_stock_info
    from analysis.strategy_v4 import get_v4_analysis

    def _scan_stock(code: str) -> dict | None:
        try:
            df = get_stock_data(code, period_days=120)
            v4 = get_v4_analysis(df)
            try:
                info = get_stock_info(code)
                sector = info.get("sector", "")
            except Exception:
                sector = ""
            return {
                "code": code,
                "name": SCAN_STOCKS.get(code, code),
                "sector": sector or "未分類",
                "signal": v4["signal"],
                "signal_maturity": v4.get("signal_maturity", "N/A"),
                "uptrend_days": v4.get("uptrend_days", 0),
            }
        except Exception as e:
            logger.warning(f"Failed to scan {code}: {e}")
            return None

    logger.info(f"Starting sector heat scan: {len(SCAN_STOCKS)} stocks...")
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(_scan_stock, list(SCAN_STOCKS.keys())))

    valid = [r for r in results if r is not None]
    elapsed = time.time() - start_time
    logger.info(f"Scan complete: {len(valid)}/{len(SCAN_STOCKS)} stocks in {elapsed:.1f}s")

    # Group by sector
    sectors: dict[str, list] = {}
    for s in valid:
        sec = s["sector"]
        sectors.setdefault(sec, []).append(s)

    heat_data = []
    for sector, stocks in sectors.items():
        total = len(stocks)
        buy_stocks = [s for s in stocks if s["signal"] == "BUY"]
        buy_count = len(buy_stocks)
        heat = buy_count / total if total > 0 else 0

        # Weighted heat: Structural Shift counts 2x, Trend Formation 1.5x
        weighted_sum = sum(
            MATURITY_WEIGHTS.get(s["signal_maturity"], 1.0) for s in buy_stocks
        )
        weighted_heat = weighted_sum / total if total > 0 else 0

        heat_data.append({
            "sector": sector,
            "total": total,
            "buy_count": buy_count,
            "heat": round(heat, 3),
            "weighted_heat": round(weighted_heat, 3),
            "buy_stocks": [
                {"code": s["code"], "name": s["name"], "maturity": s["signal_maturity"]}
                for s in buy_stocks
            ],
            "all_stocks": [s["code"] for s in stocks],
        })

    heat_data.sort(key=lambda x: x["weighted_heat"], reverse=True)

    total_buy = sum(h["buy_count"] for h in heat_data)
    logger.info(
        f"Results: {len(heat_data)} sectors, {total_buy} BUY signals, "
        f"top sector: {heat_data[0]['sector'] if heat_data else 'N/A'} "
        f"({heat_data[0]['weighted_heat']:.1%} weighted heat)" if heat_data else ""
    )

    return {
        "sectors": heat_data,
        "scanned": len(valid),
        "total_buy": total_buy,
    }


def _acquire_scan_lock(ttl: int = 300) -> bool:
    """Acquire Redis lock to prevent concurrent scans.

    Uses simple SET NX with TTL as distributed lock.
    Falls back to always-acquire if Redis unavailable.
    """
    from data.cache import get_redis
    r = get_redis()
    if r is None:
        return True  # No Redis = no lock contention possible
    try:
        # SET NX: only succeeds if key doesn't exist
        acquired = r.set("sector_heat:lock", "1", nx=True, ex=ttl)
        return bool(acquired)
    except Exception:
        return True  # On error, proceed with scan


def _release_scan_lock():
    """Release the scan lock."""
    from data.cache import get_redis
    r = get_redis()
    if r is not None:
        try:
            r.delete("sector_heat:lock")
        except Exception:
            pass


def run_scan_cycle(scan_count: int) -> int:
    """Execute one scan cycle with error handling and distributed lock.

    Returns updated scan_count.
    """
    if not _acquire_scan_lock():
        logger.warning(f"Scan #{scan_count} skipped: another worker is scanning")
        return scan_count

    try:
        result = scan_sector_heat()
        set_cached_sector_heat(result)
        set_worker_heartbeat(
            scan_count=scan_count,
            stocks_scanned=result["scanned"],
            buy_signals=result["total_buy"],
        )
        logger.info(f"Scan #{scan_count} saved to cache successfully")
        return scan_count + 1
    except Exception as e:
        logger.error(f"Scan #{scan_count} failed: {e}")
        set_sector_heat_error(str(e))
        # Keep last successful data in Redis (Stale > Empty)
        return scan_count
    finally:
        _release_scan_lock()


def main():
    """Main worker loop."""
    logger.info("=" * 60)
    logger.info("Sector Heat Worker starting")
    logger.info(f"Scan pool: {len(SCAN_STOCKS)} stocks")
    logger.info(f"Scan interval: {SCAN_INTERVAL}s ({SCAN_INTERVAL // 60} min)")
    logger.info("=" * 60)

    scan_count = 1

    # Initial scan on startup (regardless of trading hours)
    logger.info("Running initial scan...")
    scan_count = run_scan_cycle(scan_count)

    while True:
        time.sleep(SCAN_INTERVAL)

        if not is_trading_hours():
            logger.debug("Outside trading hours, skipping scan")
            continue

        scan_count = run_scan_cycle(scan_count)


if __name__ == "__main__":
    main()

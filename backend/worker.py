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
    get_sector_heat_previous,
    set_sector_heat_previous,
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


def _calculate_leader_score(stock: dict, inst_score: float | None) -> float:
    """Calculate Leader_Score for a BUY stock (Gemini R22 P1).

    Score = Maturity_Norm × 0.4 + Inst_Score_Norm × 0.4 + Vol_Strength_Norm × 0.2
    All factors normalized to [0, 1].
    """
    # Maturity: 1.0 → 0, 1.5 → 0.5, 2.0 → 1.0
    mat_weight = MATURITY_WEIGHTS.get(stock.get("signal_maturity", ""), 1.0)
    mat_norm = (mat_weight - 1.0) / 1.0

    # Institutional: [-5, 5] → [0, 1], default 0.5 if unavailable
    if inst_score is not None:
        inst_norm = max(0.0, min(1.0, (inst_score + 5) / 10))
    else:
        inst_norm = 0.5  # neutral when no data

    # Volume: ratio 1.0 → 0, ratio ≥ 2.0 → 1.0
    vol_ratio = stock.get("volume_ratio", 1.0)
    vol_norm = max(0.0, min(1.0, (vol_ratio - 1.0) / 1.0))

    return round(mat_norm * 0.4 + inst_norm * 0.4 + vol_norm * 0.2, 3)


def _fetch_inst_scores(buy_codes: list[str]) -> dict[str, float]:
    """Fetch institutional scores for BUY stocks only (minimize API calls)."""
    if not buy_codes:
        return {}

    from data.fetcher import get_institutional_data
    from analysis.report.recommendation import _calculate_institutional_score

    scores = {}

    def _get_inst(code):
        try:
            inst_df = get_institutional_data(code, days=10)
            result = _calculate_institutional_score(inst_df)
            return code, result.get("score", 0)
        except Exception:
            return code, None

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(_get_inst, buy_codes))

    for code, score in results:
        scores[code] = score
    return scores


def scan_sector_heat() -> dict:
    """Execute full sector heat scan across SCAN_STOCKS pool.

    Returns:
        dict with keys: sectors (list), scanned (int), total_buy (int)
    """
    from data.fetcher import get_stock_data
    from analysis.strategy_v4 import get_v4_analysis
    from data.sector_mapping import get_stock_sector

    def _scan_stock(code: str) -> dict | None:
        try:
            df = get_stock_data(code, period_days=120)
            v4 = get_v4_analysis(df)
            sector_l1 = get_stock_sector(code, level=1)
            sector_l2 = get_stock_sector(code, level=2)

            # Volume ratio: today's volume / 5-day avg (for Surge confirmation)
            vol_ratio = 0.0
            if len(df) >= 6:
                vol_ma5 = df["volume"].iloc[-6:-1].mean()
                if vol_ma5 > 0:
                    vol_ratio = float(df["volume"].iloc[-1] / vol_ma5)

            return {
                "code": code,
                "name": SCAN_STOCKS.get(code, code),
                "sector": sector_l1,
                "sector_l2": sector_l2,
                "signal": v4["signal"],
                "signal_maturity": v4.get("signal_maturity", "N/A"),
                "uptrend_days": v4.get("uptrend_days", 0),
                "volume_ratio": round(vol_ratio, 2),
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

    # === Fetch institutional scores for BUY stocks only ===
    buy_codes = [s["code"] for s in valid if s["signal"] == "BUY"]
    inst_scores = {}
    if buy_codes:
        logger.info(f"Fetching institutional data for {len(buy_codes)} BUY stocks...")
        inst_scores = _fetch_inst_scores(buy_codes)

    # Group by L1 sector
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

        # Sector-level avg volume ratio for BUY stocks (Surge confirmation)
        buy_vol_ratios = [s.get("volume_ratio", 0) for s in buy_stocks if s.get("volume_ratio", 0) > 0]
        avg_buy_vol_ratio = sum(buy_vol_ratios) / len(buy_vol_ratios) if buy_vol_ratios else 0

        # === Leader Score (Gemini R22 P1) ===
        leader = None
        for bs in buy_stocks:
            score = _calculate_leader_score(bs, inst_scores.get(bs["code"]))
            bs["leader_score"] = score
        # Pick highest scoring BUY stock (>0.6 threshold, tiebreak by uptrend_days)
        candidates = [bs for bs in buy_stocks if bs.get("leader_score", 0) > 0.6]
        if candidates:
            best = max(candidates, key=lambda x: (x["leader_score"], x.get("uptrend_days", 0)))
            leader = {
                "code": best["code"],
                "name": best["name"],
                "score": best["leader_score"],
                "maturity": best["signal_maturity"],
            }

        # === L2 Subsector breakdown ===
        l2_groups: dict[str, list] = {}
        for s in stocks:
            l2 = s.get("sector_l2", "未分類")
            l2_groups.setdefault(l2, []).append(s)

        subsectors = []
        for l2_name, l2_stocks in l2_groups.items():
            l2_total = len(l2_stocks)
            l2_buy = [s for s in l2_stocks if s["signal"] == "BUY"]
            l2_heat = len(l2_buy) / l2_total if l2_total > 0 else 0
            subsectors.append({
                "sector": l2_name,
                "total": l2_total,
                "buy_count": len(l2_buy),
                "heat": round(l2_heat, 3),
            })
        subsectors.sort(key=lambda x: x["heat"], reverse=True)

        heat_data.append({
            "sector": sector,
            "total": total,
            "buy_count": buy_count,
            "heat": round(heat, 3),
            "weighted_heat": round(weighted_heat, 3),
            "avg_buy_vol_ratio": round(avg_buy_vol_ratio, 2),
            "leader": leader,
            "subsectors": subsectors,
            "buy_stocks": [
                {
                    "code": s["code"], "name": s["name"],
                    "maturity": s["signal_maturity"],
                    "leader_score": s.get("leader_score"),
                }
                for s in buy_stocks
            ],
            "all_stocks": [s["code"] for s in stocks],
        })

    heat_data.sort(key=lambda x: x["weighted_heat"], reverse=True)

    # === Sector Momentum (Gemini R21 P1) ===
    # Compare current heat with previous scan
    previous = get_sector_heat_previous() or {}
    current_heat_map = {}

    for sector_data in heat_data:
        sector_name = sector_data["sector"]
        current_wh = sector_data["weighted_heat"]
        current_heat_map[sector_name] = current_wh

        prev_wh = previous.get(sector_name)
        if prev_wh is None:
            sector_data["momentum"] = "new"
            sector_data["delta_heat"] = 0
            sector_data["jump_ratio"] = 0
            continue

        delta = current_wh - prev_wh
        jump = current_wh / max(prev_wh, 0.05)

        # Classify momentum (Gemini R21: volume confirmation for Surge)
        avg_vol = sector_data.get("avg_buy_vol_ratio", 0)
        if delta >= 0.10 and jump >= 2.0 and avg_vol >= 1.2:
            momentum = "surge"
        elif delta >= 0.10 and jump >= 2.0:
            # Would be Surge but lacks volume confirmation → downgrade
            momentum = "heating"
        elif delta >= 0.10:
            momentum = "heating"
        elif delta <= -0.10:
            momentum = "cooling"
        else:
            momentum = "stable"

        sector_data["momentum"] = momentum
        sector_data["delta_heat"] = round(delta, 3)
        sector_data["jump_ratio"] = round(jump, 2)

    # Save current heat as "previous" for next scan
    set_sector_heat_previous(current_heat_map)

    total_buy = sum(h["buy_count"] for h in heat_data)

    # Log momentum changes
    momentum_changes = [
        h for h in heat_data if h.get("momentum") in ("surge", "heating", "cooling")
    ]
    if momentum_changes:
        for mc in momentum_changes:
            logger.info(
                f"  Momentum [{mc['momentum'].upper()}]: {mc['sector']} "
                f"ΔHeat={mc['delta_heat']:+.1%} Jump={mc['jump_ratio']:.1f}x"
            )

    # Log leaders
    leaders = [h for h in heat_data if h.get("leader")]
    if leaders:
        for h in leaders:
            ld = h["leader"]
            logger.info(
                f"  Leader [{h['sector']}]: {ld['code']} {ld['name']} "
                f"(Score={ld['score']:.2f}, {ld['maturity']})"
            )

    logger.info(
        f"Results: {len(heat_data)} sectors, {total_buy} BUY signals, "
        f"{len(leaders)} leaders"
        + (f", top: {heat_data[0]['sector']} ({heat_data[0]['weighted_heat']:.1%})"
           if heat_data else "")
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

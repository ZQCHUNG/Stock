"""Slippage Auditor — Real-trade friction analysis.

Phase 12 P0: CTO directive — "如果實戰滑價吃掉了預期利潤，所有回測都是幻影"
Architect OFFICIALLY APPROVED 2026-02-25.

Analyzes is_live signals to compute:
- Per-industry Median / P95 slippage (bps)
- Friction Drag = avg_slippage × 2 / virtual_expectancy
- Industry friction classification (LOW / HIGH / INSUFFICIENT_DATA)

[HYPOTHESIS: SLIPPAGE_SENSITIVITY_V1] — thresholds need real-data calibration
"""

import logging
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "signal_log.db"

# [HYPOTHESIS: SLIPPAGE_SENSITIVITY_V1]
SLIPPAGE_HIGH_MEDIAN_BPS = 50   # 0.50% — CTO: "嚴苛但必要"
SLIPPAGE_HIGH_P95_BPS = 150     # 1.50%
MIN_SAMPLES = 5                  # [HYPOTHESIS: SLIPPAGE_MIN_SAMPLES_001]


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def run_slippage_audit() -> dict[str, Any]:
    """Run full slippage audit on all is_live signals.

    Returns:
        {
            "total_live_trades": int,
            "avg_slippage_bps": float,
            "friction_drag_pct": float | None,
            "industries": [
                {
                    "industry": str,
                    "count": int,
                    "median_bps": float,
                    "p95_bps": float,
                    "avg_bps": float,
                    "status": "LOW" | "HIGH" | "INSUFFICIENT_DATA"
                }, ...
            ],
            "high_friction_industries": [str, ...],
            "virtual_expectancy": float | None,
        }
    """
    conn = _get_conn()
    try:
        # 1. Fetch all live-confirmed signals with valid prices
        rows = conn.execute(
            """SELECT stock_code, stock_name, industry, entry_price,
                      actual_entry_price, actual_return_d21, in_bounds_d21,
                      d21_expectancy
               FROM trade_signals_log
               WHERE is_live = 1
                 AND actual_entry_price IS NOT NULL
                 AND entry_price IS NOT NULL
                 AND entry_price > 0"""
        ).fetchall()

        # 2. Compute per-trade slippage in bps
        trades = []
        for r in rows:
            slip = (r["actual_entry_price"] - r["entry_price"]) / r["entry_price"]
            bps = slip * 10000
            trades.append({
                "stock_code": r["stock_code"],
                "industry": r["industry"] or "Unknown",
                "slippage_bps": bps,
                "actual_return_d21": r["actual_return_d21"],
            })

        total = len(trades)
        if total == 0:
            return {
                "total_live_trades": 0,
                "avg_slippage_bps": 0,
                "friction_drag_pct": None,
                "industries": [],
                "high_friction_industries": [],
                "virtual_expectancy": None,
            }

        # 3. Global stats
        all_bps = [t["slippage_bps"] for t in trades]
        avg_bps = float(np.mean(all_bps))

        # 4. Virtual Expectancy (from War Room realized signals)
        realized = conn.execute(
            """SELECT actual_return_d21 FROM trade_signals_log
               WHERE status = 'realized' AND actual_return_d21 IS NOT NULL"""
        ).fetchall()
        virtual_exp = None
        friction_drag = None
        if realized:
            returns = [r["actual_return_d21"] for r in realized]
            virtual_exp = float(np.mean(returns)) * 100  # as percentage
            if virtual_exp != 0:
                # Friction Drag = (avg_slippage × 2) / virtual_expectancy
                # ×2 because slippage occurs on both entry and exit
                avg_slip_pct = avg_bps / 100  # bps → percentage points
                friction_drag = round(abs(avg_slip_pct * 2 / virtual_exp) * 100, 2)

        # 5. Per-industry breakdown
        from collections import defaultdict
        industry_map: dict[str, list[float]] = defaultdict(list)
        for t in trades:
            industry_map[t["industry"]].append(t["slippage_bps"])

        industries = []
        high_friction = []
        for ind, bps_list in sorted(industry_map.items()):
            count = len(bps_list)
            arr = np.array(bps_list)
            median = float(np.median(arr))
            p95 = float(np.percentile(arr, 95))
            avg = float(np.mean(arr))

            if count < MIN_SAMPLES:
                status = "INSUFFICIENT_DATA"
            elif median >= SLIPPAGE_HIGH_MEDIAN_BPS or p95 >= SLIPPAGE_HIGH_P95_BPS:
                status = "HIGH"
                high_friction.append(ind)
            else:
                status = "LOW"

            industries.append({
                "industry": ind,
                "count": count,
                "median_bps": round(median, 1),
                "p95_bps": round(p95, 1),
                "avg_bps": round(avg, 1),
                "status": status,
            })

        # Sort: HIGH first, then by median desc
        status_order = {"HIGH": 0, "INSUFFICIENT_DATA": 1, "LOW": 2}
        industries.sort(key=lambda x: (status_order.get(x["status"], 9), -x["median_bps"]))

        return {
            "total_live_trades": total,
            "avg_slippage_bps": round(avg_bps, 1),
            "friction_drag_pct": friction_drag,
            "industries": industries,
            "high_friction_industries": high_friction,
            "virtual_expectancy": round(virtual_exp, 2) if virtual_exp is not None else None,
        }
    finally:
        conn.close()

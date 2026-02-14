"""SQS Signal Performance Tracker (Gemini R45-2)

Records SQS signal triggers and tracks forward returns to validate SQS effectiveness.

Features:
- Record each SQS BUY signal trigger (code, date, SQS, grade)
- Compute forward returns at d1/d3/d5/d10/d20 as prices become available
- Group analysis by SQS grade, threshold, time period
- Cumulative performance curve
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.scoring import TRANSACTION_COST

logger = logging.getLogger(__name__)

TRACKER_PATH = Path(__file__).resolve().parent.parent / "data" / "sqs_signal_tracker.json"
FORWARD_PERIODS = [1, 3, 5, 10, 20]


def _load_tracker() -> list[dict]:
    if TRACKER_PATH.exists():
        try:
            return json.loads(TRACKER_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_tracker(records: list[dict]):
    TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRACKER_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def record_signals(signals: list[dict]):
    """Record new SQS signal triggers.

    Args:
        signals: List of dicts with code, name, sqs, grade, maturity, confidence.
                 Typically from the alert system's triggered list.
    """
    existing = _load_tracker()
    today = datetime.now().strftime("%Y-%m-%d")

    # Build dedup set: (code, date)
    existing_keys = {(r["code"], r["trigger_date"]) for r in existing}

    new_count = 0
    for sig in signals:
        key = (sig["code"], today)
        if key in existing_keys:
            continue
        existing.append({
            "code": sig["code"],
            "name": sig.get("name", ""),
            "trigger_date": today,
            "sqs": sig["sqs"],
            "grade": sig["grade"],
            "grade_label": sig.get("grade_label", ""),
            "maturity": sig.get("maturity", ""),
            "confidence": sig.get("confidence", 0),
            "signal_price": None,
            "returns": {},  # {d1: x, d3: x, ...}
            "updated_at": None,
        })
        existing_keys.add(key)
        new_count += 1

    if new_count > 0:
        _save_tracker(existing)
        logger.info(f"Recorded {new_count} new SQS signals")

    return new_count


def update_forward_returns(max_records: int = 100):
    """Update forward returns for signals that need price data.

    Looks up actual prices after d1/d3/d5/d10/d20 trading days and computes returns.
    Only updates records that are missing return data and have enough history.
    """
    from data.fetcher import get_stock_data

    records = _load_tracker()
    today = datetime.now()
    updated = 0

    for rec in records:
        if _all_returns_filled(rec):
            continue
        if updated >= max_records:
            break

        trigger_date = rec["trigger_date"]
        code = rec["code"]

        try:
            # Fetch enough data to cover d20 forward
            df = get_stock_data(code, period_days=60)
            if df is None or len(df) < 5:
                continue

            # Find trigger date in data
            trigger_dt = pd.Timestamp(trigger_date)
            if trigger_dt not in df.index:
                # Find nearest trading day
                mask = df.index >= trigger_dt
                if not mask.any():
                    continue
                trigger_idx = df.index[mask][0]
                trigger_loc = df.index.get_loc(trigger_idx)
            else:
                trigger_loc = df.index.get_loc(trigger_dt)

            signal_price = float(df["close"].iloc[trigger_loc])
            rec["signal_price"] = round(signal_price, 2)

            # Compute forward returns for each period
            for d in FORWARD_PERIODS:
                key = f"d{d}"
                if key in rec["returns"]:
                    continue
                target_loc = trigger_loc + d
                if target_loc >= len(df):
                    # Not enough data yet — check if enough calendar days passed
                    days_since = (today - datetime.strptime(trigger_date, "%Y-%m-%d")).days
                    if days_since < d * 1.5:  # Allow for weekends/holidays
                        continue
                    # Enough time passed but data not available — skip
                    continue

                fwd_price = float(df["close"].iloc[target_loc])
                ret = (fwd_price - signal_price) / signal_price
                rec["returns"][key] = round(ret, 5)

            rec["updated_at"] = today.isoformat()
            updated += 1

        except Exception as e:
            logger.debug(f"Failed to update returns for {code}: {e}")

    if updated > 0:
        _save_tracker(records)
        logger.info(f"Updated forward returns for {updated} signals")

    return updated


def _all_returns_filled(rec: dict) -> bool:
    """Check if all forward return periods are filled."""
    returns = rec.get("returns", {})
    return all(f"d{d}" in returns for d in FORWARD_PERIODS)


def get_performance_summary(
    date_from: str | None = None,
    date_to: str | None = None,
    min_sqs: float | None = None,
) -> dict:
    """Compute performance summary for tracked SQS signals.

    Args:
        date_from: Start date filter (inclusive)
        date_to: End date filter (inclusive)
        min_sqs: Minimum SQS score filter

    Returns:
        dict with overall metrics, grade breakdown, period returns, etc.
    """
    records = _load_tracker()
    if not records:
        return {"total": 0, "message": "No tracked signals"}

    # Apply filters
    filtered = records
    if date_from:
        filtered = [r for r in filtered if r["trigger_date"] >= date_from]
    if date_to:
        filtered = [r for r in filtered if r["trigger_date"] <= date_to]
    if min_sqs is not None:
        filtered = [r for r in filtered if r["sqs"] >= min_sqs]

    if not filtered:
        return {"total": 0, "message": "No signals match filters"}

    # Overall metrics
    overall = _compute_period_metrics(filtered)

    # By grade
    grade_breakdown = {}
    for grade in ["diamond", "gold", "silver", "noise"]:
        grade_sigs = [r for r in filtered if r["grade"] == grade]
        if grade_sigs:
            grade_breakdown[grade] = _compute_period_metrics(grade_sigs)

    # By SQS bucket (10-point ranges)
    sqs_buckets = {}
    for bucket_start in range(0, 100, 10):
        bucket_end = bucket_start + 10
        bucket_sigs = [
            r for r in filtered
            if bucket_start <= r["sqs"] < bucket_end
        ]
        if bucket_sigs:
            sqs_buckets[f"{bucket_start}-{bucket_end}"] = _compute_period_metrics(bucket_sigs)

    # Cumulative returns (chronological, using d5)
    cumulative = _compute_cumulative_curve(filtered, period="d5")

    # SQS score distribution
    sqs_scores = [r["sqs"] for r in filtered]

    return {
        "total": len(filtered),
        "date_range": {
            "start": min(r["trigger_date"] for r in filtered),
            "end": max(r["trigger_date"] for r in filtered),
        },
        "sqs_stats": {
            "mean": round(float(np.mean(sqs_scores)), 1),
            "median": round(float(np.median(sqs_scores)), 1),
            "min": round(min(sqs_scores), 1),
            "max": round(max(sqs_scores), 1),
        },
        "overall": overall,
        "by_grade": grade_breakdown,
        "by_sqs_bucket": sqs_buckets,
        "cumulative_d5": cumulative,
        "transaction_cost": TRANSACTION_COST,
    }


def _compute_period_metrics(records: list[dict]) -> dict:
    """Compute win rate and avg return for each holding period."""
    result = {"count": len(records)}
    for d in FORWARD_PERIODS:
        key = f"d{d}"
        returns = [r["returns"][key] for r in records if key in r.get("returns", {})]
        if not returns:
            result[key] = {"count": 0, "win_rate": None, "avg_return": None, "net_return": None}
            continue

        wins = [r for r in returns if r > 0]
        avg_ret = float(np.mean(returns))
        result[key] = {
            "count": len(returns),
            "win_rate": round(len(wins) / len(returns), 3),
            "avg_return": round(avg_ret, 4),
            "net_return": round(avg_ret - TRANSACTION_COST, 4),
            "median_return": round(float(np.median(returns)), 4),
            "max_return": round(max(returns), 4),
            "min_return": round(min(returns), 4),
        }
    return result


def _compute_cumulative_curve(records: list[dict], period: str = "d5") -> list[dict]:
    """Compute cumulative return curve for signals sorted by trigger date."""
    sorted_recs = sorted(records, key=lambda r: r["trigger_date"])
    curve = []
    cum_return = 0.0

    for rec in sorted_recs:
        ret = rec.get("returns", {}).get(period)
        if ret is None:
            continue
        net_ret = ret - TRANSACTION_COST
        cum_return += net_ret
        curve.append({
            "date": rec["trigger_date"],
            "code": rec["code"],
            "sqs": rec["sqs"],
            "grade": rec["grade"],
            "period_return": round(ret, 4),
            "net_return": round(net_ret, 4),
            "cumulative": round(cum_return, 4),
        })

    return curve


def get_tracked_signals(
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Get raw tracked signal records for display."""
    records = _load_tracker()
    records.sort(key=lambda r: r["trigger_date"], reverse=True)
    total = len(records)
    page = records[offset:offset + limit]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "signals": page,
    }

"""Backend Alert Scheduler (Gemini R45-1)

APScheduler-based background job that periodically checks SQS alerts,
records triggered alerts with dedup, and pushes notifications (LINE Notify).

Replaces the frontend 5-min polling with a reliable backend mechanism.
"""

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Persistent storage paths
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ALERT_CONFIG_PATH = DATA_DIR / "alert_config.json"
ALERT_HISTORY_PATH = DATA_DIR / "alert_history.json"
DEDUP_PATH = DATA_DIR / "alert_dedup.json"

# Scheduler state (thread-safe access)
_lock = threading.Lock()
_scheduler = None
_last_check: dict = {
    "timestamp": None,
    "triggered_count": 0,
    "triggered": [],
    "error": None,
}


def _load_json(path: Path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default if default is not None else {}


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_dedup() -> dict:
    """Load dedup state: {stock_code: last_notified_iso_str}"""
    return _load_json(DEDUP_PATH, {})


def _save_dedup(dedup: dict):
    _save_json(DEDUP_PATH, dedup)


def _should_notify(code: str, dedup: dict, cooldown_hours: int = 4) -> bool:
    """Check if we should send notification for this stock (dedup)."""
    last = dedup.get(code)
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        return datetime.now() - last_dt > timedelta(hours=cooldown_hours)
    except Exception:
        return True


def _send_line_notify(token: str, message: str):
    """Send LINE Notify message."""
    import urllib.request
    import urllib.parse

    url = "https://notify-api.line.me/api/notify"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = urllib.parse.urlencode({"message": message}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=10)


def run_alert_check():
    """Core alert check job — called by scheduler every N minutes.

    1. Load config (threshold, watch list, notification prefs)
    2. Scan Alpha Hunter BUY signals, compute SQS
    3. Filter by threshold
    4. Dedup: only notify new/cooldown-expired stocks
    5. Push to LINE Notify if enabled
    6. Store results for frontend polling
    """
    global _last_check

    now = datetime.now()
    config_data = _load_json(ALERT_CONFIG_PATH, {
        "sqs_threshold": 70,
        "notify_browser": True,
        "notify_line": False,
        "line_token": "",
        "watch_codes": [],
    })

    threshold = config_data.get("sqs_threshold", 70)
    watch_codes = set(config_data.get("watch_codes", []))
    triggered = []
    error_msg = None

    try:
        from data.cache import get_cached_alpha_hunter
        alpha = get_cached_alpha_hunter()
        if not alpha or not alpha.get("sectors"):
            with _lock:
                _last_check = {
                    "timestamp": now.isoformat(),
                    "triggered_count": 0,
                    "triggered": [],
                    "error": None,
                }
            return

        # Collect all BUY stocks
        all_stocks = []
        for sector in alpha["sectors"]:
            for stock in sector.get("stocks", []):
                all_stocks.append(stock)

        # Filter by watch list if specified
        if watch_codes:
            all_stocks = [s for s in all_stocks if s["code"] in watch_codes]

        # Compute SQS for each
        from analysis.scoring import compute_sqs_for_signal
        for stock in all_stocks:
            try:
                sqs = compute_sqs_for_signal(
                    stock["code"],
                    signal_strategy="V4",
                    signal_maturity=stock.get("maturity", "N/A"),
                )
                if sqs["sqs"] >= threshold:
                    triggered.append({
                        "code": stock["code"],
                        "name": stock.get("name", ""),
                        "sqs": sqs["sqs"],
                        "grade": sqs["grade"],
                        "grade_label": sqs["grade_label"],
                        "maturity": stock.get("maturity", ""),
                        "confidence": stock.get("confidence", 0),
                    })
            except Exception:
                pass

        triggered.sort(key=lambda x: x["sqs"], reverse=True)

        # ---- R45-2: Record signals for performance tracking ----
        if triggered:
            try:
                from backtest.sqs_performance import record_signals
                record_signals(triggered)
            except Exception as e:
                logger.debug(f"Signal recording failed: {e}")

        # ---- Dedup + Notification ----
        if triggered:
            dedup = _load_dedup()
            new_alerts = [t for t in triggered if _should_notify(t["code"], dedup)]

            # Record history
            history = _load_json(ALERT_HISTORY_PATH, [])
            history.append({
                "timestamp": now.isoformat(),
                "count": len(triggered),
                "new_count": len(new_alerts),
                "top_stocks": [t["code"] for t in triggered[:5]],
                "threshold": threshold,
                "source": "scheduler",
            })
            _save_json(ALERT_HISTORY_PATH, history[-200:])

            # Push LINE notification for new alerts only
            if new_alerts and config_data.get("notify_line") and config_data.get("line_token"):
                try:
                    lines = [f"\n📊 SQS Alert (≥{threshold})"]
                    lines.append(f"⏰ {now.strftime('%Y-%m-%d %H:%M')}")
                    lines.append(f"共 {len(new_alerts)} 檔新觸發:\n")
                    for t in new_alerts[:10]:
                        icon = "💎" if t["grade"] == "diamond" else "🥇" if t["grade"] == "gold" else "🥈"
                        lines.append(f"{icon} {t['code']} {t['name']} — SQS {t['sqs']} ({t['maturity']})")
                    _send_line_notify(config_data["line_token"], "\n".join(lines))
                    logger.info(f"LINE notify sent for {len(new_alerts)} new alerts")
                except Exception as e:
                    logger.warning(f"LINE notify failed: {e}")

            # Update dedup
            for t in new_alerts:
                dedup[t["code"]] = now.isoformat()
            _save_dedup(dedup)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Alert check failed: {e}", exc_info=True)

    with _lock:
        _last_check = {
            "timestamp": now.isoformat(),
            "triggered_count": len(triggered),
            "triggered": triggered,
            "error": error_msg,
        }


def get_last_check() -> dict:
    """Get the result of the last scheduled alert check (thread-safe)."""
    with _lock:
        return dict(_last_check)


def get_scheduler_status() -> dict:
    """Get scheduler running status."""
    global _scheduler
    running = _scheduler is not None and _scheduler.running
    next_run = None
    if running:
        try:
            jobs = _scheduler.get_jobs()
            if jobs:
                next_run = str(jobs[0].next_run_time)
        except Exception:
            pass

    return {
        "running": running,
        "next_run": next_run,
        "last_check": get_last_check(),
    }


def start_scheduler(interval_minutes: int = 5):
    """Start the APScheduler background scheduler."""
    global _scheduler

    if _scheduler is not None:
        logger.info("Scheduler already started, skipping")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        logger.warning("APScheduler not installed. Run: pip install apscheduler")
        return

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        run_alert_check,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="sqs_alert_check",
        name="SQS Alert Check",
        replace_existing=True,
        max_instances=1,
    )
    # R45-2: Daily job to update forward returns for tracked signals
    _scheduler.add_job(
        _update_tracked_returns,
        trigger=IntervalTrigger(hours=6),
        id="sqs_return_update",
        name="SQS Forward Return Update",
        replace_existing=True,
        max_instances=1,
    )

    _scheduler.start()
    logger.info(f"Alert scheduler started (interval={interval_minutes}min)")

    # Run initial check immediately
    try:
        run_alert_check()
    except Exception as e:
        logger.warning(f"Initial alert check failed: {e}")


def _update_tracked_returns():
    """Scheduled job: update forward returns for tracked SQS signals."""
    try:
        from backtest.sqs_performance import update_forward_returns
        count = update_forward_returns(max_records=50)
        if count > 0:
            logger.info(f"Updated forward returns for {count} tracked signals")
    except Exception as e:
        logger.warning(f"Forward return update failed: {e}")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Alert scheduler stopped")

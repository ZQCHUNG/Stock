"""Backend Alert Scheduler (Gemini R45-1, R46-3 catch-up)

APScheduler-based background job that periodically checks SQS alerts,
records triggered alerts with dedup, and pushes notifications (LINE Notify).

R46-3: Startup catch-up logic — detects missed checks during downtime
and immediately runs a catch-up if needed. Health-check endpoint support.
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
HEARTBEAT_PATH = DATA_DIR / "scheduler_heartbeat.json"

# Scheduler state (thread-safe access)
_lock = threading.Lock()
_scheduler = None
_start_time: str | None = None
_total_checks: int = 0
_total_errors: int = 0
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
        global _total_checks, _total_errors
        _total_checks += 1
        if error_msg:
            _total_errors += 1
        _last_check = {
            "timestamp": now.isoformat(),
            "triggered_count": len(triggered),
            "triggered": triggered,
            "error": error_msg,
        }

    # R46-3: Persist heartbeat for catch-up detection
    _save_heartbeat(now)


def _save_heartbeat(ts: datetime):
    """Persist last successful check timestamp for catch-up detection."""
    try:
        _save_json(HEARTBEAT_PATH, {"last_check": ts.isoformat()})
    except Exception:
        pass


def _load_heartbeat() -> datetime | None:
    """Load last heartbeat timestamp."""
    data = _load_json(HEARTBEAT_PATH, {})
    ts = data.get("last_check")
    if ts:
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            pass
    return None


def _needs_catchup(interval_minutes: int) -> bool:
    """Check if scheduler missed checks during downtime.

    Returns True if last heartbeat is older than 2x the interval,
    indicating the server was down and we need an immediate catch-up.
    """
    last = _load_heartbeat()
    if last is None:
        return True  # First run ever — run immediately
    gap = datetime.now() - last
    return gap > timedelta(minutes=interval_minutes * 2)


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


def get_health() -> dict:
    """R46-3: Health check — comprehensive scheduler diagnostics."""
    global _scheduler, _start_time, _total_checks, _total_errors
    running = _scheduler is not None and _scheduler.running
    last_heartbeat = _load_heartbeat()
    now = datetime.now()

    # Check staleness: if last heartbeat > 15min ago, something is wrong
    stale = False
    if last_heartbeat and running:
        stale = (now - last_heartbeat) > timedelta(minutes=15)

    uptime_seconds = None
    if _start_time:
        try:
            uptime_seconds = (now - datetime.fromisoformat(_start_time)).total_seconds()
        except Exception:
            pass

    return {
        "status": "degraded" if stale else ("healthy" if running else "stopped"),
        "running": running,
        "uptime_seconds": uptime_seconds,
        "start_time": _start_time,
        "total_checks": _total_checks,
        "total_errors": _total_errors,
        "last_heartbeat": last_heartbeat.isoformat() if last_heartbeat else None,
        "stale": stale,
        "last_check": get_last_check(),
    }


def start_scheduler(interval_minutes: int = 5):
    """Start the APScheduler background scheduler.

    R46-3: Includes catch-up logic — if the server was down and missed
    scheduled checks, runs an immediate catch-up on startup.
    """
    global _scheduler, _start_time

    if _scheduler is not None:
        logger.info("Scheduler already started, skipping")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        logger.warning("APScheduler not installed. Run: pip install apscheduler")
        return

    _start_time = datetime.now().isoformat()

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
    # R47-3: Daily backup job
    _scheduler.add_job(
        _run_daily_backup,
        trigger=IntervalTrigger(hours=24),
        id="daily_backup",
        name="Daily Data Backup",
        replace_existing=True,
        max_instances=1,
    )
    # R49-2: Daily data quality check (every 12 hours)
    _scheduler.add_job(
        _run_data_quality_check,
        trigger=IntervalTrigger(hours=12),
        id="data_quality_check",
        name="Data Quality Check",
        replace_existing=True,
        max_instances=1,
    )
    # R49-2: System health check (every 30 minutes)
    _scheduler.add_job(
        _run_system_health_check,
        trigger=IntervalTrigger(minutes=30),
        id="system_health_check",
        name="System Health Check",
        replace_existing=True,
        max_instances=1,
    )
    # R50-2: OMS position monitor (every 5 minutes)
    _scheduler.add_job(
        _run_oms_check,
        trigger=IntervalTrigger(minutes=5),
        id="oms_position_check",
        name="OMS Position Monitor",
        replace_existing=True,
        max_instances=1,
    )

    _scheduler.start()
    logger.info(f"Alert scheduler started (interval={interval_minutes}min)")

    # R46-3: Catch-up logic — detect missed checks during downtime
    needs_catchup = _needs_catchup(interval_minutes)
    if needs_catchup:
        last_hb = _load_heartbeat()
        gap_info = f"last heartbeat: {last_hb.isoformat() if last_hb else 'never'}"
        logger.info(f"Catch-up needed ({gap_info}) — running immediate check + return update")

    # Always run initial check on startup
    try:
        run_alert_check()
    except Exception as e:
        logger.warning(f"Initial alert check failed: {e}")

    # If catch-up needed, also update forward returns immediately
    if needs_catchup:
        try:
            _update_tracked_returns()
            logger.info("Catch-up: forward return update completed")
        except Exception as e:
            logger.warning(f"Catch-up return update failed: {e}")


def _update_tracked_returns():
    """Scheduled job: update forward returns for tracked SQS signals."""
    try:
        from backtest.sqs_performance import update_forward_returns
        count = update_forward_returns(max_records=50)
        if count > 0:
            logger.info(f"Updated forward returns for {count} tracked signals")
    except Exception as e:
        logger.warning(f"Forward return update failed: {e}")


def _run_daily_backup():
    """R47-3: Scheduled job — daily backup of critical data files."""
    try:
        from backend.backup import run_backup
        result = run_backup()
        backed = len(result.get("backed_up", []))
        removed = result.get("removed_old", 0)
        logger.info(f"Daily backup completed: {backed} files backed up, {removed} old files removed")
    except Exception as e:
        logger.warning(f"Daily backup failed: {e}")


def _run_data_quality_check():
    """R49-2: Scheduled job — check data quality for watchlist + positions."""
    try:
        from concurrent.futures import ThreadPoolExecutor
        from backend import db
        from backend.data_quality import check_batch_data_quality
        from data.fetcher import get_stock_data

        codes = set()
        try:
            from backend.routers.watchlist import _load_watchlist
            codes.update(_load_watchlist()[:20])
        except Exception:
            pass
        try:
            positions = db.get_open_positions()
            codes.update(p["code"] for p in positions)
        except Exception:
            pass

        if not codes:
            return

        stock_data = {}
        import pandas as pd
        def _fetch(code):
            try:
                return code, get_stock_data(code, period_days=60)
            except Exception:
                return code, None

        with ThreadPoolExecutor(max_workers=6) as ex:
            for code, df in ex.map(_fetch, list(codes)[:20]):
                stock_data[code] = df if df is not None else pd.DataFrame()

        result = check_batch_data_quality(stock_data)
        error_count = result.get("error_count", 0)
        overall_score = result.get("overall_score", 1.0)

        # Notify if quality is poor
        if error_count > 0 or overall_score < 0.9:
            _notify_data_quality_issue(result)

        logger.info(f"Data quality check: {result['total_stocks']} stocks, "
                     f"score={overall_score:.0%}, errors={error_count}")
    except Exception as e:
        logger.warning(f"Data quality check failed: {e}")


def _run_system_health_check():
    """R49-2: Scheduled job — check system health and notify on degradation."""
    try:
        from backend.health import get_system_health
        health = get_system_health(include_slow=False)

        degraded = []
        for name, component in health.get("components", {}).items():
            if isinstance(component, dict) and component.get("status") not in ("healthy", None):
                degraded.append(f"{name}: {component.get('status', 'unknown')}")

        if degraded:
            _notify_system_health_issue(health["status"], degraded)
            logger.warning(f"System health degraded: {', '.join(degraded)}")
        else:
            logger.debug("System health check: all healthy")
    except Exception as e:
        logger.warning(f"System health check failed: {e}")


def _notify_data_quality_issue(result: dict):
    """Send LINE + log notification for data quality issues."""
    config_data = _load_json(ALERT_CONFIG_PATH, {})
    if not config_data.get("notify_line") or not config_data.get("line_token"):
        return

    now = datetime.now()
    lines = [
        f"\n📊 數據品質警報",
        f"⏰ {now.strftime('%Y-%m-%d %H:%M')}",
        f"完整度: {result.get('overall_score', 0):.0%}",
        f"異常: {result.get('error_count', 0)} / 警告: {result.get('warning_count', 0)}",
    ]
    for issue in result.get("critical_issues", [])[:5]:
        lines.append(f"❌ {issue['code']}: {issue['detail']}")

    try:
        _send_line_notify(config_data["line_token"], "\n".join(lines))
    except Exception as e:
        logger.warning(f"Data quality LINE notify failed: {e}")


def _notify_system_health_issue(status: str, degraded: list):
    """Send LINE notification for system health issues."""
    config_data = _load_json(ALERT_CONFIG_PATH, {})
    if not config_data.get("notify_line") or not config_data.get("line_token"):
        return

    now = datetime.now()
    lines = [
        f"\n⚠️ 系統健康警報",
        f"⏰ {now.strftime('%Y-%m-%d %H:%M')}",
        f"狀態: {status}",
    ]
    for d in degraded[:5]:
        lines.append(f"❌ {d}")

    try:
        _send_line_notify(config_data["line_token"], "\n".join(lines))
    except Exception as e:
        logger.warning(f"System health LINE notify failed: {e}")


def _run_oms_check():
    """R50-2: Scheduled job — OMS auto-exit check for open positions."""
    try:
        from backend.order_manager import check_positions_and_execute
        result = check_positions_and_execute()
        actions = result.get("actions", [])
        if actions:
            logger.info(f"OMS check: {len(actions)} auto-exits executed")
            # Notify via LINE for auto-exits
            _notify_oms_exits(actions)
        else:
            logger.debug(f"OMS check: {result['checked']} positions checked, no exits")
    except Exception as e:
        logger.warning(f"OMS check failed: {e}")


def _notify_oms_exits(actions: list[dict]):
    """Send LINE notification for OMS auto-exits."""
    config_data = _load_json(ALERT_CONFIG_PATH, {})
    if not config_data.get("notify_line") or not config_data.get("line_token"):
        return

    now = datetime.now()
    lines = [
        f"\n📋 OMS 自動出場通知",
        f"⏰ {now.strftime('%Y-%m-%d %H:%M')}",
        f"共 {len(actions)} 筆自動執行:\n",
    ]
    for a in actions[:10]:
        icon = "🔴" if a.get("net_pnl", 0) < 0 else "🟢"
        reason_label = {
            "stop_loss": "停損",
            "trailing_stop": "移動停利",
            "take_profit": "停利",
        }.get(a.get("exit_reason", ""), a.get("exit_reason", ""))
        lines.append(
            f"{icon} {a['code']} {a.get('name', '')} — {reason_label} "
            f"@ ${a['exit_price']:.2f} (P&L ${a.get('net_pnl', 0):,.0f})"
        )

    try:
        _send_line_notify(config_data["line_token"], "\n".join(lines))
    except Exception as e:
        logger.warning(f"OMS LINE notify failed: {e}")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Alert scheduler stopped")

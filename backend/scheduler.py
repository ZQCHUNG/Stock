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


def _send_telegram_message(bot_token: str, chat_id: str, message: str):
    """R56: Send Telegram Bot message."""
    import urllib.request
    import urllib.parse
    import json as _json

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = _json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=10)


def _send_notification(message: str, config_data: dict | None = None):
    """R56: Unified notification — send to all enabled channels (LINE + Telegram)."""
    if config_data is None:
        config_data = _load_json(ALERT_CONFIG_PATH, {})

    # LINE Notify
    if config_data.get("notify_line") and config_data.get("line_token"):
        try:
            _send_line_notify(config_data["line_token"], message)
        except Exception as e:
            logger.warning(f"LINE notify failed: {e}")

    # Telegram Bot
    if config_data.get("notify_telegram") and config_data.get("telegram_bot_token") and config_data.get("telegram_chat_id"):
        try:
            _send_telegram_message(
                config_data["telegram_bot_token"],
                config_data["telegram_chat_id"],
                message,
            )
        except Exception as e:
            logger.warning(f"Telegram notify failed: {e}")


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
        from data.cache import get_cached_sector_heat
        alpha = get_cached_sector_heat()
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
            for stock in sector.get("buy_stocks", []):
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

            # R56: Unified notification for new alerts
            if new_alerts:
                lines = [f"\n📊 SQS Alert (≥{threshold})"]
                lines.append(f"⏰ {now.strftime('%Y-%m-%d %H:%M')}")
                lines.append(f"共 {len(new_alerts)} 檔新觸發:\n")
                for t in new_alerts[:10]:
                    icon = "💎" if t["grade"] == "diamond" else "🥇" if t["grade"] == "gold" else "🥈"
                    lines.append(f"{icon} {t['code']} {t['name']} — SQS {t['sqs']} ({t['maturity']})")
                _send_notification("\n".join(lines), config_data)
                logger.info(f"Notification sent for {len(new_alerts)} new alerts")

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
        from apscheduler.triggers.cron import CronTrigger
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
    # R56: Compound alert rules check (every 5 minutes, aligned with SQS)
    _scheduler.add_job(
        _run_compound_alert_check,
        trigger=IntervalTrigger(minutes=5),
        id="compound_alert_check",
        name="Compound Alert Check",
        replace_existing=True,
        max_instances=1,
    )
    # R64: Daily TWSE/TPEX data sync (every 4 hours during trading hours)
    _scheduler.add_job(
        _run_twse_daily_sync,
        trigger=IntervalTrigger(hours=4),
        id="twse_daily_sync",
        name="TWSE/TPEX Daily Sync",
        replace_existing=True,
        max_instances=1,
    )
    # R88.7: Daily broker fetch at 18:30 (Mon-Fri)
    # [CONVERGED — Wall Street Trader 2026-02-18: "18:30 比 17:30 安全"]
    _scheduler.add_job(
        _run_daily_broker_fetch,
        trigger=CronTrigger(hour=18, minute=30, day_of_week="mon-fri"),
        id="daily_broker_fetch",
        name="Daily Broker Fetch (R88.7)",
        replace_existing=True,
        max_instances=1,
    )
    # R88.7 Phase 12: Google News RSS fetch at 18:45 (Mon-Fri)
    # [CONVERGED — Wall Street Trader 2026-02-19]
    # After broker fetch (18:30) and before parquet rebuild (19:00)
    _scheduler.add_job(
        _run_google_news_fetch,
        trigger=CronTrigger(hour=18, minute=45, day_of_week="mon-fri"),
        id="google_news_fetch",
        name="Google News RSS Fetch (R88.7 P12)",
        replace_existing=True,
        max_instances=1,
    )
    # R88.7: Parquet rebuild at 20:00 (Mon-Fri, after news fetch completes)
    # [CONVERGED — Wall Street Trader 2026-02-19]: "19:00 太緊，15分鐘緩衝極度危險"
    # News fetch ~25 min (18:45→19:10), rebuild needs clean data
    _scheduler.add_job(
        _run_parquet_rebuild,
        trigger=CronTrigger(hour=20, minute=0, day_of_week="mon-fri"),
        id="parquet_rebuild",
        name="Parquet Feature Rebuild (R88.7)",
        replace_existing=True,
        max_instances=1,
    )
    # Phase 3: Daily Pattern Update at 20:15 (Mon-Fri, after parquet rebuild)
    # Extends close matrix + recomputes RS + refreshes screener DB
    _scheduler.add_job(
        _run_daily_pattern_update,
        trigger=CronTrigger(hour=20, minute=15, day_of_week="mon-fri"),
        id="daily_pattern_update",
        name="Daily Pattern Update (Phase 3)",
        replace_existing=True,
        max_instances=1,
    )
    # R88.7: Weekly Winner Registry recalculation (Saturday 02:00)
    # [CONVERGED — Wall Street Trader 2026-02-18]
    # "每週末自動重算一次 Winner Registry，讓 Tier 2 有機會向上流動"
    _scheduler.add_job(
        _run_winner_registry_rebuild,
        trigger=CronTrigger(hour=2, minute=0, day_of_week="sat"),
        id="winner_registry_rebuild",
        name="Winner Registry Rebuild (R88.7)",
        replace_existing=True,
        max_instances=1,
    )

    # Phase 4: Weekly Parameter Scan (Sunday 22:00)
    # CTO directive: "每週末跑一次，監控策略是否因市場環境改變而產生參數漂移"
    _scheduler.add_job(
        _run_weekly_parameter_scan,
        trigger=CronTrigger(hour=22, minute=0, day_of_week="sun"),
        id="weekly_parameter_scan",
        name="Weekly Parameter Scan (Phase 4)",
        replace_existing=True,
        max_instances=1,
    )

    # Phase 14 Task 3: Monthly Parameter Recommendations
    # CTO: "系統應該能告訴 Joe 哪些參數可能需要調整"
    _scheduler.add_job(
        _run_monthly_param_recommendations,
        trigger=CronTrigger(hour=10, minute=0, day=1),  # 1st of each month
        id="monthly_param_recommendations",
        name="Monthly Parameter Recommendations (Phase 14)",
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
    """R56: Send unified notification for data quality issues."""
    now = datetime.now()
    lines = [
        f"\n📊 數據品質警報",
        f"⏰ {now.strftime('%Y-%m-%d %H:%M')}",
        f"完整度: {result.get('overall_score', 0):.0%}",
        f"異常: {result.get('error_count', 0)} / 警告: {result.get('warning_count', 0)}",
    ]
    for issue in result.get("critical_issues", [])[:5]:
        lines.append(f"❌ {issue['code']}: {issue['detail']}")
    _send_notification("\n".join(lines))


def _notify_system_health_issue(status: str, degraded: list):
    """R56: Send unified notification for system health issues."""
    now = datetime.now()
    lines = [
        f"\n⚠️ 系統健康警報",
        f"⏰ {now.strftime('%Y-%m-%d %H:%M')}",
        f"狀態: {status}",
    ]
    for d in degraded[:5]:
        lines.append(f"❌ {d}")
    _send_notification("\n".join(lines))


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


def _run_compound_alert_check():
    """R56: Scheduled job — check compound alert rules alongside SQS alerts."""
    try:
        from backend.compound_alerts import (
            load_rules, evaluate_rule, check_cooldown,
            get_stock_indicator_data, save_rules,
        )
        import time as _time

        rules = load_rules()
        active_rules = [r for r in rules if r.enabled]
        if not active_rules:
            return

        config_data = _load_json(ALERT_CONFIG_PATH, {})
        triggered_all = []
        updated = False

        for rule in active_rules:
            if not check_cooldown(rule):
                continue

            check_codes = rule.codes
            if not check_codes:
                try:
                    from config import SCAN_STOCKS
                    check_codes = SCAN_STOCKS[:20]
                except Exception:
                    check_codes = []

            for code in check_codes:
                try:
                    stock_data = get_stock_indicator_data(code)
                    if not stock_data:
                        continue
                    if evaluate_rule(rule, stock_data):
                        triggered_all.append({
                            "rule_name": rule.name,
                            "code": code,
                            "combine_mode": rule.combine_mode,
                            "conditions_count": len(rule.conditions),
                        })
                        rule.last_triggered = _time.time()
                        rule.trigger_count += 1
                        updated = True
                except Exception:
                    pass

        if updated:
            save_rules(rules)

        # Notify triggered compound alerts
        if triggered_all:
            now = datetime.now()
            lines = [f"\n🔔 複合條件警報觸發"]
            lines.append(f"⏰ {now.strftime('%Y-%m-%d %H:%M')}")
            lines.append(f"共 {len(triggered_all)} 筆觸發:\n")
            for t in triggered_all[:10]:
                lines.append(f"📌 {t['rule_name']}: {t['code']} ({t['combine_mode']}, {t['conditions_count']} conditions)")
            _send_notification("\n".join(lines), config_data)
            logger.info(f"Compound alert: {len(triggered_all)} triggered")

    except Exception as e:
        logger.warning(f"Compound alert check failed: {e}")


def _notify_oms_exits(actions: list[dict]):
    """R56: Send unified notification for OMS auto-exits."""
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
    _send_notification("\n".join(lines))


def _run_twse_daily_sync():
    """R64: Scheduled job — sync today's TWSE/TPEX data for watchlist + positions.

    Runs every 4 hours. After market close (13:30 TW), this picks up
    the final closing prices. Also syncs TAIEX index.
    """
    try:
        from data.twse_provider import sync_stock, sync_taiex

        codes = set()
        # Watchlist stocks
        try:
            from backend.routers.watchlist import _load_watchlist
            codes.update(_load_watchlist()[:50])
        except Exception:
            pass
        # Open positions
        try:
            from backend import db
            positions = db.get_open_positions()
            codes.update(p["code"] for p in positions)
        except Exception:
            pass
        # Recent stocks
        try:
            from backend.routers.system import _load_recent
            codes.update(_load_recent()[:10])
        except Exception:
            pass

        if not codes:
            logger.debug("TWSE sync: no stocks to sync")
            return

        synced = 0
        for code in codes:
            try:
                count = sync_stock(code, months_back=1)
                if count > 0:
                    synced += 1
            except Exception as e:
                logger.debug(f"TWSE sync failed for {code}: {e}")

        # Also sync TAIEX
        try:
            sync_taiex(months_back=1)
        except Exception:
            pass

        logger.info(f"TWSE daily sync: {synced}/{len(codes)} stocks updated")
    except Exception as e:
        logger.warning(f"TWSE daily sync failed: {e}")


def _run_winner_registry_rebuild():
    """R88.7: Scheduled job — rebuild Winner Registry weekly (Saturday 02:00).

    [CONVERGED — Wall Street Trader 2026-02-18]
    "每週末自動重算一次 Winner Registry，讓 Tier 2 有機會向上流動。
    保持 CI >= 1.0 的門檻，嚴禁為了好看而降低門檻。"
    """
    try:
        from analysis.winner_registry import build_registry

        logger.info("Winner Registry rebuild: starting ...")
        result = build_registry()

        tier1 = sum(1 for v in result.values() if isinstance(v, dict) and v.get("tier") == 1)
        tier2 = sum(1 for v in result.values() if isinstance(v, dict) and v.get("tier") == 2)
        total = tier1 + tier2

        logger.info(
            f"Winner Registry rebuild: {total} winners "
            f"(Tier 1: {tier1}, Tier 2: {tier2})"
        )

        # Notify on Tier 1 changes
        _send_notification(
            f"\n🏆 Winner Registry 週更完成\n"
            f"Tier 1 (Sniper Ready): {tier1}\n"
            f"Tier 2 (Observer): {tier2}\n"
            f"總計: {total}"
        )
    except Exception as e:
        logger.error(f"Winner Registry rebuild failed: {e}", exc_info=True)


def _run_daily_broker_fetch():
    """R88.7: Scheduled job — fetch daily broker data at 18:30.

    [CONVERGED — Wall Street Trader 2026-02-18]
    Run after market data settles (18:30 > 17:30 to avoid stale data).
    """
    try:
        from data.fetch_broker_daily import run_daily_fetch
        from datetime import datetime

        today = datetime.now()
        if today.weekday() >= 5:
            logger.debug("Daily broker fetch: weekend, skipping")
            return

        date_str = today.strftime("%Y%m%d")
        summary = run_daily_fetch(date_str=date_str, workers=10)

        ok = summary.get("ok", 0)
        quality = summary.get("quality", "unknown")
        elapsed = summary.get("elapsed_seconds", 0)
        logger.info(
            f"Daily broker fetch: {ok} stocks OK, quality={quality}, {elapsed:.1f}s"
        )

        # Canary failed — exchange data not ready
        if quality == "canary_failed":
            _send_notification(
                f"\n🐤 分點日頻 Canary Check 失敗\n"
                f"日期: {date_str}\n"
                f"{summary.get('canary_message', '')}\n"
                f"交易所尚未更新，本次抓取已跳過"
            )
        # Notify if quality is poor
        elif quality == "data_insufficient":
            _send_notification(
                f"\n⚠️ 分點日頻資料品質不足\n"
                f"日期: {date_str}\n"
                f"成功: {ok} / {summary.get('stocks_total', 0)}\n"
                f"失敗率: {summary.get('fail_rate', 0):.1%}"
            )
    except Exception as e:
        logger.error(f"Daily broker fetch failed: {e}", exc_info=True)


def _run_google_news_fetch():
    """R88.7 Phase 12: Scheduled job — fetch Google News RSS at 18:45.

    [CONVERGED — Wall Street Trader 2026-02-19]
    Tiered coverage: Top 500 market cap stocks only.
    Runs in ~25 min (500 stocks × 3.5s avg delay).
    """
    try:
        from data.fetch_google_news import run_fetch
        from datetime import datetime

        today = datetime.now()
        if today.weekday() >= 5:
            logger.debug("Google News fetch: weekend, skipping")
            return

        logger.info("Google News RSS fetch: starting Top 500 ...")
        run_fetch(full=False)
        logger.info("Google News RSS fetch: completed")
    except Exception as e:
        logger.error(f"Google News RSS fetch failed: {e}", exc_info=True)


def _run_parquet_rebuild():
    """R88.7: Scheduled job — rebuild Parquet features at 19:00.

    [CONVERGED — Wall Street Trader 2026-02-18]
    Runs after daily broker fetch completes (18:30 → 19:00).
    """
    try:
        import subprocess
        import sys
        from datetime import datetime

        today = datetime.now()
        if today.weekday() >= 5:
            logger.debug("Parquet rebuild: weekend, skipping")
            return

        logger.info("Parquet rebuild: starting build_features.py ...")
        result = subprocess.run(
            [sys.executable, "-m", "data.build_features"],
            capture_output=True,
            text=True,
            timeout=1800,  # 30 minutes max
            cwd=str(DATA_DIR.parent),
        )

        if result.returncode == 0:
            # Extract timing info from stdout if available
            elapsed_info = ""
            for line in result.stdout.splitlines()[-5:]:
                if "Done" in line or "elapsed" in line.lower() or "Step" in line:
                    elapsed_info += line + "\n"
            logger.info(f"Parquet rebuild: completed successfully\n{elapsed_info}")
        else:
            # [CONVERGED — Trader 2026-02-18]: Include full traceback in notification
            logger.error(f"Parquet rebuild failed: {result.stderr[-500:]}")
            _send_notification(
                f"\n⚠️ Parquet 重建失敗\n"
                f"Exit code: {result.returncode}\n"
                f"Traceback:\n{result.stderr[-500:]}"
            )
    except subprocess.TimeoutExpired:
        logger.error("Parquet rebuild: timed out (30 minutes)")
        _send_notification(
            "\n⚠️ Parquet 重建超時\n"
            "build_features.py 執行超過 30 分鐘，已被終止"
        )
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Parquet rebuild failed: {e}", exc_info=True)
        _send_notification(
            f"\n⚠️ Parquet 重建異常\n"
            f"Error: {str(e)}\n"
            f"Traceback:\n{tb[-500:]}"
        )


def _run_daily_pattern_update():
    """Phase 3: Daily pattern update — close matrix + RS + screener refresh.

    Runs at 20:15 Mon-Fri, after the 20:00 Parquet feature rebuild.
    Extends pit_close_matrix with latest trading day(s),
    recomputes PIT RS matrices, and refreshes the screener snapshot.
    """
    try:
        from datetime import datetime

        today = datetime.now()
        if today.weekday() >= 5:
            logger.debug("Daily pattern update: weekend, skipping")
            return

        from data.daily_update import run_daily_update

        logger.info("Daily pattern update: starting ...")
        result = run_daily_update()

        # Check for errors
        errors = [k for k, v in result.items() if isinstance(v, dict) and "error" in v]
        total_s = result.get("total_elapsed_s", 0)

        if errors:
            _send_notification(
                f"\n⚠️ Daily Pattern Update 部分失敗\n"
                f"失敗步驟: {', '.join(errors)}\n"
                f"總耗時: {total_s:.1f}s"
            )
            logger.warning("Daily pattern update: %d errors: %s", len(errors), errors)
        else:
            cm = result.get("close_matrix", {})
            rs = result.get("rs_matrices", {})
            sc = result.get("screener", {})
            logger.info(
                "Daily pattern update: completed in %.1fs "
                "(close +%d dates, RS %d×%d, screener %d stocks)",
                total_s,
                cm.get("new_dates", 0),
                rs.get("rs_dates", 0),
                rs.get("rs_stocks", 0),
                sc.get("stocks_updated", 0),
            )
    except Exception as e:
        logger.error("Daily pattern update failed: %s", e, exc_info=True)


def _run_weekly_parameter_scan():
    """Phase 4: Weekly parameter scan — detect parameter drift.

    Runs Sunday 22:00. Executes P2-A heatmap with default preset,
    saves results, and alerts if Plateau ratio drops >15% vs last week.
    CTO directive: "每週末跑一次即可，監控策略是否因市場環境改變而產生參數漂移"
    """
    import json as _json
    from pathlib import Path

    scan_history_path = Path(__file__).resolve().parent.parent / "data" / "parameter_scan_history.json"

    try:
        from backtest.parameter_heatmap import run_heatmap, DEFAULT_PRESETS
        from data.fetcher import get_stock_data
        from config import SCAN_STOCKS
        import random

        logger.info("Weekly parameter scan: starting ...")

        # Sample 20 stocks
        codes = list(SCAN_STOCKS.keys())
        sample = random.sample(codes, min(20, len(codes)))

        # Use first preset (threshold vs lookback)
        preset = DEFAULT_PRESETS["entry_d_threshold_vs_lookback"]

        # Fetch stock data
        stock_data = {}
        for code in sample:
            try:
                df = get_stock_data(code, period_days=1095)
                if df is not None and len(df) >= 200:
                    stock_data[code] = df
            except Exception:
                pass

        if len(stock_data) < 5:
            logger.warning("Weekly parameter scan: insufficient stock data (%d)", len(stock_data))
            return

        result = run_heatmap(
            stock_data=stock_data,
            x_param=preset["x_param"],
            x_values=preset["x_values"],
            y_param=preset["y_param"],
            y_values=preset["y_values"],
            metric="sharpe_ratio",
        )

        # Count zones
        zones = result.get("zones", {})
        total_cells = len(result.get("x_values", [])) * len(result.get("y_values", []))
        plateau_count = sum(1 for v in zones.values() if v == "plateau")
        plateau_ratio = plateau_count / total_cells if total_cells > 0 else 0

        # Load previous scan
        prev_ratio = None
        if scan_history_path.exists():
            try:
                prev = _json.loads(scan_history_path.read_text(encoding="utf-8"))
                prev_ratio = prev.get("plateau_ratio")
            except Exception:
                pass

        # Save current scan
        scan_record = {
            "scan_date": datetime.now().isoformat(),
            "plateau_ratio": round(plateau_ratio, 4),
            "plateau_count": plateau_count,
            "total_cells": total_cells,
            "stocks_used": len(stock_data),
        }
        scan_history_path.parent.mkdir(parents=True, exist_ok=True)
        scan_history_path.write_text(
            _json.dumps(scan_record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Alert if plateau dropped >15%
        if prev_ratio is not None and prev_ratio > 0:
            drop = prev_ratio - plateau_ratio
            if drop > 0.15:
                _send_notification(
                    f"\n⚠️ Parameter Drift Alert\n"
                    f"Plateau Ratio: {plateau_ratio:.0%} (was {prev_ratio:.0%})\n"
                    f"Drop: {drop:.0%} > 15% threshold\n"
                    f"Entry D parameters may be losing robustness"
                )
                logger.warning("Parameter drift alert: plateau %.0f%% → %.0f%%",
                               prev_ratio * 100, plateau_ratio * 100)

        logger.info("Weekly parameter scan: plateau %.0f%% (%d/%d cells), %d stocks",
                     plateau_ratio * 100, plateau_count, total_cells, len(stock_data))

    except Exception as e:
        logger.error("Weekly parameter scan failed: %s", e, exc_info=True)


def _run_monthly_param_recommendations():
    """Phase 14 Task 3: Monthly parameter recommendations.

    Runs 1st of each month at 10:00. Generates recommendations and
    sends a LINE notification if there are warning/critical items.
    Architect APPROVED: Read-only, no auto-modify.
    """
    try:
        from analysis.param_recommender import generate_recommendations

        result = generate_recommendations(days_back=90)
        recs = result.get("recommendations", [])

        if not recs:
            logger.info("Monthly param recommendations: no suggestions")
            return

        # Send notification for warnings/criticals
        warnings = [r for r in recs if r["severity"] in ("warning", "critical")]
        if warnings:
            lines = [
                "\nParameter Recommendations",
                f"Trades: {result.get('trade_count', 0)} | WR: {result.get('win_rate', 0):.0%}",
                "",
            ]
            for r in warnings:
                icon = "!!!" if r["severity"] == "critical" else "!"
                lines.append(f"{icon} [{r['category']}] {r['title']}")
                lines.append(f"  {r['suggestion']}")
            _send_notification("\n".join(lines))

        logger.info(
            "Monthly param recommendations: %d total, %d warnings",
            len(recs), len(warnings),
        )
    except Exception as e:
        logger.error("Monthly param recommendations failed: %s", e, exc_info=True)


def stop_scheduler():
    """Stop the scheduler gracefully."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Alert scheduler stopped")

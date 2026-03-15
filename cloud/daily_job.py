"""Daily Stock Data Update Job for Cloud Run.

Runs the complete daily pipeline as a Cloud Run Job:
  1. Check if today is a trading day (skip weekends)
  2. Run daily_update.py (close matrix, RS, screener, forward returns, signals)
  3. Run build_features.py (65 features, price cache, forward returns)
  4. Upload results to GCS bucket
  5. Send completion notification via Telegram Bot (3 alert levels)

Designed to be idempotent — safe to re-run on the same day.
Each step catches its own errors so later steps still execute.

Alert levels:
  SUCCESS  — Job completed normally
  WARNING  — Job completed but with issues (partial failures, slow build, stock drop)
  ABORT    — Critical failure, pipeline stopped

Environment variables:
  GCS_BUCKET       — GCS bucket name for result uploads (required)
  TG_BOT_TOKEN     — Telegram Bot API token for notifications (optional)
  TG_CHAT_ID       — Telegram chat ID for notifications (required if TG_BOT_TOKEN set)
  SKIP_FEATURES    — set to "1" to skip build_features (saves ~30 min)
  DRY_RUN          — set to "1" to skip GCS upload (local test mode)
"""

import json
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cloud.daily_job")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Config from environment
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
SKIP_FEATURES = os.environ.get("SKIP_FEATURES", "0") == "1"
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

# [PLACEHOLDER: BUILD_TIME_WARNING_THRESHOLD_001] 30 min = 1800s
BUILD_TIME_WARNING_S = 1800

# [PLACEHOLDER: STOCK_COUNT_DROP_THRESHOLD_001] 10% drop triggers warning
STOCK_COUNT_DROP_PCT = 0.10

# Files to upload to GCS after pipeline completes
UPLOAD_ARTIFACTS = [
    "data/pit_close_matrix.parquet",
    "data/pit_rs_matrix.parquet",
    "data/pit_rs_percentile.parquet",
    "data/pattern_data/features/features_all.parquet",
    "data/pattern_data/features/forward_returns.parquet",
    "data/pattern_data/features/price_cache.parquet",
    "data/pattern_data/features/feature_metadata.json",
    "data/screener.db",
]

# Alert level constants
ALERT_SUCCESS = "SUCCESS"
ALERT_WARNING = "WARNING"
ALERT_ABORT = "ABORT"


# ---------------------------------------------------------------------------
# Trading Day Check
# ---------------------------------------------------------------------------
def is_trading_day(target_date: date = None) -> bool:
    """Check if the given date is a Taiwan stock trading day.

    Currently checks weekday only (Mon-Fri = trading day).
    Holidays can be added later via a holiday calendar.

    Args:
        target_date: Date to check. Defaults to today.

    Returns:
        True if the date is a trading day (weekday), False otherwise.
    """
    if target_date is None:
        target_date = date.today()
    # Monday=0 ... Friday=4 are weekdays; Saturday=5, Sunday=6 are weekends
    return target_date.weekday() < 5


# ---------------------------------------------------------------------------
# Data Freshness Check
# ---------------------------------------------------------------------------
def check_data_freshness(today_override: date = None) -> date:
    """Verify close matrix has recent data. Abort if stale.

    On a trading day, gap > 1 calendar day triggers abort (data should be
    from today or yesterday at most). Weekends are handled by the
    is_trading_day() gate in main() — this function is only called on
    trading days.

    Args:
        today_override: Override today's date (for testing). Defaults to date.today().

    Returns:
        The latest date found in the close matrix.

    Raises:
        RuntimeError: If data is stale (gap > 1 calendar day on a trading day).
        FileNotFoundError: If close matrix file is missing.
    """
    import pandas as pd

    close_path = PROJECT_ROOT / "data" / "pit_close_matrix.parquet"
    if not close_path.exists():
        raise FileNotFoundError(f"Close matrix not found: {close_path}")

    close = pd.read_parquet(close_path)
    latest_date = close.index[-1].date() if hasattr(close.index[-1], 'date') else close.index[-1]
    today = today_override or date.today()

    gap = (today - latest_date).days
    logger.info("Data freshness: latest=%s, today=%s, gap=%d days", latest_date, today, gap)

    if gap > 1:
        raise RuntimeError(
            f"Data is stale! Latest: {latest_date}, Today: {today}, Gap: {gap} days. "
            f"Aborting to prevent running with outdated data."
        )

    return latest_date


# ---------------------------------------------------------------------------
# Step 1: Daily Update (close matrix + RS + screener + forward returns)
# ---------------------------------------------------------------------------
def step_daily_update() -> dict:
    """Run the 9-step daily update pipeline."""
    logger.info("=" * 50)
    logger.info("Step 1: Daily Update Pipeline")
    logger.info("=" * 50)

    try:
        from data.daily_update import run_daily_update
        result = run_daily_update()
        logger.info(
            "Daily update complete in %.1fs",
            result.get("total_elapsed_s", 0),
        )
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.error("Daily update FAILED: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Step 2: Build Features (65 features, price cache, forward returns)
# ---------------------------------------------------------------------------
def step_build_features() -> dict:
    """Run the feature engineering pipeline (~30 min)."""
    logger.info("=" * 50)
    logger.info("Step 2: Build Features")
    logger.info("=" * 50)

    if SKIP_FEATURES:
        logger.info("SKIP_FEATURES=1 — skipping feature build")
        return {"status": "skipped"}

    try:
        from data.build_features import main as build_main
        t0 = time.time()
        build_main()
        elapsed = time.time() - t0
        logger.info("Feature build complete in %.1fs", elapsed)
        return {"status": "ok", "elapsed_s": round(elapsed, 1)}
    except Exception as e:
        logger.error("Feature build FAILED: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Step 3: Upload to GCS
# ---------------------------------------------------------------------------
def step_upload_gcs() -> dict:
    """Upload pipeline artifacts to GCS bucket."""
    logger.info("=" * 50)
    logger.info("Step 3: Upload to GCS")
    logger.info("=" * 50)

    if DRY_RUN:
        logger.info("DRY_RUN=1 — skipping GCS upload")
        return {"status": "dry_run"}

    if not GCS_BUCKET:
        logger.warning("GCS_BUCKET not set — skipping upload")
        return {"status": "skipped", "reason": "no_bucket"}

    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)

        today = datetime.now().strftime("%Y-%m-%d")
        uploaded = []
        failed = []

        for rel_path in UPLOAD_ARTIFACTS:
            local_path = PROJECT_ROOT / rel_path
            if not local_path.exists():
                logger.warning("Artifact not found: %s", rel_path)
                failed.append(rel_path)
                continue

            # Upload to: daily/<date>/<filename> and latest/<filename>
            filename = local_path.name
            for gcs_prefix in [f"daily/{today}", "latest"]:
                blob_name = f"{gcs_prefix}/{filename}"
                blob = bucket.blob(blob_name)
                blob.upload_from_filename(str(local_path))
                logger.info("Uploaded: gs://%s/%s", GCS_BUCKET, blob_name)

            uploaded.append(rel_path)

        return {
            "status": "ok",
            "uploaded": len(uploaded),
            "failed": len(failed),
            "failed_files": failed,
        }
    except Exception as e:
        logger.error("GCS upload FAILED: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Alert Level Determination
# ---------------------------------------------------------------------------
def determine_alert_level(results: dict) -> tuple:
    """Determine alert level and collect warning/error messages.

    Args:
        results: Pipeline results dict.

    Returns:
        Tuple of (alert_level, list_of_issues).
        alert_level is one of ALERT_SUCCESS, ALERT_WARNING, ALERT_ABORT.
    """
    issues = []

    daily = results.get("daily_update", {})
    features = results.get("build_features", {})
    gcs = results.get("gcs_upload", {})
    freshness = results.get("data_freshness", {})

    # ABORT conditions: critical step failed entirely
    if daily.get("status") == "error":
        return ALERT_ABORT, [f"Daily update failed: {daily.get('error', '?')[:120]}"]
    if freshness.get("status") == "error":
        return ALERT_ABORT, [f"Data freshness failed: {freshness.get('error', '?')[:120]}"]
    if features.get("status") == "error":
        return ALERT_ABORT, [f"Feature build failed: {features.get('error', '?')[:120]}"]

    # WARNING conditions
    # 1. Some stocks failed to fetch
    daily_result = daily.get("result", {})
    failed_stocks = daily_result.get("failed_stocks", 0)
    if failed_stocks > 0:
        issues.append(f"{failed_stocks} stocks failed to fetch")

    # 2. Build time > 30 min
    total_elapsed = results.get("total_elapsed_s", 0)
    if total_elapsed > BUILD_TIME_WARNING_S:
        issues.append(f"Build time {total_elapsed/60:.1f} min > {BUILD_TIME_WARNING_S/60:.0f} min threshold")

    # 3. Stock count dropped > 10% from yesterday
    stock_count = daily_result.get("stock_count", 0)
    prev_stock_count = daily_result.get("prev_stock_count", 0)
    if prev_stock_count > 0 and stock_count > 0:
        drop_pct = (prev_stock_count - stock_count) / prev_stock_count
        if drop_pct > STOCK_COUNT_DROP_PCT:
            issues.append(
                f"Stock count dropped {drop_pct:.1%}: {prev_stock_count} -> {stock_count}"
            )

    # 4. GCS upload had partial failures
    if gcs.get("status") == "error":
        issues.append(f"GCS upload failed: {gcs.get('error', '?')[:80]}")
    elif gcs.get("failed", 0) > 0:
        issues.append(f"GCS: {gcs['failed']} artifacts missing")

    if issues:
        return ALERT_WARNING, issues

    return ALERT_SUCCESS, []


# ---------------------------------------------------------------------------
# Telegram Bot Helper
# ---------------------------------------------------------------------------
def send_telegram(message: str, token: str, chat_id: str) -> bool:
    """Send a message via Telegram Bot API.

    Args:
        message: Text to send (Markdown supported).
        token: Telegram Bot API token.
        chat_id: Target chat ID.

    Returns:
        True if the message was sent successfully, False otherwise.
    """
    import requests

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }
    resp = requests.post(url, json=payload, timeout=10)
    return resp.ok


# ---------------------------------------------------------------------------
# Step 4: Send Notification (3 alert levels)
# ---------------------------------------------------------------------------
def step_notify(results: dict) -> dict:
    """Send Telegram notification with pipeline summary. Always sends.

    Alert levels:
        SUCCESS — brief confirmation with stock count and duration
        WARNING — completed with issues listed
        ABORT   — critical failure with reason
    """
    logger.info("=" * 50)
    logger.info("Step 4: Notification")
    logger.info("=" * 50)

    alert_level, issues = determine_alert_level(results)
    results["alert_level"] = alert_level
    results["alert_issues"] = issues

    logger.info("Alert level: %s, issues: %s", alert_level, issues)

    if not TG_BOT_TOKEN:
        logger.info("TG_BOT_TOKEN not set — skipping notification")
        return {"status": "skipped", "alert_level": alert_level}

    if not TG_CHAT_ID:
        logger.warning("TG_CHAT_ID not set — cannot send Telegram notification")
        return {"status": "skipped", "reason": "no_chat_id", "alert_level": alert_level}

    try:
        total_elapsed = results.get("total_elapsed_s", 0)
        daily_result = results.get("daily_update", {}).get("result", {})
        stock_count = daily_result.get("stock_count", 0)

        # Emoji prefix per alert level
        level_icon = {
            ALERT_SUCCESS: "OK",
            ALERT_WARNING: "WARNING",
            ALERT_ABORT: "ABORT",
        }
        prefix = level_icon.get(alert_level, "INFO")

        # Build message based on alert level
        if alert_level == ALERT_SUCCESS:
            stock_str = f"{stock_count:,}" if stock_count else "?"
            elapsed_min = total_elapsed / 60
            message = f"*[{prefix}]* Daily update OK\n{stock_str} stocks, {elapsed_min:.1f} min"

        elif alert_level == ALERT_WARNING:
            issue_list = "\n".join(f"  - {i}" for i in issues)
            message = f"*[{prefix}]* Daily update completed with warnings:\n{issue_list}"

        else:  # ALERT_ABORT
            reason = issues[0] if issues else "Unknown error"
            message = f"*[{prefix}]* Daily update ABORTED\n{reason}"

        ok = send_telegram(message, TG_BOT_TOKEN, TG_CHAT_ID)
        logger.info("Telegram notify sent (level=%s, ok=%s)", alert_level, ok)
        return {"status": "ok" if ok else "error", "alert_level": alert_level}
    except Exception as e:
        logger.error("Notification FAILED: %s", e)
        return {"status": "error", "error": str(e), "alert_level": alert_level}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    """Entry point for Cloud Run Job."""
    logger.info("=" * 60)
    logger.info("Cloud Run Daily Job — START")
    logger.info("  Date: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("  GCS_BUCKET: %s", GCS_BUCKET or "(not set)")
    logger.info("  TG_BOT_TOKEN: %s", "set" if TG_BOT_TOKEN else "(not set)")
    logger.info("  TG_CHAT_ID: %s", TG_CHAT_ID or "(not set)")
    logger.info("  SKIP_FEATURES: %s", SKIP_FEATURES)
    logger.info("  DRY_RUN: %s", DRY_RUN)
    logger.info("=" * 60)

    # Weekend gate: skip entirely on non-trading days
    if not is_trading_day():
        weekday_name = date.today().strftime("%A")
        logger.info("Today is %s — not a trading day. Skipping job.", weekday_name)
        sys.exit(0)

    t0 = time.time()
    results = {}

    # Step 1: Daily update
    results["daily_update"] = step_daily_update()

    # Freshness gate: abort early if data is stale (silent errors are worse)
    if results["daily_update"].get("status") == "ok":
        try:
            latest = check_data_freshness()
            results["data_freshness"] = {"status": "ok", "latest_date": str(latest)}
            logger.info("Data freshness check PASSED: latest=%s", latest)
        except (RuntimeError, FileNotFoundError) as e:
            results["data_freshness"] = {"status": "error", "error": str(e)}
            logger.error("Data freshness check FAILED: %s", e)
            # Abort — don't continue with stale data
            total_elapsed = time.time() - t0
            results["total_elapsed_s"] = round(total_elapsed, 1)
            results["timestamp"] = datetime.now().isoformat()
            results["notification"] = step_notify(results)
            logger.error("Aborting pipeline due to stale data")
            sys.exit(1)
    else:
        logger.warning("Skipping freshness check — daily update failed")
        results["data_freshness"] = {"status": "skipped", "reason": "daily_update_failed"}

    # Step 2: Build features
    results["build_features"] = step_build_features()

    # Step 3: Upload to GCS
    results["gcs_upload"] = step_upload_gcs()

    total_elapsed = time.time() - t0
    results["total_elapsed_s"] = round(total_elapsed, 1)
    results["timestamp"] = datetime.now().isoformat()

    # Step 4: Notification (always sends)
    results["notification"] = step_notify(results)

    # Summary
    logger.info("=" * 60)
    logger.info("Cloud Run Daily Job — DONE in %.1fs", total_elapsed)
    logger.info("Results: %s", json.dumps(results, default=str, indent=2))
    logger.info("=" * 60)

    # Exit with error code if critical steps failed
    alert_level = results.get("alert_level", ALERT_SUCCESS)
    if alert_level == ALERT_ABORT:
        logger.error("Critical failure — exiting with code 1")
        sys.exit(1)


if __name__ == "__main__":
    main()

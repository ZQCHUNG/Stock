"""Daily Stock Data Update Job for Cloud Run.

Runs the complete daily pipeline as a Cloud Run Job:
  1. Run daily_update.py (close matrix, RS, screener, forward returns, signals)
  2. Run build_features.py (65 features, price cache, forward returns)
  3. Upload results to GCS bucket
  4. Send completion notification via LINE

Designed to be idempotent — safe to re-run on the same day.
Each step catches its own errors so later steps still execute.

Environment variables:
  GCS_BUCKET       — GCS bucket name for result uploads (required)
  LINE_TOKEN       — LINE Notify token for notifications (optional)
  SKIP_FEATURES    — set to "1" to skip build_features (saves ~30 min)
  DRY_RUN          — set to "1" to skip GCS upload (local test mode)
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
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
LINE_TOKEN = os.environ.get("LINE_TOKEN", "")
SKIP_FEATURES = os.environ.get("SKIP_FEATURES", "0") == "1"
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

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
# Step 4: Send Notification
# ---------------------------------------------------------------------------
def step_notify(results: dict) -> dict:
    """Send LINE Notify with pipeline summary."""
    logger.info("=" * 50)
    logger.info("Step 4: Notification")
    logger.info("=" * 50)

    if not LINE_TOKEN:
        logger.info("LINE_TOKEN not set — skipping notification")
        return {"status": "skipped"}

    try:
        import requests

        today = datetime.now().strftime("%Y-%m-%d")
        total_elapsed = results.get("total_elapsed_s", 0)

        # Build summary
        daily = results.get("daily_update", {})
        features = results.get("build_features", {})
        gcs = results.get("gcs_upload", {})

        errors = []
        if daily.get("status") == "error":
            errors.append(f"DailyUpdate: {daily.get('error', '?')[:80]}")
        if features.get("status") == "error":
            errors.append(f"Features: {features.get('error', '?')[:80]}")
        if gcs.get("status") == "error":
            errors.append(f"GCS: {gcs.get('error', '?')[:80]}")

        status_icon = "RED" if errors else "GREEN"

        lines = [
            f"[Cloud Run] {today} Daily Job {status_icon}",
            f"Total: {total_elapsed:.0f}s",
            f"DailyUpdate: {daily.get('status', '?')}",
            f"Features: {features.get('status', '?')}",
            f"GCS: {gcs.get('status', '?')} ({gcs.get('uploaded', 0)} files)",
        ]
        if errors:
            lines.append("Errors:")
            lines.extend(f"  - {e}" for e in errors)

        message = "\n".join(lines)

        resp = requests.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {LINE_TOKEN}"},
            data={"message": f"\n{message}"},
            timeout=10,
        )
        logger.info("LINE notify sent (status=%d)", resp.status_code)
        return {"status": "ok", "http_status": resp.status_code}
    except Exception as e:
        logger.error("Notification FAILED: %s", e)
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    """Entry point for Cloud Run Job."""
    logger.info("=" * 60)
    logger.info("Cloud Run Daily Job — START")
    logger.info("  Date: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("  GCS_BUCKET: %s", GCS_BUCKET or "(not set)")
    logger.info("  SKIP_FEATURES: %s", SKIP_FEATURES)
    logger.info("  DRY_RUN: %s", DRY_RUN)
    logger.info("=" * 60)

    t0 = time.time()
    results = {}

    # Step 1: Daily update
    results["daily_update"] = step_daily_update()

    # Step 2: Build features
    results["build_features"] = step_build_features()

    # Step 3: Upload to GCS
    results["gcs_upload"] = step_upload_gcs()

    total_elapsed = time.time() - t0
    results["total_elapsed_s"] = round(total_elapsed, 1)
    results["timestamp"] = datetime.now().isoformat()

    # Step 4: Notification
    results["notification"] = step_notify(results)

    # Summary
    logger.info("=" * 60)
    logger.info("Cloud Run Daily Job — DONE in %.1fs", total_elapsed)
    logger.info("Results: %s", json.dumps(results, default=str, indent=2))
    logger.info("=" * 60)

    # Exit with error code if critical steps failed
    critical_failed = (
        results["daily_update"].get("status") == "error"
        or results["build_features"].get("status") == "error"
    )
    if critical_failed:
        logger.error("One or more critical steps failed — exiting with code 1")
        sys.exit(1)


if __name__ == "__main__":
    main()

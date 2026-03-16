#!/bin/bash
# Deploy Cloud Run Job + Cloud Scheduler for daily stock data updates
# Usage: bash cloud/deploy.sh [create|update|run|delete]
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - APIs enabled: Cloud Run, Cloud Build, Cloud Scheduler, Artifact Registry
#   - GCS bucket created: gs://ooooorz-stock-data
#
# Estimated cost: ~NT$50-100/month (Cloud Run Job ~44min/day, 4Gi RAM, 2 vCPU)
#
# Notification setup:
#   Telegram Bot is used for pipeline notifications (3 alert levels).
#   Set the following env vars before deploying:
#     TG_BOT_TOKEN  — Telegram Bot API token (get from @BotFather)
#     TG_CHAT_ID    — Target chat ID (send /start to your bot, then call getUpdates)
#
#   To find your chat ID:
#     curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
#     Look for "chat":{"id": <NUMBER>} in the response.
#
#   These are passed as env vars to Cloud Run Job (not hardcoded).

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT="ooooorz"
REGION="asia-east1"                    # Taiwan region (lowest latency)
JOB_NAME="stock-daily-update"
GCS_BUCKET="ooooorz-stock-data"
IMAGE="gcr.io/${PROJECT}/${JOB_NAME}"
SA_EMAIL="${PROJECT}@appspot.gserviceaccount.com"

# Telegram notification (read from environment, not hardcoded)
TG_BOT_TOKEN="${TG_BOT_TOKEN:-}"
TG_CHAT_ID="${TG_CHAT_ID:-}"

# Job resources — tuned for 1096 stocks, 65 features
MEMORY="4Gi"
CPU="2"
TASK_TIMEOUT="3600"   # 60 min max (daily_update ~14min + features ~30min)
MAX_RETRIES="2"

# Scheduler: weekdays 19:00 Taiwan time (after market close + data settlement)
SCHEDULE="0 19 * * 1-5"
TIMEZONE="Asia/Taipei"

# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------
enable_apis() {
    echo "[1/5] Enabling required APIs..."
    gcloud services enable \
        run.googleapis.com \
        cloudbuild.googleapis.com \
        cloudscheduler.googleapis.com \
        storage.googleapis.com \
        --project="${PROJECT}" --quiet
}

create_bucket() {
    echo "[2/5] Creating GCS bucket (if not exists)..."
    if ! gsutil ls -b "gs://${GCS_BUCKET}" &>/dev/null; then
        gsutil mb -p "${PROJECT}" -l "${REGION}" "gs://${GCS_BUCKET}"
        # Lifecycle: delete daily snapshots older than 30 days
        cat > /tmp/lifecycle.json << 'LIFECYCLE'
{
  "rule": [
    {
      "action": {"type": "Delete"},
      "condition": {
        "age": 30,
        "matchesPrefix": ["daily/"]
      }
    }
  ]
}
LIFECYCLE
        gsutil lifecycle set /tmp/lifecycle.json "gs://${GCS_BUCKET}"
        echo "  Bucket created with 30-day lifecycle for daily/ prefix"
    else
        echo "  Bucket already exists"
    fi
}

build_image() {
    echo "[3/5] Building and pushing Docker image..."
    # Build from project root using cloud/cloudbuild.yaml (specifies cloud/Dockerfile)
    gcloud builds submit \
        --config "cloud/cloudbuild.yaml" \
        --project "${PROJECT}" \
        --gcs-log-dir="gs://${GCS_BUCKET}/build-logs" \
        .
}

create_job() {
    echo "[4/5] Creating Cloud Run Job..."

    # Build env vars string — always include GCS_BUCKET, conditionally add TG vars
    ENV_VARS="GCS_BUCKET=${GCS_BUCKET}"
    if [[ -n "${TG_BOT_TOKEN}" ]]; then
        ENV_VARS="${ENV_VARS},TG_BOT_TOKEN=${TG_BOT_TOKEN}"
    else
        echo "  WARNING: TG_BOT_TOKEN not set — Telegram notifications will be disabled"
    fi
    if [[ -n "${TG_CHAT_ID}" ]]; then
        ENV_VARS="${ENV_VARS},TG_CHAT_ID=${TG_CHAT_ID}"
    else
        echo "  WARNING: TG_CHAT_ID not set — Telegram notifications will be disabled"
    fi

    # Check if job already exists
    if gcloud run jobs describe "${JOB_NAME}" --region="${REGION}" --project="${PROJECT}" &>/dev/null; then
        echo "  Job exists — updating..."
        gcloud run jobs update "${JOB_NAME}" \
            --image "${IMAGE}" \
            --region "${REGION}" \
            --task-timeout "${TASK_TIMEOUT}" \
            --max-retries "${MAX_RETRIES}" \
            --memory "${MEMORY}" \
            --cpu "${CPU}" \
            --set-env-vars "${ENV_VARS}" \
            --project "${PROJECT}"
    else
        echo "  Creating new job..."
        gcloud run jobs create "${JOB_NAME}" \
            --image "${IMAGE}" \
            --region "${REGION}" \
            --task-timeout "${TASK_TIMEOUT}" \
            --max-retries "${MAX_RETRIES}" \
            --memory "${MEMORY}" \
            --cpu "${CPU}" \
            --set-env-vars "${ENV_VARS}" \
            --project "${PROJECT}"
    fi
}

create_scheduler() {
    echo "[5/5] Creating Cloud Scheduler trigger..."
    SCHEDULER_NAME="stock-daily-trigger"

    # Delete existing scheduler if present (idempotent)
    gcloud scheduler jobs delete "${SCHEDULER_NAME}" \
        --location="${REGION}" \
        --project="${PROJECT}" --quiet 2>/dev/null || true

    gcloud scheduler jobs create http "${SCHEDULER_NAME}" \
        --schedule="${SCHEDULE}" \
        --time-zone="${TIMEZONE}" \
        --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB_NAME}:run" \
        --http-method=POST \
        --oauth-service-account-email="${SA_EMAIL}" \
        --location="${REGION}" \
        --project="${PROJECT}"

    echo "  Scheduler: ${SCHEDULE} (${TIMEZONE})"
}

run_job() {
    echo "Manually triggering Cloud Run Job..."
    gcloud run jobs execute "${JOB_NAME}" \
        --region="${REGION}" \
        --project="${PROJECT}" \
        --wait
}

delete_all() {
    echo "Deleting all resources..."
    gcloud scheduler jobs delete "stock-daily-trigger" \
        --location="${REGION}" --project="${PROJECT}" --quiet 2>/dev/null || true
    gcloud run jobs delete "${JOB_NAME}" \
        --region="${REGION}" --project="${PROJECT}" --quiet 2>/dev/null || true
    echo "Done. GCS bucket gs://${GCS_BUCKET} preserved (delete manually if needed)."
}

show_logs() {
    echo "Fetching latest job logs..."
    gcloud logging read \
        "resource.type=cloud_run_job AND resource.labels.job_name=${JOB_NAME}" \
        --limit=50 \
        --format="table(timestamp,severity,textPayload)" \
        --project="${PROJECT}"
}

show_status() {
    echo "Job status:"
    gcloud run jobs describe "${JOB_NAME}" \
        --region="${REGION}" \
        --project="${PROJECT}" \
        --format="yaml(status)"
    echo ""
    echo "Scheduler status:"
    gcloud scheduler jobs describe "stock-daily-trigger" \
        --location="${REGION}" \
        --project="${PROJECT}" \
        --format="yaml(state,schedule,timeZone,lastAttemptTime)"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
ACTION="${1:-create}"

case "${ACTION}" in
    create)
        enable_apis
        create_bucket
        build_image
        create_job
        create_scheduler
        echo ""
        echo "=== Deployment Complete ==="
        echo "Job:       ${JOB_NAME}"
        echo "Image:     ${IMAGE}"
        echo "Schedule:  ${SCHEDULE} (${TIMEZONE})"
        echo "Bucket:    gs://${GCS_BUCKET}"
        echo ""
        echo "Test with: bash cloud/deploy.sh run"
        ;;
    update)
        build_image
        create_job
        echo "Job updated."
        ;;
    run)
        run_job
        ;;
    delete)
        delete_all
        ;;
    logs)
        show_logs
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: bash cloud/deploy.sh [create|update|run|delete|logs|status]"
        echo ""
        echo "Commands:"
        echo "  create  — Full setup: APIs + bucket + build + job + scheduler"
        echo "  update  — Rebuild image and update job"
        echo "  run     — Manually trigger the job"
        echo "  delete  — Remove job + scheduler (keeps bucket)"
        echo "  logs    — View recent job logs"
        echo "  status  — Show job and scheduler status"
        exit 1
        ;;
esac

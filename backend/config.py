"""Backend configuration — environment variable management (Gemini R47-1)

All sensitive and environment-specific settings are loaded from environment
variables with sensible defaults for local development.
"""

import os

# Redis
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))

# FastAPI
API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8000"))
API_WORKERS = int(os.environ.get("API_WORKERS", "1"))

# CORS (comma-separated origins)
CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")

# Data paths
DATA_DIR = os.environ.get("DATA_DIR", "")  # Empty = use project default

# LINE Notify (optional — also stored in alert_config.json)
LINE_NOTIFY_TOKEN = os.environ.get("LINE_NOTIFY_TOKEN", "")

# Scheduler
SCHEDULER_INTERVAL_MINUTES = int(os.environ.get("SCHEDULER_INTERVAL", "5"))

# Backup
BACKUP_DIR = os.environ.get("BACKUP_DIR", "")  # Empty = data/backup/
BACKUP_RETENTION_DAYS = int(os.environ.get("BACKUP_RETENTION_DAYS", "7"))

# Log level
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# API Key authentication (R50-1)
# Set API_KEY env var to enable authentication. Empty = no auth (dev mode).
API_KEY = os.environ.get("API_KEY", "")
API_KEY_HEADER = "X-API-Key"

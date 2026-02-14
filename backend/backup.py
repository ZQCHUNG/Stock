"""Data backup module (Gemini R47-3)

Provides:
1. Automatic backup of SQLite DB + critical JSON files
2. Backup rotation (configurable retention days)
3. CSV/JSON export for portfolio positions and SQS signals
"""

import csv
import io
import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_BACKUP_DIR = DATA_DIR / "backup"

# Critical files to back up alongside the SQLite database
CRITICAL_JSON_FILES = [
    "alert_config.json",
    "alert_history.json",
    "sqs_signal_tracker.json",
    "watchlist.json",
    "recent_stocks.json",
    "scheduler_heartbeat.json",
]


def run_backup(backup_dir: Path | None = None, retention_days: int = 7) -> dict:
    """Run a full backup of critical data files.

    Creates timestamped copies of:
    - stock.db (SQLite portfolio database)
    - All critical JSON config/data files

    Returns dict with backup details.
    """
    import os
    retention_days = int(os.environ.get("BACKUP_RETENTION_DAYS", str(retention_days)))

    if backup_dir is None:
        bdir_env = os.environ.get("BACKUP_DIR", "")
        backup_dir = Path(bdir_env) if bdir_env else DEFAULT_BACKUP_DIR

    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    backed_up = []
    errors = []

    # 1. Backup SQLite database
    db_path = DATA_DIR / "stock.db"
    if db_path.exists():
        dest = backup_dir / f"stock_{ts}.db"
        try:
            shutil.copy2(str(db_path), str(dest))
            backed_up.append(f"stock_{ts}.db ({dest.stat().st_size} bytes)")
        except Exception as e:
            errors.append(f"stock.db: {e}")

    # 2. Backup critical JSON files
    for fname in CRITICAL_JSON_FILES:
        src = DATA_DIR / fname
        if src.exists():
            dest = backup_dir / f"{fname.replace('.json', '')}_{ts}.json"
            try:
                shutil.copy2(str(src), str(dest))
                backed_up.append(f"{dest.name}")
            except Exception as e:
                errors.append(f"{fname}: {e}")

    # 3. Rotate old backups
    removed = _rotate_backups(backup_dir, retention_days)

    return {
        "timestamp": ts,
        "backed_up": backed_up,
        "errors": errors,
        "removed_old": removed,
        "backup_dir": str(backup_dir),
    }


def _rotate_backups(backup_dir: Path, retention_days: int) -> int:
    """Remove backup files older than retention_days."""
    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0

    for f in backup_dir.iterdir():
        if f.is_file():
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    f.unlink()
                    removed += 1
            except Exception:
                pass
    return removed


def list_backups(backup_dir: Path | None = None) -> list[dict]:
    """List all existing backup files."""
    import os
    if backup_dir is None:
        bdir_env = os.environ.get("BACKUP_DIR", "")
        backup_dir = Path(bdir_env) if bdir_env else DEFAULT_BACKUP_DIR

    if not backup_dir.exists():
        return []

    backups = []
    for f in sorted(backup_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file():
            stat = f.stat()
            backups.append({
                "name": f.name,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
    return backups


def export_positions_csv() -> str:
    """Export all positions (open + closed) to CSV string."""
    from backend import db
    positions = db.get_open_positions() + db.get_closed_positions(limit=9999)

    output = io.StringIO()
    if not positions:
        return ""

    fields = [
        "code", "name", "status", "entry_date", "entry_price", "lots",
        "stop_loss", "confidence", "sector", "note",
        "exit_date", "exit_price", "exit_reason",
        "pnl", "net_pnl", "return_pct", "commission", "tax", "days_held",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for p in positions:
        writer.writerow(p)

    return output.getvalue()


def export_positions_json() -> list[dict]:
    """Export all positions (open + closed) as JSON-serializable list."""
    from backend import db
    positions = db.get_open_positions() + db.get_closed_positions(limit=9999)
    return positions


def export_signals_csv(source: str | None = None) -> str:
    """Export SQS tracked signals to CSV string."""
    from backtest.sqs_performance import get_tracked_signals
    result = get_tracked_signals(limit=9999, source=source)
    signals = result.get("signals", [])

    output = io.StringIO()
    if not signals:
        return ""

    fields = [
        "trigger_date", "code", "name", "sqs", "grade",
        "source", "r_d1", "r_d3", "r_d5", "r_d10", "r_d20",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for s in signals:
        row = {
            "trigger_date": s.get("trigger_date", ""),
            "code": s.get("code", ""),
            "name": s.get("name", ""),
            "sqs": s.get("sqs", ""),
            "grade": s.get("grade", ""),
            "source": s.get("source", ""),
        }
        returns = s.get("returns", {})
        for period in ["d1", "d3", "d5", "d10", "d20"]:
            row[f"r_{period}"] = returns.get(period, "")
        writer.writerow(row)

    return output.getvalue()

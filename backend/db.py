"""SQLite database layer for portfolio & watchlist (Gemini R27).

Replaces JSON file persistence with SQLite for:
- Better query performance (indexes, aggregation)
- Safer concurrent access (file locking built-in)
- SQL-powered analytics (monthly P&L, streak detection, etc.)

Zero external dependencies — uses Python stdlib sqlite3.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "stock.db"

# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

def _ensure_db():
    """Create DB file and tables if they don't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(_SCHEMA_DDL)
        _maybe_migrate_json(conn)


@contextmanager
def _connect():
    """Context-managed SQLite connection with WAL mode + row factory."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS positions (
    id          TEXT PRIMARY KEY,
    code        TEXT NOT NULL,
    name        TEXT DEFAULT '',
    entry_date  TEXT NOT NULL,
    entry_price REAL NOT NULL,
    lots        INTEGER NOT NULL,
    stop_loss   REAL DEFAULT 0,
    trailing_stop REAL,
    confidence  REAL DEFAULT 0.7,
    sector      TEXT DEFAULT '',
    note        TEXT DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'open',   -- 'open' or 'closed'
    exit_date   TEXT,
    exit_price  REAL,
    exit_reason TEXT,
    pnl         REAL,
    net_pnl     REAL,
    return_pct  REAL,
    commission  REAL,
    tax         REAL,
    days_held   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_code ON positions(code);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    date  TEXT NOT NULL UNIQUE,
    total_equity    REAL NOT NULL,
    position_value  REAL DEFAULT 0,
    realized_pnl    REAL DEFAULT 0,
    position_count  INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_equity_date ON equity_snapshots(date);

CREATE TABLE IF NOT EXISTS watchlist (
    code       TEXT PRIMARY KEY,
    name       TEXT DEFAULT '',
    added_date TEXT DEFAULT (date('now'))
);
"""


# ---------------------------------------------------------------------------
# JSON migration (one-time, idempotent)
# ---------------------------------------------------------------------------

_PORTFOLIO_JSON = DB_PATH.parent / "portfolio.json"
_WATCHLIST_JSON = DB_PATH.parent / "watchlist.json"


def _maybe_migrate_json(conn: sqlite3.Connection):
    """Auto-migrate existing JSON files into SQLite (idempotent)."""
    _migrate_portfolio_json(conn)
    _migrate_watchlist_json(conn)


def _migrate_portfolio_json(conn: sqlite3.Connection):
    """Import portfolio.json if exists and DB positions table is empty."""
    if not _PORTFOLIO_JSON.exists():
        return

    row = conn.execute("SELECT COUNT(*) FROM positions").fetchone()
    if row[0] > 0:
        return  # Already has data

    try:
        data = json.loads(_PORTFOLIO_JSON.read_text(encoding="utf-8"))
    except Exception:
        return

    # Import open positions
    for p in data.get("positions", []):
        conn.execute(
            """INSERT OR IGNORE INTO positions
               (id, code, name, entry_date, entry_price, lots, stop_loss,
                trailing_stop, confidence, sector, note, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
            (
                p.get("id", str(uuid.uuid4())[:8]),
                p["code"], p.get("name", ""), p.get("entry_date", ""),
                p["entry_price"], p["lots"], p.get("stop_loss", 0),
                p.get("trailing_stop"), p.get("confidence", 0.7),
                p.get("sector", ""), p.get("note", ""),
            ),
        )

    # Import closed trades
    for c in data.get("closed", []):
        conn.execute(
            """INSERT OR IGNORE INTO positions
               (id, code, name, entry_date, entry_price, lots, stop_loss,
                trailing_stop, confidence, sector, note, status,
                exit_date, exit_price, exit_reason, pnl, net_pnl,
                return_pct, commission, tax, days_held)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'closed',
                       ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                c.get("id", str(uuid.uuid4())[:8]),
                c["code"], c.get("name", ""), c.get("entry_date", ""),
                c["entry_price"], c["lots"], c.get("stop_loss", 0),
                c.get("trailing_stop"), c.get("confidence", 0.7),
                c.get("sector", ""), c.get("note", ""),
                c.get("exit_date"), c.get("exit_price"),
                c.get("exit_reason"), c.get("pnl"),
                c.get("net_pnl"), c.get("return_pct"),
                c.get("commission"), c.get("tax"),
                c.get("days_held"),
            ),
        )

    # Rename the JSON file to mark migration complete
    backup = _PORTFOLIO_JSON.with_suffix(".json.bak")
    _PORTFOLIO_JSON.rename(backup)


def _migrate_watchlist_json(conn: sqlite3.Connection):
    """Import watchlist.json if exists and DB watchlist table is empty."""
    if not _WATCHLIST_JSON.exists():
        return

    row = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()
    if row[0] > 0:
        return  # Already has data

    try:
        codes = json.loads(_WATCHLIST_JSON.read_text(encoding="utf-8"))
    except Exception:
        return

    if not isinstance(codes, list):
        return

    for code in codes:
        if isinstance(code, str) and code.strip():
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (code) VALUES (?)",
                (code.strip(),),
            )

    # Rename the JSON file
    backup = _WATCHLIST_JSON.with_suffix(".json.bak")
    _WATCHLIST_JSON.rename(backup)


# ---------------------------------------------------------------------------
# Position DAO
# ---------------------------------------------------------------------------

def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def _rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]


def get_open_positions() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM positions WHERE status='open' ORDER BY entry_date DESC"
        ).fetchall()
    return _rows_to_list(rows)


def get_closed_positions(limit: int = 200) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM positions WHERE status='closed' ORDER BY exit_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return _rows_to_list(rows)


def get_position_by_id(position_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM positions WHERE id=?", (position_id,)
        ).fetchone()
    return _row_to_dict(row)


def create_position(data: dict) -> dict:
    pid = data.get("id") or str(uuid.uuid4())[:8]
    entry_date = data.get("entry_date") or datetime.now().strftime("%Y-%m-%d")

    with _connect() as conn:
        # Check duplicate open position for same code
        existing = conn.execute(
            "SELECT id FROM positions WHERE code=? AND status='open'",
            (data["code"],),
        ).fetchone()
        if existing:
            raise ValueError(f"已有 {data['code']} 的未平倉部位，請先平倉")

        conn.execute(
            """INSERT INTO positions
               (id, code, name, entry_date, entry_price, lots, stop_loss,
                trailing_stop, confidence, sector, note, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
            (
                pid, data["code"], data.get("name", ""), entry_date,
                data["entry_price"], data["lots"], data.get("stop_loss", 0),
                data.get("trailing_stop"), data.get("confidence", 0.7),
                data.get("sector", ""), data.get("note", ""),
            ),
        )

    return {
        "id": pid, "code": data["code"], "name": data.get("name", ""),
        "entry_date": entry_date, "entry_price": data["entry_price"],
        "lots": data["lots"], "stop_loss": data.get("stop_loss", 0),
        "trailing_stop": data.get("trailing_stop"),
        "confidence": data.get("confidence", 0.7),
        "sector": data.get("sector", ""), "note": data.get("note", ""),
    }


def close_position(position_id: str, exit_price: float, exit_reason: str = "manual") -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM positions WHERE id=? AND status='open'",
            (position_id,),
        ).fetchone()
        if not row:
            return None

        pos = dict(row)
        shares = pos["lots"] * 1000
        entry_cost = pos["entry_price"] * shares
        exit_value = exit_price * shares
        pnl = exit_value - entry_cost
        commission = (entry_cost + exit_value) * 0.001425
        tax = exit_value * 0.003
        net_pnl = pnl - commission - tax
        return_pct = (exit_price / pos["entry_price"] - 1) if pos["entry_price"] > 0 else 0
        days_held = (datetime.now() - datetime.fromisoformat(pos["entry_date"])).days
        exit_date = datetime.now().strftime("%Y-%m-%d")

        conn.execute(
            """UPDATE positions SET
               status='closed', exit_date=?, exit_price=?, exit_reason=?,
               pnl=?, net_pnl=?, return_pct=?, commission=?, tax=?, days_held=?
               WHERE id=?""",
            (
                exit_date, exit_price, exit_reason,
                round(pnl, 0), round(net_pnl, 0), round(return_pct, 4),
                round(commission, 0), round(tax, 0), days_held,
                position_id,
            ),
        )

    return {
        **pos,
        "status": "closed",
        "exit_date": exit_date,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "pnl": round(pnl, 0),
        "net_pnl": round(net_pnl, 0),
        "return_pct": round(return_pct, 4),
        "commission": round(commission, 0),
        "tax": round(tax, 0),
        "days_held": days_held,
    }


def update_position(position_id: str, updates: dict) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM positions WHERE id=? AND status='open'",
            (position_id,),
        ).fetchone()
        if not row:
            return None

        sets = []
        vals: list[Any] = []
        for field in ("stop_loss", "trailing_stop", "note"):
            if field in updates and updates[field] is not None:
                sets.append(f"{field}=?")
                vals.append(updates[field])

        if sets:
            vals.append(position_id)
            conn.execute(
                f"UPDATE positions SET {', '.join(sets)} WHERE id=?",
                vals,
            )

    return _row_to_dict(
        conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
    ) if sets else dict(row)


def delete_position(position_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM positions WHERE id=? AND status='open'",
            (position_id,),
        )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Equity snapshot DAO
# ---------------------------------------------------------------------------

def append_equity_snapshot(snapshot: dict):
    """Upsert daily equity snapshot (replace if same date)."""
    date = snapshot.get("date") or datetime.now().strftime("%Y-%m-%d")
    with _connect() as conn:
        conn.execute(
            """INSERT INTO equity_snapshots (date, total_equity, position_value, realized_pnl, position_count)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 total_equity=excluded.total_equity,
                 position_value=excluded.position_value,
                 realized_pnl=excluded.realized_pnl,
                 position_count=excluded.position_count""",
            (
                date,
                snapshot.get("total_equity", 0),
                snapshot.get("position_value", 0),
                snapshot.get("realized_pnl", 0),
                snapshot.get("position_count", 0),
            ),
        )


def get_equity_snapshots(limit: int = 365) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM equity_snapshots ORDER BY date DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return list(reversed(_rows_to_list(rows)))


# ---------------------------------------------------------------------------
# Watchlist DAO
# ---------------------------------------------------------------------------

def get_watchlist() -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT code FROM watchlist ORDER BY added_date ASC"
        ).fetchall()
    return [r["code"] for r in rows]


def add_to_watchlist(code: str, name: str = "") -> bool:
    with _connect() as conn:
        try:
            conn.execute(
                "INSERT INTO watchlist (code, name) VALUES (?, ?)",
                (code, name),
            )
            return True
        except sqlite3.IntegrityError:
            return False  # Already exists


def remove_from_watchlist(code: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM watchlist WHERE code=?", (code,))
    return cur.rowcount > 0


def batch_add_watchlist(codes: list[str]) -> list[str]:
    with _connect() as conn:
        for code in codes:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (code) VALUES (?)",
                (code,),
            )
        rows = conn.execute("SELECT code FROM watchlist ORDER BY added_date ASC").fetchall()
    return [r["code"] for r in rows]


# ---------------------------------------------------------------------------
# Analytics queries (SQL-powered)
# ---------------------------------------------------------------------------

def get_closed_stats() -> dict:
    """Aggregate stats for all closed trades using SQL."""
    with _connect() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN net_pnl > 0 THEN net_pnl ELSE 0 END) AS total_gain,
                SUM(CASE WHEN net_pnl <= 0 THEN ABS(net_pnl) ELSE 0 END) AS total_loss,
                AVG(days_held) AS avg_days
            FROM positions WHERE status='closed'
        """).fetchone()

    total = row["total"] or 0
    wins = row["wins"] or 0
    total_gain = row["total_gain"] or 0
    total_loss = row["total_loss"] or 0

    win_rate = wins / total if total > 0 else 0
    profit_factor = total_gain / total_loss if total_loss > 0 else 999
    avg_win = total_gain / wins if wins > 0 else 0
    avg_loss = total_loss / (total - wins) if (total - wins) > 0 else 0
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    return {
        "total": total, "wins": wins,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 2),
        "expectancy": round(expectancy, 0),
        "avg_win": round(avg_win, 0),
        "avg_loss": round(avg_loss, 0),
        "total_gain": round(total_gain, 0),
        "total_loss": round(total_loss, 0),
        "avg_days": round(row["avg_days"] or 0, 1),
    }


def get_confidence_accuracy() -> list[dict]:
    """Return avg return and win rate grouped by confidence bracket."""
    brackets = [
        ("C >= 1.2 (高信心)", 1.2, 999),
        ("1.0 <= C < 1.2 (中高)", 1.0, 1.2),
        ("0.5 <= C < 1.0 (中)", 0.5, 1.0),
        ("C < 0.5 (低信心)", -999, 0.5),
    ]
    result = []
    with _connect() as conn:
        for label, lo, hi in brackets:
            row = conn.execute("""
                SELECT
                    COUNT(*) AS cnt,
                    AVG(return_pct) AS avg_ret,
                    SUM(CASE WHEN return_pct > 0 THEN 1 ELSE 0 END) AS wins
                FROM positions
                WHERE status='closed' AND confidence >= ? AND confidence < ?
            """, (lo, hi)).fetchone()

            if row["cnt"] and row["cnt"] > 0:
                result.append({
                    "bracket": label,
                    "count": row["cnt"],
                    "avg_return": round(row["avg_ret"] or 0, 4),
                    "win_rate": round((row["wins"] or 0) / row["cnt"], 4),
                })
    return result


def get_best_worst_trades() -> tuple[dict | None, dict | None]:
    """Return best and worst closed trades by net_pnl."""
    with _connect() as conn:
        best = conn.execute(
            "SELECT code, name, net_pnl, return_pct FROM positions WHERE status='closed' ORDER BY net_pnl DESC LIMIT 1"
        ).fetchone()
        worst = conn.execute(
            "SELECT code, name, net_pnl, return_pct FROM positions WHERE status='closed' ORDER BY net_pnl ASC LIMIT 1"
        ).fetchone()
    return _row_to_dict(best), _row_to_dict(worst)


# ---------------------------------------------------------------------------
# Startup initialization
# ---------------------------------------------------------------------------

_ensure_db()

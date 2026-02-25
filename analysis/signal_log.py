"""Signal Log — SQLite trade signal tracking for drift detection.

P3: CTO Gemini directive — "讓 AI 對自己發出的信號負責"

Schema: trade_signals_log
  - signal_date, stock_code, entry_price (closing price)
  - sim_score, expected_mean_return, ci_lower, ci_upper, worst_case
  - sniper_tier, confidence_grade, industry
  - status: Active / Realized
  - actual_return_d5, actual_return_d10, actual_return_d21
  - in_bounds_d21: whether actual fell within [ci_lower, ci_upper]
  - realized_date: when returns were filled in
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "signal_log.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS trade_signals_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT,
    entry_price REAL,
    sim_score INTEGER,
    confidence_grade TEXT,
    sniper_tier TEXT,
    expected_mean_return REAL,
    ci_lower REAL,
    ci_upper REAL,
    worst_case_pct REAL,
    d21_win_rate REAL,
    d21_expectancy REAL,
    industry TEXT,
    rs_rating REAL,
    mean_similarity REAL,
    divergence_warning INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    actual_return_d5 REAL,
    actual_return_d10 REAL,
    actual_return_d21 REAL,
    in_bounds_d21 INTEGER,
    realized_date TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(signal_date, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_sig_date ON trade_signals_log(signal_date);
CREATE INDEX IF NOT EXISTS idx_sig_status ON trade_signals_log(status);
CREATE INDEX IF NOT EXISTS idx_sig_code ON trade_signals_log(stock_code);
"""


def _get_conn() -> sqlite3.Connection:
    """Get or create SQLite connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(_CREATE_TABLE)
    return conn


def log_signal(signal: dict) -> int:
    """Write a new signal to the trade log.

    Args:
        signal: Dict from auto_sim top_signals with keys:
            stock_code, name, rs_rating, industry, tier,
            mean_similarity, confidence_score, confidence_grade,
            d21_win_rate, d21_mean, d21_expectancy,
            ci_low, ci_high, worst_case_pct, divergence_warning

    Returns:
        Row ID of the inserted record.
    """
    conn = _get_conn()
    try:
        # Get entry price (today's close) from yfinance
        entry_price = _get_closing_price(signal["stock_code"])

        conn.execute(
            """INSERT OR IGNORE INTO trade_signals_log
               (signal_date, stock_code, stock_name, entry_price,
                sim_score, confidence_grade, sniper_tier,
                expected_mean_return, ci_lower, ci_upper, worst_case_pct,
                d21_win_rate, d21_expectancy, industry, rs_rating,
                mean_similarity, divergence_warning, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
            (
                datetime.now().strftime("%Y-%m-%d"),
                signal["stock_code"],
                signal.get("name", ""),
                entry_price,
                signal.get("confidence_score", 0),
                signal.get("confidence_grade", "LOW"),
                signal.get("tier", "avoid"),
                signal.get("d21_mean"),
                signal.get("ci_low"),
                signal.get("ci_high"),
                signal.get("worst_case_pct"),
                signal.get("d21_win_rate"),
                signal.get("d21_expectancy"),
                signal.get("industry", ""),
                signal.get("rs_rating", 0),
                signal.get("mean_similarity", 0),
                1 if signal.get("divergence_warning") else 0,
            ),
        )
        conn.commit()
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        logger.info("Signal logged: %s %s (score=%d, tier=%s)",
                     signal["stock_code"], signal.get("name", ""),
                     signal.get("confidence_score", 0), signal.get("tier", ""))
        return row_id
    finally:
        conn.close()


def log_signals_batch(signals: list[dict]) -> int:
    """Log multiple signals at once. Returns count of new records."""
    count = 0
    for s in signals:
        try:
            row_id = log_signal(s)
            if row_id > 0:
                count += 1
        except Exception as e:
            logger.warning("Failed to log signal %s: %s", s.get("stock_code"), e)
    return count


def get_active_signals(days_back: int = 30) -> list[dict]:
    """Get active (unrealized) signals from the last N days."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT * FROM trade_signals_log
               WHERE status = 'active'
               AND signal_date >= date('now', ?)
               ORDER BY signal_date DESC""",
            (f"-{days_back} days",),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_realized_signals(days_back: int = 90) -> list[dict]:
    """Get realized signals from the last N days."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT * FROM trade_signals_log
               WHERE status = 'realized'
               AND signal_date >= date('now', ?)
               ORDER BY signal_date DESC""",
            (f"-{days_back} days",),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_signals(limit: int = 100) -> list[dict]:
    """Get all signals (for UI display)."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM trade_signals_log ORDER BY signal_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def realize_signals() -> dict:
    """Update active signals with actual realized returns.

    For each active signal, check if enough days have passed to compute
    T+5, T+10, T+21 returns. If T+21 is available, mark as 'realized'.

    Returns:
        {"updated": int, "realized": int, "errors": int}
    """
    conn = _get_conn()
    updated = realized = errors = 0

    try:
        active = conn.execute(
            "SELECT * FROM trade_signals_log WHERE status = 'active'"
        ).fetchall()

        for row in active:
            code = row["stock_code"]
            signal_date = row["signal_date"]
            entry_price = row["entry_price"]

            if not entry_price or entry_price <= 0:
                continue

            try:
                returns = _compute_actual_returns(code, signal_date, entry_price)
            except Exception as e:
                logger.debug("Failed to compute returns for %s@%s: %s", code, signal_date, e)
                errors += 1
                continue

            if not returns:
                continue

            # Update fields
            updates = {}
            if returns.get("d5") is not None:
                updates["actual_return_d5"] = returns["d5"]
            if returns.get("d10") is not None:
                updates["actual_return_d10"] = returns["d10"]
            if returns.get("d21") is not None:
                updates["actual_return_d21"] = returns["d21"]
                # Check in-bounds
                ci_low = row["ci_lower"]
                ci_high = row["ci_upper"]
                if ci_low is not None and ci_high is not None:
                    updates["in_bounds_d21"] = 1 if ci_low <= returns["d21"] <= ci_high else 0

            if updates:
                # Mark as realized if d21 is available
                if "actual_return_d21" in updates:
                    updates["status"] = "realized"
                    updates["realized_date"] = datetime.now().strftime("%Y-%m-%d")
                    realized += 1

                set_clause = ", ".join(f"{k} = ?" for k in updates)
                vals = list(updates.values()) + [row["id"]]
                conn.execute(
                    f"UPDATE trade_signals_log SET {set_clause} WHERE id = ?",
                    vals,
                )
                updated += 1

        conn.commit()
    finally:
        conn.close()

    logger.info("Signal realization: %d updated, %d realized, %d errors", updated, realized, errors)
    return {"updated": updated, "realized": realized, "errors": errors}


def _get_closing_price(stock_code: str) -> Optional[float]:
    """Get today's closing price for a stock."""
    try:
        from data.fetcher import get_stock_data
        df = get_stock_data(stock_code, period_days=5)
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
    except Exception:
        pass
    return None


def _compute_actual_returns(
    stock_code: str, signal_date: str, entry_price: float
) -> dict:
    """Compute actual returns at T+5, T+10, T+21 from signal date."""
    import pandas as pd

    try:
        from data.fetcher import get_stock_data
        df = get_stock_data(stock_code, period_days=60)
        if df is None or df.empty:
            return {}

        df.index = pd.to_datetime(df.index)
        sig_date = pd.Timestamp(signal_date)

        # Find the signal date index (or next trading day)
        valid = df.index[df.index >= sig_date]
        if len(valid) == 0:
            return {}

        base_idx = df.index.get_loc(valid[0])
        result = {}

        for horizon, key in [(5, "d5"), (10, "d10"), (21, "d21")]:
            fwd_idx = base_idx + horizon
            if fwd_idx < len(df):
                fwd_price = float(df["close"].iloc[fwd_idx])
                result[key] = round((fwd_price / entry_price) - 1.0, 4)

        return result
    except Exception:
        return {}

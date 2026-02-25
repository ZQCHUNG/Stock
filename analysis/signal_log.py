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
    initial_stop_price REAL,
    current_stop_price REAL,
    trailing_phase INTEGER DEFAULT 0,
    highest_since_entry REAL,
    target_1r_price REAL,
    scale_out_triggered INTEGER DEFAULT 0,
    scale_out_date TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(signal_date, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_sig_date ON trade_signals_log(signal_date);
CREATE INDEX IF NOT EXISTS idx_sig_status ON trade_signals_log(status);
CREATE INDEX IF NOT EXISTS idx_sig_code ON trade_signals_log(stock_code);
"""

# Phase 7 P2: Missed Opportunities (filtered signals log)
_CREATE_FILTERED_TABLE = """
CREATE TABLE IF NOT EXISTS filtered_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT,
    raw_score INTEGER,
    final_score INTEGER,
    filter_reason TEXT,
    tr_ratio REAL,
    vol_ratio REAL,
    rs_rating REAL,
    tier TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(signal_date, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_filt_date ON filtered_signals(signal_date);
"""

# Schema migration for existing DBs (columns added in Phase 6 P0 + Phase 7 P1)
_MIGRATE_COLUMNS = [
    ("initial_stop_price", "REAL"),
    ("current_stop_price", "REAL"),
    ("trailing_phase", "INTEGER DEFAULT 0"),
    ("highest_since_entry", "REAL"),
    ("target_1r_price", "REAL"),
    ("scale_out_triggered", "INTEGER DEFAULT 0"),
    ("scale_out_date", "TEXT"),
]


def _get_conn() -> sqlite3.Connection:
    """Get or create SQLite connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(_CREATE_TABLE)
    conn.executescript(_CREATE_FILTERED_TABLE)
    _ensure_migration(conn)
    return conn


def _ensure_migration(conn: sqlite3.Connection):
    """Add new columns to existing DBs if missing (Phase 6 P0)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(trade_signals_log)")}
    for col_name, col_type in _MIGRATE_COLUMNS:
        if col_name not in existing:
            try:
                conn.execute(f"ALTER TABLE trade_signals_log ADD COLUMN {col_name} {col_type}")
                logger.info("Migrated signal_log: added column %s", col_name)
            except Exception:
                pass  # already exists or other issue


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


def log_filtered_signal(signal: dict, raw_score: int, final_score: int, reason: str) -> None:
    """Phase 7 P2: Log a signal that was penalized by Energy Score.

    Secretary directive: "究竟被過濾掉的是「子彈」還是「炸彈」？"
    """
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO filtered_signals
               (signal_date, stock_code, stock_name, raw_score, final_score,
                filter_reason, tr_ratio, vol_ratio, rs_rating, tier)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now().strftime("%Y-%m-%d"),
                signal.get("stock_code", ""),
                signal.get("name", ""),
                raw_score,
                final_score,
                reason,
                signal.get("energy_tr_ratio"),
                signal.get("energy_vol_ratio"),
                signal.get("rs_rating", 0),
                signal.get("tier", ""),
            ),
        )
        conn.commit()
    except Exception as e:
        logger.debug("Failed to log filtered signal: %s", e)
    finally:
        conn.close()


def get_filtered_signals(days_back: int = 30, limit: int = 50) -> list[dict]:
    """Phase 7 P2: Get recently filtered signals (missed opportunities)."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT * FROM filtered_signals
               WHERE signal_date >= date('now', ?)
               ORDER BY signal_date DESC, raw_score DESC
               LIMIT ?""",
            (f"-{days_back} days", limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


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


def update_trailing_stops() -> dict:
    """Phase 6 P0: Update trailing stop prices for all active signals.

    Wires R86's compute_trailing_stop() to active signals in the trade log.
    For each active signal:
      1. Fetch current price + highest since entry
      2. Compute ATR(14) from recent data
      3. Run 4-phase trailing stop logic
      4. Update DB with current_stop_price, trailing_phase, highest_since_entry

    Returns:
        {"updated": int, "errors": int, "active_stops": list[dict]}
    """
    import pandas as pd
    from analysis.stop_loss import compute_trailing_stop

    conn = _get_conn()
    updated = errors = 0
    active_stops = []

    try:
        active = conn.execute(
            "SELECT * FROM trade_signals_log WHERE status = 'active'"
        ).fetchall()

        for row in active:
            code = row["stock_code"]
            entry_price = row["entry_price"]
            if not entry_price or entry_price <= 0:
                continue

            try:
                from data.fetcher import get_stock_data
                df = get_stock_data(code, period_days=60)
                if df is None or df.empty:
                    continue

                df.index = pd.to_datetime(df.index)
                current_price = float(df["close"].iloc[-1])

                # Highest price since entry
                sig_date = pd.Timestamp(row["signal_date"])
                since_entry = df[df.index >= sig_date]
                highest = float(since_entry["high"].max()) if not since_entry.empty else current_price

                # Keep max of stored vs computed
                stored_highest = row["highest_since_entry"]
                if stored_highest and stored_highest > highest:
                    highest = stored_highest

                # Initial stop: use stored or derive from worst_case_pct
                initial_stop = row["initial_stop_price"]
                if not initial_stop:
                    worst = row["worst_case_pct"]
                    if worst and worst < 0:
                        initial_stop = entry_price * (1 + worst / 100.0)
                    else:
                        initial_stop = entry_price * 0.93  # default 7% stop

                # Compute ATR(14)
                high = df["high"]
                low = df["low"]
                close = df["close"]
                tr = pd.concat([
                    high - low,
                    (high - close.shift(1)).abs(),
                    (low - close.shift(1)).abs(),
                ], axis=1).max(axis=1)
                current_atr = float(tr.rolling(14).mean().dropna().iloc[-1])

                r_value = entry_price - initial_stop

                trail = compute_trailing_stop(
                    entry_price=entry_price,
                    current_price=current_price,
                    highest_price=highest,
                    initial_stop=initial_stop,
                    current_atr=current_atr,
                    r_value=r_value,
                )

                # Phase 7 P1: +1R Scale-out check
                # Architect: "P_target = Entry + (Entry - Stop)"
                target_1r = entry_price + r_value
                already_triggered = bool(row["scale_out_triggered"])
                scale_out_now = (not already_triggered) and (current_price >= target_1r)

                conn.execute(
                    """UPDATE trade_signals_log SET
                       current_stop_price = ?, trailing_phase = ?,
                       highest_since_entry = ?, initial_stop_price = ?,
                       target_1r_price = ?,
                       scale_out_triggered = CASE WHEN ? = 1 THEN 1 ELSE scale_out_triggered END,
                       scale_out_date = CASE WHEN ? = 1 THEN ? ELSE scale_out_date END
                       WHERE id = ?""",
                    (
                        trail["current_stop"], trail["phase"], highest, initial_stop,
                        round(target_1r, 2),
                        1 if scale_out_now else 0,
                        1 if scale_out_now else 0,
                        datetime.now().strftime("%Y-%m-%d") if scale_out_now else None,
                        row["id"],
                    ),
                )
                updated += 1

                active_stops.append({
                    "stock_code": code,
                    "stock_name": row["stock_name"] or "",
                    "entry_price": entry_price,
                    "current_price": current_price,
                    "current_stop": trail["current_stop"],
                    "trailing_phase": trail["phase"],
                    "phase_reason": trail["reason"],
                    "return_pct": round((current_price / entry_price - 1) * 100, 1),
                    "stop_distance_pct": round((current_price - trail["current_stop"]) / current_price * 100, 1),
                    "target_1r_price": round(target_1r, 2),
                    "scale_out_triggered": already_triggered or scale_out_now,
                    "scale_out_just_triggered": scale_out_now,
                })
            except Exception as e:
                logger.debug("Trailing stop update failed for %s: %s", code, e)
                errors += 1

        conn.commit()
    finally:
        conn.close()

    logger.info("Trailing stops: %d updated, %d errors", updated, errors)
    return {"updated": updated, "errors": errors, "active_stops": active_stops}


def format_active_signals_line(active_stops: list[dict]) -> str:
    """Format active signals with trailing stops for LINE Notify.

    Architect directive: "🛡️ 當前移動止盈價: {current_stop_price}"
    """
    if not active_stops:
        return ""

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    phase_names = {0: "Initial", 1: "Breakeven", 2: "ATR Trail", 3: "Tight Trail"}
    lines = [f"\n🛡️ Active Signals Update ({now})"]
    lines.append(f"追蹤中: {len(active_stops)} 檔\n")

    for s in active_stops:
        ret = s["return_pct"]
        icon = "🟢" if ret > 0 else "🔴"
        phase = phase_names.get(s["trailing_phase"], "?")
        lines.append(f"{icon} {s['stock_code']} {s['stock_name']}")
        lines.append(f"  Entry: {s['entry_price']:.1f} → Now: {s['current_price']:.1f} ({ret:+.1f}%)")
        lines.append(f"  🛡️ 移動止盈價: {s['current_stop']:.1f} ({phase})")
        lines.append(f"  距離止盈: {s['stop_distance_pct']:.1f}%")

        # Phase 7 P1: +1R Scale-out advisory
        target_1r = s.get("target_1r_price")
        if target_1r:
            lines.append(f"  🎯 +1R Target: {target_1r:.1f}")
        if s.get("scale_out_just_triggered"):
            lines.append(f"  💎 建議動作：利潤鎖定（已達 +1R）")
        elif s.get("scale_out_triggered"):
            lines.append(f"  ✅ 已觸發利潤保護")

        lines.append("")

    return "\n".join(lines)


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

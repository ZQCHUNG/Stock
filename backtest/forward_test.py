"""R59: Forward Testing Engine (Paper Trading)

Tracks V4 strategy signals in real-time, records virtual positions,
and compares forward test results against backtest expectations.

Key design decisions:
- SQLite storage for durability and easy querying
- Realistic execution: slippage, commission, tax, liquidity constraints
- Daily lifecycle: scan → signal → virtual open → track → virtual close
- Comparison: forward test win rate / return vs historical backtest
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Default DB path
_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "forward_test.db"

# Execution parameters (same as backtest defaults)
DEFAULT_COMMISSION_RATE = 0.001425
DEFAULT_TAX_RATE = 0.003
DEFAULT_SLIPPAGE = 0.001
MIN_VOLUME_LOTS = 500  # 500張 = 500,000 shares


@dataclass
class ForwardSignal:
    """A signal generated during forward testing."""
    id: int | None = None
    scan_date: str = ""         # Date signal was generated (YYYY-MM-DD)
    stock_code: str = ""
    signal_type: str = "BUY"    # BUY or SELL
    signal_price: float = 0.0   # Close price at signal time
    confidence: float = 0.0     # V4 confidence score
    adx: float = 0.0
    rsi: float = 0.0
    volume_lots: float = 0.0    # Volume in lots (÷1000)
    status: str = "pending"     # pending, opened, skipped, expired
    metadata: str = ""          # JSON extra data


@dataclass
class ForwardPosition:
    """A virtual position opened from a forward test signal."""
    id: int | None = None
    signal_id: int = 0
    stock_code: str = ""
    open_date: str = ""
    open_price: float = 0.0     # Actual entry (signal_price + slippage)
    shares: int = 0
    capital_used: float = 0.0
    tp_price: float = 0.0       # Take profit target
    sl_price: float = 0.0       # Stop loss level
    current_price: float = 0.0
    highest_price: float = 0.0
    hold_days: int = 0
    status: str = "open"        # open, closed
    close_date: str | None = None
    close_price: float | None = None
    exit_reason: str = ""
    pnl: float = 0.0
    return_pct: float = 0.0
    commission: float = 0.0
    tax: float = 0.0
    slippage_cost: float = 0.0
    liquidity_warning: str = ""


@dataclass
class ForwardTestSummary:
    """Summary statistics of forward test performance."""
    total_signals: int = 0
    signals_opened: int = 0
    signals_skipped: int = 0
    signals_pending: int = 0
    total_positions: int = 0
    open_positions: int = 0
    closed_positions: int = 0
    win_rate: float = 0.0
    avg_return: float = 0.0
    total_pnl: float = 0.0
    avg_hold_days: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    # Comparison with backtest
    backtest_win_rate: float | None = None
    backtest_avg_return: float | None = None
    divergence_pct: float | None = None  # forward vs backtest win rate diff


# =========================================================================
# Database Management
# =========================================================================

def _get_db_path() -> Path:
    return _DB_PATH


def _init_db(conn: sqlite3.Connection):
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS forward_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            signal_type TEXT DEFAULT 'BUY',
            signal_price REAL DEFAULT 0,
            confidence REAL DEFAULT 0,
            adx REAL DEFAULT 0,
            rsi REAL DEFAULT 0,
            volume_lots REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            metadata TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS forward_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER REFERENCES forward_signals(id),
            stock_code TEXT NOT NULL,
            open_date TEXT NOT NULL,
            open_price REAL NOT NULL,
            shares INTEGER DEFAULT 0,
            capital_used REAL DEFAULT 0,
            tp_price REAL DEFAULT 0,
            sl_price REAL DEFAULT 0,
            current_price REAL DEFAULT 0,
            highest_price REAL DEFAULT 0,
            hold_days INTEGER DEFAULT 0,
            status TEXT DEFAULT 'open',
            close_date TEXT,
            close_price REAL,
            exit_reason TEXT DEFAULT '',
            pnl REAL DEFAULT 0,
            return_pct REAL DEFAULT 0,
            commission REAL DEFAULT 0,
            tax REAL DEFAULT 0,
            slippage_cost REAL DEFAULT 0,
            liquidity_warning TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_signals_date ON forward_signals(scan_date);
        CREATE INDEX IF NOT EXISTS idx_signals_code ON forward_signals(stock_code);
        CREATE INDEX IF NOT EXISTS idx_positions_status ON forward_positions(status);
        CREATE INDEX IF NOT EXISTS idx_positions_code ON forward_positions(stock_code);
    """)


@contextmanager
def get_db():
    """Context manager for database connections."""
    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# =========================================================================
# Signal Generation
# =========================================================================

def scan_and_record_signals(
    stock_codes: list[str] | None = None,
    scan_date: str | None = None,
) -> list[ForwardSignal]:
    """Scan stocks for V4 BUY signals and record them.

    Args:
        stock_codes: List of codes to scan (default: SCAN_STOCKS from config)
        scan_date: Override scan date (default: today, YYYY-MM-DD)

    Returns:
        List of signals found
    """
    from config import SCAN_STOCKS
    from data.fetcher import get_stock_data
    from analysis.strategy_v4 import get_v4_analysis

    if stock_codes is None:
        stock_codes = SCAN_STOCKS
    if scan_date is None:
        scan_date = date.today().isoformat()

    signals = []
    for code in stock_codes:
        try:
            analysis = get_v4_analysis(code)
            if not analysis:
                continue

            signal = analysis.get("signal", "HOLD")
            if signal != "BUY":
                continue

            # Get current price/volume data
            df = get_stock_data(code, period_days=5)
            if df.empty:
                continue
            last_row = df.iloc[-1]

            volume_lots = last_row.get("volume", 0) / 1000
            if volume_lots < MIN_VOLUME_LOTS:
                continue

            sig = ForwardSignal(
                scan_date=scan_date,
                stock_code=code,
                signal_type="BUY",
                signal_price=float(last_row["close"]),
                confidence=float(analysis.get("confidence", 0)),
                adx=float(analysis.get("adx", 0)),
                rsi=float(analysis.get("rsi", 0)),
                volume_lots=float(volume_lots),
                status="pending",
                metadata=json.dumps({
                    "reasons": analysis.get("reasons", []),
                    "entry_type": analysis.get("entry_type", ""),
                }),
            )
            signals.append(sig)

        except Exception as e:
            logger.warning(f"Forward scan failed for {code}: {e}")
            continue

    # Save to DB
    if signals:
        with get_db() as conn:
            for sig in signals:
                cursor = conn.execute(
                    """INSERT INTO forward_signals
                    (scan_date, stock_code, signal_type, signal_price, confidence,
                     adx, rsi, volume_lots, status, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (sig.scan_date, sig.stock_code, sig.signal_type,
                     sig.signal_price, sig.confidence, sig.adx, sig.rsi,
                     sig.volume_lots, sig.status, sig.metadata),
                )
                sig.id = cursor.lastrowid

    logger.info(f"Forward scan {scan_date}: {len(signals)} BUY signals from {len(stock_codes)} stocks")
    return signals


# =========================================================================
# Position Management
# =========================================================================

def open_virtual_position(
    signal_id: int,
    capital: float = 500_000,
    commission_rate: float = DEFAULT_COMMISSION_RATE,
    slippage: float = DEFAULT_SLIPPAGE,
    tp_pct: float = 0.10,
    sl_pct: float = 0.07,
) -> ForwardPosition | None:
    """Open a virtual position from a signal.

    Simulates realistic execution with slippage and commission.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM forward_signals WHERE id = ?", (signal_id,)
        ).fetchone()
        if not row:
            return None

        signal_price = row["signal_price"]
        code = row["stock_code"]

        # Apply slippage (buy higher)
        entry_price = signal_price * (1 + slippage)
        slippage_cost = (entry_price - signal_price)

        # Calculate position size
        max_shares = int(capital / (entry_price * (1 + commission_rate)))
        max_shares = (max_shares // 1000) * 1000  # Round to lots
        if max_shares <= 0:
            return None

        cost = max_shares * entry_price
        commission = cost * commission_rate

        pos = ForwardPosition(
            signal_id=signal_id,
            stock_code=code,
            open_date=row["scan_date"],
            open_price=round(entry_price, 2),
            shares=max_shares,
            capital_used=round(cost + commission, 0),
            tp_price=round(entry_price * (1 + tp_pct), 2),
            sl_price=round(entry_price * (1 - sl_pct), 2),
            current_price=round(entry_price, 2),
            highest_price=round(entry_price, 2),
            commission=round(commission, 0),
            slippage_cost=round(slippage_cost * max_shares, 0),
        )

        # Check liquidity
        volume_lots = row["volume_lots"]
        if volume_lots > 0:
            trade_lots = max_shares / 1000
            if trade_lots > volume_lots * 0.05:
                pos.liquidity_warning = f"佔日量 {trade_lots/volume_lots:.1%}"

        cursor = conn.execute(
            """INSERT INTO forward_positions
            (signal_id, stock_code, open_date, open_price, shares, capital_used,
             tp_price, sl_price, current_price, highest_price, hold_days, status,
             commission, slippage_cost, liquidity_warning)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'open', ?, ?, ?)""",
            (pos.signal_id, pos.stock_code, pos.open_date, pos.open_price,
             pos.shares, pos.capital_used, pos.tp_price, pos.sl_price,
             pos.current_price, pos.highest_price,
             pos.commission, pos.slippage_cost, pos.liquidity_warning),
        )
        pos.id = cursor.lastrowid

        # Update signal status
        conn.execute(
            "UPDATE forward_signals SET status = 'opened' WHERE id = ?",
            (signal_id,),
        )

    return pos


def update_positions_daily(
    trailing_pct: float = 0.02,
    min_hold: int = 5,
    commission_rate: float = DEFAULT_COMMISSION_RATE,
    tax_rate: float = DEFAULT_TAX_RATE,
    slippage: float = DEFAULT_SLIPPAGE,
) -> list[dict]:
    """Update all open positions with current prices.

    Checks for TP/SL/trailing stop triggers and closes positions.
    Returns list of actions taken.
    """
    from data.fetcher import get_stock_data

    actions = []

    with get_db() as conn:
        open_positions = conn.execute(
            "SELECT * FROM forward_positions WHERE status = 'open'"
        ).fetchall()

        for row in open_positions:
            pos_id = row["id"]
            code = row["stock_code"]

            try:
                df = get_stock_data(code, period_days=5)
                if df.empty:
                    continue

                last = df.iloc[-1]
                current_price = float(last["close"])
                today_high = float(last.get("high", current_price))
                today_low = float(last.get("low", current_price))

                hold_days = row["hold_days"] + 1
                highest = max(row["highest_price"], today_high)
                tp_price = row["tp_price"]
                sl_price = row["sl_price"]
                open_price = row["open_price"]

                # Update trailing stop
                if trailing_pct > 0:
                    new_sl = highest * (1 - trailing_pct)
                    sl_price = max(sl_price, new_sl)

                # Check exit conditions
                exit_reason = ""
                exit_price = 0.0

                if hold_days >= min_hold:
                    if today_high >= tp_price:
                        exit_reason = "take_profit"
                        exit_price = tp_price
                    elif today_low <= sl_price:
                        original_sl = open_price * (1 - 0.07)
                        exit_reason = "trailing_stop" if sl_price > original_sl else "stop_loss"
                        exit_price = sl_price

                if exit_reason:
                    # Close position with slippage
                    actual_exit = exit_price * (1 - slippage)
                    shares = row["shares"]
                    revenue = shares * actual_exit
                    close_commission = revenue * commission_rate
                    tax = revenue * tax_rate
                    total_commission = row["commission"] + close_commission

                    pnl = (actual_exit - open_price) * shares - total_commission - tax
                    return_pct = pnl / (open_price * shares)

                    conn.execute("""
                        UPDATE forward_positions
                        SET status='closed', close_date=?, close_price=?,
                            exit_reason=?, pnl=?, return_pct=?,
                            commission=?, tax=?, hold_days=?,
                            highest_price=?, current_price=?
                        WHERE id=?
                    """, (
                        date.today().isoformat(), round(actual_exit, 2),
                        exit_reason, round(pnl, 0), round(return_pct, 4),
                        round(total_commission, 0), round(tax, 0), hold_days,
                        round(highest, 2), round(current_price, 2), pos_id,
                    ))
                    actions.append({
                        "action": "closed",
                        "code": code,
                        "reason": exit_reason,
                        "pnl": round(pnl, 0),
                        "return_pct": round(return_pct, 4),
                    })
                else:
                    # Update position
                    conn.execute("""
                        UPDATE forward_positions
                        SET hold_days=?, highest_price=?, current_price=?, sl_price=?
                        WHERE id=?
                    """, (hold_days, round(highest, 2), round(current_price, 2),
                          round(sl_price, 2), pos_id))

            except Exception as e:
                logger.warning(f"Forward update failed for {code}: {e}")

    return actions


# =========================================================================
# Query / Reporting
# =========================================================================

def get_summary() -> ForwardTestSummary:
    """Get overall forward test summary statistics."""
    summary = ForwardTestSummary()

    with get_db() as conn:
        # Signal stats
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status='opened' THEN 1 ELSE 0 END) as opened,
                SUM(CASE WHEN status='skipped' THEN 1 ELSE 0 END) as skipped,
                SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending
            FROM forward_signals
        """).fetchone()
        summary.total_signals = row["total"]
        summary.signals_opened = row["opened"] or 0
        summary.signals_skipped = row["skipped"] or 0
        summary.signals_pending = row["pending"] or 0

        # Position stats
        positions = conn.execute("""
            SELECT * FROM forward_positions ORDER BY created_at DESC
        """).fetchall()

        summary.total_positions = len(positions)
        closed = [p for p in positions if p["status"] == "closed"]
        open_pos = [p for p in positions if p["status"] == "open"]
        summary.open_positions = len(open_pos)
        summary.closed_positions = len(closed)

        if closed:
            wins = [p for p in closed if p["pnl"] > 0]
            summary.win_rate = len(wins) / len(closed) if closed else 0
            summary.avg_return = sum(p["return_pct"] for p in closed) / len(closed)
            summary.total_pnl = sum(p["pnl"] for p in closed)
            summary.avg_hold_days = sum(p["hold_days"] for p in closed) / len(closed)
            summary.best_trade = max(p["return_pct"] for p in closed)
            summary.worst_trade = min(p["return_pct"] for p in closed)

    return summary


def get_signals(limit: int = 50, status: str | None = None) -> list[dict]:
    """Get recent signals."""
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM forward_signals WHERE status=? ORDER BY scan_date DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM forward_signals ORDER BY scan_date DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_positions(limit: int = 50, status: str | None = None) -> list[dict]:
    """Get recent positions."""
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM forward_positions WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM forward_positions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def compare_with_backtest(
    stock_code: str | None = None,
    period_days: int = 365,
) -> dict:
    """Compare forward test results with backtest expectations.

    Returns comparison metrics showing if strategy performs as expected.
    """
    summary = get_summary()

    # Get closed positions for comparison
    with get_db() as conn:
        if stock_code:
            closed = conn.execute(
                "SELECT * FROM forward_positions WHERE status='closed' AND stock_code=?",
                (stock_code,),
            ).fetchall()
        else:
            closed = conn.execute(
                "SELECT * FROM forward_positions WHERE status='closed'"
            ).fetchall()

    forward_results = {
        "total_trades": len(closed),
        "win_rate": 0.0,
        "avg_return": 0.0,
        "total_pnl": 0.0,
        "avg_hold_days": 0.0,
    }

    if closed:
        wins = sum(1 for p in closed if p["pnl"] > 0)
        forward_results["win_rate"] = wins / len(closed)
        forward_results["avg_return"] = sum(p["return_pct"] for p in closed) / len(closed)
        forward_results["total_pnl"] = sum(p["pnl"] for p in closed)
        forward_results["avg_hold_days"] = sum(p["hold_days"] for p in closed) / len(closed)

    return {
        "forward": forward_results,
        "comparison": {
            "sufficient_data": len(closed) >= 10,
            "note": "需要至少 10 筆已平倉交易才能進行有效比較" if len(closed) < 10 else "",
        },
    }

"""Signal Tracker — 前瞻測試引擎（Gemini R39: Forward Testing Bridge）

核心功能：
1. 每日記錄所有 BUY 信號（V4, V5, Adaptive）的快照
2. 追蹤信號發出後 1/3/5 天的價格變動
3. 計算「信號後最大漲幅」與「最大回撤」
4. 為策略適配度提供「現實回饋」數據

SQLite 表：forward_signals
- signal_date: 信號發出日期
- code: 股票代號
- strategy: "V4" / "V5" / "Adaptive"
- signal_price: 信號當日收盤價
- d1_return, d3_return, d5_return: 1/3/5 日報酬率
- max_gain_5d: 5 日內最大漲幅
- max_drawdown_5d: 5 日內最大回撤
- filled_at: 追蹤數據填入時間（NULL = 尚未追蹤）
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "signal_tracker.db"


def _init_db():
    """Initialize SQLite database with forward_signals table."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forward_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_date TEXT NOT NULL,
            code TEXT NOT NULL,
            strategy TEXT NOT NULL,
            signal_price REAL NOT NULL,
            entry_type TEXT DEFAULT '',
            bias_confirmed INTEGER DEFAULT 0,
            regime TEXT DEFAULT '',
            composite_score REAL,
            d1_return REAL,
            d3_return REAL,
            d5_return REAL,
            max_gain_5d REAL,
            max_drawdown_5d REAL,
            filled_at TEXT,
            UNIQUE(signal_date, code, strategy)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_forward_date ON forward_signals(signal_date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_forward_code ON forward_signals(code)
    """)
    conn.commit()
    conn.close()


def record_daily_signals(stocks: dict[str, str] | None = None, max_workers: int = 4) -> dict:
    """Scan all stocks and record today's BUY signals.

    Args:
        stocks: {code: name} dict, defaults to SCAN_STOCKS
        max_workers: Parallel workers

    Returns:
        dict with scan results summary
    """
    if stocks is None:
        from config import SCAN_STOCKS
        stocks = SCAN_STOCKS

    _init_db()

    today = datetime.now().strftime("%Y-%m-%d")
    signals_recorded = []

    def _scan_stock(code):
        """Scan a single stock for V4/V5/Adaptive signals."""
        results = []
        try:
            from data.fetcher import get_stock_data
            df = get_stock_data(code, period_days=365)
            if df is None or len(df) < 60:
                return results

            current_price = float(df["close"].iloc[-1])

            # V4 signal
            try:
                from analysis.strategy_v4 import get_v4_analysis
                v4 = get_v4_analysis(df)
                if v4.get("signal") == "BUY":
                    results.append({
                        "code": code,
                        "strategy": "V4",
                        "signal_price": current_price,
                        "entry_type": v4.get("entry_type", ""),
                        "bias_confirmed": 0,
                        "composite_score": None,
                    })
            except Exception:
                pass

            # V5 signal
            try:
                from analysis.strategy_v5 import get_v5_analysis
                v5 = get_v5_analysis(df)
                if v5.get("signal") == "BUY":
                    results.append({
                        "code": code,
                        "strategy": "V5",
                        "signal_price": current_price,
                        "entry_type": v5.get("entry_type", ""),
                        "bias_confirmed": 1 if v5.get("bias_confirmed") else 0,
                        "composite_score": None,
                    })
            except Exception:
                pass

            # Adaptive signal
            try:
                from analysis.strategy_v4 import get_v4_analysis
                from analysis.strategy_v5 import get_v5_analysis, adaptive_strategy_score
                v4 = get_v4_analysis(df)
                v5 = get_v5_analysis(df)

                # Get regime
                regime = "range_quiet"
                try:
                    from analysis.indicators import calculate_all_indicators
                    import numpy as np
                    ind = calculate_all_indicators(df)
                    adx = ind["adx"].iloc[-1] if "adx" in ind.columns else 20
                    if not np.isnan(adx):
                        ret_std = df["close"].pct_change().tail(60).std() * (252 ** 0.5)
                        if adx >= 25:
                            regime = "trend_explosive" if ret_std > 0.3 else "trend_mild"
                        else:
                            regime = "range_volatile" if ret_std > 0.25 else "range_quiet"
                except Exception:
                    pass

                adaptive = adaptive_strategy_score(
                    v4_signal=v4["signal"],
                    v5_signal=v5["signal"],
                    regime=regime,
                    v4_confidence=1.0,
                    v5_bias_confirmed=v5.get("bias_confirmed", False),
                )
                if adaptive["final_signal"] == "BUY":
                    results.append({
                        "code": code,
                        "strategy": "Adaptive",
                        "signal_price": current_price,
                        "entry_type": f"regime={regime}",
                        "bias_confirmed": 1 if v5.get("bias_confirmed") else 0,
                        "composite_score": adaptive["composite_score"],
                    })

                # Attach regime to all results for this stock
                for r in results:
                    r["regime"] = regime

            except Exception:
                for r in results:
                    r.setdefault("regime", "range_quiet")

        except Exception as e:
            logger.warning(f"Signal scan failed for {code}: {e}")

        return results

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        all_results = list(executor.map(_scan_stock, list(stocks.keys())))

    # Flatten and write to SQLite
    conn = sqlite3.connect(str(DB_PATH))
    for stock_signals in all_results:
        for sig in stock_signals:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO forward_signals
                    (signal_date, code, strategy, signal_price, entry_type,
                     bias_confirmed, regime, composite_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    today, sig["code"], sig["strategy"], sig["signal_price"],
                    sig.get("entry_type", ""), sig.get("bias_confirmed", 0),
                    sig.get("regime", ""), sig.get("composite_score"),
                ))
                signals_recorded.append(sig)
            except Exception as e:
                logger.warning(f"Failed to record signal: {e}")

    conn.commit()
    conn.close()

    return {
        "date": today,
        "total_signals": len(signals_recorded),
        "by_strategy": {
            "V4": sum(1 for s in signals_recorded if s["strategy"] == "V4"),
            "V5": sum(1 for s in signals_recorded if s["strategy"] == "V5"),
            "Adaptive": sum(1 for s in signals_recorded if s["strategy"] == "Adaptive"),
        },
        "signals": [
            {"code": s["code"], "strategy": s["strategy"], "price": s["signal_price"]}
            for s in signals_recorded
        ],
    }


def fill_forward_returns(lookback_days: int = 10) -> dict:
    """Fill in forward returns for signals that have enough days elapsed.

    Checks signals from the last `lookback_days` that haven't been filled yet,
    and computes 1/3/5 day returns + max gain/drawdown.

    Returns:
        dict with fill results summary
    """
    _init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    # Get unfilled signals that are at least 5 trading days old
    min_date = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d")  # ~5 trading days
    rows = conn.execute("""
        SELECT id, signal_date, code, strategy, signal_price
        FROM forward_signals
        WHERE filled_at IS NULL AND signal_date >= ? AND signal_date <= ?
    """, (cutoff, min_date)).fetchall()

    filled = 0
    errors = 0

    for row in rows:
        try:
            from data.fetcher import get_stock_data
            df = get_stock_data(row["code"], period_days=30)
            if df is None or len(df) < 5:
                continue

            signal_date = row["signal_date"]
            signal_price = row["signal_price"]

            # Find signal date index
            date_idx = None
            for i, d in enumerate(df.index):
                if d.strftime("%Y-%m-%d") == signal_date:
                    date_idx = i
                    break

            if date_idx is None:
                # Signal date not in data, try closest match
                continue

            remaining = len(df) - date_idx - 1
            if remaining < 5:
                continue  # Not enough days yet

            # Compute returns
            prices = df["close"].iloc[date_idx + 1: date_idx + 6].values
            highs = df["high"].iloc[date_idx + 1: date_idx + 6].values
            lows = df["low"].iloc[date_idx + 1: date_idx + 6].values

            d1_ret = (prices[0] / signal_price - 1) if len(prices) >= 1 else None
            d3_ret = (prices[2] / signal_price - 1) if len(prices) >= 3 else None
            d5_ret = (prices[4] / signal_price - 1) if len(prices) >= 5 else None

            max_gain = (max(highs) / signal_price - 1) if len(highs) > 0 else 0
            max_dd = (min(lows) / signal_price - 1) if len(lows) > 0 else 0

            conn.execute("""
                UPDATE forward_signals SET
                    d1_return = ?, d3_return = ?, d5_return = ?,
                    max_gain_5d = ?, max_drawdown_5d = ?,
                    filled_at = ?
                WHERE id = ?
            """, (d1_ret, d3_ret, d5_ret, round(max_gain, 6), round(max_dd, 6),
                  datetime.now().isoformat(), row["id"]))
            filled += 1

        except Exception as e:
            logger.warning(f"Fill failed for signal {row['id']}: {e}")
            errors += 1

    conn.commit()
    conn.close()

    return {
        "checked": len(rows),
        "filled": filled,
        "errors": errors,
    }


def get_signal_performance(
    days: int = 30,
    strategy: str | None = None,
    code: str | None = None,
) -> list[dict]:
    """Query signal performance history.

    Args:
        days: How many days back to look
        strategy: Filter by strategy ("V4", "V5", "Adaptive")
        code: Filter by stock code

    Returns:
        List of signal records with forward returns
    """
    _init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    query = "SELECT * FROM forward_signals WHERE signal_date >= ?"
    params: list = [cutoff]

    if strategy:
        query += " AND strategy = ?"
        params.append(strategy)
    if code:
        query += " AND code = ?"
        params.append(code)

    query += " ORDER BY signal_date DESC, code"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [dict(r) for r in rows]


def get_strategy_accuracy(days: int = 60) -> dict:
    """Compute win rate and average return by strategy.

    Only considers signals where forward returns have been filled.

    Returns:
        dict with per-strategy accuracy metrics
    """
    _init_db()
    conn = sqlite3.connect(str(DB_PATH))

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    strategies = {}
    for strat in ["V4", "V5", "Adaptive"]:
        rows = conn.execute("""
            SELECT d1_return, d3_return, d5_return, max_gain_5d, max_drawdown_5d
            FROM forward_signals
            WHERE signal_date >= ? AND strategy = ? AND filled_at IS NOT NULL
        """, (cutoff, strat)).fetchall()

        if not rows:
            strategies[strat] = {
                "total_signals": 0,
                "filled": 0,
                "win_rate_5d": None,
                "avg_return_5d": None,
                "avg_max_gain": None,
                "avg_max_dd": None,
            }
            continue

        d5_returns = [r[2] for r in rows if r[2] is not None]
        max_gains = [r[3] for r in rows if r[3] is not None]
        max_dds = [r[4] for r in rows if r[4] is not None]

        wins = sum(1 for r in d5_returns if r > 0)

        strategies[strat] = {
            "total_signals": len(rows),
            "filled": len(d5_returns),
            "win_rate_5d": round(wins / len(d5_returns), 3) if d5_returns else None,
            "avg_return_5d": round(sum(d5_returns) / len(d5_returns), 4) if d5_returns else None,
            "avg_max_gain": round(sum(max_gains) / len(max_gains), 4) if max_gains else None,
            "avg_max_dd": round(sum(max_dds) / len(max_dds), 4) if max_dds else None,
        }

    # Total unfilled count
    unfilled = conn.execute("""
        SELECT COUNT(*) FROM forward_signals WHERE filled_at IS NULL AND signal_date >= ?
    """, (cutoff,)).fetchone()[0]

    conn.close()

    return {
        "period_days": days,
        "strategies": strategies,
        "pending_fill": unfilled,
    }


def get_signal_decay(days: int = 90) -> dict:
    """Compute signal decay curves: avg return at day 1, 3, 5 post-signal.

    Groups by strategy. Returns data suitable for line chart visualization.
    Gemini R40: "Signal Decay Analysis" — tells Joe when a signal's edge expires.

    Returns:
        dict with per-strategy decay curve data
    """
    _init_db()
    conn = sqlite3.connect(str(DB_PATH))

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    result = {}
    for strat in ["V4", "V5", "Adaptive"]:
        rows = conn.execute("""
            SELECT d1_return, d3_return, d5_return, max_gain_5d, max_drawdown_5d,
                   bias_confirmed, regime
            FROM forward_signals
            WHERE signal_date >= ? AND strategy = ? AND filled_at IS NOT NULL
        """, (cutoff, strat)).fetchall()

        if not rows:
            result[strat] = {
                "sample_count": 0,
                "decay_curve": [],
                "bias_decay_curve": [],
            }
            continue

        # Compute avg return at each time point
        d1 = [r[0] for r in rows if r[0] is not None]
        d3 = [r[1] for r in rows if r[1] is not None]
        d5 = [r[2] for r in rows if r[2] is not None]
        gains = [r[3] for r in rows if r[3] is not None]
        dds = [r[4] for r in rows if r[4] is not None]

        decay_curve = []
        if d1:
            decay_curve.append({"day": 1, "avg_return": round(sum(d1) / len(d1), 5), "n": len(d1)})
        if d3:
            decay_curve.append({"day": 3, "avg_return": round(sum(d3) / len(d3), 5), "n": len(d3)})
        if d5:
            decay_curve.append({"day": 5, "avg_return": round(sum(d5) / len(d5), 5), "n": len(d5)})

        # BIAS-confirmed subset (V5 only meaningful)
        bias_rows = [r for r in rows if r[5] == 1]
        bias_decay = []
        if bias_rows:
            bd1 = [r[0] for r in bias_rows if r[0] is not None]
            bd3 = [r[1] for r in bias_rows if r[1] is not None]
            bd5 = [r[2] for r in bias_rows if r[2] is not None]
            if bd1:
                bias_decay.append({"day": 1, "avg_return": round(sum(bd1) / len(bd1), 5), "n": len(bd1)})
            if bd3:
                bias_decay.append({"day": 3, "avg_return": round(sum(bd3) / len(bd3), 5), "n": len(bd3)})
            if bd5:
                bias_decay.append({"day": 5, "avg_return": round(sum(bd5) / len(bd5), 5), "n": len(bd5)})

        result[strat] = {
            "sample_count": len(rows),
            "avg_max_gain": round(sum(gains) / len(gains), 5) if gains else None,
            "avg_max_dd": round(sum(dds) / len(dds), 5) if dds else None,
            "decay_curve": decay_curve,
            "bias_decay_curve": bias_decay,
        }

    conn.close()
    return {"period_days": days, "strategies": result}

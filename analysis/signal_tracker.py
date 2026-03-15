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


def _find_date_index(df, date_str: str) -> int | None:
    """Find the index of a date string in a DataFrame index."""
    for i, d in enumerate(df.index):
        if d.strftime("%Y-%m-%d") == date_str:
            return i
    return None


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
            d10_return REAL,
            d20_return REAL,
            max_gain_5d REAL,
            max_drawdown_5d REAL,
            max_gain_20d REAL,
            max_drawdown_20d REAL,
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
    # Migration: add d10/d20 columns to existing tables (Gemini R41)
    for col in ["d10_return", "d20_return", "max_gain_20d", "max_drawdown_20d"]:
        try:
            conn.execute(f"ALTER TABLE forward_signals ADD COLUMN {col} REAL")
        except sqlite3.OperationalError:
            pass  # Column already exists
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
        """Scan a single stock for V4/V5/Adaptive signals.

        Only records signals for strategies listed in ACTIVE_STRATEGIES.
        """
        from config import ACTIVE_STRATEGIES

        results = []
        try:
            from data.fetcher import get_stock_data
            df = get_stock_data(code, period_days=365)
            if df is None or len(df) < 60:
                return results

            current_price = float(df["close"].iloc[-1])

            # V4 signal
            if "v4" in ACTIVE_STRATEGIES:
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
                except Exception as e:
                    logger.debug(f"V4 signal scan failed for {code}: {e}")

            # V5 signal
            if "v5" in ACTIVE_STRATEGIES:
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
                except Exception as e:
                    logger.debug(f"V5 signal scan failed for {code}: {e}")

            # Adaptive signal
            if "adaptive" in ACTIVE_STRATEGIES:
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
                    except Exception as e:
                        logger.debug(f"Regime detection failed for {code}: {e}")

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

                except Exception as e:
                    logger.debug(f"Adaptive signal scan failed for {code}: {e}")
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


def fill_forward_returns(lookback_days: int = 45) -> dict:
    """Fill in forward returns for signals that have enough days elapsed.

    Two-pass approach (Gemini R41: 20-day tracking):
    - Pass 1: Fill d1/d3/d5 + max_gain/dd_5d for signals ≥8 calendar days old (unfilled)
    - Pass 2: Fill d10/d20 + max_gain/dd_20d for signals ≥30 calendar days old (d20 still NULL)

    Returns:
        dict with fill results summary
    """
    _init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    filled_short = 0
    filled_long = 0
    errors = 0

    # === Pass 1: Fill d1/d3/d5 (signals ≥8 days old, not yet filled) ===
    min_date_short = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d")
    short_rows = conn.execute("""
        SELECT id, signal_date, code, strategy, signal_price
        FROM forward_signals
        WHERE filled_at IS NULL AND signal_date >= ? AND signal_date <= ?
    """, (cutoff, min_date_short)).fetchall()

    for row in short_rows:
        try:
            from data.fetcher import get_stock_data
            df = get_stock_data(row["code"], period_days=60)
            if df is None or len(df) < 5:
                continue

            date_idx = _find_date_index(df, row["signal_date"])
            if date_idx is None:
                continue

            remaining = len(df) - date_idx - 1
            if remaining < 5:
                continue

            signal_price = row["signal_price"]
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
            filled_short += 1
        except Exception as e:
            logger.warning(f"Fill (short) failed for signal {row['id']}: {e}")
            errors += 1

    # === Pass 2: Fill d10/d20 (signals ≥30 days old, d20 still NULL) ===
    min_date_long = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    long_rows = conn.execute("""
        SELECT id, signal_date, code, strategy, signal_price
        FROM forward_signals
        WHERE d20_return IS NULL AND filled_at IS NOT NULL
              AND signal_date >= ? AND signal_date <= ?
    """, (cutoff, min_date_long)).fetchall()

    for row in long_rows:
        try:
            from data.fetcher import get_stock_data
            df = get_stock_data(row["code"], period_days=60)
            if df is None or len(df) < 20:
                continue

            date_idx = _find_date_index(df, row["signal_date"])
            if date_idx is None:
                continue

            remaining = len(df) - date_idx - 1
            if remaining < 20:
                continue

            signal_price = row["signal_price"]
            prices_20 = df["close"].iloc[date_idx + 1: date_idx + 21].values
            highs_20 = df["high"].iloc[date_idx + 1: date_idx + 21].values
            lows_20 = df["low"].iloc[date_idx + 1: date_idx + 21].values

            d10_ret = (prices_20[9] / signal_price - 1) if len(prices_20) >= 10 else None
            d20_ret = (prices_20[19] / signal_price - 1) if len(prices_20) >= 20 else None
            max_gain_20 = (max(highs_20) / signal_price - 1) if len(highs_20) > 0 else 0
            max_dd_20 = (min(lows_20) / signal_price - 1) if len(lows_20) > 0 else 0

            conn.execute("""
                UPDATE forward_signals SET
                    d10_return = ?, d20_return = ?,
                    max_gain_20d = ?, max_drawdown_20d = ?
                WHERE id = ?
            """, (d10_ret, d20_ret, round(max_gain_20, 6), round(max_dd_20, 6), row["id"]))
            filled_long += 1
        except Exception as e:
            logger.warning(f"Fill (long) failed for signal {row['id']}: {e}")
            errors += 1

    conn.commit()
    conn.close()

    return {
        "checked_short": len(short_rows),
        "filled_short": filled_short,
        "checked_long": len(long_rows),
        "filled_long": filled_long,
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


def _avg(vals: list) -> float | None:
    return round(sum(vals) / len(vals), 5) if vals else None


def _decay_points(rows, signal_price_idx=None) -> list[dict]:
    """Build decay curve data points from row tuples.

    rows: list of tuples (d1, d3, d5, d10, d20, ...)
    """
    labels = [(0, 1, "d1"), (1, 3, "d3"), (2, 5, "d5"), (3, 10, "d10"), (4, 20, "d20")]
    curve = []
    for col_idx, day, _name in labels:
        vals = [r[col_idx] for r in rows if r[col_idx] is not None]
        if vals:
            curve.append({"day": day, "avg_return": _avg(vals), "n": len(vals)})
    return curve


def get_signal_decay(days: int = 90) -> dict:
    """Compute signal decay curves: avg return at day 1, 3, 5, 10, 20 post-signal.

    Gemini R40→R41: Extended to 20-day tracking + EV calculation.
    EV = (Win% × Avg_Gain) - (Loss% × Avg_Loss) at each time point.

    Returns:
        dict with per-strategy decay curve data + EV
    """
    _init_db()
    conn = sqlite3.connect(str(DB_PATH))

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    result = {}
    for strat in ["V4", "V5", "Adaptive"]:
        rows = conn.execute("""
            SELECT d1_return, d3_return, d5_return, d10_return, d20_return,
                   max_gain_5d, max_drawdown_5d, max_gain_20d, max_drawdown_20d,
                   bias_confirmed, regime
            FROM forward_signals
            WHERE signal_date >= ? AND strategy = ? AND filled_at IS NOT NULL
        """, (cutoff, strat)).fetchall()

        if not rows:
            result[strat] = {
                "sample_count": 0,
                "decay_curve": [],
                "bias_decay_curve": [],
                "ev": {},
            }
            continue

        # Decay curve (d1, d3, d5, d10, d20)
        decay_curve = _decay_points(rows)

        # 5d and 20d gain/dd
        gains_5 = [r[5] for r in rows if r[5] is not None]
        dds_5 = [r[6] for r in rows if r[6] is not None]
        gains_20 = [r[7] for r in rows if r[7] is not None]
        dds_20 = [r[8] for r in rows if r[8] is not None]

        # Compute EV at d5 and d20 (Gemini R41, R42: + Net EV)
        from analysis.scoring import TRANSACTION_COST
        ev = {}
        for day_col, day_label in [(2, "d5"), (4, "d20")]:
            rets = [r[day_col] for r in rows if r[day_col] is not None]
            if rets:
                wins = [r for r in rets if r > 0]
                losses = [r for r in rets if r <= 0]
                win_pct = len(wins) / len(rets)
                avg_win = sum(wins) / len(wins) if wins else 0
                avg_loss = abs(sum(losses) / len(losses)) if losses else 0
                raw_ev = round(win_pct * avg_win - (1 - win_pct) * avg_loss, 5)
                net_ev = round(raw_ev - TRANSACTION_COST, 5)
                ev[day_label] = {
                    "win_pct": round(win_pct, 4),
                    "avg_win": round(avg_win, 5),
                    "avg_loss": round(avg_loss, 5),
                    "ev": raw_ev,
                    "net_ev": net_ev,
                    "cost_drag": TRANSACTION_COST,
                    "cost_trap": raw_ev > 0 and net_ev < 0,
                    "n": len(rets),
                }

        # BIAS-confirmed subset
        bias_rows = [r for r in rows if r[9] == 1]  # bias_confirmed col
        bias_decay = _decay_points(bias_rows) if bias_rows else []

        result[strat] = {
            "sample_count": len(rows),
            "avg_max_gain_5d": _avg(gains_5),
            "avg_max_dd_5d": _avg(dds_5),
            "avg_max_gain_20d": _avg(gains_20),
            "avg_max_dd_20d": _avg(dds_20),
            "decay_curve": decay_curve,
            "bias_decay_curve": bias_decay,
            "ev": ev,
        }

    conn.close()
    return {"period_days": days, "strategies": result}


def get_stock_signal_summary(code: str, days: int = 180) -> dict:
    """Per-stock signal performance summary for TechnicalView overlay (Gemini R41).

    Returns win rate, EV, avg return at d5/d20, sample count per strategy.
    """
    _init_db()
    conn = sqlite3.connect(str(DB_PATH))
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    rows = conn.execute("""
        SELECT strategy, d5_return, d10_return, d20_return,
               max_gain_5d, max_drawdown_5d, max_gain_20d, max_drawdown_20d,
               signal_date, signal_price
        FROM forward_signals
        WHERE code = ? AND signal_date >= ? AND filled_at IS NOT NULL
        ORDER BY signal_date DESC
    """, (code, cutoff)).fetchall()

    conn.close()

    if not rows:
        return {"code": code, "has_data": False, "strategies": {}}

    result: dict = {}
    for strat in ["V4", "V5", "Adaptive"]:
        strat_rows = [r for r in rows if r[0] == strat]
        if not strat_rows:
            continue

        d5_vals = [r[1] for r in strat_rows if r[1] is not None]
        d20_vals = [r[3] for r in strat_rows if r[3] is not None]

        # Win rate at d5
        wins_5 = sum(1 for v in d5_vals if v > 0) if d5_vals else 0
        win_rate_5 = wins_5 / len(d5_vals) if d5_vals else None

        # EV at d5
        ev_5 = None
        if d5_vals:
            w = [v for v in d5_vals if v > 0]
            l = [v for v in d5_vals if v <= 0]
            wp = len(w) / len(d5_vals)
            aw = sum(w) / len(w) if w else 0
            al = abs(sum(l) / len(l)) if l else 0
            ev_5 = round(wp * aw - (1 - wp) * al, 5)

        # EV at d20
        ev_20 = None
        if d20_vals:
            w = [v for v in d20_vals if v > 0]
            l = [v for v in d20_vals if v <= 0]
            wp = len(w) / len(d20_vals)
            aw = sum(w) / len(w) if w else 0
            al = abs(sum(l) / len(l)) if l else 0
            ev_20 = round(wp * aw - (1 - wp) * al, 5)

        # Recent signals (last 5)
        recent = [
            {"date": r[8], "price": r[9], "d5_return": r[1], "d20_return": r[3]}
            for r in strat_rows[:5]
        ]

        result[strat] = {
            "sample_count": len(strat_rows),
            "win_rate_5d": round(win_rate_5, 3) if win_rate_5 is not None else None,
            "avg_return_5d": _avg(d5_vals),
            "avg_return_20d": _avg(d20_vals),
            "ev_5d": ev_5,
            "ev_20d": ev_20,
            "avg_max_gain_5d": _avg([r[4] for r in strat_rows if r[4] is not None]),
            "avg_max_dd_5d": _avg([r[5] for r in strat_rows if r[5] is not None]),
            "recent_signals": recent,
        }

    return {"code": code, "has_data": True, "strategies": result}

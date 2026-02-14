"""Strategy Fitness Engine — 策略適配度引擎（Gemini R38）

為每檔股票預先計算 V4/V5/Adaptive 的 Profit Factor，產生 Strategy Fitness Tags：
- "Trend Preferred (V4)" — V4 PF 顯著優於 V5
- "Volatility Preferred (V5)" — V5 PF 顯著優於 V4
- "Balanced" — 兩者相近

儲存於 SQLite，供前端快速查詢，避免即時計算延遲。
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "strategy_fitness.db"

# Profit Factor ratio threshold for tagging
PF_DOMINANCE_RATIO = 1.2  # V4 PF > V5 PF × 1.2 → "Trend Preferred"


def _init_db():
    """Initialize SQLite database with strategy_fitness table."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_fitness (
            code TEXT NOT NULL,
            computed_at TEXT NOT NULL,
            period_days INTEGER NOT NULL,
            v4_profit_factor REAL,
            v4_sharpe REAL,
            v4_total_return REAL,
            v4_trades INTEGER,
            v5_profit_factor REAL,
            v5_sharpe REAL,
            v5_total_return REAL,
            v5_trades INTEGER,
            adaptive_profit_factor REAL,
            adaptive_sharpe REAL,
            adaptive_total_return REAL,
            adaptive_trades INTEGER,
            fitness_tag TEXT,
            regime TEXT,
            PRIMARY KEY (code)
        )
    """)
    conn.commit()
    conn.close()


def compute_stock_fitness(code: str, period_days: int = 730) -> dict | None:
    """Compute V4/V5/Adaptive fitness metrics for a single stock.

    Returns dict with profit factors, sharpe ratios, and fitness tag,
    or None if data is insufficient.
    """
    from data.fetcher import get_stock_data
    from backtest.engine import BacktestEngine

    try:
        df = get_stock_data(code, period_days=period_days)
        if df is None or len(df) < 120:
            return None

        engine = BacktestEngine(initial_capital=1_000_000)

        # V4 backtest
        try:
            v4_result = engine.run_v4(df)
            v4_pf = v4_result.profit_factor if v4_result.total_trades > 0 else 0
            v4_sharpe = v4_result.sharpe_ratio
            v4_ret = v4_result.total_return
            v4_trades = v4_result.total_trades
        except Exception:
            v4_pf = v4_sharpe = v4_ret = 0
            v4_trades = 0

        # V5 backtest
        try:
            v5_result = engine.run_v5(df)
            v5_pf = v5_result.profit_factor if v5_result.total_trades > 0 else 0
            v5_sharpe = v5_result.sharpe_ratio
            v5_ret = v5_result.total_return
            v5_trades = v5_result.total_trades
        except Exception:
            v5_pf = v5_sharpe = v5_ret = 0
            v5_trades = 0

        # Detect regime for adaptive
        regime = "range_quiet"
        try:
            from analysis.indicators import calculate_all_indicators
            ind = calculate_all_indicators(df)
            latest_adx = ind["adx"].iloc[-1] if "adx" in ind.columns else 20
            import numpy as np
            if not np.isnan(latest_adx):
                ret_std = df["close"].pct_change().tail(60).std() * (252 ** 0.5)
                if latest_adx >= 25:
                    regime = "trend_explosive" if ret_std > 0.3 else "trend_mild"
                else:
                    regime = "range_volatile" if ret_std > 0.25 else "range_quiet"
        except Exception:
            pass

        # Adaptive backtest
        try:
            ad_result = engine.run_adaptive(df, regime=regime)
            ad_pf = ad_result.profit_factor if ad_result.total_trades > 0 else 0
            ad_sharpe = ad_result.sharpe_ratio
            ad_ret = ad_result.total_return
            ad_trades = ad_result.total_trades
        except Exception:
            ad_pf = ad_sharpe = ad_ret = 0
            ad_trades = 0

        # Determine fitness tag
        if v4_trades == 0 and v5_trades == 0:
            tag = "No Signal"
        elif v5_trades == 0:
            tag = "Trend Only (V4)"
        elif v4_trades == 0:
            tag = "Reversion Only (V5)"
        elif v4_pf > v5_pf * PF_DOMINANCE_RATIO:
            tag = "Trend Preferred (V4)"
        elif v5_pf > v4_pf * PF_DOMINANCE_RATIO:
            tag = "Volatility Preferred (V5)"
        else:
            tag = "Balanced"

        return {
            "code": code,
            "computed_at": datetime.now().isoformat(),
            "period_days": period_days,
            "v4_profit_factor": round(v4_pf, 3) if v4_pf != float("inf") else 99.0,
            "v4_sharpe": round(v4_sharpe, 3),
            "v4_total_return": round(v4_ret, 4),
            "v4_trades": v4_trades,
            "v5_profit_factor": round(v5_pf, 3) if v5_pf != float("inf") else 99.0,
            "v5_sharpe": round(v5_sharpe, 3),
            "v5_total_return": round(v5_ret, 4),
            "v5_trades": v5_trades,
            "adaptive_profit_factor": round(ad_pf, 3) if ad_pf != float("inf") else 99.0,
            "adaptive_sharpe": round(ad_sharpe, 3),
            "adaptive_total_return": round(ad_ret, 4),
            "adaptive_trades": ad_trades,
            "fitness_tag": tag,
            "regime": regime,
        }

    except Exception as e:
        logger.warning(f"Fitness compute failed for {code}: {e}")
        return None


def run_fitness_scan(
    stocks: dict[str, str] | None = None,
    period_days: int = 730,
    max_workers: int = 4,
    progress_callback=None,
) -> dict:
    """Batch compute strategy fitness for all stocks.

    Args:
        stocks: {code: name} dict, defaults to SCAN_STOCKS
        period_days: Backtest period
        max_workers: Parallel workers
        progress_callback: Optional callable(done, total) for progress updates

    Returns:
        dict with results summary
    """
    if stocks is None:
        from config import SCAN_STOCKS
        stocks = SCAN_STOCKS

    _init_db()

    codes = list(stocks.keys())
    total = len(codes)
    results = []
    failed = []
    done = 0

    def _compute(code):
        return compute_stock_fitness(code, period_days=period_days)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_compute, c): c for c in codes}
        for future in futures:
            code = futures[future]
            try:
                result = future.result(timeout=120)
                if result:
                    results.append(result)
                else:
                    failed.append(code)
            except Exception as e:
                logger.warning(f"Fitness scan timeout/error for {code}: {e}")
                failed.append(code)
            done += 1
            if progress_callback:
                progress_callback(done, total)

    # Write to SQLite
    if results:
        _save_results(results)

    # Tag distribution
    tag_counts = {}
    for r in results:
        tag = r["fitness_tag"]
        tag_counts[tag] = tag_counts.get(tag, 0) + 1

    return {
        "total": total,
        "computed": len(results),
        "failed": len(failed),
        "failed_codes": failed,
        "tag_distribution": tag_counts,
        "computed_at": datetime.now().isoformat(),
    }


def _save_results(results: list[dict]):
    """Save fitness results to SQLite (upsert)."""
    conn = sqlite3.connect(str(DB_PATH))
    for r in results:
        conn.execute("""
            INSERT OR REPLACE INTO strategy_fitness
            (code, computed_at, period_days,
             v4_profit_factor, v4_sharpe, v4_total_return, v4_trades,
             v5_profit_factor, v5_sharpe, v5_total_return, v5_trades,
             adaptive_profit_factor, adaptive_sharpe, adaptive_total_return, adaptive_trades,
             fitness_tag, regime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r["code"], r["computed_at"], r["period_days"],
            r["v4_profit_factor"], r["v4_sharpe"], r["v4_total_return"], r["v4_trades"],
            r["v5_profit_factor"], r["v5_sharpe"], r["v5_total_return"], r["v5_trades"],
            r["adaptive_profit_factor"], r["adaptive_sharpe"], r["adaptive_total_return"], r["adaptive_trades"],
            r["fitness_tag"], r["regime"],
        ))
    conn.commit()
    conn.close()


def get_fitness_tags(codes: list[str] | None = None) -> list[dict]:
    """Read fitness tags from SQLite.

    Args:
        codes: Optional filter. None = return all.

    Returns:
        List of fitness records.
    """
    _init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    if codes:
        placeholders = ",".join("?" for _ in codes)
        rows = conn.execute(
            f"SELECT * FROM strategy_fitness WHERE code IN ({placeholders}) ORDER BY code",
            codes,
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM strategy_fitness ORDER BY code"
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def get_fitness_summary() -> dict:
    """Get summary statistics of fitness data."""
    _init_db()
    conn = sqlite3.connect(str(DB_PATH))

    total = conn.execute("SELECT COUNT(*) FROM strategy_fitness").fetchone()[0]
    if total == 0:
        conn.close()
        return {"total": 0, "tag_distribution": {}, "last_computed": None}

    # Tag distribution
    rows = conn.execute(
        "SELECT fitness_tag, COUNT(*) as cnt FROM strategy_fitness GROUP BY fitness_tag ORDER BY cnt DESC"
    ).fetchall()
    tag_dist = {r[0]: r[1] for r in rows}

    # Last computed time
    last = conn.execute(
        "SELECT MAX(computed_at) FROM strategy_fitness"
    ).fetchone()[0]

    # Best performers per strategy
    best_v4 = conn.execute(
        "SELECT code, v4_profit_factor, v4_sharpe FROM strategy_fitness "
        "WHERE v4_trades > 0 ORDER BY v4_sharpe DESC LIMIT 5"
    ).fetchall()
    best_v5 = conn.execute(
        "SELECT code, v5_profit_factor, v5_sharpe FROM strategy_fitness "
        "WHERE v5_trades > 0 ORDER BY v5_sharpe DESC LIMIT 5"
    ).fetchall()

    conn.close()

    return {
        "total": total,
        "tag_distribution": tag_dist,
        "last_computed": last,
        "top_v4": [{"code": r[0], "pf": r[1], "sharpe": r[2]} for r in best_v4],
        "top_v5": [{"code": r[0], "pf": r[1], "sharpe": r[2]} for r in best_v5],
    }

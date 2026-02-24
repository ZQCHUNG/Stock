"""Financial Screener Indicator Engine.

Phase 1: 財報狗-style screening with pre-computed snapshot tables.
Architecture approved by CTO/PM Gemini (2026-02-24).

Data flow:
  TWSE/TPEX APIs → Raw data → Indicator Engine → SQLite snapshots → FastAPI → Vue UI

Tables:
  - screening_latest: One row per stock with latest metrics (main query table)
  - quarterly_snapshot: Historical quarterly financials
  - daily_snapshot: Historical daily price/volume/chip data
  - data_sync_log: ETL tracking

SQLite with WAL mode for zero-ops deployment (no PostgreSQL needed).
"""

import sqlite3
import logging
from pathlib import Path
from datetime import datetime, date, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "screener.db"


# ─── Database Setup ───────────────────────────────────────────────


def get_db() -> sqlite3.Connection:
    """Get SQLite connection with WAL mode."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables and indexes."""
    conn = get_db()
    conn.executescript("""
    -- Latest screening snapshot (one row per stock, main query table)
    CREATE TABLE IF NOT EXISTS screening_latest (
        code TEXT PRIMARY KEY,
        name TEXT,
        market TEXT,
        industry TEXT,
        -- Price & Volume
        close REAL,
        change_pct REAL,
        volume_avg_20d REAL,
        market_cap REAL,
        -- Valuation
        pe REAL,
        pb REAL,
        dividend_yield REAL,
        yield_3y_avg REAL,
        yield_5y_avg REAL,
        -- Profitability (latest quarter)
        gross_margin REAL,
        operating_margin REAL,
        pretax_margin REAL,
        net_margin REAL,
        roe REAL,
        roa REAL,
        -- Safety
        debt_ratio REAL,
        current_ratio REAL,
        quick_ratio REAL,
        interest_coverage REAL,
        ocf_to_debt REAL,
        ocf_to_net_income REAL,
        -- Financials
        eps REAL,
        bps REAL,
        revenue_per_share REAL,
        fcf_per_share REAL,
        cash_dividend REAL,
        stock_dividend REAL,
        dividend_payout_ratio REAL,
        -- Growth
        revenue_yoy REAL,
        revenue_mom REAL,
        operating_income_yoy REAL,
        eps_yoy REAL,
        roe_yoy REAL,
        -- Turnover
        receivable_turnover REAL,
        inventory_turnover REAL,
        asset_turnover REAL,
        operating_cycle_days REAL,
        -- Chip (籌碼)
        foreign_holding_pct REAL,
        trust_5d_net REAL,
        margin_util REAL,
        broker_net_buy REAL,
        tdcc_concentration REAL,
        -- Technical
        rs_rating REAL,
        rs_rank_pct REAL,
        ma5_ratio REAL,
        ma20_ratio REAL,
        ma60_ratio REAL,
        rsi_14 REAL,
        atr_pct REAL,
        -- Consecutive Flags
        revenue_consecutive_up INTEGER DEFAULT 0,
        revenue_consecutive_down INTEGER DEFAULT 0,
        eps_consecutive_up INTEGER DEFAULT 0,
        -- Meta
        latest_fiscal_quarter TEXT,
        updated_at TEXT
    );

    -- Quarterly financials (history for trend analysis)
    CREATE TABLE IF NOT EXISTS quarterly_snapshot (
        code TEXT NOT NULL,
        fiscal_year INTEGER NOT NULL,
        fiscal_quarter INTEGER NOT NULL,
        announcement_date TEXT,
        -- Profitability
        gross_margin REAL,
        operating_margin REAL,
        pretax_margin REAL,
        net_margin REAL,
        roe REAL,
        roa REAL,
        -- Safety
        debt_ratio REAL,
        current_ratio REAL,
        quick_ratio REAL,
        interest_coverage REAL,
        ocf_to_debt REAL,
        -- Financials
        eps REAL,
        bps REAL,
        revenue REAL,
        operating_income REAL,
        net_income REAL,
        fcf REAL,
        cash_dividend REAL,
        stock_dividend REAL,
        -- Turnover
        receivable_turnover REAL,
        inventory_turnover REAL,
        asset_turnover REAL,
        -- Growth (vs same quarter last year)
        revenue_yoy REAL,
        operating_income_yoy REAL,
        eps_yoy REAL,
        roe_yoy REAL,
        PRIMARY KEY (code, fiscal_year, fiscal_quarter)
    );

    -- Daily snapshot (price + chip, for rankings & time-series)
    CREATE TABLE IF NOT EXISTS daily_snapshot (
        code TEXT NOT NULL,
        date TEXT NOT NULL,
        close REAL,
        volume REAL,
        change_pct REAL,
        pe REAL,
        pb REAL,
        dividend_yield REAL,
        -- Technical
        ma5_ratio REAL,
        ma20_ratio REAL,
        ma60_ratio REAL,
        rsi_14 REAL,
        atr_pct REAL,
        rs_rating REAL,
        -- Chip
        foreign_net REAL,
        trust_net REAL,
        dealer_net REAL,
        margin_util REAL,
        PRIMARY KEY (code, date)
    );

    -- ETL tracking
    CREATE TABLE IF NOT EXISTS data_sync_log (
        task_name TEXT PRIMARY KEY,
        last_updated TEXT,
        status TEXT,
        row_count INTEGER DEFAULT 0
    );

    -- Indexes for common screening queries
    CREATE INDEX IF NOT EXISTS idx_scr_pe ON screening_latest(pe);
    CREATE INDEX IF NOT EXISTS idx_scr_roe ON screening_latest(roe);
    CREATE INDEX IF NOT EXISTS idx_scr_yield ON screening_latest(dividend_yield);
    CREATE INDEX IF NOT EXISTS idx_scr_revenue_yoy ON screening_latest(revenue_yoy);
    CREATE INDEX IF NOT EXISTS idx_scr_rs ON screening_latest(rs_rating);
    CREATE INDEX IF NOT EXISTS idx_scr_mcap ON screening_latest(market_cap);
    CREATE INDEX IF NOT EXISTS idx_scr_industry ON screening_latest(industry);
    CREATE INDEX IF NOT EXISTS idx_scr_main ON screening_latest(
        market_cap, pe, roe, rs_rating, gross_margin
    );
    CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_snapshot(date);
    """)
    conn.commit()
    conn.close()
    logger.info("Screener DB initialized at %s", DB_PATH)


# ─── Data Loaders (Batch-optimized) ──────────────────────────────


def _load_close_matrix() -> pd.DataFrame:
    """Load pre-computed close price matrix (1900+ stocks × 790 days)."""
    path = Path(__file__).parent.parent / "data" / "pit_close_matrix.parquet"
    if path.exists():
        try:
            return pd.read_parquet(path)
        except Exception as e:
            logger.warning("Failed to load close matrix: %s", e)
    return pd.DataFrame()


def _load_rs_percentile() -> pd.Series:
    """Load latest RS percentile for all stocks (0-100 scale)."""
    path = Path(__file__).parent.parent / "data" / "pit_rs_percentile.parquet"
    if path.exists():
        try:
            df = pd.read_parquet(path)
            if not df.empty:
                return df.iloc[-1]
        except Exception as e:
            logger.warning("Failed to load RS percentile: %s", e)
    return pd.Series(dtype=float)


def _load_valuation_data() -> pd.DataFrame:
    """Load latest PE/PB/yield from TWSE scraper."""
    try:
        from data.twse_scraper import fetch_valuation_all
        df = fetch_valuation_all(None)
        if df is not None and not df.empty:
            return df
    except Exception as e:
        logger.warning("Failed to load valuation: %s", e)
    return pd.DataFrame()


def _parse_revenue_number(s) -> float | None:
    """Parse revenue string like '14,219,975' to float."""
    if s is None:
        return None
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _load_revenue_data() -> pd.DataFrame:
    """Load recent monthly revenue for all stocks from cached JSON files.

    Uses data/pattern_data/raw/revenue/ (fetched by fetch_revenue.py).
    Format: {year_minguo, month, market, data: [{code, revenue, prev_year, mom_pct, ...}]}

    Note: yoy_pct field is mislabeled in source data (contains cumulative revenue).
    We compute YoY manually from revenue and prev_year fields.
    """
    import json

    rev_dir = Path(__file__).parent.parent / "data" / "pattern_data" / "raw" / "revenue"
    if not rev_dir.exists():
        logger.warning("Revenue data directory not found: %s", rev_dir)
        return pd.DataFrame()

    # Find the latest 2 months of data for each market (sii + otc)
    files = sorted(rev_dir.glob("*.json"), reverse=True)  # Latest first
    if not files:
        return pd.DataFrame()

    records = []
    seen_months = set()  # Track (market, year, month) to get latest only

    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not isinstance(data, dict) or "data" not in data:
            continue

        year_minguo = data.get("year_minguo", 0)
        month = data.get("month", 0)
        market = data.get("market", "")
        western_year = year_minguo + 1911

        key = (market, western_year, month)
        if key in seen_months:
            continue

        # Only load recent 13 months for YoY + consecutive calculation
        if len(seen_months) >= 26:  # 13 months × 2 markets
            break

        seen_months.add(key)

        for item in data.get("data", []):
            code = str(item.get("code", "")).strip()
            if not code or len(code) < 4:
                continue

            revenue = _parse_revenue_number(item.get("revenue"))
            prev_year = _parse_revenue_number(item.get("prev_year"))
            mom_pct_str = item.get("mom_pct")

            # Compute YoY manually (yoy_pct field is mislabeled)
            revenue_yoy = None
            if revenue is not None and prev_year is not None and prev_year > 0:
                revenue_yoy = (revenue / prev_year - 1) * 100  # as percentage

            revenue_mom = None
            if mom_pct_str is not None:
                try:
                    revenue_mom = float(str(mom_pct_str).replace(",", "").strip())
                except (ValueError, TypeError):
                    pass

            records.append({
                "code": code,
                "year": western_year,
                "month": month,
                "revenue": revenue,
                "revenue_yoy": revenue_yoy,
                "revenue_mom": revenue_mom,
            })

    if records:
        df = pd.DataFrame(records)
        logger.info("Loaded %d revenue records from %d months", len(df), len(seen_months))
        return df

    return pd.DataFrame()


def _load_stock_list() -> dict:
    """Load all stocks with metadata."""
    try:
        from data.stock_list import get_all_stocks
        return get_all_stocks()
    except Exception:
        from config import SCAN_STOCKS
        return {c: {"name": n, "market": ""} for c, n in SCAN_STOCKS.items()}


def _load_sector_mapping():
    """Load stock → sector mapping function."""
    try:
        from data.sector_mapping import get_stock_sector
        return get_stock_sector
    except Exception:
        return lambda code, level=1: "未分類"


# ─── Technical Indicator Computation ──────────────────────────────


def compute_technical_from_close(closes: pd.Series) -> dict:
    """Compute technical indicators from a close price series.

    Works with close-only data (no OHLCV needed). For ATR% we use
    close-to-close volatility as proxy.
    """
    if closes is None or len(closes) < 20:
        return {}

    c = closes.dropna().astype(float)
    if len(c) < 20:
        return {}

    latest_close = float(c.iloc[-1])
    prev_close = float(c.iloc[-2]) if len(c) > 1 else latest_close

    # MA ratios
    ma5 = c.rolling(5).mean()
    ma20 = c.rolling(20).mean()
    ma60 = c.rolling(60).mean()

    # RSI(14)
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss = (-delta).clip(lower=0).ewm(span=14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)

    # ATR% proxy: 14-day average of |daily return| (close-to-close)
    daily_ret = c.pct_change().abs()
    atr_pct = float(daily_ret.rolling(14).mean().iloc[-1]) if len(c) > 14 else None

    return {
        "close": latest_close,
        "change_pct": (latest_close / prev_close - 1) if prev_close > 0 else 0,
        "ma5_ratio": float(latest_close / ma5.iloc[-1]) if pd.notna(ma5.iloc[-1]) and ma5.iloc[-1] > 0 else None,
        "ma20_ratio": float(latest_close / ma20.iloc[-1]) if pd.notna(ma20.iloc[-1]) and ma20.iloc[-1] > 0 else None,
        "ma60_ratio": float(latest_close / ma60.iloc[-1]) if len(c) >= 60 and pd.notna(ma60.iloc[-1]) and ma60.iloc[-1] > 0 else None,
        "rsi_14": float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else None,
        "atr_pct": float(atr_pct) if atr_pct is not None and pd.notna(atr_pct) else None,
    }


# ─── Revenue Consecutive Computation ─────────────────────────────


def compute_revenue_consecutive(revenue_df: pd.DataFrame, code: str) -> dict:
    """Compute consecutive months of revenue increase/decrease."""
    if revenue_df.empty:
        return {"revenue_consecutive_up": 0, "revenue_consecutive_down": 0}

    stock_rev = revenue_df[revenue_df["code"] == code].copy()
    if stock_rev.empty or "revenue_yoy" not in stock_rev.columns:
        return {"revenue_consecutive_up": 0, "revenue_consecutive_down": 0}

    stock_rev = stock_rev.sort_values(["year", "month"])
    yoys = stock_rev["revenue_yoy"].dropna().values

    if len(yoys) == 0:
        return {"revenue_consecutive_up": 0, "revenue_consecutive_down": 0}

    # Count from most recent backwards
    consec_up = 0
    consec_down = 0

    for val in reversed(yoys):
        if val > 0:
            if consec_down > 0:
                break
            consec_up += 1
        elif val < 0:
            if consec_up > 0:
                break
            consec_down += 1
        else:
            break

    return {
        "revenue_consecutive_up": consec_up,
        "revenue_consecutive_down": consec_down,
    }


# ─── Safe Growth Rate ────────────────────────────────────────────


def safe_yoy(current, previous):
    """Compute YoY growth rate, handling negative base."""
    if previous is None or current is None:
        return None
    if previous == 0:
        return None
    if previous < 0 and current > 0:
        return None  # Turnaround — not a meaningful %
    if previous < 0 and current < 0:
        return (current / previous - 1) * -1  # Improvement shown as positive
    return (current / previous) - 1


# ─── Main Refresh Logic ──────────────────────────────────────────


def refresh_screening_data(progress_callback=None):
    """Refresh the screening_latest table with current data.

    Batch-optimized: loads parquet matrices once, computes everything
    vectorized. Typical runtime: 5-15 seconds for 1900+ stocks.
    """
    import time
    t0 = time.time()

    init_db()
    conn = get_db()

    if progress_callback:
        progress_callback(0, 100, "Loading stock list...")

    all_stocks = _load_stock_list()
    get_sector = _load_sector_mapping()

    if progress_callback:
        progress_callback(10, 100, "Loading close matrix...")

    # 1. Batch load close prices (1900+ stocks × 790 days)
    close_matrix = _load_close_matrix()
    has_prices = not close_matrix.empty
    logger.info("Close matrix: %s", close_matrix.shape if has_prices else "empty")

    # 2. Batch load RS percentile
    if progress_callback:
        progress_callback(20, 100, "Loading RS ratings...")
    rs_series = _load_rs_percentile()
    logger.info("RS data: %d stocks", len(rs_series.dropna()) if not rs_series.empty else 0)

    # 3. Load valuation (PE/PB/yield from TWSE)
    if progress_callback:
        progress_callback(30, 100, "Loading valuation...")
    valuation_df = _load_valuation_data()
    val_lookup = {}
    if not valuation_df.empty and "code" in valuation_df.columns:
        for _, row in valuation_df.iterrows():
            val_lookup[str(row["code"])] = {
                "pe": _safe_float(row.get("pe")),
                "pb": _safe_float(row.get("pb")),
                "dividend_yield": _safe_float(row.get("dividend_yield")),
                "close": _safe_float(row.get("close")),
            }
    logger.info("Valuation: %d stocks", len(val_lookup))

    # 4. Load revenue data
    if progress_callback:
        progress_callback(40, 100, "Loading revenue...")
    revenue_df = _load_revenue_data()
    rev_lookup = {}
    if not revenue_df.empty and "code" in revenue_df.columns:
        rev_sorted = revenue_df.sort_values(["year", "month"]) if "year" in revenue_df.columns else revenue_df
        for code, grp in rev_sorted.groupby("code"):
            latest = grp.iloc[-1]
            rev_lookup[str(code)] = {
                "revenue_yoy": _safe_float(latest.get("revenue_yoy")),
                "revenue_mom": _safe_float(latest.get("revenue_mom")),
            }
    logger.info("Revenue: %d stocks", len(rev_lookup))

    # 5. Build the union of all known stock codes
    all_codes = set(all_stocks.keys())
    if has_prices:
        all_codes |= set(close_matrix.columns)
    all_codes |= set(val_lookup.keys())
    all_codes = sorted(all_codes)

    total = len(all_codes)
    rows_written = 0

    if progress_callback:
        progress_callback(50, 100, f"Processing {total} stocks...")

    # 6. Iterate and write
    batch_rows = []
    for i, code in enumerate(all_codes):
        if progress_callback and i % 200 == 0:
            progress_callback(50 + int(40 * i / total), 100, f"{code} ({i}/{total})")

        # Stock metadata
        info = all_stocks.get(code, {})
        name = info.get("name", code) if isinstance(info, dict) else str(info)
        market = info.get("market", "") if isinstance(info, dict) else ""

        try:
            industry = get_sector(code, level=1) if callable(get_sector) else "未分類"
        except Exception:
            industry = "未分類"

        # Technical from close matrix
        tech = {}
        if has_prices and code in close_matrix.columns:
            closes = close_matrix[code].dropna()
            if len(closes) >= 20:
                tech = compute_technical_from_close(closes)

        # RS rating
        rs_rating = None
        rs_rank_pct = None
        if not rs_series.empty and code in rs_series.index:
            val = rs_series[code]
            if pd.notna(val):
                rs_rating = float(val)
                rs_rank_pct = float(val)

        # Valuation
        val = val_lookup.get(code, {})
        pe = val.get("pe")
        pb = val.get("pb")
        dy = val.get("dividend_yield")

        close = tech.get("close") or val.get("close")

        # Revenue
        rev = rev_lookup.get(code, {})
        revenue_yoy = rev.get("revenue_yoy")
        revenue_mom = rev.get("revenue_mom")

        # Revenue consecutive
        consec = compute_revenue_consecutive(revenue_df, code) if not revenue_df.empty else {
            "revenue_consecutive_up": 0, "revenue_consecutive_down": 0
        }

        batch_rows.append((
            code, name, market, industry,
            close, tech.get("change_pct"), None, None,  # volume_avg_20d, market_cap
            pe, pb, dy,
            revenue_yoy, revenue_mom,
            rs_rating, rs_rank_pct,
            tech.get("ma5_ratio"), tech.get("ma20_ratio"), tech.get("ma60_ratio"),
            tech.get("rsi_14"), tech.get("atr_pct"),
            consec["revenue_consecutive_up"], consec["revenue_consecutive_down"],
            datetime.now().isoformat(),
        ))
        rows_written += 1

    # Batch insert
    if progress_callback:
        progress_callback(90, 100, "Writing to database...")

    conn.executemany("""
        INSERT OR REPLACE INTO screening_latest (
            code, name, market, industry,
            close, change_pct, volume_avg_20d, market_cap,
            pe, pb, dividend_yield,
            revenue_yoy, revenue_mom,
            rs_rating, rs_rank_pct,
            ma5_ratio, ma20_ratio, ma60_ratio,
            rsi_14, atr_pct,
            revenue_consecutive_up, revenue_consecutive_down,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, batch_rows)

    conn.execute("""
        INSERT OR REPLACE INTO data_sync_log (task_name, last_updated, status, row_count)
        VALUES ('screening_latest', ?, 'OK', ?)
    """, (datetime.now().isoformat(), rows_written))

    conn.commit()
    conn.close()

    elapsed = time.time() - t0

    if progress_callback:
        progress_callback(100, 100, "Done")

    logger.info("Screening data refreshed: %d stocks in %.1fs", rows_written, elapsed)
    return {"status": "OK", "rows": rows_written, "elapsed_seconds": round(elapsed, 1)}


def _safe_float(val) -> float | None:
    """Convert to float, return None for invalid values."""
    if val is None:
        return None
    try:
        f = float(val)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


# ─── Query Functions ──────────────────────────────────────────────


_VALID_COLUMNS = {
    "code", "name", "market", "industry",
    "close", "change_pct", "volume_avg_20d", "market_cap",
    "pe", "pb", "dividend_yield", "yield_3y_avg", "yield_5y_avg",
    "gross_margin", "operating_margin", "pretax_margin", "net_margin",
    "roe", "roa",
    "debt_ratio", "current_ratio", "quick_ratio", "interest_coverage",
    "ocf_to_debt", "ocf_to_net_income",
    "eps", "bps", "revenue_per_share", "fcf_per_share",
    "cash_dividend", "stock_dividend", "dividend_payout_ratio",
    "revenue_yoy", "revenue_mom", "operating_income_yoy", "eps_yoy", "roe_yoy",
    "receivable_turnover", "inventory_turnover", "asset_turnover", "operating_cycle_days",
    "foreign_holding_pct", "trust_5d_net", "margin_util", "broker_net_buy", "tdcc_concentration",
    "rs_rating", "rs_rank_pct", "ma5_ratio", "ma20_ratio", "ma60_ratio", "rsi_14", "atr_pct",
    "revenue_consecutive_up", "revenue_consecutive_down", "eps_consecutive_up",
}


def screen_stocks(filters: dict) -> list[dict]:
    """Run screening query against screening_latest.

    Args:
        filters: dict supporting multiple formats per column:
            - Range:  {"pe": {"min": 5, "max": 25}}
            - Single: {"pe": {"op": ">=", "value": 30}}
            - Exact:  {"market": "上市"}
            - List of conditions: {"pe": [{"op": ">=", "value": 5}, {"op": "<", "value": 25}]}
            Special keys: "sort_by", "sort_desc", "limit", "offset"

    Returns:
        List of matching stock dicts.
    """
    init_db()
    conn = get_db()

    where_clauses = []
    params = []

    sort_by = filters.pop("sort_by", "code")
    sort_desc = filters.pop("sort_desc", False)
    limit = filters.pop("limit", 100)
    offset = filters.pop("offset", 0)

    # Validate sort_by against known columns
    if sort_by not in _VALID_COLUMNS:
        sort_by = "code"

    for col, spec in filters.items():
        if col not in _VALID_COLUMNS:
            continue

        if isinstance(spec, list):
            # Multiple conditions: [{"op": ">=", "value": 5}, {"op": "<", "value": 25}]
            for cond in spec:
                op = cond.get("op", ">=")
                val = cond.get("value")
                if val is not None and op in (">=", "<=", ">", "<", "=", "!="):
                    where_clauses.append(f"{col} {op} ?")
                    params.append(val)
        elif isinstance(spec, dict):
            if "min" in spec or "max" in spec:
                # Range shorthand: {"min": 5, "max": 25}
                if spec.get("min") is not None:
                    where_clauses.append(f"{col} >= ?")
                    params.append(spec["min"])
                if spec.get("max") is not None:
                    where_clauses.append(f"{col} <= ?")
                    params.append(spec["max"])
            else:
                # Single condition: {"op": ">=", "value": 30}
                op = spec.get("op", ">=")
                val = spec.get("value")
                if val is not None and op in (">=", "<=", ">", "<", "=", "!="):
                    where_clauses.append(f"{col} {op} ?")
                    params.append(val)
        elif spec is not None:
            where_clauses.append(f"{col} = ?")
            params.append(spec)

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    order = "DESC" if sort_desc else "ASC"

    query = f"""
        SELECT * FROM screening_latest
        WHERE {where_sql}
        ORDER BY {sort_by} {order}
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    try:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error("Screen query failed: %s", e)
        return []
    finally:
        conn.close()


def get_rankings(metric: str, top_n: int = 50, ascending: bool = False) -> list[dict]:
    """Get top/bottom stocks by a single metric.

    Args:
        metric: Column name in screening_latest
        top_n: Number of results
        ascending: True for lowest first (e.g., PE), False for highest first
    """
    init_db()
    conn = get_db()

    order = "ASC" if ascending else "DESC"
    query = f"""
        SELECT code, name, market, industry, {metric}, close, pe, pb,
               dividend_yield, revenue_yoy, roe, rs_rating
        FROM screening_latest
        WHERE {metric} IS NOT NULL
        ORDER BY {metric} {order}
        LIMIT ?
    """

    try:
        rows = conn.execute(query, (top_n,)).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error("Rankings query failed: %s", e)
        return []
    finally:
        conn.close()


def get_stock_snapshot(code: str) -> dict | None:
    """Get full snapshot for a single stock."""
    init_db()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM screening_latest WHERE code = ?", (code,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_screening_stats() -> dict:
    """Get summary stats of screening database."""
    init_db()
    conn = get_db()
    try:
        count = conn.execute("SELECT COUNT(*) FROM screening_latest").fetchone()[0]
        sync = conn.execute(
            "SELECT last_updated, status, row_count FROM data_sync_log WHERE task_name = 'screening_latest'"
        ).fetchone()
        return {
            "stock_count": count,
            "last_updated": dict(sync)["last_updated"] if sync else None,
            "status": dict(sync)["status"] if sync else "NEVER_RUN",
        }
    finally:
        conn.close()


# ─── Available Filter Definitions ─────────────────────────────────

FILTER_DEFINITIONS = {
    "valuation": {
        "label": "價值評估",
        "filters": [
            {"key": "pe", "label": "本益比 (PE)", "type": "range"},
            {"key": "pb", "label": "股價淨值比 (PB)", "type": "range"},
            {"key": "dividend_yield", "label": "現金殖利率 (%)", "type": "range"},
        ],
    },
    "profitability": {
        "label": "獲利能力",
        "filters": [
            {"key": "gross_margin", "label": "毛利率 (%)", "type": "range"},
            {"key": "operating_margin", "label": "營業利益率 (%)", "type": "range"},
            {"key": "net_margin", "label": "稅後淨利率 (%)", "type": "range"},
            {"key": "roe", "label": "股東權益報酬率 ROE (%)", "type": "range"},
            {"key": "roa", "label": "資產報酬率 ROA (%)", "type": "range"},
        ],
    },
    "safety": {
        "label": "安全性",
        "filters": [
            {"key": "debt_ratio", "label": "負債比 (%)", "type": "range"},
            {"key": "current_ratio", "label": "流動比率", "type": "range"},
            {"key": "quick_ratio", "label": "速動比率", "type": "range"},
        ],
    },
    "growth": {
        "label": "成長力",
        "filters": [
            {"key": "revenue_yoy", "label": "月營收年增率 (%)", "type": "range"},
            {"key": "revenue_mom", "label": "月營收月增率 (%)", "type": "range"},
            {"key": "eps_yoy", "label": "EPS 年增率 (%)", "type": "range"},
            {"key": "revenue_consecutive_up", "label": "營收連續成長月數", "type": "min"},
        ],
    },
    "technical": {
        "label": "技術面",
        "filters": [
            {"key": "rs_rating", "label": "RS 相對強度", "type": "range"},
            {"key": "rs_rank_pct", "label": "RS 全市場排名 (%)", "type": "range"},
            {"key": "rsi_14", "label": "RSI(14)", "type": "range"},
            {"key": "ma20_ratio", "label": "股價/MA20", "type": "range"},
            {"key": "ma60_ratio", "label": "股價/MA60", "type": "range"},
        ],
    },
    "chip": {
        "label": "籌碼面",
        "filters": [
            {"key": "foreign_holding_pct", "label": "外資持股比 (%)", "type": "range"},
            {"key": "trust_5d_net", "label": "投信5日買賣超", "type": "range"},
            {"key": "margin_util", "label": "融資使用率 (%)", "type": "range"},
        ],
    },
    "price": {
        "label": "價格與成交量",
        "filters": [
            {"key": "close", "label": "收盤價", "type": "range"},
            {"key": "change_pct", "label": "漲跌幅 (%)", "type": "range"},
            {"key": "volume_avg_20d", "label": "20日均量", "type": "range"},
            {"key": "market_cap", "label": "市值", "type": "range"},
        ],
    },
}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Initializing screener database...")
    init_db()
    print(f"Database created at {DB_PATH}")
    print("Refreshing screening data...")
    result = refresh_screening_data(
        progress_callback=lambda cur, tot, msg: print(f"  [{cur}/{tot}] {msg}")
    )
    print(f"Done: {result}")

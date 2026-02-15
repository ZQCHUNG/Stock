"""TWSE/TPEX 官方資料提供者 — 統一資料來源整合

P0: 歷史日K (OHLCV) + SQLite 儲存
P0.5: 除權息還原（前復權）
P2: TPEX 法人
P3: 大盤指數 (FMTQIK)

Architecture:
    SQLite (data/market_data.db)
      ├── price_daily: ticker, date, open, high, low, close, volume, adj_factor
      ├── corporate_actions: ticker, ex_date, cash_dividend, stock_dividend
      └── taiex_daily: date, open, high, low, close, volume

    Shadow Mode:
      Phase 1: Dual-write (TWSE → SQLite, yfinance still primary)
      Phase 2: Consistency check (compare TWSE vs yfinance)
      Phase 3: Gradual switch (TWSE primary, yfinance fallback)

Rate Limiting:
    - Random delay 3-8 seconds between requests
    - User-Agent rotation
    - Incremental updates (only fetch missing dates)
"""

import json
import logging
import random
import sqlite3
import time
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

_logger = logging.getLogger(__name__)

# --- Constants ---
_DB_PATH = Path(__file__).parent / "market_data.db"
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
]


# ============================================================
# SQLite Database Layer
# ============================================================

def _init_db():
    """Initialize SQLite database with required tables and indexes."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS price_daily (
                ticker    TEXT NOT NULL,
                date      TEXT NOT NULL,  -- YYYY-MM-DD
                open      REAL,
                high      REAL,
                low       REAL,
                close     REAL,
                volume    INTEGER,
                adj_factor REAL DEFAULT 1.0,
                source    TEXT DEFAULT 'twse',  -- twse / tpex
                PRIMARY KEY (ticker, date)
            );
            CREATE INDEX IF NOT EXISTS idx_price_ticker_date
                ON price_daily(ticker, date);

            CREATE TABLE IF NOT EXISTS corporate_actions (
                ticker         TEXT NOT NULL,
                ex_date        TEXT NOT NULL,  -- YYYY-MM-DD
                cash_dividend  REAL DEFAULT 0,
                stock_dividend REAL DEFAULT 0,
                source         TEXT DEFAULT 'twse',
                PRIMARY KEY (ticker, ex_date)
            );
            CREATE INDEX IF NOT EXISTS idx_ca_ticker
                ON corporate_actions(ticker);

            CREATE TABLE IF NOT EXISTS taiex_daily (
                date   TEXT NOT NULL PRIMARY KEY,  -- YYYY-MM-DD
                open   REAL,
                high   REAL,
                low    REAL,
                close  REAL,
                volume INTEGER
            );

            CREATE TABLE IF NOT EXISTS fetch_log (
                ticker  TEXT NOT NULL,
                month   TEXT NOT NULL,  -- YYYY-MM
                fetched_at TEXT NOT NULL,
                source  TEXT NOT NULL,
                row_count INTEGER DEFAULT 0,
                PRIMARY KEY (ticker, month, source)
            );
        """)


@contextmanager
def _get_conn():
    """Get a SQLite connection with WAL mode for better concurrency."""
    conn = sqlite3.connect(str(_DB_PATH), timeout=10)
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


# Initialize DB on import
_init_db()


# ============================================================
# HTTP Helper
# ============================================================

def _twse_get(url: str, timeout: int = 15, delay: tuple = (3, 8)) -> dict | None:
    """Send HTTP GET with rate limiting and UA rotation.

    Returns parsed JSON or None on failure.
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "application/json",
        "Referer": "https://www.twse.com.tw/",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read().decode("utf-8"))
        time.sleep(random.uniform(*delay))
        return data
    except Exception as e:
        _logger.warning("TWSE request failed %s: %s", url, e)
        time.sleep(random.uniform(*delay))
        return None


def _tpex_get(url: str, timeout: int = 15, delay: tuple = (3, 8)) -> dict | None:
    """Send HTTP GET to TPEX with rate limiting."""
    req = urllib.request.Request(url, headers={
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "application/json",
        "Referer": "https://www.tpex.org.tw/",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read().decode("utf-8"))
        time.sleep(random.uniform(*delay))
        return data
    except Exception as e:
        _logger.warning("TPEX request failed %s: %s", url, e)
        time.sleep(random.uniform(*delay))
        return None


# ============================================================
# Date Helpers
# ============================================================

def _to_roc_date(dt: datetime) -> str:
    """Convert datetime to ROC date string: YYY/MM/DD"""
    return f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"


def _to_roc_yearmonth(dt: datetime) -> str:
    """Convert datetime to ROC year-month: YYYMMDD (first day)"""
    return f"{dt.year - 1911}{dt.month:02d}01"


def _parse_roc_date(s: str) -> str:
    """Parse ROC date '115/02/13' → '2026-02-13'"""
    parts = s.strip().split("/")
    if len(parts) == 3:
        year = int(parts[0]) + 1911
        return f"{year}-{parts[1]}-{parts[2]}"
    return ""


def _safe_float(s) -> float | None:
    """Parse number string with commas, dashes, etc."""
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    if not s or s in ("-", "N/A", "–", "--", "X"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _safe_int(s) -> int | None:
    """Parse integer string with commas."""
    v = _safe_float(s)
    return int(v) if v is not None else None


# ============================================================
# P0: TWSE STOCK_DAY — 上市歷史日K
# ============================================================

def fetch_twse_month(stock_code: str, year: int, month: int) -> list[dict]:
    """Fetch one month of daily OHLCV from TWSE STOCK_DAY API.

    Args:
        stock_code: e.g. '2330'
        year: Western year (e.g. 2026)
        month: 1-12

    Returns:
        List of dicts: {date, open, high, low, close, volume}
    """
    date_str = f"{year}{month:02d}01"
    url = (f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
           f"?date={date_str}&stockNo={stock_code}&response=json")

    data = _twse_get(url)
    if not data or not data.get("data"):
        return []

    # Fields: 日期, 成交股數, 成交金額, 開盤價, 最高價, 最低價, 收盤價, 漲跌價差, 成交筆數
    rows = []
    for row in data["data"]:
        try:
            date_iso = _parse_roc_date(row[0])
            if not date_iso:
                continue
            volume = _safe_int(row[1])
            open_p = _safe_float(row[3])
            high_p = _safe_float(row[4])
            low_p = _safe_float(row[5])
            close_p = _safe_float(row[6])

            if open_p is None or close_p is None:
                continue

            rows.append({
                "date": date_iso,
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": volume or 0,
            })
        except (IndexError, ValueError) as e:
            _logger.debug("Skip malformed TWSE row: %s", e)
            continue

    return rows


def _month_already_fetched(ticker: str, year: int, month: int, source: str = "twse") -> bool:
    """Check if we already fetched this month's data."""
    month_key = f"{year}-{month:02d}"
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT row_count FROM fetch_log WHERE ticker=? AND month=? AND source=?",
            (ticker, month_key, source),
        ).fetchone()
        return row is not None and row[0] > 0


def _log_fetch(ticker: str, year: int, month: int, source: str, count: int):
    """Record that we fetched data for a month."""
    month_key = f"{year}-{month:02d}"
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO fetch_log (ticker, month, fetched_at, source, row_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (ticker, month_key, datetime.now().isoformat(), source, count),
        )


def _save_price_rows(ticker: str, rows: list[dict], source: str = "twse"):
    """Upsert price rows into SQLite."""
    if not rows:
        return
    with _get_conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO price_daily "
            "(ticker, date, open, high, low, close, volume, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(ticker, r["date"], r["open"], r["high"], r["low"],
              r["close"], r["volume"], source) for r in rows],
        )


def sync_twse_stock(stock_code: str, months_back: int = 12, force: bool = False) -> int:
    """Sync a TWSE (上市) stock's historical data to SQLite.

    Incrementally fetches only missing months.

    Args:
        stock_code: e.g. '2330'
        months_back: How many months to go back
        force: Re-fetch even if already in DB

    Returns:
        Total new rows inserted
    """
    total = 0
    now = datetime.now()

    for i in range(months_back):
        target = now - timedelta(days=30 * i)
        year, month = target.year, target.month

        if not force and _month_already_fetched(stock_code, year, month, "twse"):
            continue

        # Current month: always re-fetch (incomplete)
        if i == 0:
            pass  # always fetch current month

        rows = fetch_twse_month(stock_code, year, month)
        if rows:
            _save_price_rows(stock_code, rows, "twse")
            _log_fetch(stock_code, year, month, "twse", len(rows))
            total += len(rows)
            _logger.info("TWSE %s %d/%02d: %d rows", stock_code, year, month, len(rows))
        else:
            # No data (holiday month or invalid stock) — still log to avoid re-fetching
            _log_fetch(stock_code, year, month, "twse", 0)
            _logger.debug("TWSE %s %d/%02d: no data", stock_code, year, month)

    return total


# ============================================================
# P0: TPEX — 上櫃歷史日K
# ============================================================

def fetch_tpex_month(stock_code: str, year: int, month: int) -> list[dict]:
    """Fetch one month of daily OHLCV from TPEX for 上櫃 stocks.

    New TPEX API (2024+ website redesign):
    URL: https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock
    Uses Western calendar dates (YYYY/MM/DD), returns tables[0].data.
    Volume is in 張 (lots), must multiply by 1000 for shares.
    """
    d = f"{year}/{month:02d}/01"
    url = (f"https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
           f"?code={stock_code}&date={d}&response=json")

    data = _tpex_get(url)
    if not data or data.get("stat") != "ok":
        return []

    tables = data.get("tables", [])
    if not tables or not tables[0].get("data"):
        return []

    rows = []
    for row in tables[0]["data"]:
        try:
            # New TPEX format: [日期, 成交張數, 成交仟元, 開盤, 最高, 最低, 收盤, 漲跌, 筆數]
            date_iso = _parse_roc_date(str(row[0]))
            if not date_iso:
                continue
            volume_lots = _safe_int(row[1])
            volume = (volume_lots * 1000) if volume_lots is not None else 0  # 張→股
            open_p = _safe_float(row[3])
            high_p = _safe_float(row[4])
            low_p = _safe_float(row[5])
            close_p = _safe_float(row[6])

            if open_p is None or close_p is None:
                continue

            rows.append({
                "date": date_iso,
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": volume,
            })
        except (IndexError, ValueError):
            continue

    return rows


def sync_tpex_stock(stock_code: str, months_back: int = 12, force: bool = False) -> int:
    """Sync a TPEX (上櫃) stock's historical data to SQLite."""
    total = 0
    now = datetime.now()

    for i in range(months_back):
        target = now - timedelta(days=30 * i)
        year, month = target.year, target.month

        if not force and _month_already_fetched(stock_code, year, month, "tpex"):
            continue

        rows = fetch_tpex_month(stock_code, year, month)
        if rows:
            _save_price_rows(stock_code, rows, "tpex")
            _log_fetch(stock_code, year, month, "tpex", len(rows))
            total += len(rows)
            _logger.info("TPEX %s %d/%02d: %d rows", stock_code, year, month, len(rows))
        else:
            _log_fetch(stock_code, year, month, "tpex", 0)

    return total


# ============================================================
# P0: Unified Stock Data Access
# ============================================================

def sync_stock(stock_code: str, months_back: int = 12, force: bool = False) -> int:
    """Sync stock data — auto-detect TWSE vs TPEX.

    Tries TWSE first (上市). If no data found, falls back to TPEX (上櫃).
    """
    # Try TWSE first
    count = sync_twse_stock(stock_code, months_back, force)
    if count > 0:
        return count

    # Check if we already have TWSE data in DB
    with _get_conn() as conn:
        existing = conn.execute(
            "SELECT COUNT(*) FROM price_daily WHERE ticker=? AND source='twse'",
            (stock_code,),
        ).fetchone()[0]
        if existing > 0:
            return 0  # Already have TWSE data, just no new data this sync

    # No TWSE data at all — try TPEX
    _logger.info("No TWSE data for %s, trying TPEX", stock_code)
    return sync_tpex_stock(stock_code, months_back, force)


def get_stock_data_from_db(
    stock_code: str,
    start_date: str | None = None,
    end_date: str | None = None,
    period_days: int = 365,
    adjusted: bool = True,
) -> pd.DataFrame:
    """Read stock data from SQLite database.

    Args:
        stock_code: e.g. '2330'
        start_date: YYYY-MM-DD (optional, overrides period_days)
        end_date: YYYY-MM-DD (optional, defaults to today)
        period_days: If start_date not given, go back this many days
        adjusted: If True, apply forward adjustment (前復權)

    Returns:
        DataFrame with columns: open, high, low, close, volume
        Index: DatetimeIndex named 'date'
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if start_date is None:
        start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=period_days)
        start_date = start_dt.strftime("%Y-%m-%d")

    with _get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume, adj_factor "
            "FROM price_daily WHERE ticker=? AND date>=? AND date<=? "
            "ORDER BY date",
            conn,
            params=(stock_code, start_date, end_date),
        )

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")

    if adjusted:
        # Apply forward adjustment factors
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col] * df["adj_factor"]

    df = df[["open", "high", "low", "close", "volume"]].copy()
    return df


# ============================================================
# P0.5: 除權息還原（前復權 Forward Adjustment）
# ============================================================

def fetch_twse_dividends(stock_code: str) -> list[dict]:
    """Fetch dividend history from TWSE.

    Uses 除權除息計算結果表 endpoint.
    """
    # TWSE provides ex-dividend data via this endpoint
    # We search recent years
    rows = []
    now = datetime.now()

    for year_offset in range(5):  # Last 5 years
        year = now.year - year_offset
        roc_year = year - 1911
        url = (f"https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
               f"?STK_NO={stock_code}&startYear={roc_year}&endYear={roc_year}"
               f"&response=json")

        data = _twse_get(url, delay=(2, 5))
        if not data or not data.get("data"):
            continue

        for row in data["data"]:
            try:
                # Fields vary, but typically include ex-date, cash dividend, stock dividend
                date_iso = _parse_roc_date(row[0])
                if not date_iso:
                    continue
                cash_div = _safe_float(row[3]) or 0.0  # 除息金額
                stock_div = _safe_float(row[4]) or 0.0  # 除權比率
                rows.append({
                    "ticker": stock_code,
                    "ex_date": date_iso,
                    "cash_dividend": cash_div,
                    "stock_dividend": stock_div,
                })
            except (IndexError, ValueError):
                continue

    return rows


def save_corporate_actions(actions: list[dict]):
    """Save corporate actions to SQLite."""
    if not actions:
        return
    with _get_conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO corporate_actions "
            "(ticker, ex_date, cash_dividend, stock_dividend, source) "
            "VALUES (?, ?, ?, ?, ?)",
            [(a["ticker"], a["ex_date"], a["cash_dividend"],
              a["stock_dividend"], a.get("source", "twse")) for a in actions],
        )


def compute_adjustment_factors(stock_code: str):
    """Compute and store forward adjustment factors for all price data.

    前復權 (Forward Adjustment):
    - Latest prices: factor = 1.0 (no adjustment)
    - Before each ex-date, multiply factor by:
        cash: (P_pre - cash_dividend) / P_pre
        stock: 1 / (1 + stock_dividend / 10)
    - Factors accumulate: if 2 ex-dates, pre-both dates get both factors.
    """
    with _get_conn() as conn:
        # Get all corporate actions, newest first
        actions = conn.execute(
            "SELECT ex_date, cash_dividend, stock_dividend "
            "FROM corporate_actions WHERE ticker=? ORDER BY ex_date DESC",
            (stock_code,),
        ).fetchall()

        if not actions:
            conn.execute(
                "UPDATE price_daily SET adj_factor=1.0 WHERE ticker=?",
                (stock_code,),
            )
            return

        prices = conn.execute(
            "SELECT date, close FROM price_daily "
            "WHERE ticker=? ORDER BY date",
            (stock_code,),
        ).fetchall()

        if not prices:
            return

        price_dates = [p[0] for p in prices]
        price_map = {p[0]: p[1] for p in prices}

        # Initialize all factors to 1.0
        factors = {d: 1.0 for d in price_dates}

        # Process each corporate action (newest to oldest)
        for ex_date, cash_div, stock_div in actions:
            # Find close on the trading day before ex_date
            pre_dates = [d for d in price_dates if d < ex_date]
            if not pre_dates:
                continue
            pre_date = pre_dates[-1]
            pre_close = price_map.get(pre_date)
            if not pre_close or pre_close <= 0:
                continue

            # Compute this action's adjustment factor
            action_factor = 1.0
            if cash_div and cash_div > 0:
                action_factor *= (pre_close - cash_div) / pre_close
            if stock_div and stock_div > 0:
                action_factor *= 1.0 / (1.0 + stock_div / 10.0)

            # Apply to ALL dates strictly before ex_date
            for d in price_dates:
                if d < ex_date:
                    factors[d] *= action_factor

        # Write factors to DB
        batch = [(factors[d], stock_code, d) for d in price_dates]
        conn.executemany(
            "UPDATE price_daily SET adj_factor=? WHERE ticker=? AND date=?",
            batch,
        )
        _logger.info("Updated adj_factors for %s: %d dates, %d actions",
                      stock_code, len(batch), len(actions))


def detect_splits_from_prices(stock_code: str, gap_threshold: float = 0.35) -> list[dict]:
    """R72: Auto-detect stock splits from raw price data.

    Scans price_daily for day-over-day close price changes that exceed
    `gap_threshold` AND have no corresponding corporate_actions entry.

    Split detection logic:
    1. |close_t / close_{t-1} - 1| > gap_threshold (default 35%)
    2. No corporate_action within ±1 calendar day of the gap date
    3. Estimate split ratio from price ratio (round to nearest integer)

    Returns:
        List of detected split dicts:
        [{"ticker": str, "ex_date": str, "cash_dividend": 0,
          "stock_dividend": float, "source": "auto_detect",
          "price_before": float, "price_after": float, "ratio": int}]
    """
    with _get_conn() as conn:
        prices = conn.execute(
            "SELECT date, close FROM price_daily "
            "WHERE ticker=? AND close > 0 ORDER BY date",
            (stock_code,),
        ).fetchall()

        if len(prices) < 2:
            return []

        # Get existing corporate action dates for this ticker
        existing_actions = conn.execute(
            "SELECT ex_date FROM corporate_actions WHERE ticker=?",
            (stock_code,),
        ).fetchall()
        existing_dates = {row[0] for row in existing_actions}

    detected = []
    for i in range(1, len(prices)):
        prev_date, prev_close = prices[i - 1]
        curr_date, curr_close = prices[i]

        if prev_close <= 0:
            continue

        ratio = curr_close / prev_close
        gap = abs(ratio - 1.0)

        if gap < gap_threshold:
            continue

        # Check if this gap is already explained by a corporate action
        # (within ±1 calendar day to handle weekends)
        gap_explained = False
        for offset in range(-1, 2):
            try:
                check_date = (
                    datetime.strptime(curr_date, "%Y-%m-%d")
                    + timedelta(days=offset)
                ).strftime("%Y-%m-%d")
                if check_date in existing_dates:
                    gap_explained = True
                    break
            except ValueError:
                continue

        if gap_explained:
            continue

        # Estimate split ratio from price ratio
        if ratio < 1:
            # Forward split: price dropped (e.g., 188→47 = 4:1 split)
            estimated_ratio = round(1.0 / ratio)
            if estimated_ratio < 2:
                continue  # Not a real split
            # stock_dividend = (ratio - 1) * 10
            # For 4:1 split: stock_dividend = 30 → 1/(1+30/10) = 0.25
            stock_div = (estimated_ratio - 1) * 10.0
        else:
            # Reverse split: price jumped (e.g., 10→50 = 5:1 reverse)
            estimated_ratio = round(ratio)
            if estimated_ratio < 2:
                continue
            # Negative stock_dividend to represent reverse split
            # (not standard — log warning but skip for now)
            _logger.warning(
                "Possible reverse split for %s on %s: %.2f → %.2f (ratio ~%d:1). "
                "Reverse splits not auto-handled.",
                stock_code, curr_date, prev_close, curr_close, estimated_ratio,
            )
            continue

        _logger.info(
            "Auto-detected split for %s on %s: %.2f → %.2f "
            "(estimated %d:1 split, stock_dividend=%.1f)",
            stock_code, curr_date, prev_close, curr_close,
            estimated_ratio, stock_div,
        )

        detected.append({
            "ticker": stock_code,
            "ex_date": curr_date,
            "cash_dividend": 0,
            "stock_dividend": stock_div,
            "source": "auto_detect",
            "price_before": prev_close,
            "price_after": curr_close,
            "ratio": estimated_ratio,
        })

    return detected


def auto_fix_splits(stock_code: str, gap_threshold: float = 0.35) -> int:
    """Detect and auto-fix unrecorded stock splits.

    Runs detect_splits_from_prices(), inserts discovered splits into
    corporate_actions, and recomputes adjustment factors.

    Returns:
        Number of splits auto-fixed.
    """
    detected = detect_splits_from_prices(stock_code, gap_threshold)
    if not detected:
        return 0

    # Insert into corporate_actions
    save_corporate_actions(detected)

    # Recompute adjustment factors
    compute_adjustment_factors(stock_code)

    _logger.info(
        "Auto-fixed %d split(s) for %s: %s",
        len(detected), stock_code,
        ", ".join(f"{d['ex_date']} ({d['ratio']}:1)" for d in detected),
    )
    return len(detected)


def sync_and_adjust(stock_code: str, months_back: int = 12, force: bool = False) -> int:
    """Full pipeline: sync price data + fetch dividends + compute adjustments.

    This is the main entry point for getting fully-adjusted data from TWSE.
    """
    # Step 1: Sync raw price data
    count = sync_stock(stock_code, months_back, force)

    # Step 2: Fetch and save corporate actions
    actions = fetch_twse_dividends(stock_code)
    save_corporate_actions(actions)

    # Step 3: Auto-detect unrecorded stock splits (R72)
    auto_fix_splits(stock_code)

    # Step 4: Compute adjustment factors
    compute_adjustment_factors(stock_code)

    return count


# ============================================================
# P3: TAIEX 加權指數
# ============================================================

def fetch_taiex_month(year: int, month: int) -> list[dict]:
    """Fetch TAIEX monthly data from TWSE FMTQIK endpoint."""
    date_str = f"{year}{month:02d}01"
    url = (f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST"
           f"?date={date_str}&response=json")

    data = _twse_get(url, delay=(2, 5))
    if not data or not data.get("data"):
        return []

    # Fields: 日期, 開盤指數, 最高指數, 最低指數, 收盤指數
    rows = []
    for row in data["data"]:
        try:
            date_iso = _parse_roc_date(row[0])
            if not date_iso:
                continue
            rows.append({
                "date": date_iso,
                "open": _safe_float(row[1]),
                "high": _safe_float(row[2]),
                "low": _safe_float(row[3]),
                "close": _safe_float(row[4]),
                "volume": 0,  # Index doesn't have volume in this endpoint
            })
        except (IndexError, ValueError):
            continue

    return rows


def sync_taiex(months_back: int = 12) -> int:
    """Sync TAIEX index data to SQLite."""
    total = 0
    now = datetime.now()

    for i in range(months_back):
        target = now - timedelta(days=30 * i)
        year, month = target.year, target.month

        rows = fetch_taiex_month(year, month)
        if rows:
            with _get_conn() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO taiex_daily "
                    "(date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [(r["date"], r["open"], r["high"], r["low"],
                      r["close"], r["volume"]) for r in rows],
                )
            total += len(rows)

    return total


def get_taiex_from_db(
    start_date: str | None = None,
    end_date: str | None = None,
    period_days: int = 365,
) -> pd.DataFrame:
    """Read TAIEX data from SQLite."""
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if start_date is None:
        start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=period_days)
        start_date = start_dt.strftime("%Y-%m-%d")

    with _get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume "
            "FROM taiex_daily WHERE date>=? AND date<=? ORDER BY date",
            conn,
            params=(start_date, end_date),
        )

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return df


# ============================================================
# P2: TPEX 法人買賣超
# ============================================================

def fetch_tpex_institutional(stock_code: str, date: str) -> dict | None:
    """Fetch TPEX institutional data for a single date.

    Args:
        stock_code: OTC stock code
        date: YYYY-MM-DD

    Returns:
        Dict with foreign_net, trust_net, dealer_net, total_net (in shares)
    """
    dt = datetime.strptime(date, "%Y-%m-%d")
    roc_date = _to_roc_date(dt)
    url = (f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/"
           f"3itrade_hedge_result.php"
           f"?l=zh-tw&o=json&se=EW&t=D&d={roc_date}&s=0,asc,0")

    data = _tpex_get(url, delay=(2, 5))
    if not data or not data.get("aaData"):
        return None

    for row in data["aaData"]:
        try:
            code = str(row[0]).strip()
            if code != stock_code:
                continue

            # Parse institutional data
            foreign_buy = _safe_int(row[2]) or 0
            foreign_sell = _safe_int(row[3]) or 0
            trust_buy = _safe_int(row[5]) or 0
            trust_sell = _safe_int(row[6]) or 0
            dealer_buy = _safe_int(row[8]) or 0
            dealer_sell = _safe_int(row[9]) or 0

            foreign_net = foreign_buy - foreign_sell
            trust_net = trust_buy - trust_sell
            dealer_net = dealer_buy - dealer_sell

            return {
                "foreign_net": foreign_net,
                "trust_net": trust_net,
                "dealer_net": dealer_net,
                "total_net": foreign_net + trust_net + dealer_net,
            }
        except (IndexError, ValueError):
            continue

    return None


# ============================================================
# Shadow Mode: Consistency Check
# ============================================================

def compare_with_yfinance(stock_code: str, days: int = 30) -> dict:
    """Compare TWSE data with yfinance for consistency validation.

    Returns:
        {
            "match_count": int,
            "mismatch_count": int,
            "max_diff_pct": float,
            "avg_diff_pct": float,
            "details": [{date, twse_close, yf_close, diff_pct}],
        }
    """
    import yfinance as yf
    from data.fetcher import get_ticker

    end = datetime.now()
    start = end - timedelta(days=days)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")

    # Get TWSE data from DB (raw, no adjustment)
    twse_df = get_stock_data_from_db(
        stock_code, start_str, end_str, adjusted=False,
    )

    # Get yfinance data (adjusted)
    try:
        ticker = get_ticker(stock_code)
        yf_df = yf.Ticker(ticker).history(
            start=start_str, end=end_str, auto_adjust=True,
        )
        yf_df = yf_df.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })
    except Exception:
        return {"error": "yfinance fetch failed"}

    if twse_df.empty or yf_df.empty:
        return {"error": "insufficient data", "twse_rows": len(twse_df), "yf_rows": len(yf_df)}

    # Compare closing prices
    # Note: TWSE is raw price, yfinance is adjusted.
    # We compare raw TWSE close with yfinance's non-adjusted close or
    # accept small differences due to adjustment timing.
    details = []
    for date in twse_df.index:
        date_key = date.strftime("%Y-%m-%d")
        # Find matching date in yfinance (may have timezone differences)
        yf_matches = yf_df[yf_df.index.strftime("%Y-%m-%d") == date_key]
        if yf_matches.empty:
            continue

        twse_close = twse_df.loc[date, "close"]
        yf_close = yf_matches.iloc[0]["close"]

        if twse_close and yf_close and twse_close > 0:
            diff_pct = abs(twse_close - yf_close) / twse_close * 100
            details.append({
                "date": date_key,
                "twse_close": round(twse_close, 2),
                "yf_close": round(yf_close, 2),
                "diff_pct": round(diff_pct, 4),
            })

    if not details:
        return {"error": "no overlapping dates"}

    diffs = [d["diff_pct"] for d in details]
    threshold = 0.5  # Alert if >0.5% difference
    mismatches = [d for d in details if d["diff_pct"] > threshold]

    return {
        "match_count": len(details) - len(mismatches),
        "mismatch_count": len(mismatches),
        "max_diff_pct": round(max(diffs), 4),
        "avg_diff_pct": round(sum(diffs) / len(diffs), 4),
        "threshold_pct": threshold,
        "details": details,
    }


# ============================================================
# History Backfiller
# ============================================================

class HistoryBackfiller:
    """Backfill historical data for multiple stocks with rate limiting.

    Usage:
        backfiller = HistoryBackfiller()
        backfiller.add_stocks(['2330', '2317', '2454'])
        backfiller.run(months_back=36)  # 3 years
    """

    def __init__(self, delay_range: tuple = (5, 10)):
        self.stocks: list[str] = []
        self.delay_range = delay_range
        self.results: dict[str, int] = {}

    def add_stocks(self, codes: list[str]):
        self.stocks.extend(codes)

    def run(self, months_back: int = 12, with_dividends: bool = True) -> dict:
        """Run the backfill process.

        Returns:
            Dict of stock_code → rows_fetched
        """
        total_stocks = len(self.stocks)
        for i, code in enumerate(self.stocks):
            _logger.info("Backfilling %s (%d/%d)", code, i + 1, total_stocks)
            try:
                if with_dividends:
                    count = sync_and_adjust(code, months_back)
                else:
                    count = sync_stock(code, months_back)
                self.results[code] = count
            except Exception as e:
                _logger.error("Failed to backfill %s: %s", code, e)
                self.results[code] = -1

            # Extra delay between stocks
            time.sleep(random.uniform(*self.delay_range))

        return self.results


# ============================================================
# Database Stats
# ============================================================

def get_db_stats() -> dict:
    """Get database statistics."""
    with _get_conn() as conn:
        price_count = conn.execute("SELECT COUNT(*) FROM price_daily").fetchone()[0]
        ticker_count = conn.execute(
            "SELECT COUNT(DISTINCT ticker) FROM price_daily"
        ).fetchone()[0]
        ca_count = conn.execute("SELECT COUNT(*) FROM corporate_actions").fetchone()[0]
        taiex_count = conn.execute("SELECT COUNT(*) FROM taiex_daily").fetchone()[0]

        # Date range
        date_range = conn.execute(
            "SELECT MIN(date), MAX(date) FROM price_daily"
        ).fetchone()

    db_size_mb = _DB_PATH.stat().st_size / (1024 * 1024) if _DB_PATH.exists() else 0

    return {
        "price_rows": price_count,
        "tickers": ticker_count,
        "corporate_actions": ca_count,
        "taiex_rows": taiex_count,
        "date_range": {"min": date_range[0], "max": date_range[1]} if date_range[0] else None,
        "db_size_mb": round(db_size_mb, 2),
    }

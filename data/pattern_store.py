"""
Pattern Recognition Data Store — 儲存管理器
- metadata.db: 追蹤每個資料源的最後抓取日期
- Raw Layer: 原始 JSON 按日期存檔
- Feature Layer: 清理後 Parquet 檔
"""
import sqlite3
import os
import json
from datetime import datetime, date
from pathlib import Path

# 預設本機路徑，之後可改指向 Google Drive mount
BASE_DIR = Path(__file__).parent / "pattern_data"
RAW_DIR = BASE_DIR / "raw"
FEATURE_DIR = BASE_DIR / "features"
METADATA_DB = BASE_DIR / "metadata.db"

# 確保目錄存在
for d in [RAW_DIR, FEATURE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# 資料源子目錄
DATA_SOURCES = [
    "institutional",  # 三大法人
    "margin",          # 融資融券
    "revenue",         # 月營收
    "tdcc",            # 集保戶數
    "broker",          # 分點分佈 (月頻)
    "broker_daily",    # 分點分佈 (日頻, R88.7)
    "financials",      # 季報
    "news",            # 新聞
    "industry",        # 產業分類
]

for src in DATA_SOURCES:
    (RAW_DIR / src).mkdir(exist_ok=True)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(METADATA_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fetch_log (
            source TEXT NOT NULL,
            market TEXT NOT NULL DEFAULT 'twse',
            fetch_date TEXT NOT NULL,
            record_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'ok',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (source, market, fetch_date)
        )
    """)
    conn.commit()
    return conn


def get_last_fetch_date(source: str, market: str = "twse") -> str | None:
    """取得某資料源最後成功抓取的日期 (YYYYMMDD)"""
    conn = get_db()
    row = conn.execute(
        "SELECT fetch_date FROM fetch_log "
        "WHERE source=? AND market=? AND status='ok' "
        "ORDER BY fetch_date DESC LIMIT 1",
        (source, market)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def log_fetch(source: str, market: str, fetch_date: str,
              record_count: int, status: str = "ok"):
    """紀錄抓取結果"""
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO fetch_log "
        "(source, market, fetch_date, record_count, status) "
        "VALUES (?, ?, ?, ?, ?)",
        (source, market, fetch_date, record_count, status)
    )
    conn.commit()
    conn.close()


def save_raw_json(source: str, date_str: str, data: dict | list,
                  market: str = "twse"):
    """存原始 JSON 到 Raw Layer"""
    filename = f"{market}_{date_str}.json"
    filepath = RAW_DIR / source / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return filepath


def load_raw_json(source: str, date_str: str,
                  market: str = "twse") -> dict | list | None:
    """讀取已存的原始 JSON"""
    filename = f"{market}_{date_str}.json"
    filepath = RAW_DIR / source / filename
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def is_fetched(source: str, date_str: str, market: str = "twse") -> bool:
    """檢查某日期是否已成功抓取"""
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM fetch_log "
        "WHERE source=? AND market=? AND fetch_date=? AND status='ok'",
        (source, market, date_str)
    ).fetchone()
    conn.close()
    return row is not None


def get_fetch_stats(source: str = None) -> list[dict]:
    """取得抓取統計"""
    conn = get_db()
    if source:
        rows = conn.execute(
            "SELECT source, market, MIN(fetch_date) as first, "
            "MAX(fetch_date) as last, COUNT(*) as days, "
            "SUM(record_count) as total_records "
            "FROM fetch_log WHERE source=? AND status='ok' "
            "GROUP BY source, market",
            (source,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT source, market, MIN(fetch_date) as first, "
            "MAX(fetch_date) as last, COUNT(*) as days, "
            "SUM(record_count) as total_records "
            "FROM fetch_log WHERE status='ok' "
            "GROUP BY source, market"
        ).fetchall()
    conn.close()
    return [
        {"source": r[0], "market": r[1], "first": r[2],
         "last": r[3], "days": r[4], "total_records": r[5]}
        for r in rows
    ]


def get_trading_dates(start: str = "20200102", end: str = None) -> list[str]:
    """產生交易日候選清單 (YYYYMMDD)，排除週末
    實際是否有交易由 API 回傳決定（假日/颱風假會回空）"""
    from datetime import timedelta
    if end is None:
        end = datetime.now().strftime("%Y%m%d")
    start_dt = datetime.strptime(start, "%Y%m%d")
    end_dt = datetime.strptime(end, "%Y%m%d")
    dates = []
    current = start_dt
    while current <= end_dt:
        if current.weekday() < 5:  # Mon-Fri
            dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates

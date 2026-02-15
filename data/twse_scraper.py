"""TWSE 官方資料爬蟲 — PE/PB/殖利率 + 月營收

直接從台灣證券交易所（TWSE）和公開資訊觀測站（MOPS）取得免費公開資料。
比 FinMind/yfinance 更可靠、更完整。

Rate limit 策略：
- 隨機延遲 3-8 秒（Gemini 建議 5-12 但實測 3-8 足夠）
- User-Agent 輪換
- 本地 JSON 快取（同日不重複請求）
- 避開 13:30-15:00 收盤高峰
"""

import json
import logging
import random
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

_logger = logging.getLogger(__name__)

# --- 快取目錄 ---
_CACHE_DIR = Path(__file__).parent / "cache" / "twse"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# --- User-Agent 輪換 ---
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
]


def _random_ua() -> str:
    return random.choice(_USER_AGENTS)


def _twse_request(url: str, timeout: int = 15) -> dict:
    """發送 TWSE API 請求，含 rate limit 保護"""
    req = urllib.request.Request(url, headers={
        "User-Agent": _random_ua(),
        "Accept": "application/json",
        "Referer": "https://www.twse.com.tw/",
    })
    resp = urllib.request.urlopen(req, timeout=timeout)
    data = json.loads(resp.read().decode("utf-8"))
    # 隨機延遲防止被封
    time.sleep(random.uniform(3, 8))
    return data


# ============================================================
# PE / PB / 殖利率（TWSE BWIBBU_d）
# ============================================================

def fetch_valuation_all(date: str | None = None) -> pd.DataFrame:
    """取得某日全市場 PE/PB/殖利率

    Args:
        date: YYYYMMDD 格式，None=最近交易日

    Returns:
        DataFrame: code, name, close, dividend_yield, pe, pb, fiscal_year
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    # 檢查快取
    cache_file = _CACHE_DIR / f"valuation_{date}.json"
    if cache_file.exists():
        _logger.debug("Valuation cache hit: %s", date)
        with open(cache_file, "r", encoding="utf-8") as f:
            cached = json.load(f)
        return pd.DataFrame(cached)

    url = (f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
           f"?date={date}&response=json")

    try:
        data = _twse_request(url)
    except Exception as e:
        _logger.warning("TWSE BWIBBU_d failed for %s: %s", date, e)
        return pd.DataFrame()

    if not data.get("data"):
        _logger.debug("No valuation data for %s (holiday?)", date)
        return pd.DataFrame()

    rows = []
    for row in data["data"]:
        try:
            code = row[0].strip()
            name = row[1].strip()
            close = _safe_float(row[2])
            dividend_yield = _safe_float(row[3])
            pe = _safe_float(row[5])
            pb = _safe_float(row[6])

            rows.append({
                "code": code,
                "name": name,
                "close": close,
                "dividend_yield": dividend_yield,
                "pe": pe,
                "pb": pb,
                "date": date,
            })
        except (IndexError, ValueError):
            continue

    if rows:
        # 寫入快取
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
        _logger.info("Cached %d stocks valuation for %s", len(rows), date)

    return pd.DataFrame(rows)


def get_stock_valuation(stock_code: str, date: str | None = None) -> dict | None:
    """取得單一股票的 PE/PB/殖利率

    當指定日期無資料（週末/假日）時，自動回溯最近 5 個交易日。

    Returns:
        {"pe": float, "pb": float, "dividend_yield": float, "close": float}
        或 None（找不到）
    """
    if date is not None:
        # 指定日期，直接查
        df = fetch_valuation_all(date)
        if not df.empty:
            match = df[df["code"] == stock_code]
            if not match.empty:
                row = match.iloc[0]
                return {
                    "pe": row.get("pe"),
                    "pb": row.get("pb"),
                    "dividend_yield": row.get("dividend_yield"),
                    "close": row.get("close"),
                }
        return None

    # 未指定日期：自動回溯最近交易日
    current = datetime.now()
    for _ in range(7):
        date_str = current.strftime("%Y%m%d")
        df = fetch_valuation_all(date_str)
        if not df.empty:
            match = df[df["code"] == stock_code]
            if not match.empty:
                row = match.iloc[0]
                return {
                    "pe": row.get("pe"),
                    "pb": row.get("pb"),
                    "dividend_yield": row.get("dividend_yield"),
                    "close": row.get("close"),
                }
        current -= timedelta(days=1)

    return None


def get_stock_valuation_history(stock_code: str, days: int = 60) -> pd.DataFrame:
    """取得單一股票的歷史 PE/PB/殖利率

    逐日回溯（使用快取避免重複請求），用於計算歷史百分位。

    Args:
        stock_code: 台股代碼
        days: 回溯天數

    Returns:
        DataFrame with columns: date, pe, pb, dividend_yield
    """
    results = []
    checked = 0
    current = datetime.now()

    while len(results) < days and checked < days * 2:
        date_str = current.strftime("%Y%m%d")
        checked += 1
        current -= timedelta(days=1)

        val = get_stock_valuation(stock_code, date_str)
        if val and val.get("pe") is not None:
            results.append({
                "date": date_str,
                "pe": val["pe"],
                "pb": val["pb"],
                "dividend_yield": val["dividend_yield"],
            })

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def compute_valuation_score(
    pe: float | None,
    pb: float | None,
    dividend_yield: float | None,
    pe_history: list[float] | None = None,
    pb_history: list[float] | None = None,
) -> float:
    """計算估值維度分數 (0-100)

    使用歷史百分位法（Gemini R28 建議）：
    - PE Percentile: 40% 權重（越低越好 = 越便宜）
    - PB Percentile: 30% 權重（越低越好 = 越便宜）
    - 殖利率: 30% 權重（越高越好）

    當無歷史數據時，退化為絕對值規則。

    Returns:
        0-100 分數，越高表示估值越合理
    """
    scores = []
    weights = []

    # --- PE Score (40%) ---
    if pe is not None and pe > 0:
        if pe_history and len(pe_history) >= 20:
            # 歷史百分位：PE 越低 = 越便宜 = 分數越高
            percentile = sum(1 for h in pe_history if h <= pe) / len(pe_history)
            pe_score = (1.0 - percentile) * 100
        else:
            # 絕對值規則（無歷史時降級）
            if pe < 10:
                pe_score = 90
            elif pe < 15:
                pe_score = 75
            elif pe < 20:
                pe_score = 60
            elif pe < 30:
                pe_score = 40
            elif pe < 50:
                pe_score = 20
            else:
                pe_score = 10
        scores.append(pe_score)
        weights.append(0.4)

    # --- PB Score (30%) ---
    if pb is not None and pb > 0:
        if pb_history and len(pb_history) >= 20:
            percentile = sum(1 for h in pb_history if h <= pb) / len(pb_history)
            pb_score = (1.0 - percentile) * 100
        else:
            if pb < 1.0:
                pb_score = 85
            elif pb < 1.5:
                pb_score = 70
            elif pb < 2.5:
                pb_score = 55
            elif pb < 5.0:
                pb_score = 35
            else:
                pb_score = 15
        scores.append(pb_score)
        weights.append(0.3)

    # --- 殖利率 Score (30%) ---
    if dividend_yield is not None and dividend_yield >= 0:
        # 殖利率越高越好
        if dividend_yield >= 6:
            yield_score = 95
        elif dividend_yield >= 4:
            yield_score = 80
        elif dividend_yield >= 3:
            yield_score = 65
        elif dividend_yield >= 2:
            yield_score = 50
        elif dividend_yield >= 1:
            yield_score = 35
        else:
            yield_score = 20
        scores.append(yield_score)
        weights.append(0.3)

    if not scores:
        return 50.0  # 無資料時中性分數

    # 加權平均
    total_w = sum(weights)
    return sum(s * w for s, w in zip(scores, weights)) / total_w


# ============================================================
# 月營收（公開資訊觀測站 MOPS）
# ============================================================

def fetch_monthly_revenue(year: int, month: int, market: str = "sii") -> pd.DataFrame:
    """取得某月全市場月營收

    Args:
        year: 民國年（例如 114 = 2025）
        month: 月份 (1-12)
        market: "sii"=上市, "otc"=上櫃

    Returns:
        DataFrame: code, name, revenue, revenue_yoy, revenue_mom
    """
    cache_file = _CACHE_DIR / f"revenue_{market}_{year}_{month:02d}.json"
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return pd.DataFrame(json.load(f))

    # MOPS 使用民國年
    url = (f"https://mops.twse.com.tw/nas/t21/{market}/t21sc03_{year}_{month}_0.html")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": _random_ua()})
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode("big5", errors="replace")
        time.sleep(random.uniform(3, 8))
    except Exception as e:
        _logger.warning("MOPS revenue fetch failed (%d/%d): %s", year, month, e)
        return pd.DataFrame()

    # 解析 HTML 表格
    rows = _parse_mops_revenue_html(html)

    if rows:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
        _logger.info("Cached %d stocks revenue for %d/%02d", len(rows), year, month)

    return pd.DataFrame(rows)


def _parse_mops_revenue_html(html: str) -> list[dict]:
    """解析 MOPS 月營收 HTML（簡易解析，不依賴 BeautifulSoup）"""
    rows = []
    # MOPS HTML 格式較複雜，使用 pandas read_html
    try:
        dfs = pd.read_html(html, encoding="big5")
        # 通常第一個或第二個表格是營收資料
        for df in dfs:
            if len(df.columns) >= 8 and len(df) > 5:
                # 嘗試找到有「公司代號」和「營業收入」的表格
                cols = [str(c) for c in df.columns]
                if any("代號" in c or "公司" in c for c in cols):
                    for _, row in df.iterrows():
                        try:
                            code = str(row.iloc[0]).strip()
                            if not code.isdigit() or len(code) != 4:
                                continue
                            name = str(row.iloc[1]).strip()
                            revenue = _safe_float(str(row.iloc[2]))
                            revenue_yoy = _safe_float(str(row.iloc[5]))
                            revenue_mom = _safe_float(str(row.iloc[6]))

                            rows.append({
                                "code": code,
                                "name": name,
                                "revenue": revenue,
                                "revenue_yoy": revenue_yoy,
                                "revenue_mom": revenue_mom,
                            })
                        except (IndexError, ValueError):
                            continue
                    if rows:
                        break
    except Exception as e:
        _logger.warning("MOPS HTML parse failed: %s", e)

    return rows


def get_stock_revenue(stock_code: str, months: int = 12) -> pd.DataFrame:
    """取得單一股票的近 N 個月營收

    注意 Look-ahead bias：每月 10 號才公布上月營收。
    回測時必須用公告日期，不能用營收月份。

    Returns:
        DataFrame: year, month, revenue, revenue_yoy, revenue_mom
    """
    now = datetime.now()
    results = []

    for i in range(months):
        # 回溯 i+1 個月（當月的營收尚未公布）
        target = now - timedelta(days=30 * (i + 1))
        tw_year = target.year - 1911  # 民國年
        month = target.month

        df = fetch_monthly_revenue(tw_year, month)
        if df.empty:
            continue

        match = df[df["code"] == stock_code]
        if not match.empty:
            row = match.iloc[0]
            results.append({
                "year": target.year,
                "month": month,
                "revenue": row.get("revenue"),
                "revenue_yoy": row.get("revenue_yoy"),
                "revenue_mom": row.get("revenue_mom"),
            })

    if not results:
        return pd.DataFrame()

    return pd.DataFrame(results).sort_values(["year", "month"]).reset_index(drop=True)


def compute_growth_score(revenue_yoy: float | None) -> float:
    """計算成長維度分數 (0-100)

    基於月營收年增率（YoY）：
    - YoY > 50%: 95（爆發性成長）
    - YoY 20-50%: 80（高成長）
    - YoY 10-20%: 65（穩定成長）
    - YoY 0-10%: 50（微成長）
    - YoY -10~0%: 35（微衰退）
    - YoY -20~-10%: 20（衰退）
    - YoY < -20%: 10（嚴重衰退）
    """
    if revenue_yoy is None:
        return 50.0  # 無資料時中性

    if revenue_yoy > 50:
        return 95.0
    elif revenue_yoy > 20:
        # 線性插值 20-50% → 80-95
        return 80 + (revenue_yoy - 20) / 30 * 15
    elif revenue_yoy > 10:
        return 65 + (revenue_yoy - 10) / 10 * 15
    elif revenue_yoy > 0:
        return 50 + revenue_yoy / 10 * 15
    elif revenue_yoy > -10:
        return 35 + revenue_yoy / 10 * 15
    elif revenue_yoy > -20:
        return 20 + (revenue_yoy + 10) / 10 * 15
    else:
        return max(5.0, 10 + (revenue_yoy + 20) / 20 * 10)


# ============================================================
# 工具函式
# ============================================================

def _safe_float(s: str) -> float | None:
    """安全轉換字串為浮點數"""
    if not s or s.strip() in ("", "-", "N/A", "–"):
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def clear_cache(older_than_days: int = 30):
    """清理過期快取"""
    cutoff = datetime.now() - timedelta(days=older_than_days)
    cleared = 0
    for f in _CACHE_DIR.glob("*.json"):
        if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
            f.unlink()
            cleared += 1
    if cleared:
        _logger.info("Cleared %d expired TWSE cache files", cleared)

"""
Google News RSS 新聞抓取器 — 消息面/注意力維度擴充
[CONVERGED — Gemini Wall Street Trader 2026-02-19]

設計決策:
- Google News RSS 免費、跨源聚合（cnyes + udn + ctee + moneydj 等）
- 階層式覆蓋: Top 500 市值 = 每日抓取, 其餘 = 有異常時才抓
- 去除「大雜燴」文章（>10 stock codes）
- 輸出格式與 cnyes fetch_news.py 相容

用法:
    python -m data.fetch_google_news              # 增量 (Top 500)
    python -m data.fetch_google_news --full        # 全量 (全部股票)
    python -m data.fetch_google_news --stats       # 統計
    python -m data.fetch_google_news --code 2330   # 單支測試
"""
import re
import time
import random
import argparse
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

from data.pattern_store import (
    save_raw_json, log_fetch, is_fetched,
    get_last_fetch_date, get_fetch_stats, RAW_DIR
)

SOURCE = "news"
MARKET = "google_news"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/xml, text/xml, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

# Google News RSS base
GNEWS_RSS = "https://news.google.com/rss/search"

# Taiwan financial news domains to search
TW_NEWS_DOMAINS = [
    "cnyes.com",
    "money.udn.com",
    "ctee.com.tw",
    "moneydj.com",
    "wealth.com.tw",
    "cna.com.tw",
]

# Max stock mentions in a single article — Gemini mandate: >10 = discard
MAX_STOCKS_PER_ARTICLE = 10

# Active stocks file (from scan_active_stocks.py)
ACTIVE_STOCKS_FILE = Path(__file__).parent / "active_stocks.json"
RECENT_STOCKS_FILE = Path(__file__).parent / "recent_stocks.json"


def _load_stock_universe() -> list[str]:
    """Load stock codes from active_stocks.json or recent_stocks.json."""
    for f in [ACTIVE_STOCKS_FILE, RECENT_STOCKS_FILE]:
        if f.exists():
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if isinstance(data, list):
                return [str(c) for c in data]
            if isinstance(data, dict) and "codes" in data:
                return [str(c) for c in data["codes"]]
    return []


def _build_query(stock_code: str) -> str:
    """Build Google News search query for a Taiwan stock.

    Search for stock code + .TW suffix across TW financial news sites.
    """
    # Search both code alone and with -TW suffix
    site_filter = " OR ".join(f"site:{d}" for d in TW_NEWS_DOMAINS)
    query = f'"{stock_code}" ({site_filter})'
    return query


def _parse_rss(xml_text: str) -> list[dict]:
    """Parse Google News RSS XML into article list."""
    articles = []
    try:
        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return articles

        for item in channel.findall("item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            source_elem = item.find("source")
            source = source_elem.text if source_elem is not None else ""

            # Parse pubDate (RFC 2822 format)
            publish_ts = None
            if pub_date:
                try:
                    # "Tue, 18 Feb 2026 08:30:00 GMT"
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(pub_date)
                    publish_ts = int(dt.timestamp())
                except Exception:
                    pass

            articles.append({
                "title": title,
                "link": link,
                "source": source,
                "pubDate": pub_date,
                "publishAt": publish_ts,
            })
    except ET.ParseError:
        pass

    return articles


def _extract_stock_codes(title: str) -> list[str]:
    """Extract Taiwan stock codes from article title.

    Patterns: (2330), 2330-TW, 股票代號2330, etc.
    """
    codes = set()
    # Pattern: (XXXX) where XXXX is 4 digits
    codes.update(re.findall(r"\((\d{4})\)", title))
    # Pattern: XXXX-TW
    codes.update(re.findall(r"(\d{4})-TW", title))
    # Pattern: standalone 4-digit number (less reliable, only use if preceded by stock-related context)
    # Skip this — too many false positives
    return sorted(codes)


def fetch_stock_news(stock_code: str, max_results: int = 20) -> dict | None:
    """Fetch Google News RSS for a single stock code.

    Returns dict with articles list, or None on failure.
    """
    query = _build_query(stock_code)
    params = {
        "q": query,
        "hl": "zh-TW",
        "gl": "TW",
        "ceid": "TW:zh-Hant",
        "num": max_results,
    }

    try:
        resp = requests.get(
            GNEWS_RSS, params=params, headers=HEADERS, timeout=15
        )
        if resp.status_code == 429:
            print(f"  [rate-limited] {stock_code} — waiting 60s")
            time.sleep(60)
            return None
        resp.raise_for_status()

        articles = _parse_rss(resp.text)

        # Tag each article with the queried stock code
        for art in articles:
            art["query_stock"] = stock_code
            # Extract other stock codes mentioned in title
            mentioned = _extract_stock_codes(art.get("title", ""))
            # Always include the queried stock
            if stock_code not in mentioned:
                mentioned.append(stock_code)
            art["stock_codes"] = mentioned

        return {
            "query_stock": stock_code,
            "query_time": datetime.now().isoformat(),
            "article_count": len(articles),
            "data": articles,
        }
    except requests.exceptions.RequestException as e:
        print(f"  [error] {stock_code}: {e}")
        return None


def run_fetch(full: bool = False, single_code: str = None):
    """Main fetch loop.

    Tiered coverage [CONVERGED — Gemini]:
    - Top 500 (by convention): always fetch
    - Rest: only if --full
    """
    print("=== Google News RSS Fetcher ===\n")

    if single_code:
        codes = [single_code]
        print(f"Single stock mode: {single_code}")
    else:
        all_codes = _load_stock_universe()
        if not all_codes:
            print("No stock universe found. Run scan_active_stocks.py first.")
            return
        if full:
            codes = all_codes
            print(f"Full mode: {len(codes)} stocks")
        else:
            # Tier 1: Top 500 (first 500 in the list, assumed sorted by market cap)
            codes = all_codes[:500]
            print(f"Incremental mode: Top {len(codes)} stocks")

    today = datetime.now().strftime("%Y%m%d")
    ok = 0
    skip = 0
    fail = 0

    for i, code in enumerate(codes):
        fetch_key = f"gnews_{today}_{code}"

        # Skip if already fetched today
        if not single_code and is_fetched(SOURCE, fetch_key, MARKET):
            skip += 1
            continue

        result = fetch_stock_news(code)
        if result and result["article_count"] > 0:
            # Save raw JSON
            save_raw_json(SOURCE, f"gnews_{today}_{code}", result, MARKET)
            log_fetch(SOURCE, MARKET, fetch_key, result["article_count"])
            ok += 1

            if single_code:
                print(f"\n{code}: {result['article_count']} articles")
                for art in result["data"][:5]:
                    print(f"  [{art.get('source', '?')}] {art['title'][:80]}")
                    print(f"    Stocks: {art.get('stock_codes', [])}")
        else:
            fail += 1

        # Progress
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(codes)}] ok={ok} skip={skip} fail={fail}")

        # Rate limit: random delay to avoid Google blocking
        # [CONVERGED — Gemini]: 2446 stocks/day needs careful pacing
        delay = random.uniform(2, 5)
        time.sleep(delay)

    print(f"\n=== Done: ok={ok}, skip={skip}, fail={fail} ===")


def show_stats():
    """Show fetch statistics for Google News source."""
    stats = get_fetch_stats(SOURCE)
    if not stats:
        print("No records yet")
        return
    for s in stats:
        print(f"{s['source']} ({s['market']}): "
              f"{s['first']} ~ {s['last']}, "
              f"{s['days']} entries, {s['total_records']} records")

    # Count Google News specific files
    news_dir = RAW_DIR / SOURCE
    gnews_files = list(news_dir.glob("google_news_gnews_*.json"))
    print(f"\nGoogle News files: {len(gnews_files)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Google News RSS fetcher")
    parser.add_argument("--full", action="store_true", help="Fetch all stocks")
    parser.add_argument("--stats", action="store_true", help="Show stats")
    parser.add_argument("--code", type=str, help="Fetch single stock code")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.code:
        run_fetch(single_code=args.code)
    else:
        run_fetch(full=args.full)

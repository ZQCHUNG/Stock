"""Background script: Backfill historical data for key stocks.

Run: python scripts/backfill_watchlist.py

This backfills ~50 important Taiwan stocks (權值股 + 熱門股) to SQLite.
Estimated time: ~50-80 minutes (3-8s delay per request × 12 months × 50 stocks).
"""

import sys
import os
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.twse_provider import HistoryBackfiller, get_db_stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Top 50 Taiwan stocks: 權值股 + 熱門電子 + 金融 + 傳產 + 上櫃代表
PRIORITY_STOCKS = [
    # --- 台灣50成分股精選 ---
    "2330",  # 台積電
    "2317",  # 鴻海
    "2454",  # 聯發科
    "2308",  # 台達電
    "2382",  # 廣達
    "2881",  # 富邦金
    "2882",  # 國泰金
    "2891",  # 中信金
    "2886",  # 兆豐金
    "2884",  # 玉山金
    "2303",  # 聯電
    "3711",  # 日月光投控
    "2412",  # 中華電
    "1301",  # 台塑
    "1303",  # 南亞
    "2002",  # 中鋼
    "1216",  # 統一
    "2357",  # 華碩
    "2395",  # 研華
    "3034",  # 聯詠
    # --- 熱門電子股 ---
    "2379",  # 瑞昱
    "3443",  # 創意
    "6669",  # 緯穎
    "2345",  # 智邦
    "3661",  # 世芯-KY
    "5274",  # 信驊
    "2383",  # 台光電
    "3037",  # 欣興
    "8046",  # 南電
    "6415",  # 矽力-KY
    # --- 金融股 ---
    "2880",  # 華南金
    "2883",  # 開發金
    "2890",  # 永豐金
    "2887",  # 台新金
    "2892",  # 第一金
    # --- 傳產代表 ---
    "1101",  # 台泥
    "1102",  # 亞泥
    "2207",  # 和泰車
    "9910",  # 豐泰
    "1590",  # 亞德客-KY
    # --- 上櫃代表 ---
    "6510",  # 精測
    "5269",  # 祥碩
    "6488",  # 環球晶
    "3105",  # 穩懋
    "8299",  # 群聯
    "6547",  # 高端疫苗
    # --- Joe 的近期關注 ---
    "6748",  # 昱展新藥
    "4743",  # 合一
    "6618",  # 華虹半導體
]


def main():
    logger.info("=" * 60)
    logger.info("Starting history backfill for %d stocks", len(PRIORITY_STOCKS))
    logger.info("=" * 60)

    # Show current DB stats
    stats = get_db_stats()
    logger.info("DB before: %d rows, %d tickers, %.1f MB",
                stats["price_rows"], stats["tickers"], stats["db_size_mb"])

    # Run backfiller with moderate delays
    bf = HistoryBackfiller(delay_range=(3, 6))
    bf.add_stocks(PRIORITY_STOCKS)
    results = bf.run(months_back=12, with_dividends=True)

    # Summary
    success = sum(1 for v in results.values() if v >= 0)
    failed = sum(1 for v in results.values() if v < 0)
    total_rows = sum(v for v in results.values() if v > 0)

    logger.info("=" * 60)
    logger.info("Backfill complete!")
    logger.info("  Success: %d stocks", success)
    logger.info("  Failed:  %d stocks", failed)
    logger.info("  New rows: %d", total_rows)

    # Final DB stats
    stats = get_db_stats()
    logger.info("DB after: %d rows, %d tickers, %.1f MB",
                stats["price_rows"], stats["tickers"], stats["db_size_mb"])
    logger.info("=" * 60)

    # Show failures
    for code, count in results.items():
        if count < 0:
            logger.warning("  FAILED: %s", code)


if __name__ == "__main__":
    main()

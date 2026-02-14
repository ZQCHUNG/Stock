"""背景掃描 Worker — 獨立程序，定期掃描股票池並將結果存入 Redis

啟動方式：python worker.py
搭配 Streamlit 主程式使用：python -m streamlit run app.py

架構設計（Gemini R9 建議，我認同這點）：
- Worker 是完全獨立的程序，不是 app.py 的子程序
- 透過 Redis 溝通：worker 算完存入，Streamlit 只管 redis.get()
- 部署：兩個 Process（一個 Streamlit，一個 worker）
- 用 PM2 或 start.bat 管理

掃描頻率：
- 盤中 (09:00-13:30)：每 15 分鐘掃描精選 25 檔
- 收盤後 (14:00)：掃描精選 25 檔一次（TTL 較長）
- 其他時段：休眠等待
"""

import time
import logging
from datetime import datetime

from config import SCAN_STOCKS
from data.fetcher import get_stock_data, populate_ticker_cache
from data.stock_list import get_all_stocks
from data.cache import (
    get_redis,
    set_cached_scan_results,
    set_worker_heartbeat,
)
from analysis.strategy_v4 import get_v4_analysis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("worker")


def _is_trading_hours() -> bool:
    """判斷是否在台股交易時間（週一至週五 09:00-13:30）"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return 9 * 60 <= t <= 13 * 60 + 30


def _is_post_close_window() -> bool:
    """判斷是否在收盤後掃描視窗（13:31-15:00）"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return 13 * 60 + 30 < t <= 15 * 60


def scan_stocks(stock_dict: dict) -> list[dict]:
    """掃描股票池，回傳 BUY 訊號列表"""
    results = []
    total = len(stock_dict)

    for idx, (code, name) in enumerate(stock_dict.items(), 1):
        try:
            display_name = name.get("name", name) if isinstance(name, dict) else name
            df = get_stock_data(code, period_days=200)
            if df is None or len(df) < 60:
                logger.debug(f"  [{idx}/{total}] {code} 資料不足，跳過")
                continue

            analysis = get_v4_analysis(df)
            analysis["code"] = code
            analysis["name"] = display_name

            if analysis["signal"] == "BUY":
                results.append(analysis)
                logger.info(f"  [{idx}/{total}] {code} {display_name} → BUY ({analysis.get('entry_type', '')})")
            else:
                logger.debug(f"  [{idx}/{total}] {code} → {analysis['signal']}")

        except Exception as e:
            logger.warning(f"  [{idx}/{total}] {code} 掃描失敗: {e}")
            continue

    return results


def main():
    logger.info("=" * 50)
    logger.info("背景掃描 Worker 啟動")
    logger.info("=" * 50)

    # 檢查 Redis
    r = get_redis()
    if r is None:
        logger.error("Redis 未連線，Worker 無法運作。請啟動 Redis 後重試。")
        return

    logger.info("Redis 已連線")

    # 載入股票清單並預填 ticker cache
    try:
        all_stocks = get_all_stocks()
        populate_ticker_cache(all_stocks)
        logger.info(f"股票清單載入完成：{len(all_stocks)} 檔")
    except Exception as e:
        logger.warning(f"股票清單載入失敗: {e}，使用 SCAN_STOCKS")

    scan_count = 0
    _post_close_done_date = None

    while True:
        try:
            now = datetime.now()

            if _is_trading_hours():
                # 盤中：掃描精選股
                logger.info(f"盤中掃描 {len(SCAN_STOCKS)} 檔精選股...")
                start_t = time.time()
                results = scan_stocks(SCAN_STOCKS)
                elapsed = time.time() - start_t
                scan_count += 1

                if results:
                    set_cached_scan_results(results, ttl=1200)  # 20 min
                    logger.info(f"掃描完成：{len(results)} 檔買入訊號（耗時 {elapsed:.1f}s）")
                else:
                    logger.info(f"掃描完成：無買入訊號（耗時 {elapsed:.1f}s）")

                set_worker_heartbeat(scan_count, len(SCAN_STOCKS), len(results))

                # 盤中每 15 分鐘
                logger.info("下次掃描：15 分鐘後")
                time.sleep(900)

            elif _is_post_close_window() and _post_close_done_date != now.date():
                # 收盤後：掃描一次
                logger.info(f"收盤後掃描 {len(SCAN_STOCKS)} 檔精選股...")
                start_t = time.time()
                results = scan_stocks(SCAN_STOCKS)
                elapsed = time.time() - start_t
                scan_count += 1

                if results:
                    set_cached_scan_results(results, ttl=7200)  # 2 hr
                    logger.info(f"收盤後掃描完成：{len(results)} 檔買入訊號（耗時 {elapsed:.1f}s）")
                else:
                    logger.info(f"收盤後掃描完成：無買入訊號（耗時 {elapsed:.1f}s）")

                set_worker_heartbeat(scan_count, len(SCAN_STOCKS), len(results))
                _post_close_done_date = now.date()

                time.sleep(60)

            else:
                # 非交易時段：休眠
                logger.debug("非交易時段，休眠 5 分鐘...")
                time.sleep(300)

        except KeyboardInterrupt:
            logger.info("Worker 收到中斷訊號，正常退出")
            break
        except Exception as e:
            logger.error(f"Worker 錯誤: {e}", exc_info=True)
            time.sleep(60)  # 錯誤後等待 1 分鐘再重試


if __name__ == "__main__":
    main()

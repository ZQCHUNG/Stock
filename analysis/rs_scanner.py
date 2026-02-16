"""R63: Full Market RS Scanner — uses get_stock_data() for automatic fallback

Uses data/fetcher.py (Redis → TWSE → yfinance → FinMind) per stock,
with ThreadPoolExecutor for concurrency.

Produces percentile-ranked RS ratings saved to data/rs_ranking.json.
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.strategy_bold import STRATEGY_BOLD_PARAMS, compute_rs_ratio
from data.stock_list import get_all_stocks

_logger = logging.getLogger(__name__)

RS_RANKING_PATH = Path("data") / "rs_ranking.json"


def _compute_single_rs(
    code: str,
    name: str,
    period_days: int,
    lookback: int,
    exclude_recent: int,
    base_weight: float,
    recent_weight: float,
    recent_days: int,
) -> dict | None:
    """Compute RS ratio for a single stock using get_stock_data() (with fallback)."""
    from data.fetcher import get_stock_data

    try:
        df = get_stock_data(code, period_days=period_days)
        if df is None or len(df) < lookback + exclude_recent:
            return None

        rs = compute_rs_ratio(
            df,
            lookback=lookback,
            exclude_recent=exclude_recent,
            base_weight=base_weight,
            recent_weight=recent_weight,
            recent_days=recent_days,
        )
        if rs is None:
            return None

        last_price = float(df["close"].iloc[-1])
        avg_vol = float(df["volume"].tail(20).mean() / 1000)

        return {
            "code": code,
            "name": name,
            "rs_ratio": round(rs, 4),
            "last_price": round(last_price, 1),
            "avg_vol_lots": round(avg_vol, 0),
            "data_len": len(df),
        }
    except Exception as e:
        _logger.debug("RS scan failed for %s: %s", code, e)
        return None


def scan_market_rs(
    max_workers: int = 8,
    min_code_len: int = 4,
    exclude_etf: bool = True,
) -> dict:
    """Run full market RS scan with parallel get_stock_data() calls.

    Args:
        max_workers: ThreadPoolExecutor concurrency limit
        min_code_len: Minimum stock code length (filters out indices)
        exclude_etf: If True, exclude codes starting with '0' (ETFs)

    Returns:
        dict with keys: scan_date, total_stocks, params, stats, rankings
    """
    t0 = time.time()
    p = STRATEGY_BOLD_PARAMS
    lookback = p.get("rs_lookback", 120)
    exclude_recent = p.get("rs_exclude_recent", 5)
    base_weight = p.get("rs_base_weight", 0.6)
    recent_weight = p.get("rs_recent_weight", 0.4)
    recent_days = p.get("rs_recent_days", 20)
    period_days = lookback + exclude_recent + 60  # Extra buffer

    stocks = get_all_stocks()
    stock_list = [
        (code, info["name"])
        for code, info in stocks.items()
        if len(code) >= min_code_len
        and (not exclude_etf or code[0] != "0")
    ]
    _logger.info("RS scan starting: %d stocks, %d workers", len(stock_list), max_workers)

    results = []
    failed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _compute_single_rs,
                code, name, period_days,
                lookback, exclude_recent,
                base_weight, recent_weight, recent_days,
            ): code
            for code, name in stock_list
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)
            else:
                failed += 1

    elapsed = time.time() - t0
    _logger.info(
        "RS scan done: %d/%d succeeded in %.0fs (%d failed)",
        len(results), len(stock_list), elapsed, failed,
    )

    if not results:
        return {
            "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "total_stocks": 0,
            "params": {},
            "stats": {},
            "rankings": [],
            "elapsed_sec": round(elapsed, 1),
        }

    # Percentile ranking
    df_rs = pd.DataFrame(results)
    df_rs["rs_rating"] = df_rs["rs_ratio"].rank(pct=True).mul(100).round(1)
    df_rs = df_rs.sort_values("rs_rating", ascending=False)

    rankings = df_rs.to_dict(orient="records")

    output = {
        "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_stocks": len(rankings),
        "params": {
            "lookback": lookback,
            "exclude_recent": exclude_recent,
            "base_weight": base_weight,
            "recent_weight": recent_weight,
            "recent_days": recent_days,
        },
        "stats": {
            "mean_rs": round(float(df_rs["rs_ratio"].mean()), 4),
            "median_rs": round(float(df_rs["rs_ratio"].median()), 4),
            "std_rs": round(float(df_rs["rs_ratio"].std()), 4),
        },
        "rankings": rankings,
        "elapsed_sec": round(elapsed, 1),
    }

    # Save to disk
    RS_RANKING_PATH.parent.mkdir(parents=True, exist_ok=True)
    RS_RANKING_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _logger.info("RS rankings saved to %s", RS_RANKING_PATH)

    return output


def get_cached_rankings() -> dict | None:
    """Read cached RS rankings from disk."""
    if not RS_RANKING_PATH.exists():
        return None
    try:
        return json.loads(RS_RANKING_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_stock_rs_rating(code: str) -> dict | None:
    """Look up a single stock's RS rating from cached rankings."""
    rankings = get_cached_rankings()
    if not rankings:
        return None
    for r in rankings.get("rankings", []):
        if r["code"] == code:
            grade = "Noise"
            rating = r.get("rs_rating", 0)
            if rating >= 80:
                grade = "Diamond"
            elif rating >= 60:
                grade = "Gold"
            elif rating >= 40:
                grade = "Silver"
            return {
                "code": code,
                "rs_ratio": r.get("rs_ratio"),
                "rs_rating": rating,
                "grade": grade,
                "scan_date": rankings.get("scan_date"),
            }
    return None

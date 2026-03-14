"""Failure Analyst — Rule-based Post-Mortem for Signal Failures.

Phase 6 P2: CTO directive — "知道為什麼賠錢"
Architect Gate: "Rule-based 第一, AI 第二"

When a realized signal's actual loss exceeds Worst Case:
  1. Check physical facts (earnings dates, TAIEX drops, news)
  2. Categorize failure cause rule-based
  3. Output always includes physical data (Entry/Exit/ATR)
  4. [AI_GENERATED_OPINION] label only if AI analysis used (P3, default OFF)

Categories:
  - EARNINGS: 財報/法說會 within T±2 days
  - SYSTEMIC: TAIEX dropped >2% in same period
  - NEWS: Negative news keywords detected
  - TECHNICAL: Default — no external catalyst found
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Negative keywords in news titles (TW stock context)
NEGATIVE_KEYWORDS = [
    "虧損", "下修", "裁員", "減資", "違約", "調查", "跳水", "暴跌",
    "下市", "撤銷", "罰款", "掏空", "警示", "退場", "大跌", "崩盤",
    "重訊", "異常", "停牌", "處分", "訴訟", "破產", "清算", "負面",
    "營收衰退", "獲利下滑", "毛利率下降", "法說會", "財報",
]


def analyze_failure(
    stock_code: str,
    signal_date: str,
    entry_price: float,
    worst_case_pct: float,
    actual_return: float,
) -> dict:
    """Analyze why a signal failed beyond its worst case.

    Args:
        stock_code: Stock code (e.g., "2330")
        signal_date: Signal date string "YYYY-MM-DD"
        entry_price: Entry price at signal
        worst_case_pct: Predicted worst case % (e.g., -15.0)
        actual_return: Actual T+21 return fraction (e.g., -0.20 for -20%)

    Returns:
        {
            "stock_code": str,
            "signal_date": str,
            "category": "EARNINGS" | "SYSTEMIC" | "NEWS" | "TECHNICAL",
            "summary": str,      # 200-char Chinese summary
            "physical_data": {    # Always present per Architect mandate
                "entry_price": float,
                "exit_price": float,
                "atr_at_entry": float | None,
                "actual_pct": float,
                "worst_case_pct": float,
                "excess_loss_pct": float,
            },
            "evidence": list[str],  # Supporting facts
            "ai_opinion": None,     # Reserved for P3 (default OFF)
        }
    """
    sig_dt = datetime.strptime(signal_date, "%Y-%m-%d")
    exit_dt = sig_dt + timedelta(days=30)  # approximate T+21 trading days
    actual_pct = round(actual_return * 100, 1)
    exit_price = round(entry_price * (1 + actual_return), 2)
    excess_loss = round(actual_pct - (worst_case_pct or 0), 1)

    # Physical data (Architect mandate: always show)
    physical_data = {
        "entry_price": entry_price,
        "exit_price": exit_price,
        "atr_at_entry": _get_atr_at_date(stock_code, signal_date),
        "actual_pct": actual_pct,
        "worst_case_pct": worst_case_pct,
        "excess_loss_pct": excess_loss,
    }

    evidence = []
    category = "TECHNICAL"  # default

    # Check 1: TAIEX systemic drop
    taiex_drop = _check_taiex_drop(sig_dt, exit_dt)
    if taiex_drop is not None and taiex_drop < -2.0:
        category = "SYSTEMIC"
        evidence.append(f"大盤同期跌幅 {taiex_drop:.1f}% (>2% 系統性風險)")

    # Check 2: Earnings / revenue announcement near signal date
    earnings_near = _check_earnings_proximity(stock_code, sig_dt)
    if earnings_near:
        category = "EARNINGS"
        evidence.append(earnings_near)

    # Check 3: Negative news
    news_hits = _check_negative_news(stock_code, sig_dt, exit_dt)
    if news_hits:
        if category == "TECHNICAL":  # only upgrade if no stronger cause found
            category = "NEWS"
        evidence.extend(news_hits[:3])  # top 3 negative articles

    # Generate summary
    summary = _generate_summary(stock_code, category, actual_pct, worst_case_pct, evidence)

    return {
        "stock_code": stock_code,
        "signal_date": signal_date,
        "category": category,
        "summary": summary,
        "physical_data": physical_data,
        "evidence": evidence,
        "ai_opinion": None,  # P3: reserved for async Gemini analysis
    }


def analyze_all_failures(days_back: int = 90) -> list[dict]:
    """Analyze all realized signals that failed beyond worst case.

    Returns list of failure analysis results.
    """
    from analysis.signal_log import get_realized_signals

    realized = get_realized_signals(days_back=days_back)
    failures = []

    for sig in realized:
        actual = sig.get("actual_return_d21")
        worst = sig.get("worst_case_pct")
        entry = sig.get("entry_price")

        if actual is None or worst is None or entry is None:
            continue

        # Check if actual loss exceeds worst case
        actual_pct = actual * 100  # convert fraction to percentage
        if actual_pct < worst:  # worst_case_pct is already in %, actual is fraction
            try:
                result = analyze_failure(
                    stock_code=sig["stock_code"],
                    signal_date=sig["signal_date"],
                    entry_price=entry,
                    worst_case_pct=worst,
                    actual_return=actual,
                )
                failures.append(result)
            except Exception as e:
                logger.debug("Failure analysis failed for %s: %s", sig["stock_code"], e)

    logger.info("Failure analysis: %d/%d realized signals exceeded worst case",
                len(failures), len(realized))
    return failures


# --- Physical Fact Checkers ---

def _check_taiex_drop(start_dt: datetime, end_dt: datetime) -> Optional[float]:
    """Check TAIEX performance during the signal period.

    Returns percentage change (negative = drop).
    """
    try:
        from data.fetcher import get_taiex_data
        import pandas as pd

        taiex = get_taiex_data(period_days=120)
        if taiex is None or taiex.empty:
            return None

        taiex.index = pd.to_datetime(taiex.index)
        mask = (taiex.index >= start_dt) & (taiex.index <= end_dt)
        period = taiex[mask]

        if len(period) < 2:
            return None

        start_price = float(period["close"].iloc[0])
        end_price = float(period["close"].iloc[-1])
        return round((end_price / start_price - 1) * 100, 1)
    except Exception as e:
        logger.debug(f"Operation failed, returning default: {e}")
        return None


def _check_earnings_proximity(stock_code: str, sig_dt: datetime) -> Optional[str]:
    """Check if an earnings/revenue announcement was near the signal date.

    Uses MOPS monthly revenue data — revenue announcements are typically
    on the 10th of each month for the previous month.
    Architect Gate: "財報日在 T±2 天內 → 直接回報財報波動風險"
    """
    try:
        # Revenue announcements: 10th of each month (±5 days for holidays)
        # Check if signal date is within ±5 days of the 10th
        day = sig_dt.day
        if 5 <= day <= 15:
            return f"月營收公告期間 (每月10日前後，信號日={sig_dt.strftime('%m/%d')})"

        # Also check quarterly earnings (typically March, May, August, November)
        # Q4: March 31, Q1: May 15, Q2: August 14, Q3: November 14
        quarterly_months = {3: "年報", 5: "Q1報", 8: "Q2報", 11: "Q3報"}
        if sig_dt.month in quarterly_months and 1 <= sig_dt.day <= 20:
            return f"{quarterly_months[sig_dt.month]}公告期間 ({sig_dt.strftime('%Y/%m')})"

        return None
    except Exception as e:
        logger.debug(f"Operation failed, returning default: {e}")
        return None


def _check_negative_news(
    stock_code: str, start_dt: datetime, end_dt: datetime
) -> list[str]:
    """Check for negative news articles in the signal period.

    Uses cached Google News data from data/pattern_data/raw/news/.
    """
    hits = []
    try:
        from data.pattern_store import RAW_DIR
        import json

        news_dir = RAW_DIR / "news"
        if not news_dir.exists():
            return hits

        # Look for news files for this stock
        for f in news_dir.glob(f"*_{stock_code}_*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                articles = data.get("data", [])
                for art in articles:
                    title = art.get("title", "")
                    pub_date = art.get("published", "")

                    # Check if article is within signal period
                    try:
                        if pub_date:
                            pub_dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                            if pub_dt.replace(tzinfo=None) < start_dt - timedelta(days=5):
                                continue
                            if pub_dt.replace(tzinfo=None) > end_dt + timedelta(days=5):
                                continue
                    except (ValueError, TypeError):
                        pass  # include if can't parse date

                    # Check for negative keywords
                    for kw in NEGATIVE_KEYWORDS:
                        if kw in title:
                            hits.append(f"[{kw}] {title[:60]}")
                            break
            except Exception as e:
                logger.debug(f"Skipping due to data load error: {e}")
                continue
    except Exception as e:
        logger.debug(f"Optional data load failed: {e}")

    return hits


def _get_atr_at_date(stock_code: str, signal_date: str) -> Optional[float]:
    """Get ATR(14) at the signal date."""
    try:
        import pandas as pd
        from data.fetcher import get_stock_data

        df = get_stock_data(stock_code, period_days=60)
        if df is None or df.empty:
            return None

        # Compute ATR(14)
        from analysis.indicators import calculate_atr
        atr_df = calculate_atr(df, period=14, method="sma")
        atr = atr_df["atr"]

        df.index = pd.to_datetime(df.index)
        sig_dt = pd.Timestamp(signal_date)

        # Find ATR at or before signal date
        valid = atr[df.index <= sig_dt].dropna()
        if not valid.empty:
            return round(float(valid.iloc[-1]), 2)
        return None
    except Exception as e:
        logger.debug(f"Operation failed, returning default: {e}")
        return None


def _generate_summary(
    stock_code: str,
    category: str,
    actual_pct: float,
    worst_case_pct: float,
    evidence: list[str],
) -> str:
    """Generate a concise Chinese summary (≤200 chars).

    Architect mandate: physical facts first, no AI speculation.
    """
    cat_names = {
        "EARNINGS": "財報/營收公告波動",
        "SYSTEMIC": "大盤系統性下跌",
        "NEWS": "個股負面新聞",
        "TECHNICAL": "技術面惡化（無外部催化劑）",
    }
    cause = cat_names.get(category, "未知")
    excess = round(actual_pct - (worst_case_pct or 0), 1)

    summary = f"{stock_code} 實際虧損 {actual_pct:.1f}% 超出預測 {worst_case_pct:.1f}%（偏離 {excess:.1f}pp）。"
    summary += f"主因：{cause}。"

    if evidence:
        summary += evidence[0][:60]

    return summary[:200]

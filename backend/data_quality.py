"""Data quality monitoring and validation (Gemini R48-2).

Checks data completeness, anomalies, and freshness for yfinance/FinMind data.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def check_stock_data_quality(
    df: pd.DataFrame,
    code: str,
    expected_days: int = 30,
) -> dict:
    """Check a single stock's data quality.

    Returns:
        {
            "code": str,
            "status": "ok" | "warning" | "error",
            "issues": [{"type": str, "severity": str, "detail": str}],
            "completeness_score": float (0-1),
            "last_date": str | None,
            "total_rows": int,
        }
    """
    issues = []

    if df is None or df.empty:
        return {
            "code": code,
            "status": "error",
            "issues": [{"type": "empty_data", "severity": "error", "detail": "無數據"}],
            "completeness_score": 0.0,
            "last_date": None,
            "total_rows": 0,
        }

    total_rows = len(df)

    # --- 1. Check required columns ---
    required = {"open", "high", "low", "close", "volume"}
    missing_cols = required - set(df.columns)
    if missing_cols:
        issues.append({
            "type": "missing_columns",
            "severity": "error",
            "detail": f"缺少欄位: {', '.join(missing_cols)}",
        })

    # --- 2. Check for NaN values in critical columns ---
    for col in ["close", "volume"]:
        if col in df.columns:
            nan_count = df[col].isna().sum()
            if nan_count > 0:
                pct = nan_count / total_rows
                sev = "error" if pct > 0.1 else "warning"
                issues.append({
                    "type": "null_values",
                    "severity": sev,
                    "detail": f"{col} 有 {nan_count} 筆空值 ({pct:.1%})",
                })

    # --- 3. Check for zero prices ---
    if "close" in df.columns:
        zero_count = (df["close"] == 0).sum()
        if zero_count > 0:
            issues.append({
                "type": "zero_price",
                "severity": "error",
                "detail": f"收盤價為 0 共 {zero_count} 筆",
            })

    # --- 4. Check for zero volume ---
    if "volume" in df.columns:
        zero_vol = (df["volume"] == 0).sum()
        if zero_vol > total_rows * 0.1:
            issues.append({
                "type": "zero_volume",
                "severity": "warning",
                "detail": f"成交量為 0 共 {zero_vol} 筆 ({zero_vol/total_rows:.1%})",
            })

    # --- 5. Check date gaps (missing trading days) ---
    if df.index.dtype == "datetime64[ns]" or hasattr(df.index, "date"):
        try:
            dates = pd.to_datetime(df.index)
            # Expected: ~5 trading days/week
            date_range = (dates.max() - dates.min()).days
            expected_rows = max(1, int(date_range * 5 / 7))
            gap_ratio = total_rows / expected_rows if expected_rows > 0 else 1
            if gap_ratio < 0.8:
                issues.append({
                    "type": "date_gaps",
                    "severity": "warning",
                    "detail": f"日期跳躍：期望 ~{expected_rows} 交易日，實際 {total_rows} ({gap_ratio:.1%})",
                })
        except Exception:
            pass

    # --- 6. Check price anomalies (>20% daily move) ---
    if "close" in df.columns and total_rows > 1:
        returns = df["close"].pct_change().dropna()
        extreme_moves = (returns.abs() > 0.20).sum()
        if extreme_moves > 0:
            issues.append({
                "type": "extreme_moves",
                "severity": "warning",
                "detail": f"日漲跌幅超過 20% 共 {extreme_moves} 筆（可能含除權息）",
            })

    # --- 7. Check OHLC consistency ---
    if all(c in df.columns for c in ["open", "high", "low", "close"]):
        invalid = (
            (df["high"] < df["low"]) |
            (df["high"] < df["open"]) |
            (df["high"] < df["close"]) |
            (df["low"] > df["open"]) |
            (df["low"] > df["close"])
        ).sum()
        if invalid > 0:
            issues.append({
                "type": "ohlc_inconsistency",
                "severity": "error",
                "detail": f"OHLC 邏輯不一致 {invalid} 筆（high<low 等）",
            })

    # --- 8. Freshness check ---
    last_date = None
    try:
        last_date = str(pd.to_datetime(df.index[-1]).date())
        days_stale = (datetime.now() - pd.to_datetime(df.index[-1])).days
        # Allow 3 days for weekends
        if days_stale > 5:
            issues.append({
                "type": "stale_data",
                "severity": "warning",
                "detail": f"最新數據日期 {last_date}，已過 {days_stale} 天",
            })
    except Exception:
        pass

    # --- Compute completeness score ---
    error_count = sum(1 for i in issues if i["severity"] == "error")
    warning_count = sum(1 for i in issues if i["severity"] == "warning")
    completeness = max(0, 1.0 - error_count * 0.3 - warning_count * 0.1)

    status = "ok"
    if error_count > 0:
        status = "error"
    elif warning_count > 0:
        status = "warning"

    return {
        "code": code,
        "status": status,
        "issues": issues,
        "completeness_score": round(completeness, 2),
        "last_date": last_date,
        "total_rows": total_rows,
    }


def check_batch_data_quality(
    stock_data: dict[str, pd.DataFrame],
) -> dict:
    """Check quality for multiple stocks at once.

    Returns:
        {
            "checked_at": str,
            "total_stocks": int,
            "ok_count": int,
            "warning_count": int,
            "error_count": int,
            "overall_score": float,
            "stocks": [per-stock results...],
            "critical_issues": [top issues needing attention],
        }
    """
    results = []
    for code, df in stock_data.items():
        result = check_stock_data_quality(df, code)
        results.append(result)

    ok_count = sum(1 for r in results if r["status"] == "ok")
    warning_count = sum(1 for r in results if r["status"] == "warning")
    error_count = sum(1 for r in results if r["status"] == "error")

    overall_score = (
        sum(r["completeness_score"] for r in results) / len(results)
        if results else 0
    )

    # Collect critical issues
    critical = []
    for r in results:
        for issue in r["issues"]:
            if issue["severity"] == "error":
                critical.append({
                    "code": r["code"],
                    "type": issue["type"],
                    "detail": issue["detail"],
                })

    # Sort by error severity
    results.sort(key=lambda r: (
        0 if r["status"] == "error" else 1 if r["status"] == "warning" else 2,
        r["completeness_score"],
    ))

    return {
        "checked_at": datetime.now().isoformat(),
        "total_stocks": len(results),
        "ok_count": ok_count,
        "warning_count": warning_count,
        "error_count": error_count,
        "overall_score": round(overall_score, 2),
        "stocks": results,
        "critical_issues": critical[:20],  # Top 20
    }

"""匯出工具 — CSV / JSON 匯出

R55-2: 為回測結果、投資組合、選股結果提供匯出功能
"""

import csv
import io
import json
from datetime import datetime


def backtest_to_csv(result: dict) -> str:
    """Convert single backtest result to CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)

    # Header section
    writer.writerow(["台股技術分析系統 — 回測報告"])
    writer.writerow(["匯出時間", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    writer.writerow(["股票代碼", result.get("code", "")])
    writer.writerow([])

    # Metrics section
    writer.writerow(["=== 績效指標 ==="])
    metrics = result.get("metrics", {})
    metric_labels = {
        "total_return": "總報酬率 (%)",
        "annual_return": "年化報酬率 (%)",
        "max_drawdown": "最大回撤 (%)",
        "sharpe_ratio": "Sharpe Ratio",
        "win_rate": "勝率 (%)",
        "total_trades": "總交易次數",
        "profit_factor": "獲利因子",
        "avg_holding_days": "平均持有天數",
        "calmar_ratio": "Calmar Ratio",
        "sortino_ratio": "Sortino Ratio",
    }
    for key, label in metric_labels.items():
        val = metrics.get(key)
        if val is not None:
            writer.writerow([label, _fmt_val(val)])
    writer.writerow([])

    # Trades section
    trades = result.get("trades", [])
    if trades:
        writer.writerow(["=== 交易明細 ==="])
        trade_headers = [
            "進場日期", "出場日期", "進場價", "出場價",
            "報酬率(%)", "持有天數", "出場原因",
        ]
        writer.writerow(trade_headers)
        for t in trades:
            writer.writerow([
                t.get("entry_date", ""),
                t.get("exit_date", ""),
                _fmt_val(t.get("entry_price")),
                _fmt_val(t.get("exit_price")),
                _fmt_val(t.get("return_pct")),
                t.get("holding_days", ""),
                t.get("exit_reason", ""),
            ])
    writer.writerow([])

    # Monthly returns
    monthly = result.get("monthly_returns", {})
    if monthly:
        writer.writerow(["=== 月報酬率 (%) ==="])
        writer.writerow(["年月", "報酬率(%)"])
        for ym, ret in sorted(monthly.items()):
            writer.writerow([ym, _fmt_val(ret)])

    return output.getvalue()


def portfolio_to_csv(positions: list, closed: list, summary: dict) -> str:
    """Convert portfolio positions to CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["台股技術分析系統 — 投資組合報告"])
    writer.writerow(["匯出時間", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    writer.writerow([])

    # Summary
    if summary:
        writer.writerow(["=== 組合摘要 ==="])
        writer.writerow(["總持倉數", summary.get("total_positions", 0)])
        writer.writerow(["持倉市值", _fmt_val(summary.get("total_market_value"))])
        writer.writerow(["未實現損益", _fmt_val(summary.get("unrealized_pnl"))])
        writer.writerow(["已實現損益", _fmt_val(summary.get("realized_pnl"))])
        writer.writerow([])

    # Open positions
    if positions:
        writer.writerow(["=== 持倉部位 ==="])
        writer.writerow([
            "代碼", "名稱", "進場日期", "進場價", "張數",
            "停損價", "追蹤停損", "信心分數", "備註",
        ])
        for p in positions:
            writer.writerow([
                p.get("code", ""),
                p.get("name", ""),
                p.get("entry_date", ""),
                _fmt_val(p.get("entry_price")),
                p.get("lots", ""),
                _fmt_val(p.get("stop_loss")),
                _fmt_val(p.get("trailing_stop")),
                _fmt_val(p.get("confidence")),
                p.get("note", ""),
            ])
        writer.writerow([])

    # Closed positions
    if closed:
        writer.writerow(["=== 已平倉 ==="])
        writer.writerow([
            "代碼", "名稱", "進場日期", "出場日期",
            "進場價", "出場價", "報酬率(%)", "損益", "出場原因",
        ])
        for p in closed:
            writer.writerow([
                p.get("code", ""),
                p.get("name", ""),
                p.get("entry_date", ""),
                p.get("exit_date", ""),
                _fmt_val(p.get("entry_price")),
                _fmt_val(p.get("exit_price")),
                _fmt_val(p.get("return_pct")),
                _fmt_val(p.get("net_pnl")),
                p.get("exit_reason", ""),
            ])

    return output.getvalue()


def screener_to_csv(results: list, filters: dict | None = None) -> str:
    """Convert screener results to CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["台股技術分析系統 — 選股結果"])
    writer.writerow(["匯出時間", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    if filters:
        writer.writerow(["篩選條件", json.dumps(filters, ensure_ascii=False)])
    writer.writerow([])

    if results:
        # Use keys from first result as headers
        headers = list(results[0].keys())
        writer.writerow(headers)
        for r in results:
            writer.writerow([_fmt_val(r.get(h)) for h in headers])

    return output.getvalue()


def report_to_csv(report: dict) -> str:
    """Convert analysis report to CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["台股技術分析系統 — 分析報告"])
    writer.writerow(["匯出時間", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    writer.writerow(["股票代碼", report.get("code", "")])
    writer.writerow([])

    # Technical summary
    tech = report.get("technical", {})
    if tech:
        writer.writerow(["=== 技術面 ==="])
        for key, val in tech.items():
            if not isinstance(val, (dict, list)):
                writer.writerow([key, _fmt_val(val)])
        writer.writerow([])

    # Fundamental summary
    fund = report.get("fundamental", {})
    if fund:
        writer.writerow(["=== 基本面 ==="])
        for key, val in fund.items():
            if not isinstance(val, (dict, list)):
                writer.writerow([key, _fmt_val(val)])
        writer.writerow([])

    # Recommendation
    rec = report.get("recommendation", {})
    if rec:
        writer.writerow(["=== 建議 ==="])
        writer.writerow(["評分", rec.get("score", "")])
        writer.writerow(["等級", rec.get("grade", "")])
        writer.writerow(["建議", rec.get("action", "")])
        targets = rec.get("targets", {})
        if targets:
            writer.writerow(["目標價", targets.get("target", "")])
            writer.writerow(["停損價", targets.get("stop_loss", "")])

    return output.getvalue()


def _fmt_val(val) -> str:
    """Format a value for CSV output."""
    if val is None:
        return ""
    if isinstance(val, float):
        return f"{val:.4f}" if abs(val) < 1 else f"{val:.2f}"
    return str(val)

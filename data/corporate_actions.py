"""R58: Corporate Action Detection

Detects ex-dividends, stock splits, trading halts, and limit up/down events
in Taiwan stock data. Provides warnings for backtest integrity.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Taiwan stock price limits: ±10% from previous close
LIMIT_UP_PCT = 0.10
LIMIT_DOWN_PCT = 0.10

# Price gap threshold for heuristic split/action detection
PRICE_GAP_THRESHOLD = 0.15  # >15% overnight gap → suspicious


@dataclass
class CorporateAction:
    """Single corporate action event."""
    date: pd.Timestamp
    action_type: str  # "dividend", "split", "halt", "limit_up", "limit_down"
    details: str = ""

    # Split specific
    split_ratio: float | None = None  # e.g., 2.0 for 1→2 split

    # Dividend specific
    dividend_amount: float | None = None

    # Price impact
    price_before: float | None = None
    price_after: float | None = None
    gap_pct: float | None = None


@dataclass
class CorporateActionReport:
    """Aggregated corporate actions for a stock over a period."""
    stock_code: str
    period_start: pd.Timestamp | None = None
    period_end: pd.Timestamp | None = None
    actions: list[CorporateAction] = field(default_factory=list)

    @property
    def has_splits(self) -> bool:
        return any(a.action_type == "split" for a in self.actions)

    @property
    def has_dividends(self) -> bool:
        return any(a.action_type == "dividend" for a in self.actions)

    @property
    def split_dates(self) -> list[pd.Timestamp]:
        return [a.date for a in self.actions if a.action_type == "split"]

    @property
    def dividend_dates(self) -> list[pd.Timestamp]:
        return [a.date for a in self.actions if a.action_type == "dividend"]

    @property
    def limit_hit_dates(self) -> list[pd.Timestamp]:
        return [a.date for a in self.actions
                if a.action_type in ("limit_up", "limit_down")]

    @property
    def halt_dates(self) -> list[pd.Timestamp]:
        return [a.date for a in self.actions if a.action_type == "halt"]

    def summary(self) -> dict:
        """Return summary dict for API/UI."""
        return {
            "stock_code": self.stock_code,
            "period_start": str(self.period_start)[:10] if self.period_start else None,
            "period_end": str(self.period_end)[:10] if self.period_end else None,
            "total_actions": len(self.actions),
            "splits": len([a for a in self.actions if a.action_type == "split"]),
            "dividends": len([a for a in self.actions if a.action_type == "dividend"]),
            "limit_hits": len([a for a in self.actions
                              if a.action_type in ("limit_up", "limit_down")]),
            "halts": len([a for a in self.actions if a.action_type == "halt"]),
            "actions": [
                {
                    "date": str(a.date)[:10],
                    "type": a.action_type,
                    "details": a.details,
                    "gap_pct": round(a.gap_pct, 4) if a.gap_pct else None,
                }
                for a in self.actions
            ],
        }


def get_splits_data(stock_code: str) -> pd.Series:
    """Fetch stock split history from yfinance.

    Returns:
        pd.Series with dates as index and split ratios as values.
        E.g., a 1:5 split shows as 5.0
    """
    import yfinance as yf
    from data.fetcher import get_ticker

    ticker_str = get_ticker(stock_code)
    ticker = yf.Ticker(ticker_str)
    splits = ticker.splits
    if splits is not None and not splits.empty:
        if splits.index.tz is not None:
            splits.index = splits.index.tz_localize(None)
        return splits
    return pd.Series(dtype=float)


def detect_limit_hits(df: pd.DataFrame, tolerance: float = 0.005) -> list[CorporateAction]:
    """Detect days where price hit limit up or limit down.

    Taiwan stocks have ±10% daily price limits from previous close.
    We detect when close price is within `tolerance` of the limit.

    Args:
        df: OHLCV DataFrame with 'close', 'open', 'high', 'low'
        tolerance: How close to limit counts as "hit" (0.5% default)
    """
    actions = []
    if len(df) < 2:
        return actions

    closes = df["close"].values
    highs = df["high"].values if "high" in df.columns else closes
    lows = df["low"].values if "low" in df.columns else closes
    dates = df.index

    for i in range(1, len(df)):
        prev_close = closes[i - 1]
        if prev_close <= 0:
            continue

        limit_up = prev_close * (1 + LIMIT_UP_PCT)
        limit_down = prev_close * (1 - LIMIT_DOWN_PCT)

        # Check if high reached limit up
        if highs[i] >= limit_up * (1 - tolerance):
            actions.append(CorporateAction(
                date=pd.Timestamp(dates[i]),
                action_type="limit_up",
                details=f"漲停 (前收 {prev_close:.2f}, 限 {limit_up:.2f})",
                price_before=prev_close,
                price_after=closes[i],
                gap_pct=(closes[i] - prev_close) / prev_close,
            ))

        # Check if low reached limit down
        if lows[i] <= limit_down * (1 + tolerance):
            actions.append(CorporateAction(
                date=pd.Timestamp(dates[i]),
                action_type="limit_down",
                details=f"跌停 (前收 {prev_close:.2f}, 限 {limit_down:.2f})",
                price_before=prev_close,
                price_after=closes[i],
                gap_pct=(closes[i] - prev_close) / prev_close,
            ))

    return actions


def detect_price_gaps(df: pd.DataFrame,
                      threshold: float = PRICE_GAP_THRESHOLD) -> list[CorporateAction]:
    """Detect suspicious overnight price gaps that may indicate
    unhandled corporate actions (splits, rights issues, etc.)

    Note: With auto_adjust=True, splits/dividends are already adjusted.
    This detects gaps in the *adjusted* data that may indicate data issues.

    Args:
        df: OHLCV DataFrame
        threshold: Minimum gap percentage to flag (default 15%)
    """
    actions = []
    if len(df) < 2:
        return actions

    closes = df["close"].values
    dates = df.index

    for i in range(1, len(df)):
        if closes[i - 1] <= 0:
            continue
        gap = (closes[i] - closes[i - 1]) / closes[i - 1]
        if abs(gap) >= threshold:
            actions.append(CorporateAction(
                date=pd.Timestamp(dates[i]),
                action_type="price_gap",
                details=f"隔夜跳空 {gap:+.1%} (前收 {closes[i-1]:.2f} → 收 {closes[i]:.2f})",
                price_before=closes[i - 1],
                price_after=closes[i],
                gap_pct=gap,
            ))

    return actions


def detect_zero_volume_days(df: pd.DataFrame) -> list[CorporateAction]:
    """Detect trading days with zero volume (possible halt/suspension).

    Args:
        df: OHLCV DataFrame with 'volume' column
    """
    actions = []
    if "volume" not in df.columns:
        return actions

    zero_vol = df[df["volume"] == 0]
    for date in zero_vol.index:
        actions.append(CorporateAction(
            date=pd.Timestamp(date),
            action_type="halt",
            details="成交量為零（可能暫停交易）",
        ))

    return actions


def detect_corporate_actions(
    stock_code: str,
    df: pd.DataFrame,
    dividends: pd.Series | None = None,
    splits: pd.Series | None = None,
    include_limits: bool = True,
    include_gaps: bool = True,
    include_halts: bool = True,
) -> CorporateActionReport:
    """Comprehensive corporate action detection for a stock.

    Combines data from yfinance (dividends, splits) with heuristic
    detection (price gaps, limit hits, zero volume).

    Args:
        stock_code: Stock code
        df: OHLCV DataFrame (adjusted prices)
        dividends: Dividend series (from fetcher.get_dividend_data)
        splits: Split series (from get_splits_data)
        include_limits: Detect limit up/down
        include_gaps: Detect suspicious price gaps
        include_halts: Detect zero-volume days (halts)
    """
    actions: list[CorporateAction] = []

    if df.empty:
        return CorporateActionReport(stock_code=stock_code, actions=[])

    period_start = pd.Timestamp(df.index[0])
    period_end = pd.Timestamp(df.index[-1])

    # 1. Known dividends from yfinance
    if dividends is not None and not dividends.empty:
        for date, amount in dividends.items():
            dt = pd.Timestamp(date)
            if period_start <= dt <= period_end:
                actions.append(CorporateAction(
                    date=dt,
                    action_type="dividend",
                    details=f"除息 {amount:.2f} 元/股",
                    dividend_amount=float(amount),
                ))

    # 2. Known splits from yfinance
    if splits is not None and not splits.empty:
        for date, ratio in splits.items():
            dt = pd.Timestamp(date)
            if period_start <= dt <= period_end:
                actions.append(CorporateAction(
                    date=dt,
                    action_type="split",
                    details=f"股票分割 1:{ratio:.0f}" if ratio > 1 else f"合併股 {ratio:.2f}:1",
                    split_ratio=float(ratio),
                ))

    # 3. Limit up/down detection
    if include_limits:
        actions.extend(detect_limit_hits(df))

    # 4. Suspicious price gaps
    if include_gaps:
        actions.extend(detect_price_gaps(df))

    # 5. Zero-volume halt detection
    if include_halts:
        actions.extend(detect_zero_volume_days(df))

    # Sort by date
    actions.sort(key=lambda a: a.date)

    return CorporateActionReport(
        stock_code=stock_code,
        period_start=period_start,
        period_end=period_end,
        actions=actions,
    )


def annotate_trades_with_actions(
    trades: list,
    report: CorporateActionReport,
) -> list[str]:
    """Check if any trades overlap with corporate actions and return warnings.

    Args:
        trades: List of Trade objects (from backtest)
        report: CorporateActionReport for the same period

    Returns:
        List of warning strings for affected trades
    """
    warnings = []
    if not report.actions or not trades:
        return warnings

    for i, trade in enumerate(trades):
        t_open = pd.Timestamp(trade.date_open)
        t_close = pd.Timestamp(trade.date_close) if trade.date_close else pd.Timestamp.now()

        for action in report.actions:
            if t_open <= action.date <= t_close:
                if action.action_type == "split":
                    warnings.append(
                        f"交易 #{i+1} ({str(t_open)[:10]}~{str(t_close)[:10]}): "
                        f"持倉期間發生股票分割 ({str(action.date)[:10]}, {action.details})"
                    )
                elif action.action_type == "dividend":
                    warnings.append(
                        f"交易 #{i+1} ({str(t_open)[:10]}~{str(t_close)[:10]}): "
                        f"持倉期間除息 ({str(action.date)[:10]}, {action.details})"
                    )
                elif action.action_type == "halt":
                    warnings.append(
                        f"交易 #{i+1} ({str(t_open)[:10]}~{str(t_close)[:10]}): "
                        f"持倉期間暫停交易 ({str(action.date)[:10]})"
                    )
                elif action.action_type in ("limit_up", "limit_down"):
                    warnings.append(
                        f"交易 #{i+1} ({str(t_open)[:10]}~{str(t_close)[:10]}): "
                        f"持倉期間觸及{'漲停' if action.action_type == 'limit_up' else '跌停'} "
                        f"({str(action.date)[:10]})"
                    )

    return warnings

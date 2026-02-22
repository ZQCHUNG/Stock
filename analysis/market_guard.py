"""Market Regime Global Switch — 全局市場環境斷路器

[CONVERGED — Wall Street Trader + Architect Critic APPROVED]

Two-level exposure limiter based on TAIEX trend + market breadth:

Level 1 (CAUTION — 50% exposure reduction):
  TAIEX < MA20 OR ADL declining 5 consecutive days
  → Internal capital is fleeing while index stocks prop up.

Level 2 (LOCKDOWN — no new entries):
  TAIEX < MA200 AND stocks above MA20 < 20%
  → Physical momentum completely gone. Entry ban.

Implementation: get_market_exposure_limit() returns 0.0-1.0 multiplier.
Even a 100-point Diamond SQS signal gets max_exposure=0 in Level 2.

All thresholds extracted to MARKET_GUARD_CONFIG as [HYPOTHESIS: MARKET_SENTIMENT_V1]
per Architect Critic mandate. Pending sensitivity test in Tier 2.
"""

from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Configuration — all thresholds are [HYPOTHESIS: MARKET_SENTIMENT_V1]
# Architect Critic mandate: extract to config, pending sensitivity test
# ---------------------------------------------------------------------------

MARKET_GUARD_CONFIG = {
    # Level 1 triggers (any ONE triggers CAUTION)
    "adl_decline_days": 5,           # [HYPOTHESIS] ADL consecutive decline days
    "level1_exposure": 0.50,         # 50% exposure when CAUTION

    # Level 2 triggers (ALL must be true for LOCKDOWN)
    "breadth_threshold": 0.20,       # [HYPOTHESIS] % stocks above MA20
    "level2_exposure": 0.0,          # 0% exposure (no new entries)

    # MA periods
    "ma20_period": 20,
    "ma200_period": 200,

    # Price gap defense (Architect Critic addition)
    "gap_down_pct": -0.03,           # [HYPOTHESIS] -3% open vs prev close
    "gap_volume_mult": 2.0,          # [HYPOTHESIS] volume > 2x 20d avg
}


@dataclass
class MarketGuardStatus:
    """Market guard assessment result."""
    level: int = 0                   # 0=NORMAL, 1=CAUTION, 2=LOCKDOWN
    level_label: str = "NORMAL"
    exposure_limit: float = 1.0      # 0.0 to 1.0 multiplier
    taiex_close: float = 0.0
    taiex_ma20: float = 0.0
    taiex_ma200: float = 0.0
    taiex_below_ma20: bool = False
    taiex_below_ma200: bool = False
    adl_declining_days: int = 0
    breadth_pct: float = 0.0         # % of stocks above their MA20
    triggers: list[str] = None       # Active trigger reasons
    price_gap_alert: bool = False    # Architect Critic: gap-down defense
    price_gap_pct: float = 0.0
    detail: str = ""

    def __post_init__(self):
        if self.triggers is None:
            self.triggers = []

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# ADL (Advance-Decline Line) Computation
# ---------------------------------------------------------------------------

def compute_adl(stock_closes: dict[str, pd.Series]) -> pd.Series:
    """Compute Advance-Decline Line from multiple stock close prices.

    ADL = cumulative sum of (advancing stocks - declining stocks) each day.

    Args:
        stock_closes: {stock_code: close_price_series} with DatetimeIndex

    Returns:
        ADL series indexed by date.
    """
    if not stock_closes:
        return pd.Series(dtype=float)

    # Align all stocks to common dates
    df = pd.DataFrame(stock_closes)
    if df.empty or len(df) < 2:
        return pd.Series(dtype=float)

    # Daily returns
    returns = df.pct_change()

    # Count advancing (>0) and declining (<0) stocks each day
    advancing = (returns > 0).sum(axis=1)
    declining = (returns < 0).sum(axis=1)

    # ADL = cumulative (advancing - declining)
    adl = (advancing - declining).cumsum()

    return adl


def compute_adl_declining_days(adl: pd.Series) -> int:
    """Count consecutive days ADL has been declining from the end.

    Args:
        adl: Advance-Decline Line series

    Returns:
        Number of consecutive declining days (0 if not declining)
    """
    if adl is None or len(adl) < 2:
        return 0

    count = 0
    for i in range(len(adl) - 1, 0, -1):
        if adl.iloc[i] < adl.iloc[i - 1]:
            count += 1
        else:
            break

    return count


# ---------------------------------------------------------------------------
# Market Breadth
# ---------------------------------------------------------------------------

def compute_market_breadth(stock_closes: dict[str, pd.Series],
                           ma_period: int = 20) -> float:
    """Compute percentage of stocks trading above their MA20.

    Args:
        stock_closes: {stock_code: close_price_series}
        ma_period: Moving average period (default 20)

    Returns:
        Fraction 0.0-1.0 of stocks above their MA.
    """
    if not stock_closes:
        return 0.0

    above_count = 0
    total_count = 0

    for code, close in stock_closes.items():
        if close is None or len(close) < ma_period + 1:
            continue
        ma = close.rolling(ma_period).mean()
        if pd.notna(ma.iloc[-1]) and pd.notna(close.iloc[-1]):
            total_count += 1
            if close.iloc[-1] > ma.iloc[-1]:
                above_count += 1

    if total_count == 0:
        return 0.0

    return above_count / total_count


# ---------------------------------------------------------------------------
# Price Gap Detection (Architect Critic addition)
# ---------------------------------------------------------------------------

def detect_price_gap(taiex_df: pd.DataFrame,
                     gap_pct: float = -0.03,
                     volume_mult: float = 2.0) -> tuple[bool, float]:
    """Detect gap-down opening on TAIEX.

    Args:
        taiex_df: TAIEX DataFrame with open, close, volume columns
        gap_pct: Threshold for gap-down (default -3%)
        volume_mult: Volume multiplier threshold (default 2x 20d avg)

    Returns:
        (is_gap_alert, gap_pct_value)
    """
    if taiex_df is None or len(taiex_df) < 21:
        return False, 0.0

    try:
        prev_close = float(taiex_df["close"].iloc[-2])
        today_open = float(taiex_df["open"].iloc[-1])
        today_volume = float(taiex_df["volume"].iloc[-1])
        avg_volume = float(taiex_df["volume"].iloc[-21:-1].mean())

        if prev_close <= 0:
            return False, 0.0

        gap = (today_open - prev_close) / prev_close
        high_volume = today_volume > avg_volume * volume_mult if avg_volume > 0 else False

        is_alert = gap < gap_pct and high_volume
        return is_alert, round(gap, 4)
    except (IndexError, KeyError):
        return False, 0.0


# ---------------------------------------------------------------------------
# Main: Get Market Exposure Limit
# ---------------------------------------------------------------------------

def get_market_exposure_limit(
    taiex_df: pd.DataFrame,
    stock_closes: Optional[dict[str, pd.Series]] = None,
    config: Optional[dict] = None,
) -> MarketGuardStatus:
    """Evaluate market conditions and return exposure limit.

    This is the Global Switch. Called before any trade entry to determine
    maximum allowed portfolio exposure.

    Args:
        taiex_df: TAIEX DataFrame with close/open/volume (min 200 days)
        stock_closes: {stock_code: close_series} for breadth + ADL
                      If None, only TAIEX MA checks are used.
        config: Override MARKET_GUARD_CONFIG params

    Returns:
        MarketGuardStatus with level (0/1/2) and exposure_limit (0.0-1.0)
    """
    cfg = dict(MARKET_GUARD_CONFIG)
    if config:
        cfg.update(config)

    status = MarketGuardStatus()
    triggers = []

    # --- TAIEX MA checks ---
    if taiex_df is None or len(taiex_df) < cfg["ma200_period"]:
        status.detail = "TAIEX data insufficient for market guard evaluation"
        return status

    close = taiex_df["close"]
    ma20 = close.rolling(cfg["ma20_period"]).mean()
    ma200 = close.rolling(cfg["ma200_period"]).mean()

    status.taiex_close = float(close.iloc[-1])
    status.taiex_ma20 = float(ma20.iloc[-1])
    status.taiex_ma200 = float(ma200.iloc[-1])
    status.taiex_below_ma20 = status.taiex_close < status.taiex_ma20
    status.taiex_below_ma200 = status.taiex_close < status.taiex_ma200

    # --- ADL check ---
    adl_declining = 0
    if stock_closes:
        adl = compute_adl(stock_closes)
        if len(adl) > 1:
            adl_declining = compute_adl_declining_days(adl)
    status.adl_declining_days = adl_declining

    # --- Market breadth ---
    breadth = 0.0
    if stock_closes:
        breadth = compute_market_breadth(stock_closes, cfg["ma20_period"])
    status.breadth_pct = round(breadth, 4)

    # --- Price gap detection ---
    gap_alert, gap_pct = detect_price_gap(
        taiex_df, cfg["gap_down_pct"], cfg["gap_volume_mult"]
    )
    status.price_gap_alert = gap_alert
    status.price_gap_pct = gap_pct

    # --- Level 2 check (strictest first) ---
    # TAIEX < MA200 AND breadth < 20%
    if status.taiex_below_ma200 and stock_closes and breadth < cfg["breadth_threshold"]:
        triggers.append(
            f"LOCKDOWN: TAIEX {status.taiex_close:,.0f} < MA200 "
            f"{status.taiex_ma200:,.0f} AND breadth {breadth:.0%} "
            f"< {cfg['breadth_threshold']:.0%}"
        )
        status.level = 2
        status.level_label = "LOCKDOWN"
        status.exposure_limit = cfg["level2_exposure"]
        status.triggers = triggers
        status.detail = (
            f"市場環境極度惡化。TAIEX 跌破 MA200 且僅 {breadth:.0%} 股票在 MA20 上方。"
            f"禁止所有新進場。"
        )
        return status

    # --- Level 1 checks (any one triggers CAUTION) ---
    if status.taiex_below_ma20:
        triggers.append(
            f"CAUTION: TAIEX {status.taiex_close:,.0f} < MA20 "
            f"{status.taiex_ma20:,.0f}"
        )

    if adl_declining >= cfg["adl_decline_days"]:
        triggers.append(
            f"CAUTION: ADL declining {adl_declining} consecutive days "
            f"(threshold: {cfg['adl_decline_days']})"
        )

    if gap_alert:
        triggers.append(
            f"CAUTION: Gap-down {gap_pct:.1%} with abnormal volume"
        )

    if triggers:
        status.level = 1
        status.level_label = "CAUTION"
        status.exposure_limit = cfg["level1_exposure"]
        status.triggers = triggers
        reasons = "、".join([
            t.split(": ", 1)[1] if ": " in t else t for t in triggers
        ])
        status.detail = (
            f"市場出現警示信號（{reasons}）。建議降低曝險至 "
            f"{cfg['level1_exposure']:.0%}。"
        )
        return status

    # --- Level 0: NORMAL ---
    status.level = 0
    status.level_label = "NORMAL"
    status.exposure_limit = 1.0
    status.triggers = []
    status.detail = (
        f"市場環境正常。TAIEX {status.taiex_close:,.0f} "
        f"> MA20 {status.taiex_ma20:,.0f}，"
        f"廣度 {breadth:.0%}。正常操作。"
    )

    return status

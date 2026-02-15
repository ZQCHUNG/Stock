"""Liquidity Score — 流動性風險量化 (R69)

三維度評分系統，量化個股的流動性風險：
1. DTL (Days to Liquidate) — 出清天數
2. Spread Score — 價差/波幅風險（含台股 tick size）
3. ADV Ratio — 部位占日均量比例

所有權重與門檻標記 PLACEHOLDER_NEEDS_DATA，等待實證驗證。
公式來源：Square Root Law (Kyle's Lambda) 用於市場衝擊估算。

Gemini R69 提案 → Opus 實作。
"""

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ─── Taiwan Stock Tick Size Table ───────────────────────────────
# Source: TWSE trading rules (證券交易所升降單位表)
TICK_SIZE_TABLE = [
    (10,    0.01),
    (50,    0.05),
    (100,   0.10),
    (500,   0.50),
    (1000,  1.00),
    (float('inf'), 5.00),
]


def get_tick_size(price: float) -> float:
    """Get Taiwan stock tick size for a given price level."""
    for threshold, tick in TICK_SIZE_TABLE:
        if price < threshold:
            return tick
    return 5.0


# ─── Configuration ──────────────────────────────────────────────
# All thresholds/weights marked per 假精確 protocol

LIQUIDITY_CONFIG = {
    # Dimension weights — PLACEHOLDER_NEEDS_DATA
    "weight_dtl": 0.40,
    "weight_spread": 0.40,
    "weight_adv_ratio": 0.20,

    # DTL parameters — HYPOTHESIS
    "participation_rate": 0.10,  # HYPOTHESIS: 10% of ADV is safe participation
    "dtl_high_risk": 2.0,       # PLACEHOLDER_NEEDS_DATA: DTL > 2 = high risk

    # Score grade thresholds — PLACEHOLDER_NEEDS_DATA
    "grade_green": 80,    # 1 天內可出清
    "grade_yellow": 50,   # 2-3 天拆單出清
    # < 50 = Red: 無量停損失敗風險

    # Spread score parameters
    "spread_lookback": 20,  # days for average spread calculation

    # ADV lookback
    "adv_lookback": 20,     # 20-day average daily volume
}


def calculate_dtl(position_size_shares: float, adv_20: float,
                  participation_rate: float | None = None) -> float:
    """計算出清天數 (Days to Liquidate)

    DTL = Position Size / (ADV_20 × Participation Rate)

    Args:
        position_size_shares: 持倉股數
        adv_20: 20日平均日成交量（股數）
        participation_rate: 參與率 (HYPOTHESIS: default 0.10)

    Returns:
        DTL value (days). Lower is better.
    """
    if participation_rate is None:
        participation_rate = LIQUIDITY_CONFIG["participation_rate"]

    if adv_20 <= 0 or participation_rate <= 0:
        return float('inf')

    return position_size_shares / (adv_20 * participation_rate)


def calculate_market_impact(position_size_shares: float, adv_20: float,
                            volatility_20: float) -> float:
    """估算市場衝擊成本 (Square Root Law)

    SC = σ_20 × sqrt(Position Size / ADV_20)

    This formula (Kyle's Lambda approximation) estimates the price impact
    of executing a large order relative to daily volume.

    Args:
        position_size_shares: 持倉股數
        adv_20: 20日平均日成交量（股數）
        volatility_20: 20日年化波動率（decimal, e.g. 0.30 = 30%）

    Returns:
        Estimated slippage as a fraction (e.g. 0.02 = 2%).
        PLACEHOLDER_NEEDS_DATA: needs validation against 6442 actual slippage.
    """
    if adv_20 <= 0:
        return float('inf')

    ratio = position_size_shares / adv_20
    if ratio <= 0:
        return 0.0

    return volatility_20 * np.sqrt(ratio)


def calculate_spread_score(highs: np.ndarray, lows: np.ndarray,
                           closes: np.ndarray, lookback: int = 20) -> float:
    """計算價差分數 (0-100, higher = better liquidity)

    Uses average (High-Low)/Close ratio as proxy for bid-ask spread.
    Incorporates tick_size_ratio as minimum spread floor.

    Args:
        highs: High price array
        lows: Low price array
        closes: Close price array
        lookback: Number of recent days to average

    Returns:
        Score 0-100. High score = tight spread = good liquidity.
    """
    if len(highs) < 2 or len(lows) < 2 or len(closes) < 2:
        return 50.0  # Insufficient data → neutral

    n = min(lookback, len(highs))
    h = highs[-n:]
    l = lows[-n:]
    c = closes[-n:]

    # Average daily range as spread proxy
    valid_mask = c > 0
    if not np.any(valid_mask):
        return 50.0

    daily_range_pct = np.where(valid_mask, (h - l) / c, 0)
    avg_range_pct = float(np.mean(daily_range_pct[valid_mask]))

    # Tick size ratio (minimum possible spread)
    last_price = float(c[-1])
    tick = get_tick_size(last_price)
    tick_ratio = tick / last_price if last_price > 0 else 0

    # Combine: use the larger of avg_range and tick_ratio
    effective_spread = max(avg_range_pct, tick_ratio)

    # Score mapping: tight spread → high score
    # effective_spread < 0.5% → ~100, > 5% → ~0
    # Using sigmoid-like mapping
    if effective_spread <= 0:
        return 100.0
    if effective_spread >= 0.10:  # 10% spread = essentially illiquid
        return 0.0

    # Linear interpolation: 0% → 100, 5% → 0
    score = max(0, min(100, (1 - effective_spread / 0.05) * 100))
    return round(score, 1)


def calculate_adv_ratio_score(position_size_shares: float,
                              adv_20: float) -> float:
    """計算部位佔比分數 (0-100, higher = better)

    Measures how large the position is relative to daily volume.
    Lower ratio = easier to enter/exit = higher score.

    Args:
        position_size_shares: 持倉股數
        adv_20: 20日平均日成交量（股數）

    Returns:
        Score 0-100.
    """
    if adv_20 <= 0:
        return 0.0

    ratio = position_size_shares / adv_20
    # ratio < 0.01 (1% of ADV) → ~100
    # ratio > 1.0 (100% of ADV) → ~0
    if ratio <= 0:
        return 100.0
    if ratio >= 1.0:
        return 0.0

    # Log scale: ratio=0.01 → 100, ratio=0.1 → 50, ratio=1.0 → 0
    score = max(0, min(100, (-np.log10(ratio)) * 50))
    return round(score, 1)


def calculate_dtl_score(dtl: float) -> float:
    """Convert DTL to a 0-100 score (higher = better liquidity).

    Args:
        dtl: Days to liquidate

    Returns:
        Score 0-100.
    """
    if dtl <= 0:
        return 100.0
    if dtl >= 10:
        return 0.0

    # DTL < 0.5 → ~100, DTL = 2 → ~50, DTL > 10 → 0
    # Exponential decay
    score = 100 * np.exp(-0.35 * dtl)
    return round(float(score), 1)


def calculate_liquidity_score(
    df: pd.DataFrame,
    position_size_ntd: float = 1_000_000,
    config: dict | None = None,
) -> dict:
    """計算綜合流動性分數 (0-100)

    Args:
        df: OHLCV DataFrame (must have 'close', 'high', 'low', 'volume' columns)
        position_size_ntd: 持倉金額（台幣），default 100萬
        config: Optional config override

    Returns:
        dict with:
            - score: 0-100 composite score
            - grade: "green" / "yellow" / "red"
            - dtl: days to liquidate
            - dtl_score: 0-100
            - spread_score: 0-100
            - adv_ratio_score: 0-100
            - adv_20: 20-day average volume (shares)
            - market_impact: estimated slippage %
            - tick_size: current tick size
            - details: human-readable breakdown
    """
    cfg = {**LIQUIDITY_CONFIG, **(config or {})}

    # Extract arrays
    closes = df['close'].values if 'close' in df.columns else np.array([])
    highs = df['high'].values if 'high' in df.columns else np.array([])
    lows = df['low'].values if 'low' in df.columns else np.array([])
    volumes = df['volume'].values if 'volume' in df.columns else np.array([])

    if len(closes) < 5 or len(volumes) < 5:
        return {
            "score": 0, "grade": "red",
            "dtl": float('inf'), "dtl_score": 0,
            "spread_score": 0, "adv_ratio_score": 0,
            "adv_20": 0, "market_impact": 0,
            "tick_size": 0, "details": "資料不足",
        }

    # Calculate ADV (20-day average volume in shares)
    lookback = min(cfg["adv_lookback"], len(volumes))
    adv_20 = float(np.mean(volumes[-lookback:]))

    # Current price for position sizing
    last_price = float(closes[-1])
    if last_price <= 0:
        return {
            "score": 0, "grade": "red",
            "dtl": float('inf'), "dtl_score": 0,
            "spread_score": 0, "adv_ratio_score": 0,
            "adv_20": adv_20, "market_impact": 0,
            "tick_size": 0, "details": "無有效股價",
        }

    # Convert NTD position to shares
    position_shares = position_size_ntd / last_price

    # 1. DTL Score
    dtl = calculate_dtl(position_shares, adv_20, cfg["participation_rate"])
    dtl_score = calculate_dtl_score(dtl)

    # 2. Spread Score (includes tick size)
    spread_score = calculate_spread_score(
        highs, lows, closes, cfg["spread_lookback"]
    )

    # 3. ADV Ratio Score
    adv_ratio_score = calculate_adv_ratio_score(position_shares, adv_20)

    # 4. Market Impact (informational, not part of composite score)
    # Calculate 20-day volatility
    if len(closes) >= 21:
        returns = np.diff(np.log(closes[-21:]))
        vol_20 = float(np.std(returns) * np.sqrt(252))
    else:
        vol_20 = 0.3  # Default 30% annualized

    market_impact = calculate_market_impact(position_shares, adv_20, vol_20)

    # Composite Score — PLACEHOLDER_NEEDS_DATA weights
    w_dtl = cfg["weight_dtl"]
    w_spread = cfg["weight_spread"]
    w_adv = cfg["weight_adv_ratio"]
    composite = (w_dtl * dtl_score + w_spread * spread_score + w_adv * adv_ratio_score)
    composite = round(composite, 1)

    # Grade — PLACEHOLDER_NEEDS_DATA thresholds
    if composite >= cfg["grade_green"]:
        grade = "green"
    elif composite >= cfg["grade_yellow"]:
        grade = "yellow"
    else:
        grade = "red"

    tick_size = get_tick_size(last_price)

    details = (
        f"DTL={dtl:.1f}天({dtl_score:.0f}分) | "
        f"Spread({spread_score:.0f}分) | "
        f"ADV比({adv_ratio_score:.0f}分) | "
        f"衝擊≈{market_impact:.2%}"
    )

    return {
        "score": composite,
        "grade": grade,
        "dtl": round(dtl, 2),
        "dtl_score": round(dtl_score, 1),
        "spread_score": round(spread_score, 1),
        "adv_ratio_score": round(adv_ratio_score, 1),
        "adv_20": round(adv_20, 0),
        "adv_20_lots": round(adv_20 / 1000, 1),  # 張數
        "market_impact": round(market_impact, 4),
        "market_impact_pct": round(market_impact * 100, 2),
        "tick_size": tick_size,
        "tick_ratio_pct": round(tick_size / last_price * 100, 3) if last_price > 0 else 0,
        "volatility_20": round(vol_20, 4) if 'vol_20' in dir() else 0.3,
        "position_shares": round(position_shares, 0),
        "last_price": round(last_price, 2),
        "details": details,
    }


def get_liquidity_grade_label(grade: str) -> str:
    """Get human-readable label for liquidity grade."""
    labels = {
        "green": "良好 — 可順利出清",
        "yellow": "注意 — 需拆單出場",
        "red": "危險 — 停損可能失敗",
    }
    return labels.get(grade, "未知")

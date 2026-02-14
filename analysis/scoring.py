"""Signal Quality Score (SQS) — 綜合決策分數（Gemini R42）

將多維度資料塌縮為 0-100 分的單一分數，讓 Joe 一眼判斷信號品質。

5 維度權重：
- 性格匹配 (Fitness)  30% — 策略是否符合標的「性格」
- 市場環境 (Regime)    25% — 當前氣候是否適合該策略
- 期望值   (Net EV)    20% — 歷史前瞻數據的真實勝算（扣除交易成本）
- 板塊熱度 (Heat)      15% — 資金流向的支持度
- 成熟度   (Maturity)  10% — 信號的發展階段
"""

import logging

logger = logging.getLogger(__name__)

# 台股來回交易成本: 手續費 0.1425%×2 + 稅 0.3% + 滑價 0.1%×2
TRANSACTION_COST = 0.00785

# SQS grade thresholds
SQS_DIAMOND = 80   # 鑽石級機會
SQS_GOLD = 60      # 高品質信號
SQS_NOISE = 40     # 低效噪音


def _score_fitness(fitness_tag: str, signal_strategy: str) -> float:
    """Score: 性格匹配（0-100）

    Measures whether the triggered strategy matches the stock's personality.
    """
    tag_to_preferred: dict[str, list[str]] = {
        "Trend Preferred (V4)": ["V4"],
        "Trend Only (V4)": ["V4"],
        "Volatility Preferred (V5)": ["V5"],
        "Reversion Only (V5)": ["V5"],
        "Balanced": ["V4", "V5", "Adaptive"],
    }
    preferred = tag_to_preferred.get(fitness_tag, [])

    if not preferred:
        # Insufficient Data / No Signal → neutral 50
        return 50.0

    if signal_strategy in preferred:
        return 100.0  # Perfect match
    if fitness_tag == "Balanced":
        return 80.0  # Balanced accepts all
    # Mismatch: e.g., V4 signal on Volatility Preferred stock
    return 20.0


def _score_regime(regime: str, signal_strategy: str) -> float:
    """Score: 市場環境（0-100）

    V4 thrives in trend markets, V5 in ranging markets.
    """
    matrix: dict[tuple[str, str], float] = {
        # (regime, strategy) → score
        ("bull", "V4"): 95,
        ("bull", "V5"): 50,
        ("bull", "Adaptive"): 80,
        ("sideways", "V4"): 45,
        ("sideways", "V5"): 85,
        ("sideways", "Adaptive"): 75,
        ("bear", "V4"): 20,
        ("bear", "V5"): 60,
        ("bear", "Adaptive"): 50,
    }
    return matrix.get((regime, signal_strategy), 50.0)


def _score_net_ev(raw_ev: float | None, sample_count: int) -> float:
    """Score: 期望值（0-100）

    Uses Net EV (raw EV minus transaction cost).
    Penalizes small samples with confidence discount.
    """
    if raw_ev is None or sample_count < 3:
        return 40.0  # Insufficient data → slightly below neutral

    net_ev = raw_ev - TRANSACTION_COST

    # Confidence discount for small samples
    # Full confidence at n≥20, linear decay below
    confidence = min(1.0, sample_count / 20)

    # Map Net EV to score: -2% → 0, 0% → 50, +3% → 100
    if net_ev >= 0.03:
        base_score = 100.0
    elif net_ev >= 0:
        base_score = 50.0 + (net_ev / 0.03) * 50.0
    elif net_ev >= -0.02:
        base_score = max(0, 50.0 + (net_ev / 0.02) * 50.0)
    else:
        base_score = 0.0

    # Blend with neutral based on confidence
    return base_score * confidence + 40.0 * (1 - confidence)


def _score_heat(sector_weighted_heat: float | None, sector_momentum: str) -> float:
    """Score: 板塊熱度（0-100）

    Combines absolute heat level with momentum direction.
    """
    if sector_weighted_heat is None:
        return 50.0  # No data → neutral

    # Base from weighted_heat (0-1 range → 0-70)
    heat_base = min(70.0, sector_weighted_heat * 100)

    # Momentum bonus/penalty
    momentum_adj = {
        "surge": 30.0,
        "heating": 20.0,
        "stable": 0.0,
        "cooling": -20.0,
    }
    adj = momentum_adj.get(sector_momentum, 0.0)

    return max(0.0, min(100.0, heat_base + adj))


def _score_maturity(signal_maturity: str) -> float:
    """Score: 成熟度（0-100）

    Structural Shift > Trend Formation > Speculative Spike.
    """
    scores = {
        "Structural Shift": 95.0,
        "Trend Formation": 70.0,
        "Speculative Spike": 30.0,
        "N/A": 40.0,
    }
    return scores.get(signal_maturity, 40.0)


def calculate_sqs(
    fitness_tag: str = "",
    signal_strategy: str = "V4",
    regime: str = "sideways",
    raw_ev_20d: float | None = None,
    ev_sample_count: int = 0,
    sector_weighted_heat: float | None = None,
    sector_momentum: str = "stable",
    signal_maturity: str = "N/A",
) -> dict:
    """Calculate Signal Quality Score (SQS).

    Returns:
        dict with sqs (0-100), grade, breakdown, net_ev, cost_drag
    """
    # Individual dimension scores
    s_fitness = _score_fitness(fitness_tag, signal_strategy)
    s_regime = _score_regime(regime, signal_strategy)
    s_ev = _score_net_ev(raw_ev_20d, ev_sample_count)
    s_heat = _score_heat(sector_weighted_heat, sector_momentum)
    s_maturity = _score_maturity(signal_maturity)

    # Weighted sum
    sqs = (
        s_fitness * 0.30
        + s_regime * 0.25
        + s_ev * 0.20
        + s_heat * 0.15
        + s_maturity * 0.10
    )

    # Grade
    if sqs >= SQS_DIAMOND:
        grade = "diamond"
        grade_label = "鑽石級機會"
    elif sqs >= SQS_GOLD:
        grade = "gold"
        grade_label = "高品質信號"
    elif sqs >= SQS_NOISE:
        grade = "silver"
        grade_label = "普通信號"
    else:
        grade = "noise"
        grade_label = "低效噪音"

    # Net EV computation
    net_ev = (raw_ev_20d - TRANSACTION_COST) if raw_ev_20d is not None else None
    cost_trap = raw_ev_20d is not None and raw_ev_20d > 0 and net_ev is not None and net_ev < 0

    return {
        "sqs": round(sqs, 1),
        "grade": grade,
        "grade_label": grade_label,
        "net_ev": round(net_ev, 5) if net_ev is not None else None,
        "raw_ev": round(raw_ev_20d, 5) if raw_ev_20d is not None else None,
        "cost_drag": TRANSACTION_COST,
        "cost_trap": cost_trap,
        "breakdown": {
            "fitness": round(s_fitness, 1),
            "regime": round(s_regime, 1),
            "net_ev": round(s_ev, 1),
            "heat": round(s_heat, 1),
            "maturity": round(s_maturity, 1),
        },
    }


def compute_sqs_for_signal(
    code: str,
    signal_strategy: str,
    signal_maturity: str = "N/A",
) -> dict:
    """Convenience function: compute SQS for a stock with BUY signal.

    Gathers all dimension data from various sources automatically.
    """
    # 1. Fitness tag
    fitness_tag = ""
    try:
        from analysis.strategy_fitness import get_fitness_tags
        tags = get_fitness_tags([code])
        if tags:
            fitness_tag = tags[0].get("fitness_tag", "")
    except Exception:
        pass

    # 2. Market regime
    regime = "sideways"
    try:
        from analysis.market_regime import detect_market_regime
        regime_data = detect_market_regime()
        regime = regime_data.get("regime", "sideways")
    except Exception:
        pass

    # 3. Signal EV (per-stock)
    raw_ev_20d = None
    ev_sample_count = 0
    try:
        from analysis.signal_tracker import get_stock_signal_summary
        summary = get_stock_signal_summary(code, days=180)
        if summary.get("has_data"):
            strat_data = summary["strategies"].get(signal_strategy, {})
            raw_ev_20d = strat_data.get("ev_20d")
            # Fallback to d5 if d20 not yet available
            if raw_ev_20d is None:
                raw_ev_20d = strat_data.get("ev_5d")
            ev_sample_count = strat_data.get("sample_count", 0)
    except Exception:
        pass

    # 4. Sector heat
    sector_weighted_heat = None
    sector_momentum = "stable"
    try:
        from data.cache import get_cached_sector_heat
        from data.sector_mapping import get_stock_sector
        sector_l1 = get_stock_sector(code, level=1)
        cached = get_cached_sector_heat()
        if cached:
            for sec in cached.get("sectors", []):
                if sec.get("sector") == sector_l1:
                    sector_weighted_heat = sec.get("weighted_heat")
                    sector_momentum = sec.get("momentum", "stable")
                    break
    except Exception:
        pass

    sqs_result = calculate_sqs(
        fitness_tag=fitness_tag,
        signal_strategy=signal_strategy,
        regime=regime,
        raw_ev_20d=raw_ev_20d,
        ev_sample_count=ev_sample_count,
        sector_weighted_heat=sector_weighted_heat,
        sector_momentum=sector_momentum,
        signal_maturity=signal_maturity,
    )
    sqs_result["code"] = code
    sqs_result["fitness_tag"] = fitness_tag
    return sqs_result

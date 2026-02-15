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


def _score_valuation(
    pe: float | None,
    pb: float | None,
    dividend_yield: float | None,
    pe_history: list[float] | None = None,
    pb_history: list[float] | None = None,
) -> float:
    """Score: 估值合理性（0-100）— R62 新增

    PE Percentile 40% + PB Percentile 30% + 殖利率 30%
    越便宜（PE/PB 低、殖利率高）分數越高。
    無歷史數據時降級為絕對值規則。
    """
    from data.twse_scraper import compute_valuation_score
    return compute_valuation_score(pe, pb, dividend_yield, pe_history, pb_history)


def _score_growth(revenue_yoy: float | None) -> float:
    """Score: 成長動能（0-100）— R62 新增

    基於月營收年增率。YoY > 20% = 高成長。
    """
    from data.twse_scraper import compute_growth_score
    return compute_growth_score(revenue_yoy)


def _score_institutional(inst_net_ratio: float | None) -> float:
    """Score: 法人動向（0-100）（Gemini R44, backward-compatible single ratio）

    inst_net_ratio: 近 5 日法人淨買賣超佔成交量比例（正=買超, 負=賣超）
    Typical range: -0.3 to +0.3 (30% of volume)
    """
    if inst_net_ratio is None:
        return 50.0  # No data → neutral

    # Map ratio to score: -0.2 → 10, 0 → 50, +0.2 → 90
    if inst_net_ratio >= 0.2:
        return 95.0
    elif inst_net_ratio >= 0:
        return 50.0 + (inst_net_ratio / 0.2) * 45.0
    elif inst_net_ratio >= -0.2:
        return max(10.0, 50.0 + (inst_net_ratio / 0.2) * 40.0)
    else:
        return 10.0


# R45-3: Market cap tiers for institutional weight distribution
MCAP_LARGE = 50e9   # 500億 TWD — 大型股
MCAP_MID = 10e9     # 100億 TWD — 中型股

# Weights: (foreign, trust, dealer) — must sum to 1.0
INST_WEIGHTS_LARGE = (0.70, 0.20, 0.10)  # 大型股: 外資主導
INST_WEIGHTS_MID = (0.45, 0.35, 0.20)    # 中型股: 較均衡
INST_WEIGHTS_SMALL = (0.25, 0.50, 0.25)  # 小型股: 投信影響大


def _get_inst_weights(market_cap: float | None) -> tuple[float, float, float]:
    """Get institutional weight distribution based on market cap tier."""
    if market_cap is None or market_cap <= 0:
        return INST_WEIGHTS_MID  # Default: balanced
    if market_cap >= MCAP_LARGE:
        return INST_WEIGHTS_LARGE
    elif market_cap >= MCAP_MID:
        return INST_WEIGHTS_MID
    else:
        return INST_WEIGHTS_SMALL


def _ratio_to_score(ratio: float | None) -> float:
    """Convert a single institutional net ratio to a 0-100 score."""
    if ratio is None:
        return 50.0
    if ratio >= 0.2:
        return 95.0
    elif ratio >= 0:
        return 50.0 + (ratio / 0.2) * 45.0
    elif ratio >= -0.2:
        return max(10.0, 50.0 + (ratio / 0.2) * 40.0)
    else:
        return 10.0


def _score_institutional_weighted(
    foreign_ratio: float | None,
    trust_ratio: float | None,
    dealer_ratio: float | None,
    market_cap: float | None,
) -> float:
    """Score: 法人動向 — 市值分層加權版（Gemini R45-3）

    大型股: 外資 70% + 投信 20% + 自營 10%
    中型股: 外資 45% + 投信 35% + 自營 20%
    小型股: 外資 25% + 投信 50% + 自營 25%

    Returns 0-100 score.
    """
    w_f, w_t, w_d = _get_inst_weights(market_cap)
    s_foreign = _ratio_to_score(foreign_ratio)
    s_trust = _ratio_to_score(trust_ratio)
    s_dealer = _ratio_to_score(dealer_ratio)

    return s_foreign * w_f + s_trust * w_t + s_dealer * w_d


def calculate_sqs(
    fitness_tag: str = "",
    signal_strategy: str = "V4",
    regime: str = "sideways",
    raw_ev_20d: float | None = None,
    ev_sample_count: int = 0,
    sector_weighted_heat: float | None = None,
    sector_momentum: str = "stable",
    signal_maturity: str = "N/A",
    inst_net_ratio: float | None = None,
    # R45-3: Market cap weighted institutional breakdown
    foreign_ratio: float | None = None,
    trust_ratio: float | None = None,
    dealer_ratio: float | None = None,
    market_cap: float | None = None,
    # R62: Valuation + Growth dimensions (TWSE free data)
    pe_ratio: float | None = None,
    pb_ratio: float | None = None,
    dividend_yield: float | None = None,
    pe_history: list[float] | None = None,
    pb_history: list[float] | None = None,
    revenue_yoy: float | None = None,
) -> dict:
    """Calculate Signal Quality Score (SQS).

    8 dimensions (R62: Valuation + Growth from TWSE free data):
    - Institutional 20%, Growth 15%, Fitness 15%,
    - Valuation 10%, Regime 10%, EV 10%, Heat 10%, Maturity 10%

    Returns:
        dict with sqs (0-100), grade, breakdown, net_ev, cost_drag
    """
    # Individual dimension scores
    s_fitness = _score_fitness(fitness_tag, signal_strategy)
    s_regime = _score_regime(regime, signal_strategy)
    s_ev = _score_net_ev(raw_ev_20d, ev_sample_count)
    s_heat = _score_heat(sector_weighted_heat, sector_momentum)
    s_maturity = _score_maturity(signal_maturity)

    # R45-3: Use weighted institutional if breakdown available, else fallback to combined
    if foreign_ratio is not None or trust_ratio is not None or dealer_ratio is not None:
        s_inst = _score_institutional_weighted(foreign_ratio, trust_ratio, dealer_ratio, market_cap)
    else:
        s_inst = _score_institutional(inst_net_ratio)

    # R62: Valuation + Growth dimensions (TWSE free data)
    s_valuation = _score_valuation(pe_ratio, pb_ratio, dividend_yield, pe_history, pb_history)
    s_growth = _score_growth(revenue_yoy)

    # R62: 8-dimension weighted sum
    # When new dimensions have data: use full 8-dim weights (Gemini R28 agreed)
    has_valuation = pe_ratio is not None or pb_ratio is not None or dividend_yield is not None
    has_growth = revenue_yoy is not None

    if has_valuation or has_growth:
        # Full 8-dim: Inst 20%, Growth 15%, Fitness 15%, Val 10%, Regime 10%, EV 10%, Heat 10%, Mat 10%
        sqs = (
            s_inst * 0.20
            + s_growth * 0.15
            + s_fitness * 0.15
            + s_valuation * 0.10
            + s_regime * 0.10
            + s_ev * 0.10
            + s_heat * 0.10
            + s_maturity * 0.10
        )
    else:
        # Legacy 6-dim (backward compatible when no fundamental data)
        sqs = (
            s_fitness * 0.25
            + s_regime * 0.20
            + s_ev * 0.15
            + s_heat * 0.10
            + s_maturity * 0.10
            + s_inst * 0.20
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

    # Determine market cap tier label
    if market_cap is not None and market_cap > 0:
        if market_cap >= MCAP_LARGE:
            mcap_tier = "large"
        elif market_cap >= MCAP_MID:
            mcap_tier = "mid"
        else:
            mcap_tier = "small"
    else:
        mcap_tier = None

    return {
        "sqs": round(sqs, 1),
        "grade": grade,
        "grade_label": grade_label,
        "net_ev": round(net_ev, 5) if net_ev is not None else None,
        "raw_ev": round(raw_ev_20d, 5) if raw_ev_20d is not None else None,
        "cost_drag": TRANSACTION_COST,
        "cost_trap": cost_trap,
        "mcap_tier": mcap_tier,
        "breakdown": {
            "fitness": round(s_fitness, 1),
            "regime": round(s_regime, 1),
            "net_ev": round(s_ev, 1),
            "heat": round(s_heat, 1),
            "maturity": round(s_maturity, 1),
            "institutional": round(s_inst, 1),
            "valuation": round(s_valuation, 1),
            "growth": round(s_growth, 1),
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

    # 5. Institutional flow (R45-3: market-cap-weighted breakdown)
    inst_net_ratio = None
    foreign_ratio = None
    trust_ratio = None
    dealer_ratio = None
    market_cap = None
    try:
        from data.fetcher import get_institutional_data, get_stock_data
        inst_df = get_institutional_data(code, days=5)
        if inst_df is not None and len(inst_df) >= 3:
            df = get_stock_data(code, period_days=10)
            if df is not None and len(df) >= 5:
                avg_vol = float(df["volume"].tail(5).mean())
                if avg_vol > 0:
                    total_vol_5d = avg_vol * 5
                    inst_net_ratio = inst_df["total_net"].sum() / total_vol_5d
                    # Per-institution ratios
                    if "foreign_net" in inst_df.columns:
                        foreign_ratio = inst_df["foreign_net"].sum() / total_vol_5d
                    if "trust_net" in inst_df.columns:
                        trust_ratio = inst_df["trust_net"].sum() / total_vol_5d
                    if "dealer_net" in inst_df.columns:
                        dealer_ratio = inst_df["dealer_net"].sum() / total_vol_5d
    except Exception:
        pass

    # 6. Market cap for institutional weighting
    try:
        from data.fetcher import get_stock_info
        info = get_stock_info(code)
        market_cap = info.get("market_cap", 0) or None
    except Exception:
        pass

    # 7. Valuation: PE/PB/殖利率 from TWSE (R62)
    pe_ratio = None
    pb_ratio = None
    dividend_yield = None
    try:
        from data.twse_scraper import get_stock_valuation
        val = get_stock_valuation(code)
        if val:
            pe_ratio = val.get("pe")
            pb_ratio = val.get("pb")
            dividend_yield = val.get("dividend_yield")
    except Exception:
        pass

    # 8. Growth: 月營收 YoY from MOPS (R62)
    revenue_yoy = None
    try:
        from data.twse_scraper import get_stock_revenue
        rev_df = get_stock_revenue(code, months=1)
        if rev_df is not None and not rev_df.empty:
            revenue_yoy = rev_df.iloc[-1].get("revenue_yoy")
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
        inst_net_ratio=inst_net_ratio,
        foreign_ratio=foreign_ratio,
        trust_ratio=trust_ratio,
        dealer_ratio=dealer_ratio,
        market_cap=market_cap,
        pe_ratio=pe_ratio,
        pb_ratio=pb_ratio,
        dividend_yield=dividend_yield,
        revenue_yoy=revenue_yoy,
    )
    sqs_result["code"] = code
    sqs_result["fitness_tag"] = fitness_tag
    sqs_result["inst_net_ratio"] = round(inst_net_ratio, 4) if inst_net_ratio is not None else None
    sqs_result["market_cap"] = market_cap
    return sqs_result


def compute_sqs_distribution(sqs_scores: list[dict]) -> dict:
    """Compute SQS score distribution and adaptive percentile grades.

    Args:
        sqs_scores: List of dicts with at least 'code' and 'sqs' keys.

    Returns:
        dict with percentiles, histogram, and adaptive grades per stock.
    """
    import numpy as np

    if not sqs_scores:
        return {"count": 0, "percentiles": {}, "histogram": [], "adaptive_grades": {}}

    scores = [s["sqs"] for s in sqs_scores]
    arr = np.array(scores)

    percentiles = {
        "p10": round(float(np.percentile(arr, 10)), 1),
        "p25": round(float(np.percentile(arr, 25)), 1),
        "p50": round(float(np.percentile(arr, 50)), 1),
        "p75": round(float(np.percentile(arr, 75)), 1),
        "p90": round(float(np.percentile(arr, 90)), 1),
        "mean": round(float(np.mean(arr)), 1),
        "std": round(float(np.std(arr)), 1),
        "min": round(float(np.min(arr)), 1),
        "max": round(float(np.max(arr)), 1),
    }

    # Histogram (10 bins)
    counts, edges = np.histogram(arr, bins=10, range=(0, 100))
    histogram = [
        {"range": f"{int(edges[i])}-{int(edges[i + 1])}", "count": int(counts[i])}
        for i in range(len(counts))
    ]

    # Adaptive percentile grading: top 20% = diamond, 20-50% = gold, 50-80% = silver, bottom 20% = noise
    n = len(scores)
    sorted_codes = sorted(sqs_scores, key=lambda s: s["sqs"], reverse=True)
    adaptive_grades = {}
    for rank, item in enumerate(sorted_codes):
        pct = rank / n  # 0 = highest score
        if pct < 0.2:
            grade = "diamond"
        elif pct < 0.5:
            grade = "gold"
        elif pct < 0.8:
            grade = "silver"
        else:
            grade = "noise"
        adaptive_grades[item["code"]] = {
            "sqs": item["sqs"],
            "rank": rank + 1,
            "percentile_rank": round(pct * 100, 1),
            "adaptive_grade": grade,
            "fixed_grade": item.get("grade", ""),
        }

    return {
        "count": n,
        "percentiles": percentiles,
        "histogram": histogram,
        "adaptive_grades": adaptive_grades,
    }

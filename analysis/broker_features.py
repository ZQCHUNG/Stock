"""
R88.7 Method C: Daily Brokerage Feature Engine
13 日頻分點特徵計算引擎

特徵清單 (Trader CONVERGED):
A. 集中度 (3): hhi_daily, top3_pct, hhi_delta
B. 流量 (3): net_buy_ratio, spread, net_momentum_5d
C. Smart Money (3): purity_score, foreign_pct, branch_overlap_count
D. 波動性 (2): daily_net_buy_volatility, turnover_chg
E. 持續性 (1): consistency_streak
F. 量價背離 (1): price_divergence

收斂參數:
    [CONVERGED] Missing data > 50% features → NaN dimension
    [CONVERGED] Missing data 25-50% → 50% discount
    [PLACEHOLDER] Winner Score > 1.1, n >= 15
    [PLACEHOLDER] Purity cutoff: top3 >= 40%
"""
import json
import re
import numpy as np
from pathlib import Path
from typing import Optional


# --- PLACEHOLDER parameters (Trader suggested values, awaiting data validation) ---
WINNER_SCORE_THRESHOLD = 1.1      # [PLACEHOLDER: BROKER_DAILY_001]
WINNER_MIN_N = 15                  # [PLACEHOLDER: BROKER_DAILY_002]
PURITY_CONCENTRATION_CUTOFF = 0.40  # [PLACEHOLDER: BROKER_DAILY_003]

# Foreign broker name patterns [PLACEHOLDER: BROKER_DAILY_004]
FOREIGN_BROKER_PATTERNS = [
    r"瑞銀", r"高盛", r"摩根", r"美林", r"花旗", r"麥格理",
    r"瑞士信貸", r"巴克萊", r"匯豐", r"德意志", r"野村",
    r"新加坡商", r"香港上海", r"大和", r"里昂",
]

DAILY_DIR = Path(__file__).parent.parent / "data" / "pattern_data" / "raw" / "broker_daily"


def _parse_lots(val: str) -> int:
    """Parse broker lot string to int. E.g., '17,206' → 17206."""
    try:
        return int(val.replace(",", "").replace(" ", ""))
    except (ValueError, AttributeError):
        return 0


def _parse_pct(val: str) -> float:
    """Parse percentage string. E.g., '3.16%' → 0.0316."""
    try:
        return float(val.replace("%", "").replace(",", "")) / 100
    except (ValueError, AttributeError):
        return 0.0


def _is_summary_row(broker: dict) -> bool:
    """Check if a broker entry is the summary row."""
    name = broker.get("broker", "")
    return "合計" in name or "平均" in name


def _is_foreign_broker(name: str) -> bool:
    """Check if broker name matches foreign broker patterns."""
    for pattern in FOREIGN_BROKER_PATTERNS:
        if re.search(pattern, name):
            return True
    return False


def parse_daily_brokers(data: dict) -> dict:
    """Parse raw Fubon JSON into structured broker records.

    Returns dict with separated buy/sell lists (summary rows removed).
    """
    buy_raw = data.get("buy_top", [])
    sell_raw = data.get("sell_top", [])

    buy_brokers = []
    for b in buy_raw:
        if _is_summary_row(b):
            continue
        buy_brokers.append({
            "broker": b["broker"],
            "buy": _parse_lots(b["buy"]),
            "sell": _parse_lots(b["sell"]),
            "net": _parse_lots(b["net"]),
            "pct": _parse_pct(b["pct"]),
        })

    sell_brokers = []
    for b in sell_raw:
        if _is_summary_row(b):
            continue
        sell_brokers.append({
            "broker": b["broker"],
            "buy": _parse_lots(b["buy"]),
            "sell": _parse_lots(b["sell"]),
            "net": _parse_lots(b["net"]),
            "pct": _parse_pct(b["pct"]),
        })

    return {
        "buy_brokers": buy_brokers,
        "sell_brokers": sell_brokers,
        "broker_codes": data.get("broker_codes", []),
    }


def compute_broker_features(
    parsed: dict,
    prev_hhi: float = None,
    prev_turnover: float = None,
    lookback_net_ratios: list[float] = None,
    lookback_streak: int = 0,
    ohlc: dict = None,
    winner_registry: dict = None,
    market_overlap_counts: dict = None,
) -> dict:
    """Compute 13 daily brokerage features from parsed broker data.

    Args:
        parsed: Output of parse_daily_brokers()
        prev_hhi: Yesterday's HHI (for delta)
        prev_turnover: Yesterday's total broker volume (for change)
        lookback_net_ratios: Last 20 days of net_buy_ratio (for volatility)
        lookback_streak: Current streak count (signed)
        ohlc: Dict with {open, high, low, close, volume, atr_14} for price divergence
        winner_registry: Dict of {broker_code: winner_score}
        market_overlap_counts: Dict of {broker_code: count_of_stocks_today}

    Returns:
        Dict of 13 feature values. Missing features = NaN.
    """
    buy = parsed["buy_brokers"]
    sell = parsed["sell_brokers"]
    all_brokers = buy + sell

    features = {}

    # ====== A. Concentration (3) ======

    # 1. broker_hhi_daily: HHI of all broker percentages
    pcts = [b["pct"] for b in all_brokers if b["pct"] > 0]
    if pcts:
        features["broker_hhi_daily"] = sum(p ** 2 for p in pcts)
    else:
        features["broker_hhi_daily"] = np.nan

    # 2. broker_top3_pct: Top 3 buy broker % of total buy volume
    if len(buy) >= 3:
        top3_pct = sum(b["pct"] for b in buy[:3])
        features["broker_top3_pct"] = top3_pct
    elif buy:
        features["broker_top3_pct"] = sum(b["pct"] for b in buy)
    else:
        features["broker_top3_pct"] = np.nan

    # 3. broker_hhi_delta: Day-over-day HHI change
    if prev_hhi is not None and not np.isnan(features["broker_hhi_daily"]):
        features["broker_hhi_delta"] = features["broker_hhi_daily"] - prev_hhi
    else:
        features["broker_hhi_delta"] = np.nan

    # ====== B. Flow (3) ======

    # 4. broker_net_buy_ratio: Top5 net buy / (|Top5 buy| + |Top5 sell|)
    top5_buy_net = sum(b["net"] for b in buy[:5]) if len(buy) >= 5 else sum(b["net"] for b in buy)
    top5_sell_net = sum(b["net"] for b in sell[:5]) if len(sell) >= 5 else sum(b["net"] for b in sell)
    denom = abs(top5_buy_net) + abs(top5_sell_net)
    if denom > 0:
        features["broker_net_buy_ratio"] = top5_buy_net / denom
    else:
        features["broker_net_buy_ratio"] = 0.5  # Neutral

    # 5. broker_spread: Count(net buyers) / Count(net sellers)
    net_buyers = sum(1 for b in all_brokers if b["net"] > 0)
    net_sellers = sum(1 for b in all_brokers if b["net"] < 0)
    if net_sellers > 0:
        features["broker_spread"] = net_buyers / net_sellers
    elif net_buyers > 0:
        features["broker_spread"] = float(net_buyers)
    else:
        features["broker_spread"] = 1.0

    # 6. broker_net_momentum_5d: 5d SMA of daily net_buy_ratio
    if lookback_net_ratios and len(lookback_net_ratios) >= 4:
        recent = lookback_net_ratios[-4:] + [features["broker_net_buy_ratio"]]
        features["broker_net_momentum_5d"] = np.mean(recent)
    else:
        features["broker_net_momentum_5d"] = features["broker_net_buy_ratio"]

    # ====== C. Smart Money (3) ======

    # 7. broker_purity_score [CONVERGED with Trader modifications]
    top3_pct_val = features.get("broker_top3_pct", 0) or 0
    if top3_pct_val < PURITY_CONCENTRATION_CUTOFF:
        features["broker_purity_score"] = 0.0
    elif winner_registry and buy:
        # Check overlap with winner branches
        winner_count = 0
        for i, b in enumerate(buy[:3]):
            broker_codes = parsed.get("broker_codes", [])
            if i < len(broker_codes):
                code = broker_codes[i]
                if code in winner_registry:
                    winner_count += 1
        winner_overlap = winner_count / min(3, len(buy))
        features["broker_purity_score"] = top3_pct_val * winner_overlap * 100
    else:
        # No registry yet — use concentration alone
        features["broker_purity_score"] = top3_pct_val * 100 * 0.5  # Halved without winner data

    # 8. broker_foreign_pct: Foreign broker buy volume / total buy volume
    total_buy_vol = sum(b["buy"] for b in buy)
    foreign_buy_vol = sum(b["buy"] for b in buy if _is_foreign_broker(b["broker"]))
    if total_buy_vol > 0:
        features["broker_foreign_pct"] = foreign_buy_vol / total_buy_vol
    else:
        features["broker_foreign_pct"] = 0.0

    # 9. branch_overlap_count: How many stocks this broker is buying today
    if market_overlap_counts and buy:
        broker_codes = parsed.get("broker_codes", [])
        top5_codes = broker_codes[:5] if len(broker_codes) >= 5 else broker_codes
        overlaps = [market_overlap_counts.get(c, 0) for c in top5_codes]
        features["branch_overlap_count"] = np.mean(overlaps) if overlaps else 0
    else:
        features["branch_overlap_count"] = np.nan

    # ====== D. Volatility (2) ======

    # 10. daily_net_buy_volatility: 20d rolling std of net_buy_ratio
    if lookback_net_ratios and len(lookback_net_ratios) >= 10:
        recent_ratios = lookback_net_ratios[-19:] + [features["broker_net_buy_ratio"]]
        features["daily_net_buy_volatility"] = np.std(recent_ratios, ddof=1)
    else:
        features["daily_net_buy_volatility"] = np.nan

    # 11. broker_turnover_chg: Day-over-day broker volume change
    total_vol = sum(b["buy"] + b["sell"] for b in all_brokers)
    if prev_turnover is not None and prev_turnover > 0:
        features["broker_turnover_chg"] = (total_vol / prev_turnover) - 1
    else:
        features["broker_turnover_chg"] = np.nan

    # ====== E. Persistence (1) ======

    # 12. broker_consistency_streak: Consecutive net-buy days (signed)
    net_buy_ratio = features["broker_net_buy_ratio"]
    if net_buy_ratio > 0.5:
        # Net buying today
        if lookback_streak >= 0:
            features["broker_consistency_streak"] = lookback_streak + 1
        else:
            features["broker_consistency_streak"] = 1
    elif net_buy_ratio < 0.5:
        # Net selling today
        if lookback_streak <= 0:
            features["broker_consistency_streak"] = lookback_streak - 1
        else:
            features["broker_consistency_streak"] = -1
    else:
        features["broker_consistency_streak"] = 0

    # ====== F. Price Divergence (1) ======

    # 13. broker_price_divergence: (Close - VWAP_proxy) / ATR_14
    #     [CONVERGED] Trader enhancement: ATR-normalized for cross-stock comparison
    if ohlc and all(k in ohlc for k in ("high", "low", "close", "atr_14")):
        vwap_proxy = (ohlc["high"] + ohlc["low"] + ohlc["close"]) / 3
        atr = ohlc["atr_14"]
        if atr > 0:
            features["broker_price_divergence"] = (ohlc["close"] - vwap_proxy) / atr
        else:
            features["broker_price_divergence"] = 0.0
    else:
        features["broker_price_divergence"] = np.nan

    return features


def compute_data_quality(features: dict) -> dict:
    """Assess brokerage dimension data quality.

    [CONVERGED] Trader requirement:
    - <= 2 missing: quality=good, flag=partial
    - 3-6 missing: quality=degraded, 50% discount
    - > 6 missing: quality=insufficient, dimension=NaN
    """
    total_features = 13
    missing = sum(1 for v in features.values() if v is None or
                  (isinstance(v, float) and np.isnan(v)))

    if missing <= 2:
        return {"quality": "good", "missing": missing,
                "discount": 1.0, "flag": "partial" if missing > 0 else "full"}
    elif missing <= 6:
        return {"quality": "degraded", "missing": missing,
                "discount": 0.5, "flag": "degraded"}
    else:
        return {"quality": "insufficient", "missing": missing,
                "discount": 0.0, "flag": "data_insufficient"}


# --- Feature name constants for integration ---
BROKER_FEATURE_NAMES = [
    "broker_hhi_daily",
    "broker_top3_pct",
    "broker_hhi_delta",
    "broker_net_buy_ratio",
    "broker_spread",
    "broker_net_momentum_5d",
    "broker_purity_score",
    "broker_foreign_pct",
    "branch_overlap_count",
    "daily_net_buy_volatility",
    "broker_turnover_chg",
    "broker_consistency_streak",
    "broker_price_divergence",
]

assert len(BROKER_FEATURE_NAMES) == 13

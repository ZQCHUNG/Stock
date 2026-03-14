"""Adaptive Strategy Recommendation (Gemini R51-1)

Integrates ML market regime classification with strategy selection.
Automatically recommends the best strategy and parameter adjustments
based on current market conditions.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_adaptive_recommendation(regime_data: dict, strategies: list[dict]) -> dict:
    """Generate adaptive strategy recommendation based on market regime.

    Args:
        regime_data: Output from regime_classifier.classify_market_regime()
        strategies: List of strategy dicts from strategies.json

    Returns:
        Dict with recommended strategy, parameter adjustments, and reasoning.
    """
    regime = regime_data.get("regime", "unknown")
    confidence = regime_data.get("confidence", 0.5)
    kelly_mult = regime_data.get("kelly_multiplier", 0.5)
    v4_suit = regime_data.get("v4_suitability", "unknown")
    features = regime_data.get("features", {})

    # Select best strategy based on regime
    strategy_map = {s["id"]: s for s in strategies}
    strategy_names = {s["name"].lower(): s for s in strategies}

    # Default selection logic
    recommended_id = None
    for s in strategies:
        if s.get("is_default"):
            recommended_id = s["id"]
            break

    # Override based on regime
    param_adjustments = {}
    reasoning = []

    if regime in ("bull_trending",):
        # Best environment — use aggressive if available, else standard
        aggressive = _find_strategy(strategies, "aggressive")
        if aggressive:
            recommended_id = aggressive["id"]
            reasoning.append(f"趨勢牛市 (ADX={features.get('adx', '?')}) — 選用積極策略")
        else:
            reasoning.append("趨勢牛市 — 標準策略已適用")
        param_adjustments = {
            "confidence_weight": 1.2,
            "position_scale": min(1.0, kelly_mult * 1.1),
        }

    elif regime in ("bull_volatile",):
        # Good but risky — standard with tighter trailing
        standard = _find_strategy(strategies, "standard") or _find_default(strategies)
        if standard:
            recommended_id = standard["id"]
        reasoning.append(f"高波牛市 (ATR%={features.get('atr_pct', '?')}) — 標準策略 + 縮緊移動停利")
        param_adjustments = {
            "trailing_stop_pct": 0.015,  # Tighter trailing
            "position_scale": kelly_mult,
        }

    elif regime in ("bear_trending",):
        # Poor environment — conservative
        conservative = _find_strategy(strategies, "conservative")
        if conservative:
            recommended_id = conservative["id"]
            reasoning.append("趨勢熊市 — 切換保守策略，嚴格停損")
        else:
            reasoning.append("趨勢熊市 — 建議手動縮減曝險")
        param_adjustments = {
            "stop_loss_pct": -0.05,
            "position_scale": kelly_mult,
            "max_positions": 3,
        }

    elif regime in ("bear_volatile",):
        # Worst environment — minimal exposure
        conservative = _find_strategy(strategies, "conservative")
        if conservative:
            recommended_id = conservative["id"]
        reasoning.append("恐慌熊市 — 最小曝險，建議暫停新開倉")
        param_adjustments = {
            "stop_loss_pct": -0.04,
            "position_scale": kelly_mult,  # 0.1
            "max_positions": 1,
            "pause_new_entries": True,
        }

    elif regime in ("range_quiet",):
        # Waiting game — standard with patience
        standard = _find_strategy(strategies, "standard") or _find_default(strategies)
        if standard:
            recommended_id = standard["id"]
        reasoning.append("低波盤整 — 等待突破，輕倉觀望")
        param_adjustments = {
            "adx_threshold": 22,  # Stricter entry
            "position_scale": kelly_mult,
            "min_volume": 600,
        }

    elif regime in ("range_volatile",):
        # Worst for trend-following — very conservative
        conservative = _find_strategy(strategies, "conservative")
        if conservative:
            recommended_id = conservative["id"]
        reasoning.append("震盪劇烈 — V4 最差環境，大幅縮減曝險")
        param_adjustments = {
            "adx_threshold": 28,  # Very strict
            "stop_loss_pct": -0.05,
            "position_scale": kelly_mult,
            "max_positions": 2,
        }

    else:
        reasoning.append("市場情境不明 — 使用標準策略")
        param_adjustments = {"position_scale": 0.5}

    # Get recommended strategy details
    rec_strategy = strategy_map.get(recommended_id, strategies[0] if strategies else {})

    # Apply confidence scaling
    position_scale = param_adjustments.get("position_scale", kelly_mult)
    if confidence < 0.4:
        position_scale *= 0.7
        reasoning.append(f"低信心度 ({confidence:.0%}) — 額外縮減 30%")

    param_adjustments["position_scale"] = round(position_scale, 2)

    return {
        "regime": regime,
        "regime_label": regime_data.get("regime_label", ""),
        "confidence": confidence,
        "kelly_multiplier": kelly_mult,
        "v4_suitability": v4_suit,
        "recommended_strategy": {
            "id": rec_strategy.get("id", ""),
            "name": rec_strategy.get("name", ""),
            "params": rec_strategy.get("params", {}),
        },
        "param_adjustments": param_adjustments,
        "reasoning": reasoning,
        "strategy_advice": regime_data.get("strategy_advice", ""),
    }


def _find_strategy(strategies: list[dict], keyword: str) -> dict | None:
    """Find strategy by name keyword."""
    for s in strategies:
        if keyword.lower() in s.get("name", "").lower():
            return s
    return None


def _find_default(strategies: list[dict]) -> dict | None:
    """Find the default strategy."""
    for s in strategies:
        if s.get("is_default"):
            return s
    return strategies[0] if strategies else None

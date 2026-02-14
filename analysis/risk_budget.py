"""Multi-Strategy Risk Budget — 多策略風險預算管理（Gemini R37-R38）

核心功能：
1. MultiStrategyBouncer: 同一股票 V4+V5 同時 BUY 時，總曝險上限 1.2× Kelly
2. Signal Divergence Detection: V4/V5 訊號衝突偵測（一買一賣 → 建議觀望）
3. Portfolio-level 風險預算分配
4. Tiered Execution: composite 0.3-0.5 = 半倉試單, >=0.5 = 全倉進場（R38）

設計原則：
- 保守優先：訊號衝突時建議 HOLD（不做不錯）
- Kelly 上限：防止雙策略加碼造成過度集中
- 透明輸出：每筆建議都附帶理由和信心衰減係數
"""


def multi_strategy_bouncer(
    code: str,
    v4_signal: str,
    v5_signal: str,
    v4_confidence: float = 1.0,
    kelly_half: float = 0.5,
    current_exposure: float = 0.0,
    regime: str = "range_quiet",
    v5_bias_confirmed: bool = False,
) -> dict:
    """多策略彈跳器 — 偵測訊號衝突 + 曝險上限 + 分級執行

    Args:
        code: 股票代號
        v4_signal: V4 訊號 (BUY/HOLD/SELL)
        v5_signal: V5 訊號 (BUY/HOLD/SELL)
        v4_confidence: V4 信心分數 (0-2)
        kelly_half: Half-Kelly 建議曝險比例 (0-1)
        current_exposure: 目前對此股票的曝險比例 (0-1)
        regime: 市場狀態 (trend_explosive/trend_mild/range_volatile/range_quiet)
        v5_bias_confirmed: V5 BIAS 確認（乖離率 > 5%）

    Returns:
        dict with:
        - action: "BUY" / "HOLD" / "SELL" / "REDUCE"
        - reason: 決策理由
        - divergence: bool — 是否存在訊號衝突
        - max_exposure: 建議最大曝險
        - confidence_decay: 信心衰減因子 (1.0 = 無衰減)
        - confidence_tier: "full" / "half" / "none" — 分級執行建議
        - position_multiplier: 1.0 / 0.5 / 0.0 — 部位乘數
        - composite_score: 混合評分
        - warnings: list[str]
    """
    from analysis.strategy_v5 import adaptive_strategy_score

    warnings = []
    confidence_decay = 1.0

    # Compute composite score for tiered execution
    score_data = adaptive_strategy_score(
        v4_signal=v4_signal,
        v5_signal=v5_signal,
        regime=regime,
        v4_confidence=v4_confidence,
        v5_bias_confirmed=v5_bias_confirmed,
    )
    composite = score_data["composite_score"]

    # ===== 1. Signal Divergence Detection =====
    divergence = False
    is_v4_buy = v4_signal == "BUY"
    is_v4_sell = v4_signal == "SELL"
    is_v5_buy = v5_signal == "BUY"
    is_v5_sell = v5_signal == "SELL"

    # Case: V4 BUY + V5 SELL (or vice versa) → Divergence
    if (is_v4_buy and is_v5_sell) or (is_v4_sell and is_v5_buy):
        divergence = True
        confidence_decay *= 0.3
        warnings.append(
            f"訊號衝突：V4={v4_signal} vs V5={v5_signal}，"
            f"趨勢與均值回歸判斷矛盾，建議觀望"
        )

    # Case: V4 BUY + V5 BUY → Both agree, but check exposure cap
    both_buy = is_v4_buy and is_v5_buy
    both_sell = is_v4_sell and is_v5_sell

    # ===== 2. Exposure Cap: 1.2× Kelly =====
    max_kelly_mult = 1.2
    max_exposure = kelly_half * max_kelly_mult

    if both_buy and current_exposure >= max_exposure:
        warnings.append(
            f"雙策略同時買入但已達曝險上限 ({current_exposure:.0%} >= "
            f"{max_exposure:.0%} = Kelly×{max_kelly_mult})，不再加碼"
        )
        confidence_decay *= 0.5

    # ===== 3. Determine Final Action =====
    if divergence:
        action = "HOLD"
        reason = "V4/V5 訊號衝突 → 觀望（不做不錯）"
    elif both_buy:
        if current_exposure >= max_exposure:
            action = "HOLD"
            reason = f"雙策略共識買入，但曝險已達 Kelly×{max_kelly_mult} 上限"
        else:
            action = "BUY"
            reason = "V4+V5 雙策略共識買入"
            confidence_decay = min(confidence_decay, 1.2)  # Slight boost for consensus
    elif both_sell:
        action = "SELL"
        reason = "V4+V5 雙策略共識賣出"
    elif is_v4_buy or is_v5_buy:
        # Single strategy buy — apply regime weighting
        regime_weights = {
            "trend_explosive": (0.9, 0.1),
            "trend_mild": (0.8, 0.2),
            "range_volatile": (0.2, 0.8),
            "range_quiet": (0.3, 0.7),
        }
        w4, w5 = regime_weights.get(regime, (0.5, 0.5))

        if is_v4_buy and w4 >= 0.5:
            action = "BUY"
            reason = f"V4 買入（趨勢模式，權重 {w4:.0%}）"
        elif is_v5_buy and w5 >= 0.5:
            action = "BUY"
            reason = f"V5 買入（盤整模式，權重 {w5:.0%}）"
        else:
            action = "HOLD"
            reason = f"單策略買入但權重不足（V4w={w4:.0%}, V5w={w5:.0%}）"
            confidence_decay *= 0.6
    elif is_v4_sell or is_v5_sell:
        action = "SELL"
        reason = f"{'V4' if is_v4_sell else 'V5'} 發出賣出訊號"
    else:
        action = "HOLD"
        reason = "V4+V5 皆無明確訊號"

    # ===== 4. Tiered Execution (Gemini R38) =====
    # Composite 0.3-0.5 → 半倉試單, >=0.5 → 全倉進場
    if action == "BUY":
        if composite >= 0.5:
            confidence_tier = "full"
            position_multiplier = 1.0
            tier_label = "建議進場（全倉）"
        elif composite >= 0.3:
            confidence_tier = "half"
            position_multiplier = 0.5
            tier_label = "建議試單（半倉）"
            warnings.append(f"Composite={composite:.2f} 介於 0.3-0.5，建議半倉試單")
        else:
            # Composite < 0.3 but action is BUY (from single strategy weight check)
            confidence_tier = "half"
            position_multiplier = 0.5
            tier_label = "建議試單（半倉）"
            warnings.append(f"Composite={composite:.2f} < 0.3，信號較弱，建議半倉")
    else:
        confidence_tier = "none"
        position_multiplier = 0.0
        tier_label = ""

    return {
        "code": code,
        "action": action,
        "reason": reason,
        "divergence": divergence,
        "v4_signal": v4_signal,
        "v5_signal": v5_signal,
        "max_exposure": round(max_exposure, 4),
        "current_exposure": round(current_exposure, 4),
        "confidence_decay": round(confidence_decay, 3),
        "composite_score": composite,
        "confidence_tier": confidence_tier,
        "position_multiplier": position_multiplier,
        "tier_label": tier_label,
        "v5_bias_confirmed": v5_bias_confirmed,
        "regime": regime,
        "warnings": warnings,
    }


def batch_risk_budget(
    positions: list[dict],
    signals: dict[str, dict],
    kelly_half: float = 0.5,
    total_equity: float = 1_000_000,
    regime: str = "range_quiet",
) -> dict:
    """組合層級風險預算 — 檢查所有持倉的多策略風險

    Args:
        positions: 持倉清單 [{code, lots, entry_price, current_price, ...}]
        signals: {code: {v4_signal, v5_signal, v4_confidence}} 每股的策略訊號
        kelly_half: Half-Kelly 建議比例
        total_equity: 總資產
        regime: 市場狀態

    Returns:
        dict with per-stock bouncer results + portfolio warnings
    """
    results = []
    divergence_count = 0
    total_exposure = 0.0

    for pos in positions:
        code = pos["code"]
        sig = signals.get(code, {"v4_signal": "HOLD", "v5_signal": "HOLD"})

        # Calculate per-stock exposure
        market_value = pos.get("lots", 0) * 1000 * (pos.get("current_price") or pos.get("entry_price", 0))
        stock_exposure = market_value / total_equity if total_equity > 0 else 0
        total_exposure += stock_exposure

        bouncer = multi_strategy_bouncer(
            code=code,
            v4_signal=sig.get("v4_signal", "HOLD"),
            v5_signal=sig.get("v5_signal", "HOLD"),
            v4_confidence=sig.get("v4_confidence", 1.0),
            kelly_half=kelly_half,
            current_exposure=stock_exposure,
            regime=regime,
        )
        results.append(bouncer)
        if bouncer["divergence"]:
            divergence_count += 1

    # Portfolio-level warnings
    portfolio_warnings = []
    if divergence_count > 0:
        portfolio_warnings.append(
            f"⚠️ {divergence_count} 檔持倉出現 V4/V5 訊號衝突，建議逐一檢視"
        )
    if total_exposure > kelly_half * 1.5:
        portfolio_warnings.append(
            f"⚠️ 總曝險 {total_exposure:.0%} 超過 Kelly×1.5 ({kelly_half * 1.5:.0%})，"
            f"建議減碼至安全水位"
        )

    return {
        "stock_results": results,
        "divergence_count": divergence_count,
        "total_exposure": round(total_exposure, 4),
        "kelly_half": kelly_half,
        "max_total_exposure": round(kelly_half * 1.5, 4),
        "portfolio_warnings": portfolio_warnings,
        "regime": regime,
    }

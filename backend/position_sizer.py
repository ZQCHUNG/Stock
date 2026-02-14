"""VaR-based position sizing engine (Gemini R48-1).

Integrates portfolio VaR, correlation, and beta to recommend
dynamically-sized positions before opening trades.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from analysis.risk import (
    calculate_portfolio_var,
    calculate_correlation_matrix,
    calculate_portfolio_beta,
)

logger = logging.getLogger(__name__)

# --- Defaults ---
DEFAULT_ACCOUNT_VALUE = 1_000_000  # TWD
DEFAULT_VAR_LIMIT_PCT = 0.02       # Max portfolio VaR = 2% of account
DEFAULT_MAX_POSITION_PCT = 0.20    # Single position can't exceed 20% of account
DEFAULT_MAX_CORR = 0.75            # High correlation threshold
DEFAULT_MAX_BETA = 1.5             # Max portfolio beta

LOT_SIZE = 1000  # 1 lot = 1000 shares (Taiwan market)


def calculate_position_size(
    stock_code: str,
    entry_price: float,
    stock_df: pd.DataFrame,
    existing_positions: list[dict],
    existing_stock_data: dict[str, pd.DataFrame],
    account_value: float = DEFAULT_ACCOUNT_VALUE,
    var_limit_pct: float = DEFAULT_VAR_LIMIT_PCT,
    max_position_pct: float = DEFAULT_MAX_POSITION_PCT,
    confidence_score: float = 0.7,
    market_df: Optional[pd.DataFrame] = None,
) -> dict:
    """Calculate recommended position size based on VaR budget.

    Returns:
        dict with: recommended_lots, max_lots, reasons[], warnings[],
                   current_var, projected_var, risk_budget_remaining
    """
    warnings = []
    reasons = []

    # --- 1. Max lots from position size limit ---
    max_cost = account_value * max_position_pct
    max_lots_by_size = max(1, int(max_cost / (entry_price * LOT_SIZE)))

    # --- 2. Current portfolio VaR ---
    current_var_pct = 0.0
    if existing_stock_data:
        var_result = calculate_portfolio_var(
            existing_stock_data,
            confidence=0.95,
            portfolio_value=account_value,
        )
        current_var_pct = abs(var_result.get("var_pct", 0))

    var_budget_remaining = var_limit_pct - current_var_pct
    if var_budget_remaining <= 0:
        warnings.append(f"VaR 預算已滿 ({current_var_pct:.2%} >= {var_limit_pct:.2%})，建議暫停開倉")
        return {
            "recommended_lots": 0,
            "max_lots": max_lots_by_size,
            "current_var_pct": round(current_var_pct, 6),
            "projected_var_pct": round(current_var_pct, 6),
            "var_limit_pct": var_limit_pct,
            "risk_budget_remaining_pct": 0.0,
            "reasons": ["VaR 預算已用盡"],
            "warnings": warnings,
        }

    # --- 3. Estimate new stock's marginal VaR contribution ---
    if len(stock_df) >= 30 and "close" in stock_df.columns:
        stock_returns = stock_df["close"].pct_change().dropna()
        stock_vol = stock_returns.std()
        # Marginal VaR per lot (95% confidence, ~1.65 sigma)
        marginal_var_per_lot = 1.65 * stock_vol * entry_price * LOT_SIZE / account_value
    else:
        # Fallback: assume 2% daily vol
        stock_vol = 0.02
        marginal_var_per_lot = 1.65 * stock_vol * entry_price * LOT_SIZE / account_value
        warnings.append("歷史數據不足，使用預設波動率 2%")

    # Max lots from VaR budget
    if marginal_var_per_lot > 0:
        max_lots_by_var = max(1, int(var_budget_remaining / marginal_var_per_lot))
    else:
        max_lots_by_var = max_lots_by_size

    # --- 4. Correlation penalty ---
    corr_penalty = 1.0
    if existing_stock_data and len(stock_df) >= 30:
        test_data = {**existing_stock_data, stock_code: stock_df}
        try:
            corr_matrix = calculate_correlation_matrix(test_data, days=60)
            if stock_code in corr_matrix.columns:
                stock_corrs = corr_matrix[stock_code].drop(stock_code, errors="ignore")
                max_corr = stock_corrs.max() if len(stock_corrs) > 0 else 0
                if max_corr > DEFAULT_MAX_CORR:
                    corr_penalty = 0.5
                    high_corr_stock = stock_corrs.idxmax()
                    warnings.append(
                        f"與 {high_corr_stock} 高度相關 ({max_corr:.2f})，倉位縮減 50%"
                    )
                elif max_corr > 0.5:
                    corr_penalty = 0.75
                    reasons.append(f"中度相關性調整 (max corr={max_corr:.2f})")
        except Exception:
            pass

    # --- 5. Beta check ---
    beta_penalty = 1.0
    if market_df is not None and existing_stock_data:
        try:
            all_data = {**existing_stock_data, stock_code: stock_df}
            betas = calculate_portfolio_beta(all_data, market_df, days=120)
            port_beta = np.mean(list(betas.values())) if betas else 1.0
            if port_beta > DEFAULT_MAX_BETA:
                beta_penalty = 0.7
                warnings.append(
                    f"投資組合 Beta 偏高 ({port_beta:.2f})，倉位縮減 30%"
                )
            elif port_beta > 1.2:
                beta_penalty = 0.85
                reasons.append(f"Beta 調整 ({port_beta:.2f})")
        except Exception:
            pass

    # --- 6. Confidence scaling ---
    # Higher confidence → allow larger position
    confidence_factor = 0.5 + 0.5 * min(confidence_score, 1.0)  # Range: 0.5-1.0

    # --- 7. Final recommendation ---
    effective_max = min(max_lots_by_size, max_lots_by_var)
    recommended = int(effective_max * corr_penalty * beta_penalty * confidence_factor)
    recommended = max(1, recommended)

    # Project new VaR
    projected_var_pct = current_var_pct + recommended * marginal_var_per_lot

    reasons.append(f"VaR 預算限制: {max_lots_by_var} 張")
    reasons.append(f"部位上限限制: {max_lots_by_size} 張")
    reasons.append(f"信心度係數: {confidence_factor:.1%}")
    if corr_penalty < 1:
        reasons.append(f"相關性折扣: {corr_penalty:.0%}")
    if beta_penalty < 1:
        reasons.append(f"Beta 折扣: {beta_penalty:.0%}")

    return {
        "recommended_lots": recommended,
        "max_lots": effective_max,
        "cost_estimate": round(recommended * entry_price * LOT_SIZE, 0),
        "position_pct": round(recommended * entry_price * LOT_SIZE / account_value, 4),
        "current_var_pct": round(current_var_pct, 6),
        "projected_var_pct": round(projected_var_pct, 6),
        "var_limit_pct": var_limit_pct,
        "risk_budget_remaining_pct": round(max(0, var_limit_pct - projected_var_pct), 6),
        "marginal_var_per_lot": round(marginal_var_per_lot, 6),
        "confidence_factor": round(confidence_factor, 4),
        "corr_penalty": round(corr_penalty, 2),
        "beta_penalty": round(beta_penalty, 2),
        "reasons": reasons,
        "warnings": warnings,
    }


def run_scenario_analysis(
    positions: list[dict],
    stock_data: dict[str, pd.DataFrame],
    account_value: float = DEFAULT_ACCOUNT_VALUE,
    scenarios: Optional[list[dict]] = None,
) -> list[dict]:
    """Run stress-test scenario analysis on current portfolio.

    Each scenario: {"name": str, "market_shock_pct": float, "vol_multiplier": float}

    Returns list of scenario results.
    """
    if scenarios is None:
        scenarios = [
            {"name": "溫和回調 (-3%)", "market_shock_pct": -0.03, "vol_multiplier": 1.0},
            {"name": "中度下跌 (-5%)", "market_shock_pct": -0.05, "vol_multiplier": 1.3},
            {"name": "劇烈崩跌 (-10%)", "market_shock_pct": -0.10, "vol_multiplier": 2.0},
            {"name": "黑天鵝 (-20%)", "market_shock_pct": -0.20, "vol_multiplier": 3.0},
        ]

    if not positions or not stock_data:
        return [
            {
                **s,
                "portfolio_loss": 0,
                "portfolio_loss_pct": 0,
                "var_stressed": 0,
                "positions_at_risk": [],
            }
            for s in scenarios
        ]

    # Calculate position values
    total_value = 0
    position_values = []
    for p in positions:
        code = p.get("code", "")
        lots = p.get("lots", 0)
        current = p.get("current_price") or p.get("entry_price", 0)
        value = current * lots * LOT_SIZE
        total_value += value

        # Estimate beta for this stock
        beta = 1.0
        if code in stock_data and "close" in stock_data[code].columns:
            returns = stock_data[code]["close"].pct_change().dropna()
            beta = max(0.5, min(2.5, returns.std() / 0.01))  # Rough beta proxy

        position_values.append({
            "code": code,
            "name": p.get("name", code),
            "value": value,
            "beta": beta,
            "lots": lots,
        })

    results = []
    for scenario in scenarios:
        shock = scenario["market_shock_pct"]
        vol_mult = scenario.get("vol_multiplier", 1.0)

        portfolio_loss = 0
        at_risk = []
        for pv in position_values:
            # Stock-specific impact = market shock * beta
            stock_loss_pct = shock * pv["beta"]
            stock_loss = pv["value"] * stock_loss_pct
            portfolio_loss += stock_loss

            if abs(stock_loss_pct) > 0.05:  # >5% loss
                at_risk.append({
                    "code": pv["code"],
                    "name": pv["name"],
                    "loss_pct": round(stock_loss_pct, 4),
                    "loss_amount": round(stock_loss, 0),
                })

        # Stressed VaR = normal VaR * vol_multiplier
        var_result = calculate_portfolio_var(
            stock_data, confidence=0.95, portfolio_value=account_value
        )
        stressed_var = abs(var_result.get("var_pct", 0)) * vol_mult

        results.append({
            "name": scenario["name"],
            "market_shock_pct": shock,
            "vol_multiplier": vol_mult,
            "portfolio_loss": round(portfolio_loss, 0),
            "portfolio_loss_pct": round(portfolio_loss / account_value, 4) if account_value > 0 else 0,
            "var_stressed_pct": round(stressed_var, 6),
            "positions_at_risk": at_risk,
        })

    return results

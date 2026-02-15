"""R58: Performance Attribution — Brinson Model + Factor Analysis

Decomposes portfolio/strategy returns into:
1. Brinson Attribution: Allocation, Selection, Interaction effects
2. Factor Analysis: Market, Size, Value, Momentum exposures
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# =========================================================================
# Brinson Attribution Model
# =========================================================================

@dataclass
class BrinsonAttribution:
    """Brinson-Hood-Beebower single-period attribution result."""
    period: str = ""  # e.g., "2024-01" or "full"

    # Portfolio vs benchmark returns
    portfolio_return: float = 0.0
    benchmark_return: float = 0.0
    active_return: float = 0.0  # portfolio - benchmark

    # Brinson decomposition
    allocation_effect: float = 0.0   # Sector/timing allocation
    selection_effect: float = 0.0    # Stock selection within sectors
    interaction_effect: float = 0.0  # Cross-term

    # Residual (should be ~0 if decomposition is correct)
    residual: float = 0.0

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "portfolio_return": round(self.portfolio_return, 6),
            "benchmark_return": round(self.benchmark_return, 6),
            "active_return": round(self.active_return, 6),
            "allocation_effect": round(self.allocation_effect, 6),
            "selection_effect": round(self.selection_effect, 6),
            "interaction_effect": round(self.interaction_effect, 6),
            "residual": round(self.residual, 6),
        }


@dataclass
class BrinsonReport:
    """Full Brinson attribution across multiple periods."""
    periods: list[BrinsonAttribution] = field(default_factory=list)
    total: BrinsonAttribution | None = None

    # Sector-level detail
    sector_detail: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total.to_dict() if self.total else None,
            "periods": [p.to_dict() for p in self.periods],
            "sector_detail": self.sector_detail,
        }


def compute_brinson_single_period(
    portfolio_weights: dict[str, float],
    benchmark_weights: dict[str, float],
    portfolio_returns: dict[str, float],
    benchmark_returns: dict[str, float],
    period: str = "full",
) -> BrinsonAttribution:
    """Compute Brinson attribution for a single period.

    Brinson-Hood-Beebower (BHB) decomposition:
    - Allocation Effect = Σ (wp_i - wb_i) × Rb_i
    - Selection Effect  = Σ wb_i × (Rp_i - Rb_i)
    - Interaction Effect = Σ (wp_i - wb_i) × (Rp_i - Rb_i)
    - Active Return = Allocation + Selection + Interaction

    Where:
    - wp_i = portfolio weight in sector/stock i
    - wb_i = benchmark weight in sector/stock i
    - Rp_i = portfolio return in sector/stock i
    - Rb_i = benchmark return in sector/stock i

    Args:
        portfolio_weights: {sector: weight} for portfolio (sum ~1.0)
        benchmark_weights: {sector: weight} for benchmark (sum ~1.0)
        portfolio_returns: {sector: return} for portfolio
        benchmark_returns: {sector: return} for benchmark
        period: Label for this period
    """
    all_sectors = set(portfolio_weights) | set(benchmark_weights)

    allocation = 0.0
    selection = 0.0
    interaction = 0.0

    for sector in all_sectors:
        wp = portfolio_weights.get(sector, 0.0)
        wb = benchmark_weights.get(sector, 0.0)
        rp = portfolio_returns.get(sector, 0.0)
        rb = benchmark_returns.get(sector, 0.0)

        allocation += (wp - wb) * rb
        selection += wb * (rp - rb)
        interaction += (wp - wb) * (rp - rb)

    # Total returns
    port_ret = sum(portfolio_weights.get(s, 0) * portfolio_returns.get(s, 0) for s in all_sectors)
    bench_ret = sum(benchmark_weights.get(s, 0) * benchmark_returns.get(s, 0) for s in all_sectors)
    active = port_ret - bench_ret

    return BrinsonAttribution(
        period=period,
        portfolio_return=port_ret,
        benchmark_return=bench_ret,
        active_return=active,
        allocation_effect=allocation,
        selection_effect=selection,
        interaction_effect=interaction,
        residual=active - allocation - selection - interaction,
    )


def compute_trade_attribution(
    trades: list,
    benchmark_returns: pd.Series,
) -> BrinsonAttribution:
    """Simplified Brinson for single-stock backtest.

    For a single-stock V4 strategy, we decompose:
    - Selection Effect: Returns when holding (strategy's stock picking skill)
    - Allocation Effect: Returns from market timing (in vs out of market)
    - The benchmark is buy-and-hold of the same stock

    Args:
        trades: List of Trade objects from backtest
        benchmark_returns: Daily returns of benchmark (same stock or index)
    """
    if not trades or benchmark_returns.empty:
        return BrinsonAttribution(period="full")

    # Calculate holding periods
    holding_dates = set()
    for t in trades:
        if t.date_open and t.date_close:
            mask = (benchmark_returns.index >= t.date_open) & (benchmark_returns.index <= t.date_close)
            holding_dates.update(benchmark_returns.index[mask].tolist())

    all_dates = set(benchmark_returns.index.tolist())
    not_holding_dates = all_dates - holding_dates

    # Returns during holding periods vs not-holding
    holding_mask = benchmark_returns.index.isin(holding_dates)

    # Strategy performance: sum of trade PnLs as pct
    total_trade_return = sum(t.return_pct for t in trades if hasattr(t, "return_pct"))
    total_pnl = sum(t.pnl for t in trades if hasattr(t, "pnl"))

    # Benchmark return over full period
    bench_total = (1 + benchmark_returns).prod() - 1

    # Benchmark return during holding periods only
    bench_holding = (1 + benchmark_returns[holding_mask]).prod() - 1 if holding_mask.any() else 0.0

    # Benchmark return during not-holding periods
    bench_not_holding = (1 + benchmark_returns[~holding_mask]).prod() - 1 if (~holding_mask).any() else 0.0

    # Holding fraction
    n_total = len(benchmark_returns)
    n_holding = holding_mask.sum()
    hold_fraction = n_holding / n_total if n_total > 0 else 0

    # Simplified attribution:
    # Allocation = benefit of being in/out of market at right times
    # Selection = benefit of stock picking (excess return during holding)
    allocation = -((1 - hold_fraction) * bench_not_holding)  # opportunity cost / gain of not holding
    selection = total_trade_return - bench_holding if n_holding > 0 else 0.0
    active = total_trade_return - bench_total

    return BrinsonAttribution(
        period="full",
        portfolio_return=total_trade_return,
        benchmark_return=bench_total,
        active_return=active,
        allocation_effect=allocation,
        selection_effect=selection,
        interaction_effect=active - allocation - selection,
    )


# =========================================================================
# Factor Analysis (Fama-French inspired, Taiwan-adapted)
# =========================================================================

@dataclass
class FactorExposure:
    """Factor regression results."""
    alpha: float = 0.0      # Regression intercept (annualized)
    market_beta: float = 0.0
    size_exposure: float = 0.0      # SMB-like factor
    value_exposure: float = 0.0     # HML-like factor
    momentum_exposure: float = 0.0  # MOM factor
    r_squared: float = 0.0
    residual_vol: float = 0.0  # Unexplained volatility (annualized)

    # Factor contributions to total return
    market_contribution: float = 0.0
    size_contribution: float = 0.0
    value_contribution: float = 0.0
    momentum_contribution: float = 0.0
    alpha_contribution: float = 0.0

    def to_dict(self) -> dict:
        return {
            "alpha": round(self.alpha, 6),
            "market_beta": round(self.market_beta, 4),
            "size_exposure": round(self.size_exposure, 4),
            "value_exposure": round(self.value_exposure, 4),
            "momentum_exposure": round(self.momentum_exposure, 4),
            "r_squared": round(self.r_squared, 4),
            "residual_vol": round(self.residual_vol, 4),
            "contributions": {
                "market": round(self.market_contribution, 6),
                "size": round(self.size_contribution, 6),
                "value": round(self.value_contribution, 6),
                "momentum": round(self.momentum_contribution, 6),
                "alpha": round(self.alpha_contribution, 6),
            },
        }


def build_proxy_factors(
    market_returns: pd.Series,
    stock_returns: pd.Series | None = None,
) -> pd.DataFrame:
    """Build proxy factor returns from market data.

    Since Taiwan doesn't have public Fama-French factors,
    we construct proxies from market data:
    - MKT: Market excess return (from ^TWII or provided)
    - SIZE: Lagged negative of log(price) as size proxy
    - VALUE: Not constructable from single stock; set to 0
    - MOM: 20-day momentum of market returns

    Args:
        market_returns: Daily market index returns
        stock_returns: Optional stock returns (for momentum factor)

    Returns:
        DataFrame with columns: MKT, SIZE, VALUE, MOM
    """
    factors = pd.DataFrame(index=market_returns.index)

    # Market factor
    rf_daily = 0.015 / 252  # ~1.5% annual risk-free
    factors["MKT"] = market_returns - rf_daily

    # Size proxy: not available for single stock; use market vol as proxy
    factors["SIZE"] = 0.0  # Placeholder — needs cross-sectional data

    # Value proxy: not available without fundamentals
    factors["VALUE"] = 0.0  # Placeholder

    # Momentum factor: 20-day rolling return of market
    ret_source = stock_returns if stock_returns is not None else market_returns
    factors["MOM"] = ret_source.rolling(20).mean().shift(1).fillna(0)

    return factors.dropna()


def compute_factor_exposure(
    strategy_returns: pd.Series,
    market_returns: pd.Series,
    rf_annual: float = 0.015,
) -> FactorExposure:
    """Compute factor exposures via OLS regression.

    Regresses strategy daily returns against factor returns:
    R_strategy - Rf = α + β_MKT × MKT + β_MOM × MOM + ε

    Args:
        strategy_returns: Daily strategy returns
        market_returns: Daily market index returns
        rf_annual: Annual risk-free rate
    """
    result = FactorExposure()

    if strategy_returns.empty or market_returns.empty:
        return result

    # Align dates
    common = strategy_returns.index.intersection(market_returns.index)
    if len(common) < 30:
        return result

    strat = strategy_returns.loc[common].values
    mkt = market_returns.loc[common].values

    rf_daily = rf_annual / 252
    excess_strat = strat - rf_daily
    excess_mkt = mkt - rf_daily

    # Build factors
    factors = build_proxy_factors(market_returns.loc[common])
    factors = factors.loc[common]

    # Simple OLS: excess_strat ~ MKT + MOM
    # (SIZE and VALUE are 0 placeholders for now)
    X_cols = ["MKT", "MOM"]
    X = factors[X_cols].values
    y = excess_strat[:len(X)]

    if len(y) < len(X):
        X = X[:len(y)]

    # Add intercept
    X_with_const = np.column_stack([np.ones(len(X)), X])

    try:
        # OLS via normal equations
        beta_hat = np.linalg.lstsq(X_with_const, y, rcond=None)[0]
        y_pred = X_with_const @ beta_hat
        residuals = y - y_pred

        ss_res = np.sum(residuals ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        alpha_daily = beta_hat[0]
        result.alpha = alpha_daily * 252  # Annualize
        result.market_beta = beta_hat[1]
        result.momentum_exposure = beta_hat[2] if len(beta_hat) > 2 else 0
        result.r_squared = max(0, r_squared)
        result.residual_vol = np.std(residuals) * np.sqrt(252)

        # Factor contributions
        n_days = len(y)
        result.market_contribution = result.market_beta * np.mean(excess_mkt) * 252
        result.momentum_contribution = result.momentum_exposure * np.mean(factors["MOM"].values[:n_days]) * 252
        result.alpha_contribution = result.alpha

    except Exception as e:
        logger.warning(f"Factor regression failed: {e}")

    return result

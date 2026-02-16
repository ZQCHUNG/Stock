"""R60: 全面風險管理框架

Portfolio-level risk management with:
- VaR: Historical, Parametric (Gaussian), Conditional (CVaR/ES)
- Concentration risk: single-stock & sector limits
- Drawdown monitoring: current DD, max DD threshold, capital utilization
- Circuit breaker: daily/weekly/monthly loss caps, consecutive loss count
- Stress testing: historical scenarios + hypothetical shocks
"""

from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats as sp_stats


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class VaRResult:
    """Value-at-Risk calculation result."""
    historical_var: float = 0.0       # Historical VaR (daily, %)
    parametric_var: float = 0.0       # Parametric (Gaussian) VaR (daily, %)
    conditional_var: float = 0.0      # CVaR / Expected Shortfall (daily, %)
    confidence: float = 0.95
    holding_period_days: int = 1
    portfolio_value: float = 0.0
    # Amounts
    historical_var_amt: float = 0.0
    parametric_var_amt: float = 0.0
    conditional_var_amt: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ConcentrationAlert:
    """Single concentration risk alert."""
    asset: str
    weight: float         # Current weight (0-1)
    limit: float          # Threshold
    alert_type: str       # "single_stock" or "sector"
    message: str = ""


@dataclass
class DrawdownStatus:
    """Current drawdown monitoring status."""
    current_drawdown: float = 0.0        # Current DD from peak (negative %)
    max_drawdown_threshold: float = -0.15  # Alert threshold
    peak_value: float = 0.0
    current_value: float = 0.0
    capital_utilization: float = 0.0     # Invested / Total (0-1)
    is_breached: bool = False


@dataclass
class CircuitBreakerStatus:
    """Circuit breaker state."""
    triggered: bool = False
    reason: str = ""
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0
    consecutive_losses: int = 0
    # Limits
    daily_loss_limit: float = -0.03     # -3% daily
    weekly_loss_limit: float = -0.05    # -5% weekly
    monthly_loss_limit: float = -0.10   # -10% monthly
    max_consecutive_losses: int = 5

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StressScenario:
    """A stress test scenario definition."""
    name: str
    description: str
    shocks: dict[str, float]  # {asset_or_factor: shock_pct}
    scenario_type: str = "historical"  # "historical" or "hypothetical"


@dataclass
class StressTestResult:
    """Result of a single stress test."""
    scenario: str
    portfolio_pnl: float = 0.0        # Portfolio P&L under stress (%)
    portfolio_pnl_amt: float = 0.0    # Portfolio P&L amount
    worst_stock: str = ""
    worst_stock_pnl: float = 0.0
    details: dict = field(default_factory=dict)  # Per-stock P&L


@dataclass
class RiskReport:
    """Comprehensive risk report."""
    var_result: Optional[VaRResult] = None
    concentration_alerts: list[ConcentrationAlert] = field(default_factory=list)
    drawdown_status: Optional[DrawdownStatus] = None
    circuit_breaker: Optional[CircuitBreakerStatus] = None
    stress_results: list[StressTestResult] = field(default_factory=list)
    risk_score: float = 0.0           # 0-100, higher = more risky
    alerts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "risk_score": self.risk_score,
            "alerts": self.alerts,
        }
        if self.var_result:
            d["var"] = self.var_result.to_dict()
        if self.concentration_alerts:
            d["concentration"] = [
                {"asset": a.asset, "weight": a.weight, "limit": a.limit,
                 "type": a.alert_type, "message": a.message}
                for a in self.concentration_alerts
            ]
        if self.drawdown_status:
            d["drawdown"] = asdict(self.drawdown_status)
        if self.circuit_breaker:
            d["circuit_breaker"] = self.circuit_breaker.to_dict()
        if self.stress_results:
            d["stress_tests"] = [
                {"scenario": s.scenario, "portfolio_pnl": s.portfolio_pnl,
                 "portfolio_pnl_amt": s.portfolio_pnl_amt,
                 "worst_stock": s.worst_stock,
                 "worst_stock_pnl": s.worst_stock_pnl,
                 "details": s.details}
                for s in self.stress_results
            ]
        return d


# ---------------------------------------------------------------------------
# VaR Calculations
# ---------------------------------------------------------------------------

def compute_var(
    returns: pd.Series,
    confidence: float = 0.95,
    portfolio_value: float = 1_000_000,
) -> VaRResult:
    """Compute Historical, Parametric, and Conditional VaR.

    Args:
        returns: Daily portfolio returns series.
        confidence: Confidence level (0.95 = 95%).
        portfolio_value: Total portfolio value for amount calculation.

    Returns:
        VaRResult with all three VaR measures.
    """
    if returns is None or len(returns) < 20:
        return VaRResult(confidence=confidence, portfolio_value=portfolio_value)

    clean = returns.dropna()
    if len(clean) < 20:
        return VaRResult(confidence=confidence, portfolio_value=portfolio_value)

    alpha = 1 - confidence  # e.g. 0.05

    # 1. Historical VaR: empirical quantile
    hist_var = float(np.percentile(clean, alpha * 100))

    # 2. Parametric VaR: assume normal distribution
    mu = float(clean.mean())
    sigma = float(clean.std(ddof=1))
    z = sp_stats.norm.ppf(alpha)
    param_var = mu + z * sigma

    # 3. Conditional VaR (CVaR / Expected Shortfall)
    # Average of returns below the VaR threshold
    tail = clean[clean <= hist_var]
    cvar = float(tail.mean()) if len(tail) > 0 else hist_var

    return VaRResult(
        historical_var=round(hist_var, 6),
        parametric_var=round(param_var, 6),
        conditional_var=round(cvar, 6),
        confidence=confidence,
        portfolio_value=portfolio_value,
        historical_var_amt=round(hist_var * portfolio_value, 2),
        parametric_var_amt=round(param_var * portfolio_value, 2),
        conditional_var_amt=round(cvar * portfolio_value, 2),
    )


def compute_portfolio_returns(
    stock_data: dict[str, pd.DataFrame],
    weights: Optional[dict[str, float]] = None,
    days: int = 250,
) -> pd.Series:
    """Compute weighted portfolio daily returns.

    Args:
        stock_data: {code: DataFrame with 'close' column}
        weights: {code: weight}. If None, equal-weight.
        days: Lookback window.

    Returns:
        Portfolio daily returns Series.
    """
    returns_dict = {}
    for code, df in stock_data.items():
        if df is None or len(df) < 30:
            continue
        close = df["close"].tail(days + 1)
        ret = close.pct_change().dropna()
        if len(ret) >= 20:
            returns_dict[code] = ret

    if not returns_dict:
        return pd.Series(dtype=float)

    df_ret = pd.DataFrame(returns_dict).dropna()
    if len(df_ret) < 20:
        return pd.Series(dtype=float)

    if weights:
        # Normalize weights to sum to 1 for available stocks
        available = [c for c in df_ret.columns if c in weights]
        if not available:
            return df_ret.mean(axis=1)
        w = np.array([weights[c] for c in available])
        w = w / w.sum()
        return (df_ret[available] * w).sum(axis=1)
    else:
        return df_ret.mean(axis=1)


# ---------------------------------------------------------------------------
# Concentration Risk
# ---------------------------------------------------------------------------

def check_concentration(
    holdings: dict[str, float],
    sectors: Optional[dict[str, str]] = None,
    single_stock_limit: float = 0.20,
    sector_limit: float = 0.40,
) -> list[ConcentrationAlert]:
    """Check portfolio concentration risk.

    Args:
        holdings: {stock_code: market_value}
        sectors: {stock_code: sector_name} (optional)
        single_stock_limit: Max single stock weight (default 20%)
        sector_limit: Max sector weight (default 40%)

    Returns:
        List of concentration alerts.
    """
    alerts = []
    total = sum(holdings.values())
    if total <= 0:
        return alerts

    # Single stock concentration
    for code, value in holdings.items():
        weight = value / total
        if weight > single_stock_limit:
            alerts.append(ConcentrationAlert(
                asset=code,
                weight=round(weight, 4),
                limit=single_stock_limit,
                alert_type="single_stock",
                message=f"{code} 佔比 {weight:.1%} 超過單一股票上限 {single_stock_limit:.0%}",
            ))

    # Sector concentration
    if sectors:
        sector_values: dict[str, float] = {}
        for code, value in holdings.items():
            sector = sectors.get(code, "未分類")
            sector_values[sector] = sector_values.get(sector, 0) + value

        for sector, value in sector_values.items():
            weight = value / total
            if weight > sector_limit and sector != "未分類":
                alerts.append(ConcentrationAlert(
                    asset=sector,
                    weight=round(weight, 4),
                    limit=sector_limit,
                    alert_type="sector",
                    message=f"{sector} 產業佔比 {weight:.1%} 超過上限 {sector_limit:.0%}",
                ))

    return alerts


# ---------------------------------------------------------------------------
# Drawdown Monitoring
# ---------------------------------------------------------------------------

def monitor_drawdown(
    equity_curve: pd.Series,
    invested_value: float = 0.0,
    total_value: float = 0.0,
    max_dd_threshold: float = -0.15,
) -> DrawdownStatus:
    """Monitor current drawdown status.

    Args:
        equity_curve: Equity curve series (portfolio values over time).
        invested_value: Current total invested amount.
        total_value: Current total portfolio value (invested + cash).
        max_dd_threshold: Alert threshold (e.g. -0.15 = -15%).

    Returns:
        DrawdownStatus with current state.
    """
    if equity_curve is None or len(equity_curve) < 2:
        return DrawdownStatus(max_drawdown_threshold=max_dd_threshold)

    peak = equity_curve.cummax()
    dd = (equity_curve - peak) / peak
    current_dd = float(dd.iloc[-1])
    peak_val = float(peak.iloc[-1])
    current_val = float(equity_curve.iloc[-1])

    utilization = invested_value / total_value if total_value > 0 else 0.0

    return DrawdownStatus(
        current_drawdown=round(current_dd, 4),
        max_drawdown_threshold=max_dd_threshold,
        peak_value=round(peak_val, 2),
        current_value=round(current_val, 2),
        capital_utilization=round(utilization, 4),
        is_breached=current_dd < max_dd_threshold,
    )


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

def evaluate_circuit_breaker(
    daily_pnl: float = 0.0,
    weekly_pnl: float = 0.0,
    monthly_pnl: float = 0.0,
    consecutive_losses: int = 0,
    daily_limit: float = -0.03,
    weekly_limit: float = -0.05,
    monthly_limit: float = -0.10,
    max_consec_losses: int = 5,
) -> CircuitBreakerStatus:
    """Evaluate circuit breaker conditions.

    Any breached condition triggers the circuit breaker, pausing all trading.

    Args:
        daily_pnl: Today's P&L as fraction of capital.
        weekly_pnl: This week's cumulative P&L as fraction.
        monthly_pnl: This month's cumulative P&L as fraction.
        consecutive_losses: Number of consecutive losing trades.
        daily_limit: Daily loss limit (negative fraction).
        weekly_limit: Weekly loss limit.
        monthly_limit: Monthly loss limit.
        max_consec_losses: Max consecutive losses before pause.

    Returns:
        CircuitBreakerStatus.
    """
    reasons = []

    if daily_pnl < daily_limit:
        reasons.append(f"日損失 {daily_pnl:.2%} 超過限額 {daily_limit:.2%}")
    if weekly_pnl < weekly_limit:
        reasons.append(f"週損失 {weekly_pnl:.2%} 超過限額 {weekly_limit:.2%}")
    if monthly_pnl < monthly_limit:
        reasons.append(f"月損失 {monthly_pnl:.2%} 超過限額 {monthly_limit:.2%}")
    if consecutive_losses >= max_consec_losses:
        reasons.append(f"連續虧損 {consecutive_losses} 次 ≥ {max_consec_losses} 次上限")

    return CircuitBreakerStatus(
        triggered=len(reasons) > 0,
        reason="; ".join(reasons) if reasons else "",
        daily_pnl=round(daily_pnl, 4),
        weekly_pnl=round(weekly_pnl, 4),
        monthly_pnl=round(monthly_pnl, 4),
        consecutive_losses=consecutive_losses,
        daily_loss_limit=daily_limit,
        weekly_loss_limit=weekly_limit,
        monthly_loss_limit=monthly_limit,
        max_consecutive_losses=max_consec_losses,
    )


# ---------------------------------------------------------------------------
# Stress Testing
# ---------------------------------------------------------------------------

# Pre-defined historical stress scenarios (Taiwan market)
HISTORICAL_SCENARIOS = [
    StressScenario(
        name="COVID_2020",
        description="2020年3月 COVID-19 崩盤：台股 -28.5%",
        shocks={"market": -0.285, "high_beta": -0.35, "defensive": -0.15},
        scenario_type="historical",
    ),
    StressScenario(
        name="RATE_HIKE_2022",
        description="2022年 聯準會急升息：台股 -22%",
        shocks={"market": -0.22, "high_beta": -0.30, "growth": -0.28},
        scenario_type="historical",
    ),
    StressScenario(
        name="TAIWAN_STRAIT_2022",
        description="2022年8月 台海危機：台股 -5% 單週",
        shocks={"market": -0.05, "semiconductor": -0.08, "defense": 0.10},
        scenario_type="historical",
    ),
    StressScenario(
        name="TECH_BUBBLE_2000",
        description="2000年 科技泡沫：科技股 -50%",
        shocks={"market": -0.30, "tech": -0.50, "value": -0.10},
        scenario_type="historical",
    ),
]

HYPOTHETICAL_SCENARIOS = [
    StressScenario(
        name="MARKET_CRASH_10",
        description="假設情境：大盤 -10%",
        shocks={"market": -0.10},
        scenario_type="hypothetical",
    ),
    StressScenario(
        name="SINGLE_LIMIT_DOWN",
        description="假設情境：最大持股跌停 (-10%)",
        shocks={"largest_holding": -0.10},
        scenario_type="hypothetical",
    ),
    StressScenario(
        name="RATE_SHOCK",
        description="假設情境：利率急升 2%，成長股受創",
        shocks={"market": -0.05, "growth": -0.15, "value": -0.03},
        scenario_type="hypothetical",
    ),
    StressScenario(
        name="BLACK_SWAN",
        description="假設情境：黑天鵝事件 大盤 -20%",
        shocks={"market": -0.20, "high_beta": -0.30},
        scenario_type="hypothetical",
    ),
]


def run_stress_test(
    holdings: dict[str, float],
    betas: Optional[dict[str, float]] = None,
    scenarios: Optional[list[StressScenario]] = None,
    portfolio_value: float = 1_000_000,
) -> list[StressTestResult]:
    """Run stress tests on the portfolio.

    For each scenario, estimate portfolio P&L by applying market shock
    scaled by each stock's beta.

    Args:
        holdings: {stock_code: market_value}
        betas: {stock_code: beta_to_market}. If None, assume beta=1.
        scenarios: Custom scenarios. If None, use all built-in.
        portfolio_value: Total portfolio value.

    Returns:
        List of StressTestResult.
    """
    if not holdings:
        return []

    if scenarios is None:
        scenarios = HISTORICAL_SCENARIOS + HYPOTHETICAL_SCENARIOS

    if betas is None:
        betas = {}

    total = sum(holdings.values())
    if total <= 0:
        return []

    results = []
    for scenario in scenarios:
        market_shock = scenario.shocks.get("market", 0)
        details: dict[str, float] = {}

        for code, value in holdings.items():
            weight = value / total
            beta = betas.get(code, 1.0)

            # Apply shock: stock return = beta * market_shock
            # Additional shocks for specific categories can be layered
            stock_shock = beta * market_shock

            # Special handling for "largest_holding" scenario
            if "largest_holding" in scenario.shocks and value == max(holdings.values()):
                stock_shock = scenario.shocks["largest_holding"]

            details[code] = round(stock_shock * weight, 6)

        portfolio_pnl = sum(details.values())
        worst = min(details, key=details.get) if details else ""
        worst_pnl = details.get(worst, 0)

        results.append(StressTestResult(
            scenario=scenario.name,
            portfolio_pnl=round(portfolio_pnl, 4),
            portfolio_pnl_amt=round(portfolio_pnl * portfolio_value, 2),
            worst_stock=worst,
            worst_stock_pnl=round(worst_pnl, 4),
            details=details,
        ))

    return results


# ---------------------------------------------------------------------------
# Aggregate Risk Score
# ---------------------------------------------------------------------------

def compute_risk_score(
    var_result: Optional[VaRResult] = None,
    concentration_alerts: Optional[list[ConcentrationAlert]] = None,
    drawdown_status: Optional[DrawdownStatus] = None,
    circuit_breaker: Optional[CircuitBreakerStatus] = None,
) -> float:
    """Compute aggregate risk score (0-100, higher = more risky).

    Scoring:
    - VaR severity: 0-30 points (based on daily VaR magnitude)
    - Concentration: 0-20 points (count and severity of alerts)
    - Drawdown: 0-30 points (current DD relative to threshold)
    - Circuit breaker proximity: 0-20 points
    """
    score = 0.0

    # VaR component (0-30)
    if var_result:
        # CVaR magnitude (expected to be negative)
        cvar = abs(var_result.conditional_var)
        # 0% → 0, 3%+ → 30
        score += min(30, cvar / 0.03 * 30)

    # Concentration (0-20)
    if concentration_alerts:
        n_alerts = len(concentration_alerts)
        max_excess = 0.0
        for a in concentration_alerts:
            excess = a.weight - a.limit
            if excess > max_excess:
                max_excess = excess
        # Each alert = 5 pts, max 15 from count + severity bonus
        score += min(20, n_alerts * 5 + max_excess * 50)

    # Drawdown (0-30)
    if drawdown_status:
        dd = abs(drawdown_status.current_drawdown)
        threshold = abs(drawdown_status.max_drawdown_threshold)
        if threshold > 0:
            ratio = dd / threshold
            score += min(30, ratio * 30)

    # Circuit breaker proximity (0-20)
    if circuit_breaker:
        if circuit_breaker.triggered:
            score += 20
        else:
            # How close to daily limit?
            if circuit_breaker.daily_loss_limit < 0:
                daily_ratio = abs(circuit_breaker.daily_pnl) / abs(circuit_breaker.daily_loss_limit)
                score += min(10, daily_ratio * 10)
            # Consecutive losses
            if circuit_breaker.max_consecutive_losses > 0:
                loss_ratio = circuit_breaker.consecutive_losses / circuit_breaker.max_consecutive_losses
                score += min(10, loss_ratio * 10)

    return round(min(100, score), 1)


# ---------------------------------------------------------------------------
# Full Risk Assessment
# ---------------------------------------------------------------------------

def assess_portfolio_risk(
    stock_data: dict[str, pd.DataFrame],
    holdings: Optional[dict[str, float]] = None,
    weights: Optional[dict[str, float]] = None,
    betas: Optional[dict[str, float]] = None,
    sectors: Optional[dict[str, str]] = None,
    equity_curve: Optional[pd.Series] = None,
    daily_pnl: float = 0.0,
    weekly_pnl: float = 0.0,
    monthly_pnl: float = 0.0,
    consecutive_losses: int = 0,
    portfolio_value: float = 1_000_000,
    invested_value: float = 0.0,
    confidence: float = 0.95,
    single_stock_limit: float = 0.20,
    sector_limit: float = 0.40,
    max_dd_threshold: float = -0.15,
) -> RiskReport:
    """Run full portfolio risk assessment.

    Combines VaR, concentration, drawdown, circuit breaker, and stress tests
    into a single RiskReport.
    """
    alerts = []

    # 1. Portfolio returns + VaR
    port_returns = compute_portfolio_returns(stock_data, weights)
    var_result = compute_var(port_returns, confidence, portfolio_value)

    if var_result.conditional_var < -0.03:
        alerts.append(
            f"VaR 警告：CVaR({confidence:.0%}) = {var_result.conditional_var:.2%}，"
            f"預期尾部損失 ${abs(var_result.conditional_var_amt):,.0f}"
        )

    # 2. Concentration
    conc_alerts = []
    if holdings:
        conc_alerts = check_concentration(holdings, sectors, single_stock_limit, sector_limit)
        for ca in conc_alerts:
            alerts.append(ca.message)

    # 3. Drawdown
    dd_status = monitor_drawdown(
        equity_curve, invested_value, portfolio_value, max_dd_threshold
    ) if equity_curve is not None and len(equity_curve) > 0 else None

    if dd_status and dd_status.is_breached:
        alerts.append(
            f"回撤警告：目前回撤 {dd_status.current_drawdown:.2%} "
            f"已超過閾值 {max_dd_threshold:.2%}"
        )

    # 4. Circuit breaker
    cb_status = evaluate_circuit_breaker(
        daily_pnl, weekly_pnl, monthly_pnl, consecutive_losses
    )
    if cb_status.triggered:
        alerts.append(f"熔斷觸發：{cb_status.reason}")

    # 5. Stress tests
    stress_results = []
    if holdings:
        stress_results = run_stress_test(holdings, betas, portfolio_value=portfolio_value)
        for sr in stress_results:
            if sr.portfolio_pnl < -0.10:
                alerts.append(
                    f"壓力測試「{sr.scenario}」：組合損失 {sr.portfolio_pnl:.1%} "
                    f"(${abs(sr.portfolio_pnl_amt):,.0f})"
                )

    # 6. Risk score
    risk_score = compute_risk_score(var_result, conc_alerts, dd_status, cb_status)

    return RiskReport(
        var_result=var_result,
        concentration_alerts=conc_alerts,
        drawdown_status=dd_status,
        circuit_breaker=cb_status,
        stress_results=stress_results,
        risk_score=risk_score,
        alerts=alerts,
    )


# ---------------------------------------------------------------------------
# R80: Risk-Adaptive Position Sizing (Equal Risk Contribution)
# ---------------------------------------------------------------------------
# Gemini CTO spec: each trade's max loss on stop-loss should be a fixed % of equity.
# Regime Premium: Scalper gets smaller position (higher gap risk), Trender gets standard.

@dataclass
class SizingResult:
    """Per-trade position sizing recommendation."""
    position_pct: float = 0.0       # Recommended position as % of equity (0-1)
    position_amount: float = 0.0    # Dollar amount to allocate
    shares: int = 0                 # Number of shares (rounded to 1000-share lots)
    regime_multiplier: float = 1.0  # Mode-based adjustment factor
    risk_per_trade_pct: float = 0.0 # Actual risk per trade (should ≈ target)
    mode: str = ""                  # Trender / Scalper
    over_risk: bool = False         # True if 1-lot floor exceeded risk budget
    reasoning: str = ""             # Human-readable explanation

    def to_dict(self) -> dict:
        return asdict(self)


# Default sizing parameters
SIZING_DEFAULTS = {
    "max_risk_per_trade": 0.030,    # 3.0% of equity at risk per trade (Gemini CTO: R80)
    "hard_stop_loss": 0.07,         # 7% stop loss (V4 default)
    "max_position_pct": 0.90,       # Max 90% of equity in single position
    "min_position_pct": 0.05,       # Min 5% (avoid dust positions)
    "atr_threshold": 0.018,         # 1.8% ATR% boundary (Scalper/Trender)
    "trade_unit": 1000,             # Taiwan stock: 1 lot = 1000 shares
    "min_lot_floor": True,          # Force at least 1 lot if cash allows (R80)
}


def get_suggested_position(
    mode: str,
    atr_pct: float,
    equity: float,
    entry_price: float,
    stop_loss_pct: float | None = None,
    params: dict | None = None,
) -> SizingResult:
    """Calculate risk-adaptive position size based on stock personality.

    Equal Risk Contribution: Position sized so that hitting stop-loss
    loses exactly `max_risk_per_trade` of equity.

    Regime Premium (Gemini CTO spec):
    - Trender (low vol): multiplier = 1.0 (standard position)
    - Scalper (high vol): multiplier = 1.8% / ATR% (shrinks with higher vol)

    Args:
        mode: "Trender" or "Scalper" (from auto trail classifier)
        atr_pct: Rolling median ATR% (e.g., 0.025 = 2.5%)
        equity: Current account equity
        entry_price: Expected entry price per share
        stop_loss_pct: Override stop loss % (default 7%)
        params: Override sizing parameters

    Returns:
        SizingResult with recommended position details
    """
    p = dict(SIZING_DEFAULTS)
    if params:
        p.update(params)

    max_risk = p["max_risk_per_trade"]
    sl_pct = stop_loss_pct or p["hard_stop_loss"]
    max_pos = p["max_position_pct"]
    min_pos = p["min_position_pct"]
    threshold = p["atr_threshold"]
    trade_unit = p["trade_unit"]

    if equity <= 0 or entry_price <= 0 or sl_pct <= 0:
        return SizingResult(reasoning="Invalid inputs")

    # Step 1: Base position from equal risk formula
    # If SL = 7%, and we want max 1.5% equity loss:
    # position_pct = max_risk / sl_pct = 0.015 / 0.07 ≈ 21.4%
    base_position_pct = max_risk / sl_pct

    # Step 2: Regime multiplier
    if mode == "Trender":
        regime_mult = 1.0
    else:
        # Scalper: shrink position proportional to excess volatility
        # multiplier = threshold / atr_pct (e.g., 1.8% / 2.5% = 0.72)
        if atr_pct > 0:
            regime_mult = min(1.0, threshold / atr_pct)
        else:
            regime_mult = 1.0

    # Step 3: Apply regime multiplier and clamp
    position_pct = base_position_pct * regime_mult
    position_pct = max(min_pos, min(max_pos, position_pct))

    # Step 4: Calculate concrete amounts
    position_amount = equity * position_pct
    raw_shares = position_amount / entry_price
    # Round down to lot size (Taiwan: 1000 shares per lot)
    shares = int(raw_shares // trade_unit) * trade_unit

    # R80: Min-1-lot floor — if sizing says 0 lots but cash can afford 1 lot,
    # force 1 lot and flag as over_risk (Gemini CTO: don't let sizing become a "buy ban")
    over_risk = False
    min_lot_floor = p.get("min_lot_floor", True)
    one_lot_cost = trade_unit * entry_price

    if shares < trade_unit:
        if min_lot_floor and equity >= one_lot_cost * 1.01:  # 1% buffer for commission
            shares = trade_unit
            over_risk = True  # This trade exceeds risk budget
        else:
            shares = 0  # Truly can't afford (capital too small for 1 lot)

    # Actual values after lot rounding (for display)
    actual_amount = shares * entry_price
    actual_pct = actual_amount / equity if equity > 0 else 0
    actual_risk = actual_pct * sl_pct
    target_risk = position_pct * sl_pct

    # When over_risk, use the actual 1-lot pct as position_pct (so engine can buy)
    effective_pct = actual_pct if over_risk else position_pct

    # Build reasoning
    over_risk_tag = " [OVER-RISK: 1-lot floor]" if over_risk else ""
    reasoning = (
        f"Equal Risk: {max_risk:.1%} equity risk / {sl_pct:.1%} SL = "
        f"{base_position_pct:.1%} base. "
        f"Mode={mode} (ATR%={atr_pct*100:.2f}%), mult={regime_mult:.2f} -> "
        f"{position_pct:.1%} target -> {shares:,} shares (${actual_amount:,.0f}, "
        f"actual risk={actual_risk:.2%}){over_risk_tag}"
    )

    return SizingResult(
        position_pct=round(effective_pct, 4),  # engine uses this as cap
        position_amount=round(actual_amount, 0),
        shares=shares,
        regime_multiplier=round(regime_mult, 4),
        risk_per_trade_pct=round(actual_risk if over_risk else target_risk, 4),
        mode=mode,
        over_risk=over_risk,
        reasoning=reasoning,
    )

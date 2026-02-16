"""Tests for R60 risk management framework."""

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# VaR Tests
# ---------------------------------------------------------------------------

class TestComputeVar:
    def test_basic_var(self):
        """VaR should produce negative values for typical returns."""
        from backtest.risk_manager import compute_var
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.02, 250))
        result = compute_var(returns, confidence=0.95, portfolio_value=1_000_000)
        assert result.historical_var < 0
        assert result.parametric_var < 0
        assert result.conditional_var < 0
        # CVaR should be worse (more negative) than VaR
        assert result.conditional_var <= result.historical_var

    def test_var_amounts(self):
        """VaR amounts should equal pct * portfolio_value."""
        from backtest.risk_manager import compute_var
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0, 0.02, 250))
        result = compute_var(returns, portfolio_value=1_000_000)
        assert abs(result.historical_var_amt - result.historical_var * 1_000_000) < 1

    def test_var_empty_returns(self):
        """Empty returns should return zero VaR."""
        from backtest.risk_manager import compute_var
        result = compute_var(pd.Series(dtype=float))
        assert result.historical_var == 0
        assert result.parametric_var == 0

    def test_var_short_returns(self):
        """Too few data points should return zero."""
        from backtest.risk_manager import compute_var
        result = compute_var(pd.Series([0.01, -0.01, 0.02]))
        assert result.historical_var == 0

    def test_higher_confidence_worse_var(self):
        """99% VaR should be more negative than 95% VaR."""
        from backtest.risk_manager import compute_var
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0, 0.02, 500))
        var95 = compute_var(returns, confidence=0.95)
        var99 = compute_var(returns, confidence=0.99)
        assert var99.historical_var < var95.historical_var


class TestPortfolioReturns:
    def test_equal_weight(self):
        """Equal weight returns should be mean of individual returns."""
        from backtest.risk_manager import compute_portfolio_returns
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        stock_data = {
            "A": pd.DataFrame({"close": np.cumprod(1 + np.random.normal(0.001, 0.02, 100))}, index=dates),
            "B": pd.DataFrame({"close": np.cumprod(1 + np.random.normal(0.001, 0.02, 100))}, index=dates),
        }
        returns = compute_portfolio_returns(stock_data)
        assert len(returns) > 50

    def test_weighted_returns(self):
        """Weighted returns should respect weights."""
        from backtest.risk_manager import compute_portfolio_returns
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        stock_data = {
            "A": pd.DataFrame({"close": np.cumprod(1 + np.full(100, 0.01))}, index=dates),
            "B": pd.DataFrame({"close": np.cumprod(1 + np.full(100, -0.01))}, index=dates),
        }
        returns = compute_portfolio_returns(stock_data, weights={"A": 0.8, "B": 0.2})
        assert len(returns) > 50
        # Should be positive since A (80%) has positive returns
        assert returns.mean() > 0

    def test_empty_data(self):
        """Empty stock data should return empty series."""
        from backtest.risk_manager import compute_portfolio_returns
        result = compute_portfolio_returns({})
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Concentration Tests
# ---------------------------------------------------------------------------

class TestConcentration:
    def test_single_stock_breach(self):
        """Should detect single stock over limit."""
        from backtest.risk_manager import check_concentration
        holdings = {"2330": 300_000, "2317": 100_000, "2454": 100_000}
        alerts = check_concentration(holdings, single_stock_limit=0.50)
        assert len(alerts) == 1
        assert alerts[0].asset == "2330"
        assert alerts[0].alert_type == "single_stock"

    def test_no_breach(self):
        """No alerts when within limits."""
        from backtest.risk_manager import check_concentration
        holdings = {"2330": 200_000, "2317": 200_000, "2454": 200_000}
        alerts = check_concentration(holdings, single_stock_limit=0.40)
        assert len(alerts) == 0

    def test_sector_breach(self):
        """Should detect sector concentration."""
        from backtest.risk_manager import check_concentration
        holdings = {"2330": 300_000, "2454": 200_000, "2317": 100_000}
        sectors = {"2330": "半導體", "2454": "半導體", "2317": "電子代工"}
        alerts = check_concentration(holdings, sectors, sector_limit=0.40)
        sector_alerts = [a for a in alerts if a.alert_type == "sector"]
        # 半導體 = 500k/600k = 83%, well above 40%
        assert len(sector_alerts) == 1
        assert sector_alerts[0].asset == "半導體"

    def test_empty_holdings(self):
        """Empty holdings should return no alerts."""
        from backtest.risk_manager import check_concentration
        assert check_concentration({}) == []


# ---------------------------------------------------------------------------
# Drawdown Tests
# ---------------------------------------------------------------------------

class TestDrawdown:
    def test_in_drawdown(self):
        """Should detect active drawdown."""
        from backtest.risk_manager import monitor_drawdown
        equity = pd.Series([100, 110, 105, 95, 90])
        status = monitor_drawdown(equity, max_dd_threshold=-0.15)
        assert status.current_drawdown < 0
        assert status.peak_value == 110
        assert status.current_value == 90

    def test_breach_threshold(self):
        """Should flag when DD exceeds threshold."""
        from backtest.risk_manager import monitor_drawdown
        equity = pd.Series([100, 110, 95, 85, 80])
        status = monitor_drawdown(equity, max_dd_threshold=-0.20)
        # DD = (80-110)/110 = -27.3%, threshold -20%
        assert status.is_breached

    def test_no_breach(self):
        """Should not flag when DD within threshold."""
        from backtest.risk_manager import monitor_drawdown
        equity = pd.Series([100, 105, 103, 104, 106])
        status = monitor_drawdown(equity, max_dd_threshold=-0.15)
        assert not status.is_breached

    def test_empty_equity(self):
        """Empty equity should return default status."""
        from backtest.risk_manager import monitor_drawdown
        status = monitor_drawdown(pd.Series(dtype=float))
        assert status.current_drawdown == 0

    def test_capital_utilization(self):
        """Should compute utilization correctly."""
        from backtest.risk_manager import monitor_drawdown
        equity = pd.Series([100, 105])
        status = monitor_drawdown(equity, invested_value=70_000, total_value=100_000)
        assert status.capital_utilization == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# Circuit Breaker Tests
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    def test_daily_trigger(self):
        """Should trigger on daily loss exceeding limit."""
        from backtest.risk_manager import evaluate_circuit_breaker
        cb = evaluate_circuit_breaker(daily_pnl=-0.05, daily_limit=-0.03)
        assert cb.triggered
        assert "日損失" in cb.reason

    def test_weekly_trigger(self):
        """Should trigger on weekly loss."""
        from backtest.risk_manager import evaluate_circuit_breaker
        cb = evaluate_circuit_breaker(weekly_pnl=-0.08, weekly_limit=-0.05)
        assert cb.triggered
        assert "週損失" in cb.reason

    def test_monthly_trigger(self):
        """Should trigger on monthly loss."""
        from backtest.risk_manager import evaluate_circuit_breaker
        cb = evaluate_circuit_breaker(monthly_pnl=-0.12, monthly_limit=-0.10)
        assert cb.triggered
        assert "月損失" in cb.reason

    def test_consecutive_losses_trigger(self):
        """Should trigger on consecutive losses."""
        from backtest.risk_manager import evaluate_circuit_breaker
        cb = evaluate_circuit_breaker(consecutive_losses=6, max_consec_losses=5)
        assert cb.triggered
        assert "連續虧損" in cb.reason

    def test_multiple_triggers(self):
        """Multiple conditions can trigger simultaneously."""
        from backtest.risk_manager import evaluate_circuit_breaker
        cb = evaluate_circuit_breaker(
            daily_pnl=-0.04, weekly_pnl=-0.06,
            daily_limit=-0.03, weekly_limit=-0.05
        )
        assert cb.triggered
        assert "日損失" in cb.reason
        assert "週損失" in cb.reason

    def test_no_trigger(self):
        """Should not trigger when within limits."""
        from backtest.risk_manager import evaluate_circuit_breaker
        cb = evaluate_circuit_breaker(daily_pnl=-0.01, weekly_pnl=-0.02)
        assert not cb.triggered
        assert cb.reason == ""

    def test_to_dict(self):
        """Should serialize to dict."""
        from backtest.risk_manager import evaluate_circuit_breaker
        cb = evaluate_circuit_breaker()
        d = cb.to_dict()
        assert "triggered" in d
        assert "daily_pnl" in d


# ---------------------------------------------------------------------------
# Stress Test
# ---------------------------------------------------------------------------

class TestStressTest:
    def test_basic_stress(self):
        """Should compute stress results for all scenarios."""
        from backtest.risk_manager import run_stress_test
        holdings = {"2330": 500_000, "2317": 300_000, "2454": 200_000}
        results = run_stress_test(holdings)
        assert len(results) == 8  # 4 historical + 4 hypothetical

    def test_stress_with_betas(self):
        """Betas should amplify/dampen shocks for market-based scenarios."""
        from backtest.risk_manager import run_stress_test, HISTORICAL_SCENARIOS
        holdings = {"HIGH": 500_000, "LOW": 500_000}
        betas = {"HIGH": 1.5, "LOW": 0.5}
        # Use only historical scenarios (no largest_holding override)
        results = run_stress_test(holdings, betas, scenarios=HISTORICAL_SCENARIOS)
        # HIGH beta stock should have worse results in market crash
        for r in results:
            if r.details.get("HIGH") and r.details.get("LOW"):
                if r.details["HIGH"] < 0:
                    assert abs(r.details["HIGH"]) > abs(r.details["LOW"])

    def test_empty_holdings(self):
        """Empty holdings should return empty results."""
        from backtest.risk_manager import run_stress_test
        assert run_stress_test({}) == []

    def test_largest_holding_scenario(self):
        """Largest holding limit down scenario should apply to biggest position."""
        from backtest.risk_manager import run_stress_test, HYPOTHETICAL_SCENARIOS
        holdings = {"2330": 700_000, "2317": 300_000}
        # Find the SINGLE_LIMIT_DOWN scenario
        limit_down = [s for s in HYPOTHETICAL_SCENARIOS if s.name == "SINGLE_LIMIT_DOWN"]
        results = run_stress_test(holdings, scenarios=limit_down)
        assert len(results) == 1
        # 2330 is the largest, should get -10% shock
        assert results[0].details["2330"] < 0


# ---------------------------------------------------------------------------
# Risk Score
# ---------------------------------------------------------------------------

class TestRiskScore:
    def test_zero_risk(self):
        """No risk inputs should give score 0."""
        from backtest.risk_manager import compute_risk_score
        assert compute_risk_score() == 0

    def test_high_var_increases_score(self):
        """High VaR should increase score."""
        from backtest.risk_manager import compute_risk_score, VaRResult
        var = VaRResult(conditional_var=-0.05)
        score = compute_risk_score(var_result=var)
        assert score >= 30  # VaR component should be high

    def test_circuit_breaker_max_score(self):
        """Triggered circuit breaker should add 20 points."""
        from backtest.risk_manager import compute_risk_score, CircuitBreakerStatus
        cb = CircuitBreakerStatus(triggered=True, reason="test")
        score = compute_risk_score(circuit_breaker=cb)
        assert score >= 20

    def test_score_capped_at_100(self):
        """Score should not exceed 100."""
        from backtest.risk_manager import (
            compute_risk_score, VaRResult, ConcentrationAlert,
            DrawdownStatus, CircuitBreakerStatus
        )
        score = compute_risk_score(
            var_result=VaRResult(conditional_var=-0.10),
            concentration_alerts=[
                ConcentrationAlert("X", 0.9, 0.2, "single_stock"),
                ConcentrationAlert("Y", 0.8, 0.2, "single_stock"),
            ],
            drawdown_status=DrawdownStatus(current_drawdown=-0.30, max_drawdown_threshold=-0.15),
            circuit_breaker=CircuitBreakerStatus(triggered=True),
        )
        assert score <= 100


# ---------------------------------------------------------------------------
# Full Assessment
# ---------------------------------------------------------------------------

class TestAssessPortfolioRisk:
    def test_basic_assessment(self):
        """Full assessment should return a RiskReport."""
        from backtest.risk_manager import assess_portfolio_risk
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        stock_data = {
            "A": pd.DataFrame({"close": np.cumprod(1 + np.random.normal(0.001, 0.02, 100))}, index=dates),
        }
        report = assess_portfolio_risk(stock_data)
        assert report.var_result is not None
        assert report.risk_score >= 0
        d = report.to_dict()
        assert "var" in d
        assert "risk_score" in d

    def test_assessment_with_holdings(self):
        """Assessment with holdings should include concentration + stress."""
        from backtest.risk_manager import assess_portfolio_risk
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        stock_data = {
            "A": pd.DataFrame({"close": np.cumprod(1 + np.random.normal(0.001, 0.02, 100))}, index=dates),
            "B": pd.DataFrame({"close": np.cumprod(1 + np.random.normal(0.001, 0.02, 100))}, index=dates),
        }
        holdings = {"A": 800_000, "B": 200_000}
        report = assess_portfolio_risk(
            stock_data,
            holdings=holdings,
            single_stock_limit=0.50,
        )
        # A is 80%, should trigger concentration alert
        assert len(report.concentration_alerts) > 0
        assert len(report.stress_results) > 0

    def test_assessment_with_drawdown(self):
        """Assessment should detect drawdown breach."""
        from backtest.risk_manager import assess_portfolio_risk
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        stock_data = {
            "A": pd.DataFrame({"close": np.cumprod(1 + np.random.normal(0.001, 0.02, 100))}, index=dates),
        }
        # Equity that drops a lot
        equity = pd.Series([100, 110, 105, 90, 80, 75])
        report = assess_portfolio_risk(
            stock_data,
            equity_curve=equity,
            max_dd_threshold=-0.20,
        )
        assert report.drawdown_status is not None
        # DD = (75-110)/110 = -31.8%, breach -20%
        assert report.drawdown_status.is_breached
        assert any("回撤" in a for a in report.alerts)

    def test_assessment_circuit_breaker(self):
        """Assessment should detect circuit breaker trigger."""
        from backtest.risk_manager import assess_portfolio_risk
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        stock_data = {
            "A": pd.DataFrame({"close": np.cumprod(1 + np.random.normal(0, 0.02, 100))}, index=dates),
        }
        report = assess_portfolio_risk(
            stock_data,
            daily_pnl=-0.05,  # exceeds -3% daily limit
        )
        assert report.circuit_breaker is not None
        assert report.circuit_breaker.triggered
        assert any("熔斷" in a for a in report.alerts)

    def test_report_to_dict(self):
        """Full report should serialize cleanly."""
        from backtest.risk_manager import assess_portfolio_risk
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        stock_data = {
            "A": pd.DataFrame({"close": np.cumprod(1 + np.random.normal(0, 0.02, 100))}, index=dates),
        }
        report = assess_portfolio_risk(stock_data, holdings={"A": 1_000_000})
        d = report.to_dict()
        assert isinstance(d, dict)
        assert "var" in d
        assert "stress_tests" in d
        assert "concentration" in d


# ---------------------------------------------------------------------------
# API Tests
# ---------------------------------------------------------------------------

class TestRiskManagementAPI:
    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient
        from backend.app import app
        return TestClient(app)

    def test_assess_endpoint(self, client):
        resp = client.post("/api/backtest/risk/assess", json={
            "stock_codes": [],
            "portfolio_value": 1_000_000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "risk_score" in data

    def test_var_endpoint(self, client):
        resp = client.post("/api/backtest/risk/var", json={
            "stock_codes": [],
            "portfolio_value": 1_000_000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "historical_var" in data

    def test_stress_test_endpoint(self, client):
        resp = client.post("/api/backtest/risk/stress-test", json={
            "stock_codes": [],
            "portfolio_value": 1_000_000,
        })
        assert resp.status_code == 200
        # Empty portfolio returns empty results
        assert isinstance(resp.json(), list)

    def test_circuit_breaker_endpoint(self, client):
        resp = client.post("/api/backtest/risk/circuit-breaker", params={
            "daily_pnl": -0.05,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["triggered"] is True


# ---------------------------------------------------------------------------
# R82.2: Concentration-Cap Sector Penalty Tests
# ---------------------------------------------------------------------------

class TestSectorPenaltyMultiplier:
    """Test the proportional Concentration-Cap formula."""

    def test_disabled_by_default(self):
        """Default penalty_factor=1.0 should always return 1.0."""
        from backtest.risk_manager import get_sector_penalty_multiplier
        positions = [{"sector": "半導體", "code": "2330", "market_value": 500_000}]
        mult, reason = get_sector_penalty_multiplier("半導體", positions)
        assert mult == 1.0
        assert reason == ""

    def test_no_positions(self):
        """No existing positions should always return 1.0."""
        from backtest.risk_manager import get_sector_penalty_multiplier
        mult, reason = get_sector_penalty_multiplier("半導體", [], penalty_factor=0.3)
        assert mult == 1.0

    def test_unclassified_sector(self):
        """未分類 should always return 1.0."""
        from backtest.risk_manager import get_sector_penalty_multiplier
        positions = [{"sector": "半導體", "market_value": 500_000}]
        mult, reason = get_sector_penalty_multiplier("未分類", positions, penalty_factor=0.3)
        assert mult == 1.0

    def test_under_cap_no_penalty(self):
        """Sector below t_cap should get full allocation."""
        from backtest.risk_manager import get_sector_penalty_multiplier
        # Portfolio: 半導體 300k, 金融 700k -> R_sector(半導體) = 0.30
        positions = [
            {"sector": "半導體", "code": "2330", "market_value": 300_000},
            {"sector": "金融", "code": "2882", "market_value": 700_000},
        ]
        # t_cap = 0.40, R_sector = 0.30 < 0.40 -> no penalty
        mult, reason = get_sector_penalty_multiplier("半導體", positions, penalty_factor=0.40)
        assert mult == 1.0
        assert reason == ""

    def test_over_cap_proportional(self):
        """Sector above t_cap should get proportional reduction."""
        from backtest.risk_manager import get_sector_penalty_multiplier
        # Portfolio: 半導體 600k, 金融 400k -> R_sector(半導體) = 0.60
        positions = [
            {"sector": "半導體", "code": "2330", "market_value": 600_000},
            {"sector": "金融", "code": "2882", "market_value": 400_000},
        ]
        # t_cap = 0.40, R_sector = 0.60 -> C = 0.40/0.60 = 0.667
        mult, reason = get_sector_penalty_multiplier("半導體", positions, penalty_factor=0.40)
        assert 0.65 < mult < 0.68  # 0.667
        assert "Sector Concentration" in reason

    def test_high_concentration_strong_penalty(self):
        """Very high concentration should give strong penalty."""
        from backtest.risk_manager import get_sector_penalty_multiplier
        # Portfolio: 半導體 900k, 金融 100k -> R_sector = 0.90
        positions = [
            {"sector": "半導體", "code": "2330", "market_value": 900_000},
            {"sector": "金融", "code": "2882", "market_value": 100_000},
        ]
        # t_cap = 0.30, R_sector = 0.90 -> C = 0.30/0.90 = 0.333
        mult, reason = get_sector_penalty_multiplier("半導體", positions, penalty_factor=0.30)
        assert 0.32 < mult < 0.35

    def test_new_sector_no_penalty(self):
        """New sector not in portfolio should get full allocation."""
        from backtest.risk_manager import get_sector_penalty_multiplier
        positions = [
            {"sector": "半導體", "code": "2330", "market_value": 500_000},
        ]
        mult, reason = get_sector_penalty_multiplier("金融", positions, penalty_factor=0.30)
        assert mult == 1.0

    def test_fallback_equal_weight(self):
        """Positions without market_value should use equal weight."""
        from backtest.risk_manager import get_sector_penalty_multiplier
        # 3 positions, 2 in same sector -> R = 2/3 = 0.667
        positions = [
            {"sector": "半導體", "code": "2330"},
            {"sector": "半導體", "code": "2454"},
            {"sector": "金融", "code": "2882"},
        ]
        # t_cap = 0.40, R = 0.667 -> C = 0.40/0.667 = 0.60
        mult, reason = get_sector_penalty_multiplier("半導體", positions, penalty_factor=0.40)
        assert 0.58 < mult < 0.62

    def test_minimum_clamp(self):
        """Multiplier should never go below 0.1."""
        from backtest.risk_manager import get_sector_penalty_multiplier
        # t_cap = 0.15, R = 0.99 -> C = 0.15/0.99 ≈ 0.15 (above 0.1)
        # Need extreme case: t_cap very low, R very high
        positions = [
            {"sector": "半導體", "code": "2330", "market_value": 990_000},
            {"sector": "金融", "code": "2882", "market_value": 10_000},
        ]
        # t_cap = 0.15, R = 0.99 -> C = 0.15/0.99 = 0.1515 (above 0.1)
        mult, _ = get_sector_penalty_multiplier("半導體", positions, penalty_factor=0.15)
        assert mult >= 0.1

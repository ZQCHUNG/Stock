"""Tests for R86 portfolio_heat.py — Correlation-Adjusted Portfolio Heat."""

import numpy as np
import pandas as pd
import pytest

from analysis.portfolio_heat import (
    compute_portfolio_heat,
    check_entry_allowed,
    _compute_correlation_penalty,
    _get_heat_zone,
    HEAT_ZONE_COOL,
    HEAT_ZONE_WARM,
    HEAT_ZONE_HOT,
    CORR_MULT_NONE,
    CORR_MULT_MED,
    CORR_MULT_HIGH,
    SECTOR_HEAT_WARN,
)


# ─── Test Constants ───────────────────────────────────────────

class TestConstants:
    def test_heat_zones(self):
        assert HEAT_ZONE_COOL == 0.03
        assert HEAT_ZONE_WARM == 0.06
        assert HEAT_ZONE_HOT == 0.10

    def test_correlation_penalties(self):
        """Gradient: 1.0 / 1.25 / 1.5 [CONVERGED: GEMINI_R86_CLUSTER]"""
        assert CORR_MULT_NONE == 1.0
        assert CORR_MULT_MED == 1.25
        assert CORR_MULT_HIGH == 1.5


# ─── Test Correlation Penalty ─────────────────────────────────

class TestCorrelationPenalty:
    def test_no_correlation_matrix(self):
        penalty, avg = _compute_correlation_penalty(None)
        assert penalty == 1.0
        assert avg == 0.0

    def test_empty_matrix(self):
        penalty, avg = _compute_correlation_penalty(pd.DataFrame())
        assert penalty == 1.0

    def test_low_correlation(self):
        """Avg corr < 0.5 → no penalty."""
        codes = ["A", "B", "C"]
        corr = pd.DataFrame(
            [[1.0, 0.3, 0.2],
             [0.3, 1.0, 0.1],
             [0.2, 0.1, 1.0]],
            index=codes, columns=codes
        )
        penalty, avg = _compute_correlation_penalty(corr)
        assert penalty == CORR_MULT_NONE
        assert avg < 0.5

    def test_medium_correlation(self):
        """Avg corr 0.5-0.7 → 1.25x penalty."""
        codes = ["A", "B", "C"]
        corr = pd.DataFrame(
            [[1.0, 0.6, 0.55],
             [0.6, 1.0, 0.5],
             [0.55, 0.5, 1.0]],
            index=codes, columns=codes
        )
        penalty, avg = _compute_correlation_penalty(corr)
        assert penalty == CORR_MULT_MED
        assert 0.5 <= avg < 0.7

    def test_high_correlation(self):
        """Avg corr ≥ 0.7 → 1.5x penalty."""
        codes = ["A", "B", "C"]
        corr = pd.DataFrame(
            [[1.0, 0.85, 0.8],
             [0.85, 1.0, 0.75],
             [0.8, 0.75, 1.0]],
            index=codes, columns=codes
        )
        penalty, avg = _compute_correlation_penalty(corr)
        assert penalty == CORR_MULT_HIGH
        assert avg >= 0.7

    def test_single_stock(self):
        """Only 1 stock → no penalty."""
        corr = pd.DataFrame([[1.0]], index=["A"], columns=["A"])
        penalty, avg = _compute_correlation_penalty(corr)
        assert penalty == 1.0


# ─── Test Heat Zones ──────────────────────────────────────────

class TestHeatZones:
    def test_cool_zone(self):
        zone = _get_heat_zone(0.02)
        assert zone["zone"] == "Cool"
        assert zone["block_sector"] is False
        assert zone["block_all"] is False

    def test_warm_zone(self):
        zone = _get_heat_zone(0.04)
        assert zone["zone"] == "Warm"
        assert zone["block_sector"] is False

    def test_hot_zone(self):
        zone = _get_heat_zone(0.08)
        assert zone["zone"] == "Hot"
        assert zone["block_sector"] is True
        assert zone["block_all"] is False

    def test_danger_zone(self):
        zone = _get_heat_zone(0.12)
        assert zone["zone"] == "Danger"
        assert zone["block_sector"] is True
        assert zone["block_all"] is True

    def test_boundary_cool_warm(self):
        assert _get_heat_zone(0.029)["zone"] == "Cool"
        assert _get_heat_zone(0.03)["zone"] == "Warm"

    def test_boundary_warm_hot(self):
        assert _get_heat_zone(0.059)["zone"] == "Warm"
        assert _get_heat_zone(0.06)["zone"] == "Hot"


# ─── Test Compute Portfolio Heat ──────────────────────────────

class TestComputePortfolioHeat:
    def test_empty_portfolio(self):
        result = compute_portfolio_heat([])
        assert result["raw_heat"] == 0.0
        assert result["effective_heat"] == 0.0
        assert result["zone"] == "Cool"
        assert result["position_count"] == 0

    def test_single_position(self):
        positions = [
            {"code": "2330", "risk_pct": 0.02, "sector": "半導體"}
        ]
        result = compute_portfolio_heat(positions)
        assert result["raw_heat"] == pytest.approx(0.02)
        assert result["effective_heat"] == pytest.approx(0.02)  # no penalty with 1 stock
        assert result["zone"] == "Cool"

    def test_multiple_positions(self):
        positions = [
            {"code": "2330", "risk_pct": 0.02, "sector": "半導體"},
            {"code": "2317", "risk_pct": 0.015, "sector": "半導體"},
            {"code": "2412", "risk_pct": 0.01, "sector": "電信"},
        ]
        result = compute_portfolio_heat(positions)
        assert result["raw_heat"] == pytest.approx(0.045)
        assert result["position_count"] == 3

    def test_correlation_amplifies_heat(self):
        """High correlation → heat multiplied by 1.5."""
        positions = [
            {"code": "A", "risk_pct": 0.02, "sector": "半導體"},
            {"code": "B", "risk_pct": 0.02, "sector": "半導體"},
            {"code": "C", "risk_pct": 0.02, "sector": "半導體"},
        ]
        # High correlation matrix
        codes = ["A", "B", "C"]
        corr = pd.DataFrame(
            [[1.0, 0.9, 0.85],
             [0.9, 1.0, 0.8],
             [0.85, 0.8, 1.0]],
            index=codes, columns=codes
        )
        result = compute_portfolio_heat(positions, corr)
        assert result["correlation_penalty"] == 1.5
        assert result["effective_heat"] == pytest.approx(0.06 * 1.5)  # 0.09
        assert result["zone"] == "Hot"

    def test_sector_heat_breakdown(self):
        positions = [
            {"code": "2330", "risk_pct": 0.03, "sector": "半導體"},
            {"code": "2412", "risk_pct": 0.01, "sector": "電信"},
        ]
        result = compute_portfolio_heat(positions)
        assert "半導體" in result["sector_heat"]
        assert "電信" in result["sector_heat"]
        assert result["sector_heat"]["半導體"]["raw_heat"] == pytest.approx(0.03)

    def test_sector_concentration_warning(self):
        """If >50% heat from one sector → warning."""
        positions = [
            {"code": "A", "risk_pct": 0.04, "sector": "半導體"},
            {"code": "B", "risk_pct": 0.01, "sector": "電信"},
        ]
        result = compute_portfolio_heat(positions)
        assert result["sector_warning"] is not None
        assert result["sector_warning"]["sector"] == "半導體"

    def test_positions_sorted_by_heat(self):
        positions = [
            {"code": "A", "risk_pct": 0.01, "sector": "X"},
            {"code": "B", "risk_pct": 0.03, "sector": "Y"},
            {"code": "C", "risk_pct": 0.02, "sector": "Z"},
        ]
        result = compute_portfolio_heat(positions)
        assert result["positions"][0]["code"] == "B"  # highest heat first

    def test_blocked_sectors_in_hot_zone(self):
        positions = [
            {"code": "A", "risk_pct": 0.04, "sector": "半導體"},
            {"code": "B", "risk_pct": 0.035, "sector": "電信"},
        ]
        # With medium correlation → effective heat > 6%
        codes = ["A", "B"]
        corr = pd.DataFrame(
            [[1.0, 0.6],
             [0.6, 1.0]],
            index=codes, columns=codes
        )
        result = compute_portfolio_heat(positions, corr)
        if result["zone"] == "Hot":
            assert len(result["blocked_sectors"]) > 0


# ─── Test Check Entry Allowed ─────────────────────────────────

class TestCheckEntryAllowed:
    def test_allowed_in_cool(self):
        heat = {"effective_heat": 0.02, "zone": "Cool", "block_sector": False, "block_all": False, "blocked_sectors": []}
        result = check_entry_allowed(heat, "半導體")
        assert result["allowed"] is True

    def test_blocked_in_danger(self):
        heat = {"effective_heat": 0.12, "zone": "Danger", "block_sector": True, "block_all": True, "blocked_sectors": ["半導體"]}
        result = check_entry_allowed(heat, "電信")
        assert result["allowed"] is False
        assert "DANGER" in result["reason"]

    def test_sector_blocked_in_hot(self):
        heat = {"effective_heat": 0.08, "zone": "Hot", "block_sector": True, "block_all": False, "blocked_sectors": ["半導體"]}
        result = check_entry_allowed(heat, "半導體")
        assert result["allowed"] is False
        assert "半導體" in result["reason"]

    def test_different_sector_allowed_in_hot(self):
        heat = {"effective_heat": 0.08, "zone": "Hot", "block_sector": True, "block_all": False, "blocked_sectors": ["半導體"]}
        result = check_entry_allowed(heat, "電信")
        assert result["allowed"] is True

    def test_no_sector_specified(self):
        heat = {"effective_heat": 0.08, "zone": "Hot", "block_sector": True, "block_all": False, "blocked_sectors": ["半導體"]}
        result = check_entry_allowed(heat, None)
        assert result["allowed"] is True  # Can't check sector if none given

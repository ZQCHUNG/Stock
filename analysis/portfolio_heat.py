"""
R86: Portfolio Heat Map — Gemini CTO Approved

Correlation-adjusted portfolio heat calculation.
Heat = Σ(position_risk_pct) × Correlation_Penalty

Heat zones with enforcement actions:
- Cool (<3%): Green. Full trading allowed.
- Warm (3-6%): Yellow. Warning badge only.
- Hot (6-10%): Orange. BLOCK new entries in correlated sector.
- Danger (>10%): Red. BLOCK ALL new entries.

Correlation penalty gradient [CONVERGED: GEMINI_R86_CLUSTER]:
- avg_top3_corr < 0.5 → 1.0 (no penalty)
- 0.5 ≤ avg_top3_corr < 0.7 → 1.25
- avg_top3_corr ≥ 0.7 → 1.5
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Any

# ─── Constants ────────────────────────────────────────────────

# Heat zone thresholds [CONVERGED: GEMINI_R86_LOCK_DOOR]
HEAT_ZONE_COOL = 0.03        # < 3% = Cool (green)
HEAT_ZONE_WARM = 0.06        # 3-6% = Warm (yellow)
HEAT_ZONE_HOT = 0.10         # 6-10% = Hot (orange, block sector)
# > 10% = Danger (red, block ALL)

# Correlation penalty gradient [CONVERGED: GEMINI_R86_CLUSTER]
CORR_PENALTY_LOW = 0.5       # Below this: no penalty
CORR_PENALTY_MED = 0.7       # Above this: max penalty
CORR_MULT_NONE = 1.0         # No cluster risk
CORR_MULT_MED = 1.25         # Medium cluster risk
CORR_MULT_HIGH = 1.5         # High cluster risk

# Sector heat warning threshold
SECTOR_HEAT_WARN = 0.50      # [PLACEHOLDER: SECTOR_HEAT_WARN_001] 50% of heat from one sector


# ─── Core Functions ───────────────────────────────────────────

def _compute_correlation_penalty(corr_matrix: pd.DataFrame | None) -> tuple[float, float]:
    """Compute the correlation penalty multiplier.

    Uses average correlation of top 3 most-correlated pairs.

    Returns:
        (penalty_multiplier, avg_top3_correlation)
    """
    if corr_matrix is None or corr_matrix.empty or len(corr_matrix) < 2:
        return CORR_MULT_NONE, 0.0

    # Extract upper triangle correlations (exclude diagonal)
    n = len(corr_matrix)
    corrs = []
    for i in range(n):
        for j in range(i + 1, n):
            corrs.append(corr_matrix.iloc[i, j])

    if not corrs:
        return CORR_MULT_NONE, 0.0

    # Average of top 3 (or all if fewer)
    sorted_corrs = sorted(corrs, reverse=True)
    top_n = min(3, len(sorted_corrs))
    avg_top3 = sum(sorted_corrs[:top_n]) / top_n

    if avg_top3 >= CORR_PENALTY_MED:
        return CORR_MULT_HIGH, avg_top3
    elif avg_top3 >= CORR_PENALTY_LOW:
        return CORR_MULT_MED, avg_top3
    else:
        return CORR_MULT_NONE, avg_top3


def _get_heat_zone(effective_heat: float) -> dict[str, Any]:
    """Classify heat into zone with action recommendation."""
    if effective_heat < HEAT_ZONE_COOL:
        return {
            "zone": "Cool",
            "color": "#22c55e",
            "action": "Full trading allowed",
            "block_sector": False,
            "block_all": False,
        }
    elif effective_heat < HEAT_ZONE_WARM:
        return {
            "zone": "Warm",
            "color": "#f59e0b",
            "action": "Warning — monitor positions",
            "block_sector": False,
            "block_all": False,
        }
    elif effective_heat < HEAT_ZONE_HOT:
        return {
            "zone": "Hot",
            "color": "#f97316",
            "action": "BLOCK new entries in correlated sector",
            "block_sector": True,
            "block_all": False,
        }
    else:
        return {
            "zone": "Danger",
            "color": "#ef4444",
            "action": "BLOCK ALL new entries until heat reduces",
            "block_sector": True,
            "block_all": True,
        }


def compute_portfolio_heat(
    positions: list[dict],
    corr_matrix: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Compute correlation-adjusted portfolio heat.

    Each position dict should have:
        code, risk_pct (distance to stop as fraction of portfolio)
    Optional:
        sector, name, lots, entry_price, stop_price, current_price,
        market_value (for weighting)

    Args:
        positions: List of open position dicts
        corr_matrix: Correlation matrix (codes × codes). If None, uses raw sum.

    Returns:
        Portfolio heat report with zone classification and sector breakdown.
    """
    if not positions:
        zone = _get_heat_zone(0.0)
        return {
            "raw_heat": 0.0,
            "effective_heat": 0.0,
            "correlation_penalty": 1.0,
            "avg_top3_correlation": 0.0,
            "position_count": 0,
            "positions": [],
            "sector_heat": {},
            "sector_warning": None,
            **zone,
        }

    # Calculate raw heat = Σ(position_risk_pct)
    position_heats = []
    sector_totals: dict[str, float] = {}

    for pos in positions:
        risk_pct = pos.get("risk_pct", 0.0)
        sector = pos.get("sector", "未分類")
        code = pos.get("code", "")

        position_heats.append({
            "code": code,
            "name": pos.get("name", ""),
            "risk_pct": round(risk_pct, 4),
            "sector": sector,
            "heat_contribution": round(risk_pct, 4),
        })

        sector_totals[sector] = sector_totals.get(sector, 0) + risk_pct

    raw_heat = sum(p["risk_pct"] for p in position_heats)

    # Correlation penalty
    penalty, avg_corr = _compute_correlation_penalty(corr_matrix)
    effective_heat = raw_heat * penalty

    # Heat zone
    zone = _get_heat_zone(effective_heat)

    # Update position heat contributions with penalty
    for p in position_heats:
        p["heat_contribution"] = round(p["risk_pct"] * penalty, 4)

    # Sort by heat contribution descending
    position_heats.sort(key=lambda x: x["heat_contribution"], reverse=True)

    # Sector heat analysis
    sector_heat = {}
    for sector, total in sector_totals.items():
        adj_total = total * penalty
        pct_of_heat = adj_total / effective_heat if effective_heat > 0 else 0
        sector_heat[sector] = {
            "raw_heat": round(total, 4),
            "adjusted_heat": round(adj_total, 4),
            "pct_of_total": round(pct_of_heat, 3),
        }

    # Sector concentration warning
    sector_warning = None
    if sector_heat:
        max_sector = max(sector_heat.items(), key=lambda x: x[1]["pct_of_total"])
        if max_sector[1]["pct_of_total"] >= SECTOR_HEAT_WARN:
            sector_warning = {
                "sector": max_sector[0],
                "pct": round(max_sector[1]["pct_of_total"], 3),
                "message": f"{max_sector[0]} accounts for {max_sector[1]['pct_of_total']:.0%} of portfolio heat",
            }

    # Blocked sectors (if Hot zone)
    blocked_sectors = []
    if zone["block_sector"] and not zone["block_all"]:
        # Block the sector with highest heat
        if sector_heat:
            top_sector = max(sector_heat.items(), key=lambda x: x[1]["adjusted_heat"])
            blocked_sectors.append(top_sector[0])

    return {
        "raw_heat": round(raw_heat, 4),
        "effective_heat": round(effective_heat, 4),
        "correlation_penalty": penalty,
        "avg_top3_correlation": round(avg_corr, 3),
        "position_count": len(positions),
        "positions": position_heats,
        "sector_heat": sector_heat,
        "sector_warning": sector_warning,
        "blocked_sectors": blocked_sectors,
        **zone,
    }


def check_entry_allowed(
    heat_report: dict,
    new_sector: str | None = None,
) -> dict[str, Any]:
    """Check if a new entry is allowed given current portfolio heat.

    Args:
        heat_report: Output of compute_portfolio_heat()
        new_sector: Sector of the potential new entry

    Returns:
        Dict with allowed (bool), reason, heat_zone
    """
    if heat_report.get("block_all"):
        return {
            "allowed": False,
            "reason": f"Portfolio heat at {heat_report['effective_heat']:.1%} — DANGER zone. All entries blocked.",
            "zone": heat_report.get("zone", "Danger"),
        }

    if heat_report.get("block_sector") and new_sector:
        blocked = heat_report.get("blocked_sectors", [])
        if new_sector in blocked:
            return {
                "allowed": False,
                "reason": f"Sector '{new_sector}' blocked — portfolio heat at {heat_report['effective_heat']:.1%} (Hot zone).",
                "zone": heat_report.get("zone", "Hot"),
            }

    return {
        "allowed": True,
        "reason": f"Entry allowed — portfolio heat at {heat_report['effective_heat']:.1%} ({heat_report.get('zone', 'Cool')}).",
        "zone": heat_report.get("zone", "Cool"),
    }

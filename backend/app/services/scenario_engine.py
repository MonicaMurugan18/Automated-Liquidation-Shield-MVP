"""Scenario engine: project the position forward through hypothetical price
moves and report the Health Factor trajectory for each.

This is differentiator #1. It answers "what happens if the market keeps
falling?" *before* it falls, which is what lets the agent pre-compute the
intervention it would need rather than reacting after the fact.

The model is deterministic: a scenario is a single instantaneous price shock
applied to the collateral asset, with debt held constant. That is the right
level of fidelity for an MVP. A production version would layer on a stochastic
path model (GBM or a historical bootstrap) to attach a probability to each
scenario -- the interface here is shaped so that becomes an extra field rather
than a rewrite.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from ..models.domain import Position, RiskPreferences, Scenario, ValidationError
from . import risk_engine

# The ladder the dashboard shows by default: current price plus four
# progressively worse shocks.
DEFAULT_DROPS: Sequence[float] = (0.0, 5.0, 10.0, 15.0, 20.0)


def _label(drop_pct: float) -> str:
    if drop_pct == 0:
        return "Current"
    return f"-{drop_pct:g}%"


def simulate_scenario(
    position: Position,
    drop_pct: float,
    prefs: Optional[RiskPreferences] = None,
) -> Scenario:
    """Apply a single price shock and describe the resulting position."""
    prefs = prefs or RiskPreferences()
    risk_engine.validate_position(position)
    risk_engine.validate_preferences(prefs)

    if drop_pct < 0 or drop_pct >= 100:
        raise ValidationError(
            "Price drop must be between 0 and 100 percent (exclusive of 100)."
        )

    new_price = position.collateral_price * (1.0 - drop_pct / 100.0)
    shocked = position.with_price(new_price)

    hf = risk_engine.health_factor(shocked)
    level = risk_engine.classify_risk(hf)
    needs_action = shocked.debt_value > 0 and hf <= prefs.trigger_health_factor
    repayment = risk_engine.minimum_repayment_to_target(
        shocked, prefs.target_health_factor
    )
    topup = risk_engine.minimum_collateral_topup_to_target(
        shocked, prefs.target_health_factor
    )

    if shocked.debt_value <= 0:
        summary = "No debt outstanding -- no intervention possible or needed."
    elif repayment <= 0:
        # Edge case 6: minimum repayment is zero.
        summary = "None required -- position stays above the safety target."
    elif hf <= risk_engine.LIQUIDATION_HF:
        summary = (
            f"Liquidatable. Repay ${repayment:,.0f} or add ${topup:,.0f} "
            f"collateral immediately."
        )
    else:
        summary = f"Repay ${repayment:,.0f} or add ${topup:,.0f} collateral."

    return Scenario(
        label=_label(drop_pct),
        price_drop_pct=drop_pct,
        new_price=round(new_price, 2),
        new_collateral_value=round(shocked.collateral_value, 2),
        health_factor=round(hf, 4),
        risk_level=level,
        liquidatable=hf <= risk_engine.LIQUIDATION_HF,
        requires_intervention=needs_action,
        required_repayment=round(repayment, 2),
        required_collateral_topup=round(topup, 2),
        intervention_summary=summary,
    )


def simulate(
    position: Position,
    drops: Optional[Sequence[float]] = None,
    prefs: Optional[RiskPreferences] = None,
) -> List[Scenario]:
    """Run the full scenario ladder. Drives the Scenario Prediction page."""
    drops = DEFAULT_DROPS if drops is None else drops
    if not drops:
        raise ValidationError("At least one price-drop scenario is required.")
    return [simulate_scenario(position, d, prefs) for d in drops]


def first_breaking_scenario(scenarios: Sequence[Scenario]) -> Optional[Scenario]:
    """The mildest scenario in the ladder that would liquidate the position.

    Returns None when the position survives every scenario tested -- which the
    UI reports as "survives the full ladder".
    """
    for s in scenarios:
        if s.liquidatable:
            return s
    return None


def summarise(position: Position, scenarios: Sequence[Scenario]) -> str:
    """One-line headline for the Scenario Prediction page."""
    breaking = first_breaking_scenario(scenarios)
    if position.debt_value <= 0:
        return "No debt outstanding -- every scenario is survivable."
    if breaking is None:
        worst = min(scenarios, key=lambda s: s.health_factor)
        # HF 1.0 exactly is the liquidation line, not past it. Reporting that
        # as a clean survival would understate the risk, so call it out.
        if worst.health_factor <= risk_engine.LIQUIDATION_HF + 0.05:
            return (
                f"Survives the ladder, but only just: {worst.label} puts the "
                f"Health Factor on the liquidation line at "
                f"{worst.health_factor:.3f}."
            )
        return (
            f"Survives the full ladder. At {worst.label} the Health Factor "
            f"holds at {worst.health_factor:.3f}."
        )
    return (
        f"A {breaking.label} move liquidates this position "
        f"(HF {breaking.health_factor:.3f})."
    )

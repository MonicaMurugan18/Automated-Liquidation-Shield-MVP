"""Advisor: turns engine output into guidance a non-specialist can act on.

WHY THIS IS ON THE SERVER
-------------------------
The dashboard's Agent Decision panel needs prose -- a headline, a plain
explanation, two or three concrete next steps. All of it is a function of the
position, the Health Factor and the strategies the engine generated, so it
belongs here rather than in a component. A React file that decides "this
position needs collateral" has quietly become a second risk engine, and the
two will disagree the first time either changes.

The frontend receives `guidance` and renders it. It chooses colours from the
`tone` field and lays out the list; it does not decide what the advice is.

BANDS
-----
  SAFE          nothing to do; say so, and say what to watch
  WARNING       below target but above the trigger -- preventive options
  DANGER        act now; lead with the recommended strategy
  LIQUIDATABLE  a liquidator can act already; same, but blunter

Every number quoted in the text is computed here from the same functions the
rest of the system uses, so the prose can never drift from the figures beside
it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from ..models.domain import (
    ExecutionStatus,
    Position,
    ProtectionDecision,
    RiskLevel,
    RiskPreferences,
    Strategy,
)
from . import risk_engine

#: How urgent the situation is, independent of the colour used to show it.
URGENCY_HEALTHY = "HEALTHY"
URGENCY_MONITOR = "MONITOR"
URGENCY_PREVENTIVE = "PREVENTIVE"
URGENCY_URGENT = "URGENT"
URGENCY_CRITICAL = "CRITICAL"

TONE_FOR_RISK = {
    RiskLevel.SAFE: "safe",
    RiskLevel.WARNING: "warn",
    RiskLevel.DANGER: "danger",
    RiskLevel.LIQUIDATABLE: "danger",
}

#: Plain-language names. The enum values are engineering vocabulary; these are
#: what a borrower should read.
PLAIN_STRATEGY = {
    "REPAY_DEBT": "paying down part of your loan",
    "ADD_COLLATERAL": "topping up your deposit",
    "COLLATERAL_SWAP": "selling a slice of your deposit to pay down the loan",
    "FLASH_LOAN_DELEVERAGE": "an instant borrow-repay-sell in a single step",
    "PARTIAL_DELEVERAGE": "a small partial repayment",
}


@dataclass
class Suggestion:
    """One concrete thing the user could do, with the number as support."""

    title: str
    detail: str
    kind: str = "action"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Guidance:
    headline: str
    tone: str
    urgency: str
    summary: str
    suggestions: List[Suggestion] = field(default_factory=list)
    primary_strategy: Optional[Dict[str, Any]] = None
    primary_reason: Optional[str] = None
    alternatives: List[Dict[str, Any]] = field(default_factory=list)
    blocked_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "headline": self.headline,
            "tone": self.tone,
            "urgency": self.urgency,
            "summary": self.summary,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "primary_strategy": self.primary_strategy,
            "primary_reason": self.primary_reason,
            "alternatives": self.alternatives,
            "blocked_reason": self.blocked_reason,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _money(amount: float) -> str:
    return f"${amount:,.0f}" if amount >= 100 else f"${amount:,.2f}"


def _strategy_card(strategy: Strategy) -> Dict[str, Any]:
    """The subset of a strategy the guidance panel needs."""
    d = strategy.to_dict()
    return {
        "strategy_type": d["strategy_type"],
        "name": d["name"],
        "plain_action": PLAIN_STRATEGY.get(d["strategy_type"], d["name"].lower()),
        "action_amount": d["action_amount"],
        "required_capital": d["required_capital"],
        "resulting_health_factor": d["resulting_health_factor"],
        "resulting_risk_level": d["resulting_risk_level"],
        "total_cost": d["total_cost"],
        "score_100": d["score_100"],
        "safety_level": d["safety_level"],
        "slippage_pct": d["slippage_pct"],
        "status": d["status"],
        "rejection_reason": d["rejection_reason"],
    }


def _safest(strategies: List[Strategy]) -> Optional[Strategy]:
    """The viable candidate with the highest safety sub-score.

    Not necessarily the one the agent executes: selection weighs cost and
    capital too. Where they differ the guidance says so, rather than quietly
    recommending something other than what ran.
    """
    viable = [s for s in strategies if s.is_executable]
    if not viable:
        return None
    return max(viable, key=lambda s: (s.score_breakdown.get("safety", 0.0), s.score))


def _headroom_suggestion(position: Position, prefs: RiskPreferences) -> Suggestion:
    """How far the price can fall before the agent steps in."""
    to_trigger = risk_engine.price_drop_to_health_factor_pct(
        position, prefs.trigger_health_factor
    )
    to_liq = risk_engine.price_drop_to_liquidation_pct(position)
    asset = position.collateral_asset

    if to_trigger <= 0:
        return Suggestion(
            title="Watch the price closely",
            detail=(
                f"You are already at the point where the agent intervenes. A "
                f"further {to_liq:.1f}% fall in {asset} would allow liquidation."
            ),
            kind="watch",
        )
    return Suggestion(
        title="Keep an eye on the price",
        detail=(
            f"{asset} would have to fall about {to_trigger:.1f}% before the agent "
            f"steps in, and {to_liq:.1f}% before liquidation becomes possible."
        ),
        kind="watch",
    )


def _preventive_suggestions(
    position: Position, prefs: RiskPreferences
) -> List[Suggestion]:
    """Two ways to restore the target, plus what to watch.

    Sized from the real position. The action leads and the number supports it,
    because "Add $500" on its own tells someone nothing about why.
    """
    target = prefs.target_health_factor
    repayment = risk_engine.minimum_repayment_to_target(position, target)
    topup = risk_engine.minimum_collateral_topup_to_target(position, target)

    suggestions: List[Suggestion] = []
    if repayment > 0:
        suggestions.append(
            Suggestion(
                title="Pay down part of your loan",
                detail=(
                    f"Repaying about {_money(repayment)} would lift your Health "
                    f"Factor back to your {target:.2f} target. This is the "
                    f"cheapest route because it touches nothing else."
                ),
            )
        )
    if topup > 0:
        suggestions.append(
            Suggestion(
                title="Top up your deposit",
                detail=(
                    f"Adding about {_money(topup)} of "
                    f"{position.collateral_asset} reaches the same target "
                    f"without reducing your loan, so you keep full exposure to "
                    f"any price recovery."
                ),
            )
        )
    suggestions.append(_headroom_suggestion(position, prefs))
    return suggestions


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------

def advise(
    position: Position,
    prefs: RiskPreferences,
    decision: ProtectionDecision,
) -> Guidance:
    """Build the guidance for one evaluated position."""
    assessment = decision.assessment
    level = assessment.risk_level
    tone = TONE_FOR_RISK[level]
    strategies = decision.strategies
    selected = decision.selected_strategy
    asset = position.collateral_asset

    # --- no debt: nothing can go wrong ------------------------------------
    if position.debt_value <= 0:
        return Guidance(
            headline="Healthy",
            tone="safe",
            urgency=URGENCY_HEALTHY,
            summary="You have no outstanding debt, so this position cannot be liquidated.",
            suggestions=[
                Suggestion(
                    title="Nothing to do",
                    detail="Liquidation risk only exists while you owe something.",
                    kind="watch",
                )
            ],
        )

    # --- SAFE --------------------------------------------------------------
    if level is RiskLevel.SAFE:
        return Guidance(
            headline="Healthy",
            tone="safe",
            urgency=URGENCY_HEALTHY,
            summary=(
                f"No intervention is required. Your Health Factor of "
                f"{assessment.health_factor:.3f} is above your "
                f"{prefs.target_health_factor:.2f} target, so the agent is "
                f"monitoring rather than acting."
            ),
            suggestions=[_headroom_suggestion(position, prefs)],
        )

    # --- WARNING: below target, above the trigger --------------------------
    if level is RiskLevel.WARNING and not assessment.requires_action:
        return Guidance(
            headline="Warning",
            tone="warn",
            urgency=URGENCY_PREVENTIVE,
            summary=(
                f"Your Health Factor of {assessment.health_factor:.3f} sits below "
                f"your {prefs.target_health_factor:.2f} target but above the "
                f"{prefs.trigger_health_factor:.2f} level where the agent acts. "
                f"Nothing is being executed. These are optional steps to rebuild "
                f"your buffer now, while it is cheap."
            ),
            suggestions=_preventive_suggestions(position, prefs),
        )

    # --- DANGER / LIQUIDATABLE, or WARNING that crossed the trigger --------
    critical = level is RiskLevel.LIQUIDATABLE
    if critical:
        headline = "Liquidatable"
        summary = (
            f"Your Health Factor is {assessment.health_factor:.3f}. Below 1.00 a "
            f"liquidator can seize your collateral at a discount right now, "
            f"costing you about "
            f"{_money(assessment.potential_liquidation_loss)}."
        )
    else:
        headline = "High Risk"
        summary = (
            f"Your Health Factor is {assessment.health_factor:.3f}, at or below "
            f"the {prefs.trigger_health_factor:.2f} level where the agent "
            f"intervenes. A further {assessment.price_drop_to_liquidation_pct:.1f}% "
            f"fall in {asset} would make liquidation possible."
        )

    urgency = URGENCY_CRITICAL if critical else URGENCY_URGENT

    # Nothing viable: say exactly which constraint blocked it.
    if selected is None:
        rejected = [s for s in strategies if s.rejection_reason]
        return Guidance(
            headline=headline,
            tone="danger",
            urgency=urgency,
            summary=summary,
            blocked_reason=decision.explanation,
            suggestions=[
                Suggestion(
                    title="No strategy satisfies the constraints",
                    detail=(
                        "The agent generated "
                        f"{len(strategies)} option"
                        f"{'s' if len(strategies) != 1 else ''} and rejected every "
                        "one. Loosening a limit on the Settings page -- more "
                        "wallet capital, a higher slippage tolerance -- may make "
                        "one workable."
                    ),
                    kind="blocked",
                ),
                *[
                    Suggestion(
                        title=s.name,
                        detail=s.rejection_reason or "Rejected.",
                        kind="rejected",
                    )
                    for s in rejected
                ],
            ],
            alternatives=[_strategy_card(s) for s in strategies],
        )

    # A viable recommendation exists.
    safest = _safest(strategies)
    others = [s for s in strategies if s.is_executable and s is not selected]

    reason = (
        f"The agent picked {PLAIN_STRATEGY.get(selected.strategy_type.value, selected.name.lower())}"
        f" because it restores your {prefs.target_health_factor:.2f} target for "
        f"{_money(selected.total_cost)} -- the best balance of safety and cost "
        f"among the {len([s for s in strategies if s.is_executable])} workable "
        f"options."
    )
    if safest is not None and safest is not selected:
        reason += (
            f" {safest.name} scores higher on safety alone, but costs "
            f"{_money(safest.total_cost)}."
        )

    executed = decision.execution_status is ExecutionStatus.EXECUTED
    awaiting = decision.execution_status is ExecutionStatus.AWAITING_CONFIRMATION

    suggestions = [
        Suggestion(
            title=f"Recommended: {selected.name}",
            detail=(
                f"{_money(selected.action_amount)} — brings your Health Factor to "
                f"{selected.resulting_health_factor:.3f} "
                f"({selected.resulting_risk_level.value.lower()}) at a cost of "
                f"{_money(selected.total_cost)}."
            ),
            kind="primary",
        )
    ]
    if awaiting:
        suggestions.append(
            Suggestion(
                title="Confirm to execute",
                detail=(
                    "You are in Advisory mode, so nothing runs until you approve "
                    "it. Switch to Autonomous on the Settings page to let the "
                    "agent act on its own."
                ),
                kind="watch",
            )
        )
    elif executed:
        suggestions.append(
            Suggestion(
                title="Already executed (simulated)",
                detail=(
                    "Autonomous mode acted without waiting. No real transaction "
                    "was signed or broadcast."
                ),
                kind="watch",
            )
        )

    return Guidance(
        headline=headline,
        tone="danger",
        urgency=urgency,
        summary=summary,
        suggestions=suggestions,
        primary_strategy=_strategy_card(selected),
        primary_reason=reason,
        alternatives=[_strategy_card(s) for s in others],
    )

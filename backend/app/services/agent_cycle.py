"""One complete agent cycle, run end to end on the server.

This module is the answer to "is the dashboard a mockup?". Everything the UI
shows during a demo run -- the shocked price, the recalculated Health Factor,
the risk level, the candidate set, the rejections, the winning score, the
execution result, the final Health Factor, and the status-bar state at every
step -- is computed here and returned in one response.

The frontend's only job is to render it. It does not recompute a price, it
does not decide a state, and it does not narrate a step the engine did not
take.

Cycle order (matching the product spec):

     1. accept the scenario request        9.  run economic viability checks
     2. apply the price shock             10.  reject invalid strategies
     3. revalue collateral                11.  score the valid ones
     4. recalculate the Health Factor     12.  auto-select the highest score
     5. reclassify risk                   13.  autonomous -> simulate execution
     6. generate protection strategies    14.  advisory   -> hold for confirm
     7. size the minimum repayment        15.  recalculate the final HF
     8. cost gas / slippage / flash fee   16.  hand the whole trace back

Step 17 (persistence) belongs to the route, not here, so this module stays
pure and unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional

from ..models.domain import (
    CycleStage,
    ExecutionStatus,
    HealthAssessment,
    MarketConditions,
    Position,
    ProtectionMode,
    RiskPreferences,
    Scenario,
    ShieldState,
    Strategy,
    StrategyStatus,
    TraceStep,
    ValidationError,
)
from . import risk_engine, scenario_engine, strategy_engine


@dataclass
class CycleResult:
    """Everything one cycle produced. Serialised wholesale to the client."""

    price_drop_pct: float
    price_before: float
    price_after: float
    position_before: Position
    position_shocked: Position
    position_final: Position
    assessment_before: HealthAssessment
    assessment_shocked: HealthAssessment
    assessment_final: HealthAssessment
    scenarios: List[Scenario]
    strategies: List[Strategy]
    selected_strategy: Optional[Strategy]
    execution_status: ExecutionStatus
    shield_state: ShieldState
    executed: bool
    explanation: str
    economics: Dict[str, Any]
    market: MarketConditions
    trace: List[TraceStep]
    transaction: Optional[Dict[str, Any]] = None

    @property
    def strategies_generated(self) -> int:
        return len(self.strategies)

    @property
    def strategies_rejected(self) -> int:
        return sum(1 for s in self.strategies if not s.is_executable)

    @property
    def strategies_viable(self) -> int:
        return sum(1 for s in self.strategies if s.is_executable)

    @property
    def final_status(self) -> str:
        """Headline outcome of the cycle, for the Decision Trace footer."""
        if self.executed:
            return "PROTECTED"
        if self.execution_status is ExecutionStatus.AWAITING_CONFIRMATION:
            return "AWAITING CONFIRMATION"
        if self.execution_status is ExecutionStatus.NO_ACTION_REQUIRED:
            return "MONITORING"
        return "STOOD DOWN"

    def decision_trace(self) -> Dict[str, Any]:
        """The compact summary the Decision Trace panel renders."""
        drop = self.price_drop_pct
        scenario = (
            f"{self.position_before.collateral_asset} -{drop:g}%"
            if drop
            else f"{self.position_before.collateral_asset} at entered price"
        )
        if self.executed:
            execution = "SIMULATED SUCCESS"
        elif self.execution_status is ExecutionStatus.AWAITING_CONFIRMATION:
            execution = "AWAITING CONFIRMATION"
        elif self.execution_status is ExecutionStatus.NO_ACTION_REQUIRED:
            execution = "NOT REQUIRED"
        else:
            execution = "STOOD DOWN"

        return {
            "scenario": scenario,
            "price_before": round(self.price_before, 2),
            "price_after": round(self.price_after, 2),
            "collateral_value_after": self.assessment_shocked.collateral_value,
            "health_factor_before": self.assessment_before.health_factor,
            "health_factor_after_shock": self.assessment_shocked.health_factor,
            "risk_level_before": self.assessment_before.risk_level.value,
            "risk_level": self.assessment_shocked.risk_level.value,
            "strategies_generated": self.strategies_generated,
            "strategies_rejected": self.strategies_rejected,
            "strategies_viable": self.strategies_viable,
            "selected": self.selected_strategy.name if self.selected_strategy else None,
            "why_selected": self.explanation,
            "execution": execution,
            "final_health_factor": self.assessment_final.health_factor,
            "final_risk_level": self.assessment_final.risk_level.value,
            "final_status": self.final_status,
            "mode": None,  # filled by the caller from preferences
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "price_drop_pct": self.price_drop_pct,
            "price_before": round(self.price_before, 2),
            "price_after": round(self.price_after, 2),
            "position_before": self.position_before.to_dict(),
            "position_shocked": self.position_shocked.to_dict(),
            "position_final": self.position_final.to_dict(),
            "assessment_before": self.assessment_before.to_dict(),
            "assessment_shocked": self.assessment_shocked.to_dict(),
            "assessment_final": self.assessment_final.to_dict(),
            "scenarios": [s.to_dict() for s in self.scenarios],
            "strategies": [s.to_dict() for s in self.strategies],
            "selected_strategy": (
                self.selected_strategy.to_dict() if self.selected_strategy else None
            ),
            "execution_status": self.execution_status.value,
            "shield_state": self.shield_state.value,
            "executed": self.executed,
            "explanation": self.explanation,
            "economics": self.economics,
            "market": self.market.to_dict(),
            "trace": [t.to_dict() for t in self.trace],
            "decision_trace": self.decision_trace(),
            "transaction": self.transaction,
            "simulated": True,
        }


def _rejection_summary(strategies: List[Strategy]) -> str:
    rejected = [s for s in strategies if not s.is_executable]
    if not rejected:
        return "No candidate broke a constraint."
    return "; ".join(f"{s.name} ({s.status.value})" for s in rejected)


def run_cycle(
    position: Position,
    prefs: Optional[RiskPreferences] = None,
    market: Optional[MarketConditions] = None,
    price_drop_pct: float = 10.0,
    confirm: bool = False,
) -> CycleResult:
    """Run the full cycle and return every intermediate result.

    `confirm` only matters in Advisory mode: it is the user authorising the
    recommendation the agent already made. In Autonomous mode it is ignored,
    because the agent does not wait for it.
    """
    prefs = prefs or RiskPreferences()
    market = market or MarketConditions(eth_price=position.collateral_price)

    # --- 1. validate the request -------------------------------------------
    risk_engine.validate_position(position)
    risk_engine.validate_preferences(prefs)
    if price_drop_pct < 0 or price_drop_pct >= 100:
        raise ValidationError(
            "Price drop must be between 0 and 100 percent (exclusive of 100)."
        )

    trace: List[TraceStep] = []
    assessment_before = risk_engine.assess(position, prefs)

    trace.append(
        TraceStep(
            stage=CycleStage.MONITOR,
            shield_state=ShieldState.ARMED,
            label="Monitoring position" if price_drop_pct > 0 else "Position received",
            detail=(
                f"{position.collateral_asset} "
                f"${position.collateral_price:,.2f} · Health Factor "
                f"{assessment_before.health_factor:.3f} · "
                f"{assessment_before.risk_level.value}"
            ),
        )
    )

    # --- 2/3. apply the shock and revalue collateral ------------------------
    price_after = position.collateral_price * (1.0 - price_drop_pct / 100.0)
    shocked = position.with_price(price_after)

    # Gas is paid in ETH. Re-price it only when ETH is what moved -- costing a
    # BTC-collateralised rescue at the BTC price would overstate gas twentyfold.
    if position.collateral_asset.upper() == "ETH":
        market = replace(market, eth_price=price_after)

    shocked_label = (
        f"Price shock: {position.collateral_asset} -{price_drop_pct:g}%"
        if price_drop_pct > 0
        else f"Analysing at the entered {position.collateral_asset} price"
    )
    shocked_detail = (
        f"${position.collateral_price:,.2f} → ${price_after:,.2f} · "
        f"collateral revalued "
        f"${position.collateral_value:,.0f} → ${shocked.collateral_value:,.0f}"
        if price_drop_pct > 0
        else (
            f"{position.collateral_amount:,.4f} {position.collateral_asset} at "
            f"${position.collateral_price:,.2f} = "
            f"${shocked.collateral_value:,.0f} of collateral against "
            f"${shocked.debt_value:,.0f} of {position.debt_asset} debt"
        )
    )

    trace.append(
        TraceStep(
            stage=CycleStage.SHOCK,
            shield_state=ShieldState.ARMED,
            label=shocked_label,
            detail=shocked_detail,
        )
    )

    # --- 4/5. recalculate the Health Factor and reclassify risk ------------
    assessment_shocked = risk_engine.assess(shocked, prefs)
    breached = assessment_shocked.requires_action

    trace.append(
        TraceStep(
            stage=CycleStage.ASSESS,
            shield_state=ShieldState.ALERT if breached else ShieldState.ARMED,
            label=(
                f"Health Factor {assessment_shocked.health_factor:.3f} · "
                f"{assessment_shocked.risk_level.value}"
            ),
            detail=assessment_shocked.message,
        )
    )

    scenarios = scenario_engine.simulate(shocked, prefs=prefs)

    # The position never crossed the trigger: nothing will be executed. But
    # options are still generated and shown, because a position below target is
    # one a user may want to act on early -- and reporting "0 strategies" while
    # the scenario ladder shows the trigger being crossed two rungs down is a
    # contradiction, not restraint.
    if not breached:
        idle = strategy_engine.evaluate(shocked, prefs, market)
        options = idle.strategies
        viable = [s for s in options if s.is_executable]

        if options:
            trace.append(
                TraceStep(
                    stage=CycleStage.GENERATE,
                    shield_state=ShieldState.ARMED,
                    label=f"{len(options)} protection options available",
                    detail=(
                        f"{len(viable)} clear every constraint. Nothing is "
                        f"executed above the "
                        f"{prefs.trigger_health_factor:.2f} trigger -- these "
                        f"are choices, not actions."
                    ),
                )
            )

        trace.append(
            TraceStep(
                stage=CycleStage.REARM,
                shield_state=ShieldState.ARMED,
                label="Re-armed",
                detail=(
                    f"Above the {prefs.trigger_health_factor:.2f} intervention "
                    f"trigger. Continuing to monitor."
                ),
            )
        )
        return CycleResult(
            price_drop_pct=price_drop_pct,
            price_before=position.collateral_price,
            price_after=price_after,
            position_before=position,
            position_shocked=shocked,
            position_final=shocked,
            assessment_before=assessment_before,
            assessment_shocked=assessment_shocked,
            assessment_final=assessment_shocked,
            scenarios=scenarios,
            strategies=options,
            selected_strategy=None,
            execution_status=ExecutionStatus.NO_ACTION_REQUIRED,
            shield_state=ShieldState.ARMED,
            executed=False,
            explanation=idle.explanation,
            economics=idle.economics,
            market=market,
            trace=trace,
        )

    # --- 6-12. generate, size, cost, check, reject, score, select ----------
    decision = strategy_engine.evaluate(shocked, prefs, market)
    strategies = decision.strategies

    trace.append(
        TraceStep(
            stage=CycleStage.GENERATE,
            shield_state=ShieldState.ALERT,
            label=f"{len(strategies)} strategies generated",
            detail=(
                "Repayment sized from the documented formula; gas, slippage "
                "and flash-loan premium costed against current market "
                "conditions."
            ),
        )
    )

    viable = [s for s in strategies if s.is_executable]
    trace.append(
        TraceStep(
            stage=CycleStage.SCORE,
            shield_state=ShieldState.ALERT,
            label=(
                f"{len(viable)} viable · {len(strategies) - len(viable)} rejected"
            ),
            detail=_rejection_summary(strategies),
        )
    )

    # --- stand-down paths (edge cases 3/4/5/7) -----------------------------
    if decision.selected_strategy is None:
        trace.append(
            TraceStep(
                stage=CycleStage.STAND_DOWN,
                shield_state=ShieldState.SKIPPED,
                label="Rescue skipped",
                detail=decision.explanation,
            )
        )
        return CycleResult(
            price_drop_pct=price_drop_pct,
            price_before=position.collateral_price,
            price_after=price_after,
            position_before=position,
            position_shocked=shocked,
            position_final=shocked,
            assessment_before=assessment_before,
            assessment_shocked=assessment_shocked,
            assessment_final=assessment_shocked,
            scenarios=scenarios,
            strategies=strategies,
            selected_strategy=None,
            execution_status=decision.execution_status,
            shield_state=ShieldState.SKIPPED,
            executed=False,
            explanation=decision.explanation,
            economics=decision.economics,
            market=market,
            trace=trace,
        )

    best = decision.selected_strategy
    trace.append(
        TraceStep(
            stage=CycleStage.SELECT,
            shield_state=ShieldState.ALERT,
            label=f"Auto-selected: {best.name}",
            detail=decision.explanation,
        )
    )

    # --- 14. advisory mode holds -------------------------------------------
    holding = (
        prefs.mode is ProtectionMode.ADVISORY
        and decision.execution_status is ExecutionStatus.AWAITING_CONFIRMATION
        and not confirm
    )
    if holding:
        trace.append(
            TraceStep(
                stage=CycleStage.HOLD,
                shield_state=ShieldState.ALERT,
                label="Advisory mode — holding",
                detail=(
                    f"Recommendation ready. {best.name} would restore Health "
                    f"Factor {best.resulting_health_factor:.3f} for "
                    f"${best.total_cost:,.2f}. Awaiting confirmation."
                ),
            )
        )
        return CycleResult(
            price_drop_pct=price_drop_pct,
            price_before=position.collateral_price,
            price_after=price_after,
            position_before=position,
            position_shocked=shocked,
            position_final=shocked,
            assessment_before=assessment_before,
            assessment_shocked=assessment_shocked,
            assessment_final=assessment_shocked,
            scenarios=scenarios,
            strategies=strategies,
            selected_strategy=best,
            execution_status=ExecutionStatus.AWAITING_CONFIRMATION,
            shield_state=ShieldState.ALERT,
            executed=False,
            explanation=decision.explanation,
            economics=decision.economics,
            market=market,
            trace=trace,
        )

    # --- 13. simulated execution -------------------------------------------
    trace.append(
        TraceStep(
            stage=CycleStage.EXECUTE,
            shield_state=ShieldState.PROTECTING,
            label="Executing (simulated)",
            detail=(
                f"{best.name} · ${best.action_amount:,.0f} · estimated cost "
                f"${best.total_cost:,.2f}. No transaction is signed or "
                f"broadcast."
            ),
        )
    )

    final_position = strategy_engine.apply_strategy(shocked, best)

    # --- 15. recalculate the final Health Factor from the mutated position --
    assessment_final = risk_engine.assess(final_position, prefs)

    trace.append(
        TraceStep(
            stage=CycleStage.SETTLE,
            shield_state=ShieldState.PROTECTED,
            label="Position protected",
            detail=(
                f"Health Factor {assessment_shocked.health_factor:.3f} → "
                f"{assessment_final.health_factor:.3f} · "
                f"{assessment_final.risk_level.value}"
            ),
        )
    )
    trace.append(
        TraceStep(
            stage=CycleStage.REARM,
            shield_state=ShieldState.ARMED,
            label="Re-armed",
            detail=(
                f"Watching again. Next intervention below Health Factor "
                f"{prefs.trigger_health_factor:.2f}."
            ),
        )
    )

    return CycleResult(
        price_drop_pct=price_drop_pct,
        price_before=position.collateral_price,
        price_after=price_after,
        position_before=position,
        position_shocked=shocked,
        position_final=final_position,
        assessment_before=assessment_before,
        assessment_shocked=assessment_shocked,
        assessment_final=assessment_final,
        scenarios=scenarios,
        strategies=strategies,
        selected_strategy=best,
        execution_status=ExecutionStatus.EXECUTED,
        shield_state=ShieldState.ARMED,
        executed=True,
        explanation=decision.explanation,
        economics=decision.economics,
        market=market,
        trace=trace,
    )

"""HTTP surface.

The routes are a thin adapter: parse, delegate to an engine, serialise. No
liquidation logic lives here -- if a rule cannot be unit-tested without
starting a web server, it is in the wrong file.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from ..config import get_settings
from ..models.domain import (
    ExecutionStatus,
    MarketConditions,
    Position,
    ProtectionDecision,
    ProtectionMode,
    RiskPreferences,
    ShieldState,
    ValidationError,
)
from ..schemas.api import (
    AnalyzeRequest,
    AnalyzeResponse,
    ComparisonResponse,
    CycleRequest,
    HealthResponse,
    HistoryResponse,
    RescueRequest,
    RescueResponse,
    ScenarioRequest,
    ScenarioResponse,
    StrategiesResponse,
    StrategyRequest,
    ValidationResponse,
)
from ..services import (
    agent_cycle,
    assets,
    market_data,
    risk_engine,
    scenario_engine,
    strategy_engine,
)
from ..services.repository import get_repository

router = APIRouter()

API_VERSION = "0.1.0"


def _guard(exc: ValidationError) -> HTTPException:
    """Surface a domain validation error as a 422 the UI can render inline."""
    return HTTPException(status_code=422, detail=str(exc))


def _unpack(request: AnalyzeRequest):
    position = request.position.to_domain(owner_id=get_settings().demo_user_id)
    prefs = request.preferences.to_domain()
    return position, prefs


def _market(request: StrategyRequest, position: Position) -> MarketConditions:
    """Build market conditions for this request.

    The fallback is the configured ETH price, not the position's collateral
    price: gas is denominated in ETH regardless of what secures the loan.
    """
    return request.market.to_domain(fallback_price=get_settings().default_eth_price)


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=get_settings().app_name,
        version=API_VERSION,
        persistence=get_repository().backend_name,
        engines={
            "risk_engine": "ready",
            "scenario_engine": "ready",
            "strategy_engine": "ready",
            "blockchain": "simulated",
        },
    )


# ---------------------------------------------------------------------------
# POST /api/position/analyze
# ---------------------------------------------------------------------------

@router.post("/position/analyze", response_model=AnalyzeResponse)
def analyze_position(request: AnalyzeRequest) -> AnalyzeResponse:
    """Health Factor, risk band, liquidation price and headroom."""
    position, prefs = _unpack(request)
    try:
        assessment = risk_engine.assess(position, prefs)
    except ValidationError as exc:
        raise _guard(exc)

    if request.persist:
        get_repository().record_analysis(
            {
                "collateral_asset": position.collateral_asset,
                "collateral_amount": position.collateral_amount,
                "debt_asset": position.debt_asset,
                "debt_amount": position.debt_amount,
                "collateral_price": position.collateral_price,
                "liquidation_threshold": position.liquidation_threshold,
                "health_factor": assessment.health_factor,
                "risk_level": assessment.risk_level.value,
            }
        )

    return AnalyzeResponse(
        position=position.to_dict(),
        assessment=assessment.to_dict(),
        preferences=prefs.to_dict(),
    )


# ---------------------------------------------------------------------------
# POST /api/scenario/simulate
# ---------------------------------------------------------------------------

@router.post("/scenario/simulate", response_model=ScenarioResponse)
def simulate_scenarios(request: ScenarioRequest) -> ScenarioResponse:
    """Project the Health Factor across a ladder of price drops."""
    position, prefs = _unpack(request)
    try:
        scenarios = scenario_engine.simulate(position, request.price_drops, prefs)
    except ValidationError as exc:
        raise _guard(exc)

    breaking = scenario_engine.first_breaking_scenario(scenarios)

    if request.persist:
        get_repository().record_scenarios(
            {
                "base_price": position.collateral_price,
                "target_health_factor": prefs.target_health_factor,
                "results": [s.to_dict() for s in scenarios],
            }
        )

    return ScenarioResponse(
        position=position.to_dict(),
        scenarios=[s.to_dict() for s in scenarios],
        summary=scenario_engine.summarise(position, scenarios),
        first_breaking_scenario=breaking.to_dict() if breaking else None,
        thresholds={
            "liquidation": risk_engine.LIQUIDATION_HF,
            "intervention_trigger": prefs.trigger_health_factor,
            "target": prefs.target_health_factor,
        },
    )


# ---------------------------------------------------------------------------
# POST /api/strategies/generate
# ---------------------------------------------------------------------------

@router.post("/strategies/generate", response_model=StrategiesResponse)
def generate_strategies(request: StrategyRequest) -> StrategiesResponse:
    """Generate, cost, constraint-check and score every candidate rescue."""
    position, prefs = _unpack(request)
    market = _market(request, position)
    try:
        decision = strategy_engine.evaluate(position, prefs, market)
    except ValidationError as exc:
        raise _guard(exc)

    if request.persist and decision.strategies:
        get_repository().record_strategies(
            {
                "health_factor": decision.assessment.health_factor,
                "risk_level": decision.assessment.risk_level.value,
                "candidates": [s.to_dict() for s in decision.strategies],
                "selected_strategy_type": (
                    decision.selected_strategy.strategy_type.value
                    if decision.selected_strategy
                    else None
                ),
                "explanation": decision.explanation,
            }
        )

    return StrategiesResponse(
        position=position.to_dict(),
        assessment=decision.assessment.to_dict(),
        strategies=[s.to_dict() for s in decision.strategies],
        selected_strategy=(
            decision.selected_strategy.to_dict() if decision.selected_strategy else None
        ),
        explanation=decision.explanation,
        market=market.to_dict(),
    )


# ---------------------------------------------------------------------------
# POST /api/strategies/compare
# ---------------------------------------------------------------------------

@router.post("/strategies/compare", response_model=ComparisonResponse)
def compare_strategies(request: StrategyRequest) -> ComparisonResponse:
    """The comparison matrix behind the auto-selection.

    Same engine call as /strategies/generate, projected onto the columns the
    Strategy Comparison table renders. It exists so the UI does not have to
    know which fields are comparable.
    """
    position, prefs = _unpack(request)
    market = _market(request, position)
    try:
        decision = strategy_engine.evaluate(position, prefs, market)
    except ValidationError as exc:
        raise _guard(exc)

    rows = [
        {
            "strategy_type": s.strategy_type.value,
            "name": s.name,
            "description": s.description,
            "action_amount": s.action_amount,
            "resulting_health_factor": s.resulting_health_factor,
            "resulting_risk_level": s.resulting_risk_level.value,
            "required_capital": s.required_capital,
            "slippage_pct": s.slippage_pct,
            "gas_cost": s.gas_cost,
            "flash_loan_fee": s.flash_loan_fee,
            "total_cost": s.total_cost,
            "status": s.status.value,
            "score": s.score,
            "score_breakdown": s.score_breakdown,
            "selected": s.selected,
            "rejection_reason": s.rejection_reason,
        }
        for s in decision.strategies
    ]

    return ComparisonResponse(
        rows=rows,
        selected_strategy=(
            decision.selected_strategy.to_dict() if decision.selected_strategy else None
        ),
        explanation=decision.explanation,
        weights=strategy_engine.normalised_weights(prefs),
    )


# ---------------------------------------------------------------------------
# POST /api/rescue/validate
# ---------------------------------------------------------------------------

@router.post("/rescue/validate", response_model=ValidationResponse)
def validate_rescue(request: StrategyRequest) -> ValidationResponse:
    """Pre-flight check: would the agent execute right now, and if not, why?

    Runs the identical decision path as /rescue/autoexecute but stops short of
    applying anything. Advisory mode uses this to render the recommendation.
    """
    position, prefs = _unpack(request)
    market = _market(request, position)
    try:
        decision = strategy_engine.evaluate(position, prefs, market)
    except ValidationError as exc:
        raise _guard(exc)

    can_execute = decision.selected_strategy is not None and decision.execution_status in (
        ExecutionStatus.EXECUTED,
        ExecutionStatus.AWAITING_CONFIRMATION,
    )

    return ValidationResponse(
        can_execute=can_execute,
        reason=decision.explanation,
        execution_status=decision.execution_status.value,
        shield_state=decision.shield_state.value,
        economics=decision.economics,
        selected_strategy=(
            decision.selected_strategy.to_dict() if decision.selected_strategy else None
        ),
    )


# ---------------------------------------------------------------------------
# POST /api/rescue/autoexecute
# ---------------------------------------------------------------------------

def _simulated_transaction(decision: ProtectionDecision, position: Position) -> Dict[str, Any]:
    """Build the record of a rescue that was never broadcast anywhere.

    `simulated: True` and the `0xSIM...` hash prefix are deliberate: nothing
    downstream should ever be able to mistake this for a real receipt.
    """
    strategy = decision.selected_strategy
    return {
        "tx_hash": "0xSIM" + uuid.uuid4().hex[:58],
        "simulated": True,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "strategy_type": strategy.strategy_type.value if strategy else None,
        "strategy_name": strategy.name if strategy else None,
        "action_amount": strategy.action_amount if strategy else 0.0,
        "total_cost": strategy.total_cost if strategy else 0.0,
        "health_factor_before": decision.assessment.health_factor,
        "health_factor_after": (
            strategy.resulting_health_factor if strategy else decision.assessment.health_factor
        ),
        "collateral_price": position.collateral_price,
        "execution_status": decision.execution_status.value,
        "mode": None,  # filled by the caller
        "explanation": decision.explanation,
    }


@router.post("/rescue/autoexecute", response_model=RescueResponse)
def autoexecute_rescue(request: RescueRequest) -> RescueResponse:
    """Run one full agent cycle and, if warranted, execute the winner.

    SIMULATED EXECUTION. No transaction is signed or broadcast. The position is
    advanced in memory so the UI can show the post-rescue Health Factor, and a
    row is written to the rescue history.
    """
    position, prefs = _unpack(request)
    market = _market(request, position)
    try:
        decision = strategy_engine.evaluate(position, prefs, market)
    except ValidationError as exc:
        raise _guard(exc)

    assessment_before = decision.assessment.to_dict()
    strategies = [s.to_dict() for s in decision.strategies]

    # Advisory mode holds unless the user has confirmed this specific
    # recommendation. Autonomous mode never reaches this branch.
    holding_for_confirmation = (
        decision.execution_status is ExecutionStatus.AWAITING_CONFIRMATION
        and not request.confirm
    )

    if decision.selected_strategy is None or holding_for_confirmation:
        return RescueResponse(
            executed=False,
            execution_status=decision.execution_status.value,
            shield_state=decision.shield_state.value,
            explanation=decision.explanation,
            economics=decision.economics,
            selected_strategy=(
                decision.selected_strategy.to_dict()
                if decision.selected_strategy
                else None
            ),
            strategies=strategies,
            assessment_before=assessment_before,
        )

    # --- simulated execution ------------------------------------------------
    after = strategy_engine.apply_strategy(position, decision.selected_strategy)
    assessment_after = risk_engine.assess(after, prefs)

    transaction = _simulated_transaction(decision, position)
    transaction["mode"] = prefs.mode.value
    transaction["health_factor_after"] = assessment_after.health_factor
    transaction["execution_status"] = ExecutionStatus.EXECUTED.value

    stored = get_repository().record_rescue(transaction)

    return RescueResponse(
        executed=True,
        execution_status=ExecutionStatus.EXECUTED.value,
        shield_state=ShieldState.PROTECTED.value,
        explanation=decision.explanation,
        economics=decision.economics,
        selected_strategy=decision.selected_strategy.to_dict(),
        strategies=strategies,
        assessment_before=assessment_before,
        assessment_after=assessment_after.to_dict(),
        position_after=after.to_dict(),
        transaction=stored,
    )


# ---------------------------------------------------------------------------
# POST /api/demo/simulate-drop -- one full agent cycle, server-side
# ---------------------------------------------------------------------------

@router.post("/demo/simulate-drop")
def simulate_drop(request: CycleRequest) -> Dict[str, Any]:
    """Apply a price shock and run the whole cycle in one call.

    This is what the Demo Mode button hits. The client sends a percentage and
    receives every intermediate result: the shocked price, the revalued
    collateral, the recalculated Health Factor and risk level, the full
    candidate set with rejections, the auto-selected winner, the simulated
    execution, the final Health Factor, and an ordered trace carrying the
    shield state at each stage.

    Nothing about the run is computed in the browser.
    """
    position, prefs = _unpack(request)
    market = _market(request, position)
    try:
        result = agent_cycle.run_cycle(
            position,
            prefs,
            market,
            price_drop_pct=request.price_drop_pct,
            confirm=request.confirm,
        )
    except ValidationError as exc:
        raise _guard(exc)

    payload = result.to_dict()
    payload["decision_trace"]["mode"] = prefs.mode.value
    payload["preferences"] = prefs.to_dict()

    # --- step 17: persistence ----------------------------------------------
    repo = get_repository()
    if request.persist:
        repo.record_analysis(
            {
                "collateral_asset": result.position_shocked.collateral_asset,
                "collateral_amount": result.position_shocked.collateral_amount,
                "debt_asset": result.position_shocked.debt_asset,
                "debt_amount": result.position_shocked.debt_amount,
                "collateral_price": result.position_shocked.collateral_price,
                "liquidation_threshold": result.position_shocked.liquidation_threshold,
                "health_factor": result.assessment_shocked.health_factor,
                "risk_level": result.assessment_shocked.risk_level.value,
            }
        )
        repo.record_scenarios(
            {
                "base_price": result.price_after,
                "target_health_factor": prefs.target_health_factor,
                "results": [s.to_dict() for s in result.scenarios],
            }
        )
        if result.strategies:
            repo.record_strategies(
                {
                    "health_factor": result.assessment_shocked.health_factor,
                    "risk_level": result.assessment_shocked.risk_level.value,
                    "candidates": [s.to_dict() for s in result.strategies],
                    "selected_strategy_type": (
                        result.selected_strategy.strategy_type.value
                        if result.selected_strategy
                        else None
                    ),
                    "explanation": result.explanation,
                }
            )

    if result.executed:
        transaction = {
            "tx_hash": "0xSIM" + uuid.uuid4().hex[:58],
            "simulated": True,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "strategy_type": result.selected_strategy.strategy_type.value,
            "strategy_name": result.selected_strategy.name,
            "action_amount": result.selected_strategy.action_amount,
            "total_cost": result.selected_strategy.total_cost,
            "health_factor_before": result.assessment_shocked.health_factor,
            "health_factor_after": result.assessment_final.health_factor,
            "collateral_price": result.price_after,
            "execution_status": ExecutionStatus.EXECUTED.value,
            "mode": prefs.mode.value,
            "explanation": result.explanation,
        }
        payload["transaction"] = repo.record_rescue(transaction)

    return payload


# ---------------------------------------------------------------------------
# GET /api/history
# ---------------------------------------------------------------------------

@router.get("/history", response_model=HistoryResponse)
def history(limit: int = Query(default=50, ge=1, le=200)) -> HistoryResponse:
    repo = get_repository()
    return HistoryResponse(transactions=repo.list_rescues(limit), persistence=repo.backend_name)


# ---------------------------------------------------------------------------
# GET /api/market/eth-price -- the one endpoint that reads real-world data
# ---------------------------------------------------------------------------

@router.get("/market/eth-price")
def eth_price(refresh: bool = Query(default=False)) -> Dict[str, Any]:
    """Current ETH/USD spot price from a public market-data provider.

    This is the only REAL data in the system. Everything derived from it --
    the -5/-10/-15/-20% scenarios, the projected Health Factors, the
    strategies, the execution -- remains simulated.

    `refresh=true` bypasses the cache for a user-initiated refresh. It is still
    floored by a minimum interval so the public API cannot be hammered.

    Returns 503 when every provider fails. That is not fatal: the client falls
    back to a manual price and labels it as such.
    """
    try:
        price = market_data.fetch_price(force=refresh)
    except market_data.MarketDataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    payload = price.to_dict()
    payload["is_simulated"] = False
    payload["note"] = (
        "Live spot price. Scenario prices derived from it are simulated "
        "projections, not forecasts."
    )
    return payload


# ---------------------------------------------------------------------------
# GET /api/assets -- the collateral catalogue that populates the input form
# ---------------------------------------------------------------------------

@router.get("/assets")
def list_assets() -> Dict[str, Any]:
    """Supported collateral assets with their simulated market parameters.

    The form reads this rather than hard-coding a list, so adding an asset is a
    backend-only change and the risk parameters can never drift between the two
    sides.
    """
    return {
        "assets": assets.catalogue(),
        "default_collateral_asset": assets.DEFAULT_ASSET,
        "debt_assets": assets.DEBT_ASSETS,
        "default_debt_asset": assets.DEFAULT_DEBT_ASSET,
    }


# ---------------------------------------------------------------------------
# GET /api/defaults -- bootstrap payload for the frontend
# ---------------------------------------------------------------------------

@router.get("/defaults")
def defaults() -> Dict[str, Any]:
    """Seed position, preferences and market the UI starts from.

    Keeps the demo position defined in exactly one place (the domain layer)
    rather than duplicated in the frontend.
    """
    settings = get_settings()
    position = Position(collateral_price=settings.default_eth_price)
    prefs = RiskPreferences()
    market = MarketConditions(
        eth_price=settings.default_eth_price,
        gas_price_gwei=settings.default_gas_price_gwei,
        dex_liquidity_usd=settings.default_dex_liquidity_usd,
    )
    return {
        "position": position.to_dict(),
        "preferences": prefs.to_dict(),
        "market": market.to_dict(),
        "risk_bands": {
            "liquidatable": risk_engine.LIQUIDATION_HF,
            "danger": risk_engine.DANGER_HF,
            "warning": risk_engine.WARNING_HF,
        },
        "modes": [m.value for m in ProtectionMode],
    }

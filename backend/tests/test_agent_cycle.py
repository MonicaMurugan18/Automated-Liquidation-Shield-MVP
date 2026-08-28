"""Agent-cycle tests.

These exist to prove the dashboard is not a mockup: every number and every
status-bar state the UI shows during a demo run is produced here, by the
engines, from the position the client sent -- not assembled in the browser.
"""

import pytest

from app.models.domain import (
    CycleStage,
    ExecutionStatus,
    MarketConditions,
    Position,
    ProtectionMode,
    RiskLevel,
    RiskPreferences,
    ShieldState,
    ValidationError,
)
from app.services import agent_cycle, risk_engine

SEED = Position()
PREFS = RiskPreferences()
MARKET = MarketConditions(eth_price=3000.0)


def _states(result):
    return [step.shield_state.value for step in result.trace]


def _stages(result):
    return [step.stage.value for step in result.trace]


# ---------------------------------------------------------------------------
# The shock is applied server-side
# ---------------------------------------------------------------------------

def test_cycle_applies_the_price_drop_itself():
    """The client sends a percentage; the backend produces the price."""
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=10.0)

    assert result.price_before == 3000.0
    assert result.price_after == pytest.approx(2700.0)
    assert result.position_shocked.collateral_price == pytest.approx(2700.0)
    # Collateral units are untouched; only the valuation moves.
    assert result.position_shocked.collateral_amount == SEED.collateral_amount
    assert result.assessment_shocked.collateral_value == pytest.approx(9000.0, abs=0.01)


def test_cycle_recalculates_the_health_factor_from_the_shocked_position():
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=10.0)

    assert result.assessment_before.health_factor == pytest.approx(1.25, abs=1e-4)
    assert result.assessment_shocked.health_factor == pytest.approx(1.125, abs=1e-4)
    # Matches the documented formula, computed independently here.
    expected = risk_engine.health_factor(SEED.with_price(2700.0))
    assert result.assessment_shocked.health_factor == pytest.approx(expected, abs=1e-4)


def test_cycle_reclassifies_risk_after_the_shock():
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=10.0)
    assert result.assessment_before.risk_level is RiskLevel.WARNING
    assert result.assessment_shocked.risk_level is RiskLevel.DANGER


def test_gas_is_repriced_at_the_shocked_price():
    """Gas is denominated in the collateral asset, so a 10% drop makes the
    rescue 10% cheaper in USD. Costing it at the pre-shock price would be
    wrong by exactly the size of the move."""
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=10.0)
    assert result.market.eth_price == pytest.approx(2700.0)
    repay = next(s for s in result.strategies if s.strategy_type.value == "REPAY_DEBT")
    assert repay.gas_cost == pytest.approx(180_000 * 20 * 1e-9 * 2700.0, abs=0.01)


@pytest.mark.parametrize("drop", [0.0, 5.0, 10.0, 15.0, 20.0, 25.0])
def test_any_drop_size_is_honoured(drop):
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=drop)
    assert result.price_after == pytest.approx(3000.0 * (1 - drop / 100))


@pytest.mark.parametrize("drop", [-1.0, 100.0, 250.0])
def test_out_of_range_drops_are_rejected(drop):
    with pytest.raises(ValidationError):
        agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=drop)


def test_invalid_position_is_rejected():
    with pytest.raises(ValidationError):
        agent_cycle.run_cycle(Position(collateral_amount=-1.0), PREFS, MARKET)


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------

def test_autonomous_cycle_walks_armed_alert_protecting_protected_armed():
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=10.0)
    states = _states(result)

    assert states[0] == "ARMED"
    assert "ALERT" in states
    assert states.index("ALERT") < states.index("PROTECTING")
    assert states.index("PROTECTING") < states.index("PROTECTED")
    assert states[-1] == "ARMED"


def test_trace_stages_are_in_cycle_order():
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=10.0)
    assert _stages(result) == [
        CycleStage.MONITOR.value,
        CycleStage.SHOCK.value,
        CycleStage.ASSESS.value,
        CycleStage.GENERATE.value,
        CycleStage.SCORE.value,
        CycleStage.SELECT.value,
        CycleStage.EXECUTE.value,
        CycleStage.SETTLE.value,
        CycleStage.REARM.value,
    ]


def test_every_trace_step_carries_a_state_and_text():
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=10.0)
    for step in result.trace:
        assert step.label
        assert step.detail
        assert isinstance(step.shield_state, ShieldState)


def test_trace_quotes_the_recalculated_numbers():
    """The narration is built from engine output, so the text and the data
    can never drift apart."""
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=10.0)
    shock = next(s for s in result.trace if s.stage is CycleStage.SHOCK)
    assert "$3,000" in shock.detail and "$2,700" in shock.detail
    assert "$10,000" in shock.detail and "$9,000" in shock.detail

    settle = next(s for s in result.trace if s.stage is CycleStage.SETTLE)
    assert "1.125" in settle.detail and "1.500" in settle.detail


# ---------------------------------------------------------------------------
# Execution and the final Health Factor
# ---------------------------------------------------------------------------

def test_autonomous_mode_executes_without_confirmation():
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=10.0)
    assert result.executed is True
    assert result.execution_status is ExecutionStatus.EXECUTED
    assert result.selected_strategy is not None


def test_final_health_factor_is_recalculated_from_the_mutated_position():
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=10.0)

    assert result.assessment_final.health_factor >= PREFS.target_health_factor - 1e-6
    assert result.assessment_final.risk_level is RiskLevel.SAFE
    # Independently recompute from the returned position.
    recomputed = risk_engine.health_factor(result.position_final)
    assert result.assessment_final.health_factor == pytest.approx(recomputed, abs=1e-4)
    # The rescue actually changed the position.
    assert result.position_final.debt_amount < result.position_shocked.debt_amount


def test_advisory_mode_holds_and_does_not_mutate_the_position():
    advisory = RiskPreferences(mode=ProtectionMode.ADVISORY)
    result = agent_cycle.run_cycle(SEED, advisory, MARKET, price_drop_pct=10.0)

    assert result.executed is False
    assert result.execution_status is ExecutionStatus.AWAITING_CONFIRMATION
    assert result.selected_strategy is not None
    assert _states(result)[-1] == "ALERT"
    assert result.position_final.debt_amount == result.position_shocked.debt_amount
    assert CycleStage.EXECUTE.value not in _stages(result)


def test_advisory_mode_executes_once_confirmed():
    advisory = RiskPreferences(mode=ProtectionMode.ADVISORY)
    result = agent_cycle.run_cycle(
        SEED, advisory, MARKET, price_drop_pct=10.0, confirm=True
    )
    assert result.executed is True
    assert "PROTECTED" in _states(result)


def test_both_modes_select_the_same_strategy():
    auto = agent_cycle.run_cycle(SEED, RiskPreferences(), MARKET, price_drop_pct=10.0)
    advisory = agent_cycle.run_cycle(
        SEED, RiskPreferences(mode=ProtectionMode.ADVISORY), MARKET, price_drop_pct=10.0
    )
    assert (
        auto.selected_strategy.strategy_type is advisory.selected_strategy.strategy_type
    )


# ---------------------------------------------------------------------------
# Stand-down paths
# ---------------------------------------------------------------------------

def test_a_shock_that_does_not_breach_the_trigger_executes_nothing():
    """A 2% dip leaves HF 1.225: below the 1.50 target, above the 1.20 trigger.

    Options are offered, nothing runs, and the position is untouched."""
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=2.0)

    assert result.executed is False
    assert result.execution_status is ExecutionStatus.NO_ACTION_REQUIRED
    assert result.selected_strategy is None
    assert result.strategies, "below target, the user should still see choices"
    assert set(_states(result)) == {"ARMED"}
    assert result.assessment_final.health_factor == result.assessment_shocked.health_factor


def test_a_position_above_target_generates_nothing_at_all():
    safe = Position(debt_amount=1_000.0)          # HF 6.25
    result = agent_cycle.run_cycle(safe, PREFS, MARKET, price_drop_pct=2.0)

    assert result.strategies == []
    assert result.executed is False


def test_insufficient_liquidity_stands_the_agent_down():
    thin = MarketConditions(eth_price=3000.0, dex_liquidity_usd=5_000.0)
    broke = RiskPreferences(available_capital=0.0)
    result = agent_cycle.run_cycle(SEED, broke, thin, price_drop_pct=10.0)

    assert result.executed is False
    assert result.shield_state is ShieldState.SKIPPED
    assert _stages(result)[-1] == CycleStage.STAND_DOWN.value
    assert "insufficient liquidity" in result.explanation


def test_uneconomical_rescue_stands_the_agent_down():
    small = Position(collateral_amount=0.3, debt_amount=500.0, collateral_price=3000.0)
    pricey = MarketConditions(eth_price=3000.0, gas_price_gwei=60.0)
    result = agent_cycle.run_cycle(small, PREFS, pricey, price_drop_pct=10.0)

    assert result.executed is False
    assert result.execution_status is ExecutionStatus.SKIPPED_UNECONOMICAL
    assert result.economics["net_benefit"] < 0


# ---------------------------------------------------------------------------
# The Decision Trace panel payload
# ---------------------------------------------------------------------------

def test_decision_trace_summarises_the_run():
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=10.0)
    trace = result.decision_trace()

    assert trace["scenario"] == "ETH -10%"
    assert trace["risk_level"] == "DANGER"
    assert trace["strategies_generated"] == 5
    assert trace["strategies_rejected"] == 1
    assert trace["strategies_viable"] == 4
    assert trace["selected"] == "Repay debt from wallet"
    assert "selected" in trace["why_selected"]
    assert trace["execution"] == "SIMULATED SUCCESS"
    assert trace["final_health_factor"] == pytest.approx(1.5, abs=1e-4)
    assert trace["final_risk_level"] == "SAFE"


def test_decision_trace_counts_match_the_strategy_list():
    thin = MarketConditions(eth_price=3000.0, dex_liquidity_usd=60_000.0)
    result = agent_cycle.run_cycle(SEED, PREFS, thin, price_drop_pct=10.0)
    trace = result.decision_trace()

    assert trace["strategies_generated"] == len(result.strategies)
    assert trace["strategies_rejected"] == sum(
        1 for s in result.strategies if not s.is_executable
    )
    assert trace["strategies_viable"] + trace["strategies_rejected"] == (
        trace["strategies_generated"]
    )


def test_decision_trace_reports_advisory_hold():
    advisory = RiskPreferences(mode=ProtectionMode.ADVISORY)
    trace = agent_cycle.run_cycle(SEED, advisory, MARKET, price_drop_pct=10.0).decision_trace()
    assert trace["execution"] == "AWAITING CONFIRMATION"


def test_decision_trace_reports_a_stand_down():
    small = Position(collateral_amount=0.3, debt_amount=500.0, collateral_price=3000.0)
    pricey = MarketConditions(eth_price=3000.0, gas_price_gwei=60.0)
    trace = agent_cycle.run_cycle(small, PREFS, pricey, price_drop_pct=10.0).decision_trace()
    assert trace["execution"] == "STOOD DOWN"
    assert trace["selected"] is None


def test_result_serialises_to_json_safe_primitives():
    import json

    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=10.0)
    payload = json.dumps(result.to_dict())
    assert '"simulated": true' in payload
    assert "PROTECTED" in payload


# ---------------------------------------------------------------------------
# Presentation fields the UI reads (still backend-computed)
# ---------------------------------------------------------------------------

def test_scores_are_also_reported_out_of_100():
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=10.0)
    for s in result.strategies:
        d = s.to_dict()
        assert d["score_100"] == round(s.score * 100)
        assert 0 <= d["score_100"] <= 100
        if not s.is_executable:
            assert d["score_100"] == 0


def test_safety_level_agrees_with_the_safety_sub_score():
    """The label can never contradict the ranking, because both read the same
    number."""
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=10.0)
    for s in result.strategies:
        d = s.to_dict()
        if not s.is_executable:
            assert d["safety_level"] is None
            continue
        safety = s.score_breakdown["safety"]
        expected = "HIGH" if safety >= 0.90 else "MEDIUM" if safety >= 0.75 else "LOW"
        assert d["safety_level"] == expected


def test_a_single_transaction_rescue_is_rated_higher_safety_than_a_swap():
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=10.0)
    by_type = {s.strategy_type.value: s for s in result.strategies}
    assert by_type["REPAY_DEBT"].safety_level == "HIGH"
    assert by_type["COLLATERAL_SWAP"].safety_level in ("MEDIUM", "LOW")


def test_decision_trace_reports_the_risk_transition():
    trace = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=10.0).decision_trace()
    assert trace["risk_level_before"] == "WARNING"
    assert trace["risk_level"] == "DANGER"
    assert trace["final_risk_level"] == "SAFE"


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"price_drop_pct": 10.0}, "PROTECTED"),
        ({"price_drop_pct": 2.0}, "MONITORING"),
    ],
)
def test_decision_trace_final_status(kwargs, expected):
    trace = agent_cycle.run_cycle(SEED, PREFS, MARKET, **kwargs).decision_trace()
    assert trace["final_status"] == expected


def test_final_status_reports_a_stand_down():
    small = Position(collateral_amount=0.3, debt_amount=500.0, collateral_price=3000.0)
    pricey = MarketConditions(eth_price=3000.0, gas_price_gwei=60.0)
    trace = agent_cycle.run_cycle(small, PREFS, pricey, price_drop_pct=10.0).decision_trace()
    assert trace["final_status"] == "STOOD DOWN"


def test_final_status_reports_an_advisory_hold():
    advisory = RiskPreferences(mode=ProtectionMode.ADVISORY)
    trace = agent_cycle.run_cycle(SEED, advisory, MARKET, price_drop_pct=10.0).decision_trace()
    assert trace["final_status"] == "AWAITING CONFIRMATION"


# ---------------------------------------------------------------------------
# Scenario ladder: intervention flag
# ---------------------------------------------------------------------------

def test_scenarios_flag_which_rungs_need_intervention():
    """The flag tracks the user's trigger, not the liquidation line -- the
    agent acts before the position is underwater."""
    result = agent_cycle.run_cycle(SEED, PREFS, MARKET, price_drop_pct=0.0)
    flags = {s.label: s.requires_intervention for s in result.scenarios}

    # HF 1.250 at spot is above the 1.20 trigger; every rung below is not.
    assert flags["Current"] is False
    assert flags["-5%"] is True
    assert flags["-20%"] is True
    # The -20% rung is exactly HF 1.0, the liquidation threshold.
    assert all(not s.liquidatable for s in result.scenarios[:-1])
    assert result.scenarios[-1].liquidatable is True


def test_a_safe_position_needs_no_intervention_anywhere_on_the_ladder():
    safe = Position(debt_amount=1_000.0)
    result = agent_cycle.run_cycle(safe, PREFS, MARKET, price_drop_pct=0.0)
    assert all(s.requires_intervention is False for s in result.scenarios)


def test_the_trigger_setting_moves_the_intervention_flag():
    strict = RiskPreferences(target_health_factor=2.0, trigger_health_factor=1.9)
    result = agent_cycle.run_cycle(SEED, strict, MARKET, price_drop_pct=0.0)
    assert all(s.requires_intervention is True for s in result.scenarios)

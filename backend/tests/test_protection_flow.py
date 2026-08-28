"""The demo ladder, end to end.

Pins the behaviour the dashboard depends on:

    1.264  WARNING  ->  options offered, nothing executed
    1.201  WARNING  ->  options offered, nothing executed
    1.138  DANGER   ->  intervention required, best viable strategy executed
    1.074  DANGER   ->  intervention required
    1.011  DANGER   ->  intervention required

The bug these tests exist to prevent: generation was gated on the ACTION
trigger rather than on being below target, so a position at HF 1.264 reported
"0 strategies generated" while its own scenario ladder showed the trigger being
crossed two rungs down.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.domain import (
    ExecutionStatus,
    MarketConditions,
    Position,
    RiskLevel,
    RiskPreferences,
)
from app.services import risk_engine, scenario_engine, strategy_engine
from app.services.repository import reset_repository

client = TestClient(app)

# The live demo position: ~4.9987 ETH worth ~$12,134 against $6,000 of debt.
DEMO_PRICE = 12_134.0 / 4.9987
DEMO = Position(collateral_amount=4.9987, collateral_price=DEMO_PRICE, debt_amount=6_000.0)
PREFS = RiskPreferences()                    # target 1.50, trigger 1.20, $4,000
MARKET = MarketConditions(eth_price=DEMO_PRICE)


@pytest.fixture(autouse=True)
def _clean_repository():
    reset_repository()
    yield
    reset_repository()


def _decide(position, prefs=PREFS, market=None):
    return strategy_engine.evaluate(
        position, prefs, market or MarketConditions(eth_price=position.collateral_price)
    )


# ---------------------------------------------------------------------------
# The ladder itself is computed, not asserted from constants
# ---------------------------------------------------------------------------

def test_the_demo_position_matches_the_dashboard():
    assessment = risk_engine.assess(DEMO, PREFS)
    assert assessment.collateral_value == pytest.approx(12_134.0, abs=1.0)
    assert assessment.health_factor == pytest.approx(1.264, abs=0.001)
    assert assessment.risk_level is RiskLevel.WARNING
    assert assessment.requires_action is False


def test_the_scenario_ladder_is_derived_from_the_position():
    """Every rung recomputed from the entered position -- no fixed table."""
    ladder = scenario_engine.simulate(DEMO, prefs=PREFS)
    got = {s.label: (round(s.health_factor, 3), s.risk_level.value) for s in ladder}

    assert got["Current"] == (1.264, "WARNING")
    assert got["-5%"] == (1.201, "WARNING")
    assert got["-10%"] == (1.138, "DANGER")
    assert got["-15%"] == (1.074, "DANGER")
    assert got["-20%"] == (1.011, "DANGER")


def test_the_ladder_flags_exactly_the_rungs_below_the_trigger():
    ladder = {s.label: s for s in scenario_engine.simulate(DEMO, prefs=PREFS)}
    assert ladder["Current"].requires_intervention is False
    assert ladder["-5%"].requires_intervention is False       # 1.201 > 1.20
    for label in ("-10%", "-15%", "-20%"):
        assert ladder[label].requires_intervention is True, label


def test_a_ladder_that_crosses_the_trigger_is_not_contradicted_by_zero_options():
    """The inconsistency that started this: the ladder said the trigger gets
    crossed, the dashboard said there was nothing to do about it."""
    ladder = scenario_engine.simulate(DEMO, prefs=PREFS)
    assert any(s.requires_intervention for s in ladder)

    decision = _decide(DEMO)
    assert decision.strategies, "options must exist when the ladder crosses the trigger"


# ---------------------------------------------------------------------------
# 1.264 and 1.201 -- warning, monitoring, no execution
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("drop_pct", [0.0, 5.0])
def test_warning_rungs_offer_options_but_execute_nothing(drop_pct):
    position = DEMO.with_price(DEMO_PRICE * (1 - drop_pct / 100))
    decision = _decide(position)

    assert decision.assessment.risk_level is RiskLevel.WARNING
    assert decision.execution_status is ExecutionStatus.NO_ACTION_REQUIRED
    assert decision.selected_strategy is None
    assert not any(s.selected for s in decision.strategies)
    assert any(s.is_executable for s in decision.strategies)


def test_the_warning_explanation_mentions_the_available_options():
    decision = _decide(DEMO)
    assert "protection option" in decision.explanation


def test_at_least_one_option_is_viable_within_the_available_capital():
    """Requirement: a realistic strategy must be viable when mathematically
    possible with the $4,000 the user has."""
    decision = _decide(DEMO)
    viable = [s for s in decision.strategies if s.is_executable]

    assert viable, "a $944 repayment against $4,000 of capital must be viable"
    affordable = [s for s in viable if s.required_capital <= PREFS.available_capital]
    assert affordable
    for s in viable:
        assert s.resulting_health_factor >= PREFS.target_health_factor - 1e-6


def test_the_repayment_is_sized_from_the_position_not_a_constant():
    decision = _decide(DEMO)
    repay = next(
        s for s in decision.strategies if s.strategy_type.value == "REPAY_DEBT"
    )
    expected = risk_engine.minimum_repayment_to_target(DEMO, PREFS.target_health_factor)
    assert repay.action_amount == pytest.approx(expected, abs=0.01)
    assert repay.action_amount == pytest.approx(944.17, abs=0.5)


# ---------------------------------------------------------------------------
# 1.138 / 1.074 / 1.011 -- intervention required
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("drop_pct,expected_hf", [(10.0, 1.138), (15.0, 1.074), (20.0, 1.011)])
def test_rungs_below_the_trigger_require_intervention(drop_pct, expected_hf):
    position = DEMO.with_price(DEMO_PRICE * (1 - drop_pct / 100))
    decision = _decide(position)

    assert decision.assessment.health_factor == pytest.approx(expected_hf, abs=0.001)
    assert decision.assessment.risk_level is RiskLevel.DANGER
    assert decision.assessment.requires_action is True
    assert decision.selected_strategy is not None
    assert decision.execution_status is ExecutionStatus.EXECUTED


def test_the_selected_strategy_restores_the_target_at_every_risky_rung():
    for drop_pct in (10.0, 15.0, 20.0):
        position = DEMO.with_price(DEMO_PRICE * (1 - drop_pct / 100))
        decision = _decide(position)
        after = strategy_engine.apply_strategy(position, decision.selected_strategy)
        assert risk_engine.health_factor(after) >= PREFS.target_health_factor - 1e-6


def test_exactly_one_strategy_is_selected_when_acting():
    position = DEMO.with_price(DEMO_PRICE * 0.90)
    decision = _decide(position)
    assert sum(1 for s in decision.strategies if s.selected) == 1


# ---------------------------------------------------------------------------
# Capital constraints
# ---------------------------------------------------------------------------

def test_insufficient_capital_rejects_the_funded_routes_with_a_reason():
    broke = RiskPreferences(available_capital=100.0)
    decision = _decide(DEMO.with_price(DEMO_PRICE * 0.90), broke)

    funded = [
        s for s in decision.strategies
        if s.strategy_type.value in ("REPAY_DEBT", "ADD_COLLATERAL")
    ]
    assert funded
    for s in funded:
        assert s.status.value == "REJECTED_INSUFFICIENT_CAPITAL"
        assert "available" in s.rejection_reason


def test_self_funded_routes_survive_with_no_capital_at_all():
    broke = RiskPreferences(available_capital=0.0)
    decision = _decide(DEMO.with_price(DEMO_PRICE * 0.90), broke)

    assert decision.selected_strategy is not None
    assert decision.selected_strategy.required_capital == 0.0


def test_more_capital_changes_which_strategy_wins():
    """Scoring is dynamic: the answer depends on what the user actually has."""
    risky = DEMO.with_price(DEMO_PRICE * 0.90)
    poor = _decide(risky, RiskPreferences(available_capital=0.0))
    rich = _decide(risky, RiskPreferences(available_capital=50_000.0))
    assert poor.selected_strategy.strategy_type is not rich.selected_strategy.strategy_type


# ---------------------------------------------------------------------------
# The comparison must explain acceptance as well as rejection
# ---------------------------------------------------------------------------

def test_every_candidate_carries_a_reason_either_way():
    decision = _decide(DEMO.with_price(DEMO_PRICE * 0.90))
    for s in decision.strategies:
        if s.is_executable:
            assert s.acceptance_reason, f"{s.name} was accepted with no reason given"
            assert s.acceptance_reason.startswith("Accepted:")
        else:
            assert s.rejection_reason, f"{s.name} was rejected with no reason given"


def test_the_acceptance_reason_quotes_the_binding_numbers():
    decision = _decide(DEMO.with_price(DEMO_PRICE * 0.90))
    repay = next(
        s for s in decision.strategies
        if s.strategy_type.value == "REPAY_DEBT" and s.is_executable
    )
    reason = repay.acceptance_reason
    assert f"{repay.resulting_health_factor:.3f}" in reason
    assert f"{PREFS.available_capital:,.0f}" in reason


def test_reasons_survive_serialisation_to_the_comparison_endpoint():
    body = client.post(
        "/api/strategies/compare",
        json={
            "position": {
                "collateral_amount": 4.9987,
                "collateral_price": DEMO_PRICE * 0.90,
                "debt_amount": 6000,
            }
        },
    ).json()
    for row in body["rows"]:
        assert row["acceptance_reason"] or row["rejection_reason"], row["name"]


# ---------------------------------------------------------------------------
# The whole flow over HTTP
# ---------------------------------------------------------------------------

def _cycle(drop_pct):
    return client.post(
        "/api/demo/simulate-drop",
        json={
            "price_drop_pct": drop_pct,
            "position": {
                "collateral_amount": 4.9987,
                "collateral_price": DEMO_PRICE,
                "debt_amount": 6000,
            },
        },
    ).json()


def test_the_full_demo_flow_over_http():
    warning = _cycle(0)
    assert warning["decision_trace"]["risk_level"] == "WARNING"
    assert warning["executed"] is False
    assert warning["strategies"], "0 strategies at WARNING was the reported bug"
    assert warning["selected_strategy"] is None

    danger = _cycle(10)
    assert danger["decision_trace"]["risk_level"] == "DANGER"
    assert danger["executed"] is True
    assert danger["decision_trace"]["selected"]
    assert danger["decision_trace"]["final_status"] == "PROTECTED"


def test_the_validate_endpoint_agrees_with_the_cycle():
    body = client.post(
        "/api/rescue/validate",
        json={
            "position": {
                "collateral_amount": 4.9987,
                "collateral_price": DEMO_PRICE,
                "debt_amount": 6000,
            }
        },
    ).json()

    assert body["can_execute"] is False          # WARNING: nothing runs
    assert body["execution_status"] == "NO_ACTION_REQUIRED"
    assert body["guidance"]["tone"] == "warn"
    assert body["future_risk"], "the ladder travels with the verdict"

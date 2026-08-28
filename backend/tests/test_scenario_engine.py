"""Scenario engine unit tests: the price-drop ladder and its projections."""

import pytest

from app.models.domain import Position, RiskLevel, RiskPreferences, ValidationError
from app.services import risk_engine, scenario_engine

SEED = Position()


def test_default_ladder_has_five_rungs():
    scenarios = scenario_engine.simulate(SEED)
    assert [s.label for s in scenarios] == ["Current", "-5%", "-10%", "-15%", "-20%"]


def test_prices_step_down_correctly():
    scenarios = scenario_engine.simulate(SEED)
    assert [s.new_price for s in scenarios] == [3000.0, 2850.0, 2700.0, 2550.0, 2400.0]


def test_collateral_is_revalued_at_each_rung():
    scenarios = scenario_engine.simulate(SEED)
    assert scenarios[0].new_collateral_value == pytest.approx(10_000.0, abs=0.01)
    assert scenarios[2].new_collateral_value == pytest.approx(9_000.0, abs=0.01)
    assert scenarios[4].new_collateral_value == pytest.approx(8_000.0, abs=0.01)


def test_health_factor_trajectory():
    scenarios = scenario_engine.simulate(SEED)
    expected = [1.25, 1.1875, 1.125, 1.0625, 1.0]
    assert [s.health_factor for s in scenarios] == pytest.approx(expected, abs=1e-4)


def test_risk_escalates_down_the_ladder():
    levels = [s.risk_level for s in scenario_engine.simulate(SEED)]
    assert levels[0] is RiskLevel.WARNING
    assert levels[2] is RiskLevel.DANGER
    assert levels[4] is RiskLevel.LIQUIDATABLE


def test_health_factor_is_monotonically_decreasing():
    hfs = [s.health_factor for s in scenario_engine.simulate(SEED)]
    assert all(a >= b for a, b in zip(hfs, hfs[1:]))


def test_required_repayment_grows_as_price_falls():
    repayments = [s.required_repayment for s in scenario_engine.simulate(SEED)]
    assert all(a <= b for a, b in zip(repayments, repayments[1:]))
    # -10% rung matches the hand-checked figure from the risk engine tests.
    assert repayments[2] == pytest.approx(1250.0, abs=0.01)


def test_seed_position_reaches_liquidation_at_the_default_ladder_floor():
    scenarios = scenario_engine.simulate(SEED)
    breaking = scenario_engine.first_breaking_scenario(scenarios)
    assert breaking is not None
    assert breaking.label == "-20%"
    assert "liquidates" in scenario_engine.summarise(SEED, scenarios)


def test_a_deeper_ladder_finds_the_breaking_point():
    scenarios = scenario_engine.simulate(SEED, drops=[0, 10, 20, 25, 30])
    breaking = scenario_engine.first_breaking_scenario(scenarios)
    assert breaking is not None
    assert breaking.label == "-20%"
    assert breaking.liquidatable is True


def test_safe_position_reports_no_intervention_needed():
    """Edge case 1 / 6 seen through the scenario lens."""
    safe = Position(debt_amount=1_000.0)  # HF 6.25
    scenarios = scenario_engine.simulate(safe)
    assert all(s.required_repayment == 0.0 for s in scenarios)
    assert all("None required" in s.intervention_summary for s in scenarios)


def test_zero_debt_position_needs_nothing_at_any_price():
    scenarios = scenario_engine.simulate(Position(debt_amount=0.0))
    assert all(s.liquidatable is False for s in scenarios)
    assert all("No debt outstanding" in s.intervention_summary for s in scenarios)


def test_custom_target_changes_the_required_repayment():
    conservative = RiskPreferences(target_health_factor=2.0)
    default = scenario_engine.simulate_scenario(SEED, 10.0)
    strict = scenario_engine.simulate_scenario(SEED, 10.0, conservative)
    assert strict.required_repayment > default.required_repayment


# ---------------------------------------------------------------------------
# Edge case 8: invalid input
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("drop", [-5.0, 100.0, 150.0])
def test_out_of_range_price_drops_are_rejected(drop):
    with pytest.raises(ValidationError):
        scenario_engine.simulate_scenario(SEED, drop)


def test_empty_ladder_is_rejected():
    with pytest.raises(ValidationError):
        scenario_engine.simulate(SEED, drops=[])


def test_negative_collateral_is_rejected():
    with pytest.raises(ValidationError):
        scenario_engine.simulate(Position(collateral_amount=-1.0))

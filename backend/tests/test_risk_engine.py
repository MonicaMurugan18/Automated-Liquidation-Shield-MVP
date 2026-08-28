"""Risk engine unit tests: Health Factor maths, classification, sizing."""

import math

import pytest

from app.models.domain import Position, RiskLevel, RiskPreferences, ValidationError
from app.services import risk_engine

SEED = Position()  # $10,000 collateral, $5,000 debt, LT 0.625, ETH $3,000


# ---------------------------------------------------------------------------
# Health Factor
# ---------------------------------------------------------------------------

def test_seed_position_reports_health_factor_1_25():
    assert risk_engine.health_factor(SEED) == pytest.approx(1.25, abs=1e-6)


def test_health_factor_formula_matches_definition():
    hf = risk_engine.health_factor(SEED)
    expected = (SEED.collateral_value * SEED.liquidation_threshold) / SEED.debt_value
    assert hf == pytest.approx(expected)


def test_health_factor_falls_proportionally_with_price():
    dropped = SEED.with_price(SEED.collateral_price * 0.90)
    assert risk_engine.health_factor(dropped) == pytest.approx(1.125, abs=1e-6)


def test_zero_debt_reports_sentinel_infinite_health_factor():
    """Edge case 6 tail: no debt means no liquidation risk at any price."""
    no_debt = Position(debt_amount=0.0)
    assert risk_engine.health_factor(no_debt) == risk_engine.INFINITE_HF
    assert math.isfinite(risk_engine.health_factor(no_debt))


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "hf,expected",
    [
        (0.85, RiskLevel.LIQUIDATABLE),
        (0.999, RiskLevel.LIQUIDATABLE),
        (1.0, RiskLevel.LIQUIDATABLE),
        (1.125, RiskLevel.DANGER),
        (1.199, RiskLevel.DANGER),
        (1.20, RiskLevel.WARNING),
        (1.25, RiskLevel.WARNING),
        (1.499, RiskLevel.WARNING),
        (1.50, RiskLevel.SAFE),
        (3.0, RiskLevel.SAFE),
    ],
)
def test_risk_bands(hf, expected):
    assert risk_engine.classify_risk(hf) == expected


def test_seed_position_is_warning():
    """Matches the dashboard spec: HF 1.25 -> WARNING."""
    assert risk_engine.assess(SEED).risk_level is RiskLevel.WARNING


# ---------------------------------------------------------------------------
# Liquidation price
# ---------------------------------------------------------------------------

def test_liquidation_price_is_2400_for_seed_position():
    # 5000 / (3.3333 ETH * 0.625) = $2,400 -> exactly 20% below $3,000.
    assert risk_engine.liquidation_price(SEED) == pytest.approx(2400.0, abs=0.01)


def test_price_drop_to_liquidation_is_20_percent():
    assert risk_engine.price_drop_to_liquidation_pct(SEED) == pytest.approx(20.0, abs=0.01)


def test_health_factor_is_exactly_one_at_the_liquidation_price():
    at_liq = SEED.with_price(risk_engine.liquidation_price(SEED))
    assert risk_engine.health_factor(at_liq) == pytest.approx(1.0, abs=1e-9)


def test_liquidation_price_is_zero_without_debt():
    assert risk_engine.liquidation_price(Position(debt_amount=0.0)) == 0.0


# ---------------------------------------------------------------------------
# Minimum repayment (documented formula, not a placeholder)
# ---------------------------------------------------------------------------

def test_minimum_repayment_restores_the_target_exactly():
    dropped = SEED.with_price(2700.0)  # -10%, HF 1.125
    repayment = risk_engine.minimum_repayment_to_target(dropped, 1.5)
    assert repayment == pytest.approx(1250.0, abs=0.01)

    after = risk_engine.apply_repayment(dropped, repayment)
    assert risk_engine.health_factor(after) == pytest.approx(1.5, abs=1e-9)


def test_minimum_repayment_is_zero_when_already_safe():
    """Edge case 6: minimum repayment is zero -> no repayment required."""
    safe = Position(debt_amount=2_000.0)  # HF = 10000*0.625/2000 = 3.125
    assert risk_engine.minimum_repayment_to_target(safe, 1.5) == 0.0


def test_minimum_repayment_is_zero_without_debt():
    assert risk_engine.minimum_repayment_to_target(Position(debt_amount=0.0), 1.5) == 0.0


def test_minimum_repayment_never_exceeds_outstanding_debt():
    wrecked = SEED.with_price(300.0)  # collateral almost worthless
    repayment = risk_engine.minimum_repayment_to_target(wrecked, 1.5)
    assert repayment <= wrecked.debt_value


def test_minimum_repayment_rejects_non_positive_target():
    with pytest.raises(ValidationError):
        risk_engine.minimum_repayment_to_target(SEED, 0.0)


# ---------------------------------------------------------------------------
# Collateral top-up
# ---------------------------------------------------------------------------

def test_minimum_collateral_topup_restores_the_target_exactly():
    dropped = SEED.with_price(2700.0)
    topup = risk_engine.minimum_collateral_topup_to_target(dropped, 1.5)
    assert topup == pytest.approx(3000.0, abs=0.01)

    after = risk_engine.apply_collateral_topup(dropped, topup)
    assert risk_engine.health_factor(after) == pytest.approx(1.5, abs=1e-9)


def test_minimum_collateral_topup_is_zero_when_already_safe():
    assert risk_engine.minimum_collateral_topup_to_target(
        Position(debt_amount=2_000.0), 1.5
    ) == 0.0


# ---------------------------------------------------------------------------
# Self-funded (collateral swap) repayment
# ---------------------------------------------------------------------------

def test_collateral_swap_repayment_restores_the_target():
    dropped = SEED.with_price(2700.0)
    repayment = risk_engine.collateral_swap_repayment(dropped, 1.5, slippage_pct=0.15)
    assert repayment is not None

    after = risk_engine.apply_collateral_swap(dropped, repayment, 0.15)
    assert risk_engine.health_factor(after) == pytest.approx(1.5, abs=1e-6)


def test_self_funded_rescue_needs_more_repayment_than_an_external_one():
    """Selling collateral shrinks both sides of the ratio, so it is less
    capital-efficient. This ordering is a structural property, not a tuning
    artefact -- if it ever inverts, the maths is wrong."""
    dropped = SEED.with_price(2700.0)
    external = risk_engine.minimum_repayment_to_target(dropped, 1.5)
    self_funded = risk_engine.collateral_swap_repayment(dropped, 1.5, 0.15)
    assert self_funded > external


def test_collateral_swap_returns_none_when_target_unreachable():
    """Edge case 7 source: deleveraging cannot always reach an arbitrary target."""
    dropped = SEED.with_price(1500.0)  # HF 0.625, deeply underwater
    assert risk_engine.collateral_swap_repayment(dropped, 3.0, 0.15) is None


def test_collateral_swap_returns_zero_when_already_at_target():
    safe = Position(debt_amount=2_000.0)
    assert risk_engine.collateral_swap_repayment(safe, 1.5, 0.15) == 0.0


# ---------------------------------------------------------------------------
# Potential liquidation loss
# ---------------------------------------------------------------------------

def test_potential_liquidation_loss_is_close_factor_times_bonus():
    # 5000 * 0.5 * 0.05 = 125
    assert risk_engine.potential_liquidation_loss(SEED) == pytest.approx(125.0)


# ---------------------------------------------------------------------------
# Edge case 8: invalid / negative input
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kwargs",
    [
        {"collateral_amount": -1.0},
        {"debt_amount": -500.0},
        {"collateral_price": 0.0},
        {"collateral_price": -3000.0},
        {"liquidation_threshold": 0.0},
        {"liquidation_threshold": 1.5},
        {"liquidation_bonus": -0.1},
        {"close_factor": 0.0},
        {"close_factor": 1.4},
    ],
)
def test_invalid_positions_are_rejected(kwargs):
    with pytest.raises(ValidationError):
        risk_engine.health_factor(Position(**kwargs))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target_health_factor": 1.0},
        {"target_health_factor": 0.5},
        {"trigger_health_factor": 0.9},
        {"trigger_health_factor": 1.8},  # trigger above target
        {"max_slippage_pct": 0.0},
        {"available_capital": -1.0},
    ],
)
def test_invalid_preferences_are_rejected(kwargs):
    with pytest.raises(ValidationError):
        risk_engine.validate_preferences(RiskPreferences(**kwargs))


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------

def test_assessment_does_not_require_action_at_the_seed_position():
    """Edge case 1: HF 1.25 is above the 1.20 trigger -- watch, do not act."""
    assessment = risk_engine.assess(SEED)
    assert assessment.requires_action is False
    assert "No rescue required" in assessment.message or "Monitoring" in assessment.message


def test_assessment_requires_action_after_a_ten_percent_drop():
    """Edge case 2: HF 1.125 is at or below the trigger -- act."""
    assessment = risk_engine.assess(SEED.with_price(2700.0))
    assert assessment.requires_action is True
    assert assessment.risk_level is RiskLevel.DANGER


def test_assessment_never_requires_action_without_debt():
    assert risk_engine.assess(Position(debt_amount=0.0)).requires_action is False


def test_safety_buffer_is_zero_at_the_liquidation_line():
    at_liq = SEED.with_price(risk_engine.liquidation_price(SEED))
    assert risk_engine.assess(at_liq).safety_buffer_pct == pytest.approx(0.0, abs=1e-6)

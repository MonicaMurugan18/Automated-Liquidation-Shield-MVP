"""Risk engine: Health Factor maths, risk classification and the repayment
formulas that every downstream engine depends on.

SIMPLIFIED SIMULATION -- READ THIS FIRST
========================================
The formulas below are a deliberately simplified model of an Aave-v3-style
lending market. They are correct for the single-collateral / single-debt case
with a stablecoin debt asset, which is what this MVP simulates. They are NOT a
drop-in replacement for a live protocol read. Known simplifications:

  * One collateral asset and one debt asset. Real accounts hold baskets, and
    the real Health Factor sums each reserve weighted by its own liquidation
    threshold.
  * The debt asset is assumed to be worth exactly $1 (stablecoin). A volatile
    debt asset would need its own price feed in the denominator.
  * Accrued interest between blocks is ignored; balances are point-in-time.
  * Oracle price == spot price. Real protocols use a lagging oracle, so the
    protocol's view of your HF can differ from the DEX price for a few blocks.

Every function that encodes protocol behaviour is isolated here so it can be
swapped for a real `getUserAccountData` call without touching the scenario or
strategy engines. See `docs` note in README, section "What is simulated".
"""

from __future__ import annotations

import math
from typing import Optional

from ..models.domain import (
    HealthAssessment,
    Position,
    RiskLevel,
    RiskPreferences,
    ValidationError,
)

# A position with zero debt has a mathematically infinite Health Factor.
# JSON cannot carry Infinity, so the engine reports this sentinel instead and
# the UI renders it as the "no debt" state.
INFINITE_HF = 999.0

# Risk bands, in Health Factor terms.
#   HF <  1.00  -> LIQUIDATABLE  (a liquidator can act right now)
#   HF <  1.20  -> DANGER        (one bad candle away)
#   HF <  1.50  -> WARNING       (below the default safety target)
#   HF >= 1.50  -> SAFE
LIQUIDATION_HF = 1.0
DANGER_HF = 1.20
WARNING_HF = 1.50


# ---------------------------------------------------------------------------
# Validation (edge case 8)
# ---------------------------------------------------------------------------

def validate_position(position: Position) -> None:
    """Reject structurally impossible positions.

    Raises ValidationError with a message intended for direct display in the
    UI. Called at the top of every public entry point so a bad payload fails
    fast and loudly rather than producing a plausible-looking wrong number.
    """
    if position.collateral_amount < 0:
        raise ValidationError("Collateral amount cannot be negative.")
    if position.debt_amount < 0:
        raise ValidationError("Debt amount cannot be negative.")
    if position.collateral_price <= 0:
        raise ValidationError("Collateral price must be greater than zero.")
    if not 0 < position.liquidation_threshold <= 1:
        raise ValidationError(
            "Liquidation threshold must be between 0 and 1 (exclusive of 0)."
        )
    if not 0 <= position.liquidation_bonus < 1:
        raise ValidationError("Liquidation bonus must be between 0 and 1.")
    if not 0 < position.close_factor <= 1:
        raise ValidationError("Close factor must be between 0 and 1.")
    if math.isnan(position.collateral_amount) or math.isnan(position.debt_amount):
        raise ValidationError("Position values must be finite numbers.")
    if position.collateral_amount <= 0 and position.debt_amount > 0:
        raise ValidationError(
            "A position with outstanding debt must have collateral securing it. "
            "Enter a collateral amount greater than zero."
        )


def validate_preferences(prefs: RiskPreferences) -> None:
    if prefs.target_health_factor <= LIQUIDATION_HF:
        raise ValidationError(
            "Target Health Factor must be greater than 1.0 -- a target at or "
            "below the liquidation threshold offers no protection."
        )
    if prefs.trigger_health_factor <= LIQUIDATION_HF:
        raise ValidationError("Trigger Health Factor must be greater than 1.0.")
    if prefs.trigger_health_factor > prefs.target_health_factor:
        raise ValidationError(
            "Trigger Health Factor cannot exceed the target Health Factor."
        )
    if prefs.max_slippage_pct <= 0:
        raise ValidationError("Maximum slippage must be greater than zero.")
    if prefs.available_capital < 0:
        raise ValidationError("Available capital cannot be negative.")


# ---------------------------------------------------------------------------
# Core maths
# ---------------------------------------------------------------------------

def health_factor(position: Position) -> float:
    """Health Factor.

        HF = (collateral_value * liquidation_threshold) / debt_value

    Below 1.0 the position is liquidatable. Returns INFINITE_HF when there is
    no debt, since an undebted position can never be liquidated.
    """
    validate_position(position)
    if position.debt_value <= 0:
        return INFINITE_HF
    hf = (position.collateral_value * position.liquidation_threshold) / position.debt_value
    return min(hf, INFINITE_HF)


def classify_risk(hf: float) -> RiskLevel:
    """Map a Health Factor onto a risk band."""
    if hf < LIQUIDATION_HF:
        return RiskLevel.LIQUIDATABLE
    if hf < DANGER_HF:
        return RiskLevel.DANGER
    if hf < WARNING_HF:
        return RiskLevel.WARNING
    return RiskLevel.SAFE


def liquidation_price(position: Position) -> float:
    """Collateral price at which HF reaches exactly 1.0.

        P_liq = debt_value / (collateral_amount * liquidation_threshold)

    Returns 0.0 when there is no debt (the position never liquidates) and 0.0
    when there is no collateral but debt exists (already underwater at any
    price -- the caller should read the risk level, not this number).
    """
    validate_position(position)
    if position.debt_value <= 0 or position.collateral_amount <= 0:
        return 0.0
    return position.debt_value / (
        position.collateral_amount * position.liquidation_threshold
    )


def price_drop_to_liquidation_pct(position: Position) -> float:
    """How far the collateral price can fall before liquidation, in percent.

    Negative when the position is already liquidatable.
    """
    p_liq = liquidation_price(position)
    if p_liq <= 0:
        return 100.0  # no debt: the whole price range is survivable
    return (position.collateral_price - p_liq) / position.collateral_price * 100.0


def potential_liquidation_loss(position: Position) -> float:
    """Value the owner loses if this position is liquidated right now.

        loss = debt_value * close_factor * liquidation_bonus

    The liquidator repays up to `close_factor` of the debt and seizes an
    equivalent amount of collateral plus the `liquidation_bonus` discount. That
    bonus is paid out of the owner's collateral, so it is the owner's loss.
    This is the "benefit" side of the economic viability check in the strategy
    engine -- a rescue is only worth running if it costs less than this.
    """
    validate_position(position)
    return position.debt_value * position.close_factor * position.liquidation_bonus


# ---------------------------------------------------------------------------
# Intervention sizing
# ---------------------------------------------------------------------------

def minimum_repayment_to_target(position: Position, target_hf: float) -> float:
    """Debt to repay, from external funds, to reach `target_hf`.

    DERIVATION
    ----------
    Repaying R with wallet funds leaves collateral untouched and reduces debt:

        HF_target = (C * LT) / (D - R)

    Solving for R:

        R = D - (C * LT) / HF_target

    ASSUMPTIONS
    -----------
      * The repayment comes from outside the position (wallet balance), so
        collateral value C is unchanged. For a self-funded variant that sells
        collateral, use `collateral_swap_repayment`.
      * Clamped at zero: if the position already meets the target, no repayment
        is required (edge case 6 -- "minimum repayment is zero").
      * Clamped at D: you cannot repay more debt than exists. Repaying all of
        D clears the debt and removes liquidation risk entirely, so repayment
        from external funds can always reach any target -- given enough
        capital. Where capital is limited the strategy engine caps the amount
        and marks the strategy invalid if the capped amount misses the target
        (edge case 7).

    This is the single place the sizing formula lives. Swapping in a real
    protocol's accounting means replacing this function and nothing else.
    """
    validate_position(position)
    if target_hf <= 0:
        raise ValidationError("Target Health Factor must be greater than zero.")
    if position.debt_value <= 0:
        return 0.0

    raw = position.debt_value - (
        position.collateral_value * position.liquidation_threshold
    ) / target_hf
    return max(0.0, min(raw, position.debt_value))


def minimum_collateral_topup_to_target(position: Position, target_hf: float) -> float:
    """Collateral value (USD) to deposit to reach `target_hf`.

    DERIVATION
    ----------
        HF_target = ((C + dC) * LT) / D   =>   dC = (HF_target * D) / LT - C

    Clamped at zero when the position already meets the target.
    """
    validate_position(position)
    if target_hf <= 0:
        raise ValidationError("Target Health Factor must be greater than zero.")
    if position.debt_value <= 0:
        return 0.0

    raw = (target_hf * position.debt_value) / position.liquidation_threshold - (
        position.collateral_value
    )
    return max(0.0, raw)


def collateral_swap_repayment(
    position: Position, target_hf: float, slippage_pct: float
) -> Optional[float]:
    """Debt to repay when the repayment is funded by *selling collateral*.

    DERIVATION
    ----------
    To repay R the position must give up R * (1 + s) of collateral value, where
    s is the round-trip cost of the swap (pool fee + price impact) expressed as
    a fraction. Both sides of the ratio move:

        HF_target = ((C - R*(1+s)) * LT) / (D - R)

    Expanding and solving for R:

        HF_target * D - HF_target * R = C*LT - R*(1+s)*LT
        R * ((1+s)*LT - HF_target)    = C*LT - HF_target*D
        R = (C*LT - HF_target*D) / ((1+s)*LT - HF_target)

    Returns None when the equation has no usable solution -- which happens when
    the denominator is zero, or when the required R exceeds the outstanding
    debt. Both mean "deleveraging cannot reach this target"; the caller marks
    the strategy invalid (edge case 7).

    Note the structural reason a self-funded rescue is weaker than an
    externally funded one: selling collateral shrinks the numerator too, so
    each dollar of repayment buys less Health Factor.
    """
    validate_position(position)
    if target_hf <= 0:
        raise ValidationError("Target Health Factor must be greater than zero.")
    if position.debt_value <= 0:
        return 0.0

    s = slippage_pct / 100.0
    lt = position.liquidation_threshold
    denominator = (1.0 + s) * lt - target_hf
    numerator = position.collateral_value * lt - target_hf * position.debt_value

    if abs(denominator) < 1e-12:
        return None

    r = numerator / denominator
    if r < 0:
        # Already at or above target: nothing to do.
        return 0.0
    if r > position.debt_value:
        return None
    if r * (1.0 + s) > position.collateral_value:
        # Not enough collateral to fund the swap.
        return None
    return r


def apply_repayment(position: Position, repayment: float) -> Position:
    """Position after repaying `repayment` of debt with external funds."""
    from dataclasses import replace

    return replace(position, debt_amount=max(0.0, position.debt_amount - repayment))


def apply_collateral_topup(position: Position, usd_amount: float) -> Position:
    """Position after depositing `usd_amount` of additional collateral."""
    from dataclasses import replace

    extra_units = usd_amount / position.collateral_price
    return replace(
        position, collateral_amount=position.collateral_amount + extra_units
    )


def apply_collateral_swap(
    position: Position, repayment: float, slippage_pct: float
) -> Position:
    """Position after selling collateral to repay `repayment` of debt."""
    from dataclasses import replace

    s = slippage_pct / 100.0
    collateral_spent_usd = repayment * (1.0 + s)
    units_spent = collateral_spent_usd / position.collateral_price
    return replace(
        position,
        collateral_amount=max(0.0, position.collateral_amount - units_spent),
        debt_amount=max(0.0, position.debt_amount - repayment),
    )


# ---------------------------------------------------------------------------
# Top-level assessment
# ---------------------------------------------------------------------------

def assess(
    position: Position, prefs: Optional[RiskPreferences] = None
) -> HealthAssessment:
    """Full health read-out for a position. The Dashboard renders this."""
    prefs = prefs or RiskPreferences()
    validate_position(position)
    validate_preferences(prefs)

    hf = health_factor(position)
    level = classify_risk(hf)
    p_liq = liquidation_price(position)
    drop_pct = price_drop_to_liquidation_pct(position)

    # Safety buffer: how much headroom above the liquidation line, as a
    # percentage of the target band. 0% means sitting exactly on HF 1.0.
    span = max(prefs.target_health_factor - LIQUIDATION_HF, 1e-9)
    buffer_pct = max(0.0, min(100.0, (hf - LIQUIDATION_HF) / span * 100.0))

    requires_action = (
        position.debt_value > 0 and hf <= prefs.trigger_health_factor
    )

    if position.debt_value <= 0:
        message = "No outstanding debt -- this position cannot be liquidated."
    elif level is RiskLevel.LIQUIDATABLE:
        message = (
            f"Position is liquidatable now (HF {hf:.3f}). Immediate "
            f"intervention required."
        )
    elif level is RiskLevel.DANGER:
        message = (
            f"HF {hf:.3f} is inside the danger band. A {drop_pct:.1f}% further "
            f"drop triggers liquidation."
        )
    elif requires_action:
        message = (
            f"HF {hf:.3f} is at or below the {prefs.trigger_health_factor:.2f} "
            f"intervention trigger. Generating protection strategies."
        )
    elif level is RiskLevel.WARNING:
        message = (
            f"HF {hf:.3f} is below the {prefs.target_health_factor:.2f} target "
            f"but above the intervention trigger. Monitoring."
        )
    else:
        message = f"HF {hf:.3f} is within the safe band. No rescue required."

    return HealthAssessment(
        health_factor=round(hf, 4),
        risk_level=level,
        collateral_value=round(position.collateral_value, 2),
        debt_value=round(position.debt_value, 2),
        liquidation_price=round(p_liq, 2),
        price_drop_to_liquidation_pct=round(drop_pct, 2),
        safety_buffer_pct=round(buffer_pct, 2),
        potential_liquidation_loss=round(potential_liquidation_loss(position), 2),
        requires_action=requires_action,
        message=message,
    )

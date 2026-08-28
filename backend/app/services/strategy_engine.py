"""Strategy engine: generate candidate rescues, cost them, score them, and
autonomously select the one to execute.

This is differentiators #2 and #3. The engine does not ask the user which
rescue to run -- it generates every intervention it knows how to perform,
prices each one against simulated market conditions, rejects the ones that
break a constraint, scores the survivors on a weighted composite, and returns
the winner already marked `selected`. The Strategy Comparison view in the UI
renders this trace so a human can audit the decision; it does not gate it.

COST MODEL (simulated)
----------------------
  gas       = gas_units * gas_price_gwei * 1e-9 * eth_price
  slippage  = pool fee + price impact, where impact = trade / (depth + trade)
  flash fee = flash_loan_fee_pct * flashed amount

Each of these is a pure function of MarketConditions, so pointing them at a gas
oracle, a DEX quoter and the real Aave premium is a per-function change.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from ..models.domain import (
    ExecutionStatus,
    MarketConditions,
    Position,
    ProtectionDecision,
    ProtectionMode,
    RiskLevel,
    RiskPreferences,
    ShieldState,
    Strategy,
    StrategyStatus,
    StrategyType,
)
from . import risk_engine

# Gas budget per strategy, in gas units. Order-of-magnitude figures for the
# equivalent Aave v3 + Uniswap v3 call paths.
GAS_UNITS: Dict[StrategyType, int] = {
    StrategyType.REPAY_DEBT: 180_000,
    StrategyType.ADD_COLLATERAL: 160_000,
    StrategyType.COLLATERAL_SWAP: 320_000,
    StrategyType.FLASH_LOAN_DELEVERAGE: 520_000,
    StrategyType.PARTIAL_DELEVERAGE: 180_000,
}

# Execution risk: the share of the safety score withheld for moving parts that
# can fail or be front-run between submission and inclusion. A single repay is
# nearly risk-free; a two-transaction swap is exposed to MEV and to the price
# moving underneath it; a flash loan is complex but atomic, so it sits between.
EXECUTION_RISK: Dict[StrategyType, float] = {
    StrategyType.REPAY_DEBT: 0.02,
    StrategyType.ADD_COLLATERAL: 0.02,
    StrategyType.COLLATERAL_SWAP: 0.12,
    StrategyType.FLASH_LOAN_DELEVERAGE: 0.06,
    StrategyType.PARTIAL_DELEVERAGE: 0.02,
}

# Fraction of outstanding debt the "minimal nibble" candidate repays. It is
# deliberately under-sized: it exists so the agent can demonstrate that it
# considered, and rejected, the cheapest possible action.
PARTIAL_DEBT_FRACTION = 0.10

# Health Factor tolerance when checking whether a strategy hit its target.
HF_TOLERANCE = 1e-6


def _ceil_cents(amount: float) -> float:
    """Round an action amount UP to the nearest cent.

    Execution acts on the amount the UI displays, so this cannot be a
    round-to-nearest. Rounding down lands the position a hair BELOW the target:
    with a real market price of $2,445.16 the exact repayment is $1,924.7333,
    and repaying the rounded $1,924.73 yields HF 1.4999987 -- which the UI
    reports as "1.500" while classifying it WARNING. Rounding up costs at most
    one cent and guarantees the executed rescue meets or beats the target.

    Every amount is derived from this rounded figure rather than the exact one,
    so the Health Factor shown on the card is the Health Factor execution
    actually produces.
    """
    return math.ceil(amount * 100) / 100

SKIP_UNECONOMICAL = "Rescue skipped – economically unviable."
SKIP_INSUFFICIENT_LIQUIDITY = "Rescue skipped – insufficient liquidity."


# ---------------------------------------------------------------------------
# Simulated market primitives
# ---------------------------------------------------------------------------

def estimate_gas_cost(strategy_type: StrategyType, market: MarketConditions) -> float:
    """USD cost of the transaction(s) this strategy submits."""
    gas_units = GAS_UNITS[strategy_type]
    return gas_units * market.gas_price_gwei * 1e-9 * market.eth_price


def estimate_slippage_pct(trade_usd: float, market: MarketConditions) -> float:
    """Round-trip swap cost in percent: static pool fee plus price impact.

    Impact uses the constant-product shape `trade / (depth + trade)`, which is
    ~0 for a trade small against the pool and grows without bound as the trade
    approaches pool depth. Small trades therefore cost roughly the pool fee,
    which matches how a real AMM behaves.
    """
    if trade_usd <= 0:
        return 0.0
    impact = trade_usd / (market.dex_liquidity_usd + trade_usd) * 100.0
    return market.dex_base_fee_pct + impact


def has_sufficient_liquidity(trade_usd: float, market: MarketConditions) -> bool:
    """Whether the pool can absorb this trade at all (edge case 4).

    Distinct from the slippage check: a trade can be inside the slippage budget
    on paper and still be one the agent refuses to route, because taking more
    than `max_pool_utilisation` of a pool is how you get sandwiched.
    """
    if trade_usd <= 0:
        return True
    return trade_usd <= market.dex_liquidity_usd * market.max_pool_utilisation


# ---------------------------------------------------------------------------
# Self-funded sizing (slippage depends on trade size, which depends on
# slippage -- solved by fixed-point iteration)
# ---------------------------------------------------------------------------

def _solve_self_funded_repayment(
    position: Position,
    target_hf: float,
    market: MarketConditions,
    max_iterations: int = 12,
) -> Optional[Tuple[float, float]]:
    """Return (repayment, slippage_pct) for a collateral-funded rescue.

    The repayment size depends on the swap cost, and the swap cost depends on
    the repayment size, so we iterate to a fixed point. Converges in a handful
    of passes for any trade that is small against pool depth; bails out and
    returns None when no consistent solution exists (edge case 7).
    """
    slippage = market.dex_base_fee_pct
    repayment: Optional[float] = None

    for _ in range(max_iterations):
        repayment = risk_engine.collateral_swap_repayment(
            position, target_hf, slippage
        )
        if repayment is None:
            return None
        trade = repayment * (1.0 + slippage / 100.0)
        new_slippage = estimate_slippage_pct(trade, market)
        if abs(new_slippage - slippage) < 1e-9:
            slippage = new_slippage
            break
        slippage = new_slippage

    if repayment is None:
        return None
    return repayment, slippage


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

def _finalise(
    strategy: Strategy,
    prefs: RiskPreferences,
    market: MarketConditions,
    trade_usd: float,
    target_hf: float,
) -> Strategy:
    """Apply the shared constraint checks to a costed candidate.

    Order matters: a strategy is reported against the *first* constraint it
    violates, so the rejection reason a judge reads is the binding one.
    """
    # Edge case 4 -- the pool cannot absorb the trade.
    if not has_sufficient_liquidity(trade_usd, market):
        cap = market.dex_liquidity_usd * market.max_pool_utilisation
        strategy.status = StrategyStatus.REJECTED_INSUFFICIENT_LIQUIDITY
        strategy.rejection_reason = (
            f"Requires a ${trade_usd:,.0f} swap but routable DEX depth is "
            f"${cap:,.0f}."
        )
        return strategy

    # Edge case 3 -- price impact beyond the user's tolerance.
    if strategy.slippage_pct > prefs.max_slippage_pct:
        strategy.status = StrategyStatus.REJECTED_HIGH_SLIPPAGE
        strategy.rejection_reason = (
            f"Estimated slippage {strategy.slippage_pct:.2f}% exceeds the "
            f"{prefs.max_slippage_pct:.2f}% limit."
        )
        return strategy

    # Not enough idle capital to fund an externally funded rescue.
    if strategy.required_capital > prefs.available_capital + 1e-9:
        strategy.status = StrategyStatus.REJECTED_INSUFFICIENT_CAPITAL
        strategy.rejection_reason = (
            f"Needs ${strategy.required_capital:,.0f} of wallet capital; "
            f"${prefs.available_capital:,.0f} available."
        )
        return strategy

    # Edge case 7 -- the action does not restore the target Health Factor.
    if strategy.resulting_health_factor < target_hf - HF_TOLERANCE:
        strategy.status = StrategyStatus.INVALID_CANNOT_REACH_TARGET
        strategy.rejection_reason = (
            f"Restores HF to only {strategy.resulting_health_factor:.3f}, "
            f"short of the {target_hf:.2f} target."
        )
        return strategy

    strategy.status = StrategyStatus.VIABLE
    return strategy


def _repay_debt(
    position: Position, prefs: RiskPreferences, market: MarketConditions
) -> Strategy:
    target = prefs.target_health_factor
    repayment = _ceil_cents(risk_engine.minimum_repayment_to_target(position, target))
    after = risk_engine.apply_repayment(position, repayment)
    hf_after = risk_engine.health_factor(after)
    gas = estimate_gas_cost(StrategyType.REPAY_DEBT, market)

    s = Strategy(
        strategy_type=StrategyType.REPAY_DEBT,
        name="Repay debt from wallet",
        description=(
            f"Repay ${repayment:,.0f} of {position.debt_asset} debt using idle "
            f"wallet capital. Collateral is untouched, so no swap and no price "
            f"impact."
        ),
        action_amount=round(repayment, 2),
        required_capital=round(repayment, 2),
        resulting_health_factor=round(hf_after, 4),
        resulting_risk_level=risk_engine.classify_risk(hf_after),
        slippage_pct=0.0,
        slippage_cost=0.0,
        gas_cost=round(gas, 2),
        flash_loan_fee=0.0,
        total_cost=round(gas, 2),
        status=StrategyStatus.VIABLE,
    )
    return _finalise(s, prefs, market, trade_usd=0.0, target_hf=target)


def _add_collateral(
    position: Position, prefs: RiskPreferences, market: MarketConditions
) -> Strategy:
    target = prefs.target_health_factor
    topup = _ceil_cents(risk_engine.minimum_collateral_topup_to_target(position, target))
    after = risk_engine.apply_collateral_topup(position, topup)
    hf_after = risk_engine.health_factor(after)
    gas = estimate_gas_cost(StrategyType.ADD_COLLATERAL, market)

    s = Strategy(
        strategy_type=StrategyType.ADD_COLLATERAL,
        name="Top up collateral",
        description=(
            f"Deposit ${topup:,.0f} of additional {position.collateral_asset} "
            f"collateral. Debt is unchanged; the position keeps full upside "
            f"exposure."
        ),
        action_amount=round(topup, 2),
        required_capital=round(topup, 2),
        resulting_health_factor=round(hf_after, 4),
        resulting_risk_level=risk_engine.classify_risk(hf_after),
        slippage_pct=0.0,
        slippage_cost=0.0,
        gas_cost=round(gas, 2),
        flash_loan_fee=0.0,
        total_cost=round(gas, 2),
        status=StrategyStatus.VIABLE,
    )
    return _finalise(s, prefs, market, trade_usd=0.0, target_hf=target)


def _collateral_swap(
    position: Position, prefs: RiskPreferences, market: MarketConditions
) -> Optional[Strategy]:
    target = prefs.target_health_factor
    solved = _solve_self_funded_repayment(position, target, market)
    if solved is None:
        return _unreachable_strategy(
            StrategyType.COLLATERAL_SWAP,
            "Swap collateral and repay",
            "Selling collateral shrinks the numerator of the Health Factor as "
            "fast as it shrinks the denominator, so this target is unreachable "
            "by deleveraging alone.",
            target,
        )

    repayment, slippage_pct = solved
    repayment = _ceil_cents(repayment)
    trade = repayment * (1.0 + slippage_pct / 100.0)
    after = risk_engine.apply_collateral_swap(position, repayment, slippage_pct)
    hf_after = risk_engine.health_factor(after)
    gas = estimate_gas_cost(StrategyType.COLLATERAL_SWAP, market)
    slip_cost = trade * slippage_pct / 100.0

    s = Strategy(
        strategy_type=StrategyType.COLLATERAL_SWAP,
        name="Swap collateral and repay",
        description=(
            f"Sell ${trade:,.0f} of {position.collateral_asset} on-DEX and "
            f"repay ${repayment:,.0f} of debt. Self-funded -- needs no wallet "
            f"capital, but gives up collateral and takes price impact."
        ),
        action_amount=round(repayment, 2),
        required_capital=0.0,
        resulting_health_factor=round(hf_after, 4),
        resulting_risk_level=risk_engine.classify_risk(hf_after),
        slippage_pct=round(slippage_pct, 4),
        slippage_cost=round(slip_cost, 2),
        gas_cost=round(gas, 2),
        flash_loan_fee=0.0,
        total_cost=round(gas + slip_cost, 2),
        status=StrategyStatus.VIABLE,
    )
    return _finalise(s, prefs, market, trade_usd=trade, target_hf=target)


def _flash_loan_deleverage(
    position: Position, prefs: RiskPreferences, market: MarketConditions
) -> Optional[Strategy]:
    target = prefs.target_health_factor
    solved = _solve_self_funded_repayment(position, target, market)
    if solved is None:
        return _unreachable_strategy(
            StrategyType.FLASH_LOAN_DELEVERAGE,
            "Flash-loan deleverage",
            "The atomic route sizes the same as the manual swap, and that "
            "size cannot reach the target.",
            target,
        )

    repayment, slippage_pct = solved
    repayment = _ceil_cents(repayment)
    trade = repayment * (1.0 + slippage_pct / 100.0)
    after = risk_engine.apply_collateral_swap(position, repayment, slippage_pct)
    hf_after = risk_engine.health_factor(after)
    gas = estimate_gas_cost(StrategyType.FLASH_LOAN_DELEVERAGE, market)
    slip_cost = trade * slippage_pct / 100.0
    flash_fee = repayment * market.flash_loan_fee_pct / 100.0

    s = Strategy(
        strategy_type=StrategyType.FLASH_LOAN_DELEVERAGE,
        name="Flash-loan deleverage",
        description=(
            f"Flash-borrow ${repayment:,.0f}, repay the debt, withdraw and "
            f"sell collateral to close the loan -- all in one atomic "
            f"transaction. No wallet capital and no window for the price to "
            f"move mid-rescue."
        ),
        action_amount=round(repayment, 2),
        required_capital=0.0,
        resulting_health_factor=round(hf_after, 4),
        resulting_risk_level=risk_engine.classify_risk(hf_after),
        slippage_pct=round(slippage_pct, 4),
        slippage_cost=round(slip_cost, 2),
        gas_cost=round(gas, 2),
        flash_loan_fee=round(flash_fee, 2),
        total_cost=round(gas + slip_cost + flash_fee, 2),
        status=StrategyStatus.VIABLE,
    )
    return _finalise(s, prefs, market, trade_usd=trade, target_hf=target)


def _partial_deleverage(
    position: Position, prefs: RiskPreferences, market: MarketConditions
) -> Strategy:
    """The cheapest conceivable action: repay a fixed slice of the debt.

    Usually falls short of the target and is reported as invalid. It is kept in
    the candidate set on purpose -- the comparison table is an audit trail, and
    an audit trail that only lists winners is not one.
    """
    target = prefs.target_health_factor
    repayment = position.debt_value * PARTIAL_DEBT_FRACTION
    after = risk_engine.apply_repayment(position, repayment)
    hf_after = risk_engine.health_factor(after)
    gas = estimate_gas_cost(StrategyType.PARTIAL_DELEVERAGE, market)

    s = Strategy(
        strategy_type=StrategyType.PARTIAL_DELEVERAGE,
        name="Minimal partial repayment",
        description=(
            f"Repay a fixed {PARTIAL_DEBT_FRACTION:.0%} of outstanding debt "
            f"(${repayment:,.0f}) -- the smallest meaningful action, evaluated "
            f"as a low-cost baseline."
        ),
        action_amount=round(repayment, 2),
        required_capital=round(repayment, 2),
        resulting_health_factor=round(hf_after, 4),
        resulting_risk_level=risk_engine.classify_risk(hf_after),
        slippage_pct=0.0,
        slippage_cost=0.0,
        gas_cost=round(gas, 2),
        flash_loan_fee=0.0,
        total_cost=round(gas, 2),
        status=StrategyStatus.VIABLE,
    )
    return _finalise(s, prefs, market, trade_usd=0.0, target_hf=target)


def _unreachable_strategy(
    strategy_type: StrategyType, name: str, reason: str, target: float
) -> Strategy:
    return Strategy(
        strategy_type=strategy_type,
        name=name,
        description=reason,
        action_amount=0.0,
        required_capital=0.0,
        resulting_health_factor=0.0,
        resulting_risk_level=RiskLevel.LIQUIDATABLE,
        slippage_pct=0.0,
        slippage_cost=0.0,
        gas_cost=0.0,
        flash_loan_fee=0.0,
        total_cost=0.0,
        status=StrategyStatus.INVALID_CANNOT_REACH_TARGET,
        rejection_reason=f"Cannot restore the {target:.2f} target Health Factor.",
    )


def generate(
    position: Position,
    prefs: Optional[RiskPreferences] = None,
    market: Optional[MarketConditions] = None,
) -> List[Strategy]:
    """Produce every candidate rescue for this position, costed and checked."""
    prefs = prefs or RiskPreferences()
    market = market or MarketConditions(eth_price=position.collateral_price)
    risk_engine.validate_position(position)
    risk_engine.validate_preferences(prefs)

    if position.debt_value <= 0:
        return []

    candidates = [
        _repay_debt(position, prefs, market),
        _add_collateral(position, prefs, market),
        _collateral_swap(position, prefs, market),
        _flash_loan_deleverage(position, prefs, market),
        _partial_deleverage(position, prefs, market),
    ]
    return [c for c in candidates if c is not None]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def normalised_weights(prefs: RiskPreferences) -> Dict[str, float]:
    """Score weights rescaled to sum to 1.0, so callers may pass any ratio."""
    raw = {
        "safety": prefs.weight_safety,
        "cost": prefs.weight_cost,
        "slippage": prefs.weight_slippage,
        "liquidity": prefs.weight_liquidity,
        "capital": prefs.weight_capital,
    }
    total = sum(raw.values())
    if total <= 0:
        raise risk_engine.ValidationError("Score weights must sum to a positive value.")
    return {k: v / total for k, v in raw.items()}


def score_strategy(
    strategy: Strategy,
    position: Position,
    prefs: RiskPreferences,
    market: MarketConditions,
) -> Strategy:
    """Attach a composite score in [0, 1] and its component breakdown.

    Non-viable candidates score 0 -- they are never selectable, and giving them
    a number would imply otherwise.
    """
    if not strategy.is_executable:
        strategy.score = 0.0
        strategy.score_breakdown = {}
        return strategy

    target = prefs.target_health_factor
    span = max(target - risk_engine.LIQUIDATION_HF, 1e-9)
    at_risk = max(risk_engine.potential_liquidation_loss(position), 1e-9)
    routable = max(market.dex_liquidity_usd * market.max_pool_utilisation, 1e-9)
    trade = strategy.action_amount if strategy.slippage_pct > 0 else 0.0

    # Safety: does it clear the target, discounted for execution risk.
    hf_score = _clamp01((strategy.resulting_health_factor - risk_engine.LIQUIDATION_HF) / span)
    safety = hf_score * (1.0 - EXECUTION_RISK[strategy.strategy_type])

    # Cost: total cost measured against the loss the rescue is preventing.
    cost = 1.0 - _clamp01(strategy.total_cost / at_risk)

    # Slippage: headroom left inside the user's tolerance.
    slippage = 1.0 - _clamp01(strategy.slippage_pct / prefs.max_slippage_pct)

    # Liquidity: how much of the routable depth the trade consumes.
    liquidity = 1.0 - _clamp01(trade / routable)

    # Capital: prefer rescues that lock up less of the idle balance.
    if prefs.available_capital <= 0:
        capital = 1.0 if strategy.required_capital <= 0 else 0.0
    else:
        capital = 1.0 - _clamp01(strategy.required_capital / prefs.available_capital)

    w = normalised_weights(prefs)
    composite = (
        w["safety"] * safety
        + w["cost"] * cost
        + w["slippage"] * slippage
        + w["liquidity"] * liquidity
        + w["capital"] * capital
    )

    strategy.score = round(composite, 4)
    strategy.score_breakdown = {
        "safety": round(safety, 4),
        "cost": round(cost, 4),
        "slippage": round(slippage, 4),
        "liquidity": round(liquidity, 4),
        "capital": round(capital, 4),
    }
    return strategy


def score_all(
    strategies: List[Strategy],
    position: Position,
    prefs: Optional[RiskPreferences] = None,
    market: Optional[MarketConditions] = None,
) -> List[Strategy]:
    prefs = prefs or RiskPreferences()
    market = market or MarketConditions(eth_price=position.collateral_price)
    for s in strategies:
        score_strategy(s, position, prefs, market)
    return sorted(strategies, key=lambda s: (s.is_executable, s.score), reverse=True)


def select_best(strategies: List[Strategy]) -> Optional[Strategy]:
    """Autonomous selection: highest composite score among viable candidates."""
    viable = [s for s in strategies if s.is_executable]
    if not viable:
        return None
    best = max(viable, key=lambda s: s.score)
    for s in strategies:
        s.selected = s is best
    return best


# ---------------------------------------------------------------------------
# Economic viability (edge case 5)
# ---------------------------------------------------------------------------

def check_economic_viability(
    strategy: Strategy, position: Position
) -> Tuple[bool, Dict[str, float]]:
    """Is this rescue worth running at all?

    Compares the all-in rescue cost (gas + slippage + flash-loan fee) against
    the loss a liquidation would inflict. Spending $40 to avoid losing $12 is
    strictly worse than doing nothing, and an agent that executes anyway is not
    autonomous, it is just automatic.
    """
    at_risk = risk_engine.potential_liquidation_loss(position)
    economics = {
        "rescue_cost": round(strategy.total_cost, 2),
        "potential_loss": round(at_risk, 2),
        "net_benefit": round(at_risk - strategy.total_cost, 2),
    }
    return strategy.total_cost <= at_risk, economics


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------

def _explain(best: Strategy, others: List[Strategy]) -> str:
    viable_others = [s for s in others if s.is_executable and s is not best]
    lead = (
        f"{best.name} selected — restores HF "
        f"{best.resulting_health_factor:.3f} at an estimated ${best.total_cost:,.2f}"
    )
    if not viable_others:
        return lead + ", and was the only candidate that cleared every constraint."
    runner_up = max(viable_others, key=lambda s: s.score)
    margin = best.score - runner_up.score
    return (
        f"{lead}. It scored {best.score:.3f} against {runner_up.score:.3f} for "
        f"{runner_up.name}, a {margin:.3f} margin driven by "
        f"{_dominant_factor(best, runner_up)}."
    )


def _dominant_factor(best: Strategy, runner_up: Strategy) -> str:
    """Which score component explains the gap between the top two."""
    if not best.score_breakdown or not runner_up.score_breakdown:
        return "the composite score"
    labels = {
        "safety": "lower execution risk",
        "cost": "lower total cost",
        "slippage": "less price impact",
        "liquidity": "lighter use of DEX depth",
        "capital": "less capital locked up",
    }
    deltas = {
        k: best.score_breakdown.get(k, 0.0) - runner_up.score_breakdown.get(k, 0.0)
        for k in best.score_breakdown
    }
    key = max(deltas, key=lambda k: deltas[k])
    return labels.get(key, key)


def evaluate(
    position: Position,
    prefs: Optional[RiskPreferences] = None,
    market: Optional[MarketConditions] = None,
) -> ProtectionDecision:
    """One full agent cycle: assess, generate, score, select, decide.

    This is the function the autonomous loop calls. Execution is simulated --
    no transaction is broadcast anywhere.
    """
    prefs = prefs or RiskPreferences()
    market = market or MarketConditions(eth_price=position.collateral_price)
    assessment = risk_engine.assess(position, prefs)

    # Edge case 1 / 6 -- healthy position, nothing to do.
    if not assessment.requires_action:
        return ProtectionDecision(
            assessment=assessment,
            strategies=[],
            selected_strategy=None,
            execution_status=ExecutionStatus.NO_ACTION_REQUIRED,
            shield_state=ShieldState.ARMED,
            explanation=assessment.message,
            economics={
                "rescue_cost": 0.0,
                "potential_loss": assessment.potential_liquidation_loss,
                "net_benefit": 0.0,
            },
        )

    strategies = score_all(generate(position, prefs, market), position, prefs, market)
    best = select_best(strategies)

    # Edge cases 3 / 4 / 7 -- every candidate broke a constraint.
    if best is None:
        detail = " ".join(
            f"{s.name}: {s.rejection_reason}"
            for s in strategies
            if s.rejection_reason
        )
        # A depth shortfall is a market-level blocker, so it outranks the
        # per-strategy reasons when reporting why nothing ran.
        blocked_on_depth = any(
            s.status is StrategyStatus.REJECTED_INSUFFICIENT_LIQUIDITY
            for s in strategies
        )
        if blocked_on_depth:
            explanation = f"{SKIP_INSUFFICIENT_LIQUIDITY} {detail}".strip()
        else:
            explanation = (
                f"Rescue skipped – no strategy cleared every constraint. {detail}"
            ).strip()
        return ProtectionDecision(
            assessment=assessment,
            strategies=strategies,
            selected_strategy=None,
            execution_status=ExecutionStatus.SKIPPED_NO_VIABLE_STRATEGY,
            shield_state=ShieldState.SKIPPED,
            explanation=explanation,
            economics={
                "rescue_cost": 0.0,
                "potential_loss": assessment.potential_liquidation_loss,
                "net_benefit": 0.0,
            },
        )

    viable, economics = check_economic_viability(best, position)

    # Edge case 5 -- the cure costs more than the disease.
    if not viable:
        best.selected = False
        return ProtectionDecision(
            assessment=assessment,
            strategies=strategies,
            selected_strategy=None,
            execution_status=ExecutionStatus.SKIPPED_UNECONOMICAL,
            shield_state=ShieldState.SKIPPED,
            explanation=(
                f"{SKIP_UNECONOMICAL} Cheapest viable rescue costs "
                f"${economics['rescue_cost']:,.2f} against "
                f"${economics['potential_loss']:,.2f} at risk."
            ),
            economics=economics,
        )

    explanation = _explain(best, strategies)

    if prefs.mode is ProtectionMode.ADVISORY:
        return ProtectionDecision(
            assessment=assessment,
            strategies=strategies,
            selected_strategy=best,
            execution_status=ExecutionStatus.AWAITING_CONFIRMATION,
            shield_state=ShieldState.ALERT,
            explanation=explanation + " Advisory mode: awaiting confirmation.",
            economics=economics,
        )

    return ProtectionDecision(
        assessment=assessment,
        strategies=strategies,
        selected_strategy=best,
        execution_status=ExecutionStatus.EXECUTED,
        shield_state=ShieldState.PROTECTING,
        explanation=explanation,
        economics=economics,
    )


def apply_strategy(position: Position, strategy: Strategy) -> Position:
    """The simulated on-chain effect of executing `strategy`.

    In production this is where the call to the protection smart contract goes.
    Here it mutates the in-memory position so the UI can show the post-rescue
    Health Factor. Nothing is broadcast.
    """
    if strategy.strategy_type in (
        StrategyType.REPAY_DEBT,
        StrategyType.PARTIAL_DELEVERAGE,
    ):
        return risk_engine.apply_repayment(position, strategy.action_amount)
    if strategy.strategy_type is StrategyType.ADD_COLLATERAL:
        return risk_engine.apply_collateral_topup(position, strategy.action_amount)
    return risk_engine.apply_collateral_swap(
        position, strategy.action_amount, strategy.slippage_pct
    )

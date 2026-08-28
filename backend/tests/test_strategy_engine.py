"""Strategy engine unit tests: generation, costing, constraint rejection,
scoring, autonomous selection and the economic viability gate.

The edge cases from the brief map onto tests as follows:
  1 safe position                -> test_safe_position_needs_no_rescue
  2 risky position               -> test_risky_position_auto_selects_a_strategy
  3 very high slippage           -> test_high_slippage_strategies_are_rejected
  4 insufficient DEX liquidity   -> test_thin_liquidity_is_rejected
  5 cost > potential loss        -> test_rescue_is_skipped_when_uneconomical
  6 minimum repayment is zero    -> test_safe_position_needs_no_rescue
  7 cannot restore target        -> test_partial_repayment_is_marked_invalid
  8 invalid input                -> test_invalid_position_is_rejected
"""

import pytest

from app.models.domain import (
    ExecutionStatus,
    MarketConditions,
    Position,
    ProtectionMode,
    RiskLevel,
    RiskPreferences,
    ShieldState,
    StrategyStatus,
    StrategyType,
    ValidationError,
)
from app.services import risk_engine, strategy_engine

SEED = Position()
DROPPED = SEED.with_price(2700.0)          # -10%, HF 1.125, needs rescue
MARKET = MarketConditions(eth_price=2700.0)
PREFS = RiskPreferences()


def _by_type(strategies, strategy_type):
    return next(s for s in strategies if s.strategy_type is strategy_type)


# ---------------------------------------------------------------------------
# Simulated market primitives
# ---------------------------------------------------------------------------

def test_gas_cost_uses_gas_units_price_and_eth():
    # 180,000 * 20 gwei * $2,700 = 0.0036 ETH = $9.72
    cost = strategy_engine.estimate_gas_cost(StrategyType.REPAY_DEBT, MARKET)
    assert cost == pytest.approx(9.72, abs=0.01)


def test_slippage_is_near_the_pool_fee_for_a_small_trade():
    slip = strategy_engine.estimate_slippage_pct(1_000.0, MARKET)
    assert slip == pytest.approx(MARKET.dex_base_fee_pct, abs=0.06)


def test_slippage_grows_with_trade_size():
    small = strategy_engine.estimate_slippage_pct(1_000.0, MARKET)
    large = strategy_engine.estimate_slippage_pct(400_000.0, MARKET)
    assert large > small * 5


def test_zero_size_trade_has_no_slippage():
    assert strategy_engine.estimate_slippage_pct(0.0, MARKET) == 0.0


def test_liquidity_check_respects_max_pool_utilisation():
    thin = MarketConditions(dex_liquidity_usd=10_000.0, max_pool_utilisation=0.25)
    assert strategy_engine.has_sufficient_liquidity(2_000.0, thin) is True
    assert strategy_engine.has_sufficient_liquidity(3_000.0, thin) is False


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def test_generator_produces_all_five_candidate_types():
    strategies = strategy_engine.generate(DROPPED, PREFS, MARKET)
    assert {s.strategy_type for s in strategies} == set(StrategyType)


def test_every_viable_strategy_actually_reaches_the_target():
    strategies = strategy_engine.generate(DROPPED, PREFS, MARKET)
    for s in strategies:
        if s.is_executable:
            assert s.resulting_health_factor >= PREFS.target_health_factor - 1e-6


def test_repay_and_topup_amounts_match_the_risk_engine():
    strategies = strategy_engine.generate(DROPPED, PREFS, MARKET)
    repay = _by_type(strategies, StrategyType.REPAY_DEBT)
    topup = _by_type(strategies, StrategyType.ADD_COLLATERAL)
    assert repay.action_amount == pytest.approx(1250.0, abs=0.01)
    assert topup.action_amount == pytest.approx(3000.0, abs=0.01)


def test_self_funded_strategies_need_no_wallet_capital():
    strategies = strategy_engine.generate(DROPPED, PREFS, MARKET)
    for t in (StrategyType.COLLATERAL_SWAP, StrategyType.FLASH_LOAN_DELEVERAGE):
        assert _by_type(strategies, t).required_capital == 0.0


def test_flash_loan_route_costs_more_than_the_manual_swap():
    """Same sizing, extra premium and heavier gas -- so it must cost more."""
    strategies = strategy_engine.generate(DROPPED, PREFS, MARKET)
    swap = _by_type(strategies, StrategyType.COLLATERAL_SWAP)
    flash = _by_type(strategies, StrategyType.FLASH_LOAN_DELEVERAGE)
    assert flash.flash_loan_fee > 0
    assert swap.flash_loan_fee == 0.0
    assert flash.total_cost > swap.total_cost


def test_total_cost_is_the_sum_of_its_parts():
    for s in strategy_engine.generate(DROPPED, PREFS, MARKET):
        assert s.total_cost == pytest.approx(
            s.gas_cost + s.slippage_cost + s.flash_loan_fee, abs=0.02
        )


def test_no_strategies_are_generated_without_debt():
    assert strategy_engine.generate(Position(debt_amount=0.0), PREFS, MARKET) == []


# ---------------------------------------------------------------------------
# Edge case 3: very high slippage
# ---------------------------------------------------------------------------

def test_high_slippage_strategies_are_rejected():
    shallow = MarketConditions(
        eth_price=2700.0, dex_liquidity_usd=30_000.0, max_pool_utilisation=0.95
    )
    strategies = strategy_engine.generate(DROPPED, PREFS, shallow)
    swap = _by_type(strategies, StrategyType.COLLATERAL_SWAP)

    assert swap.slippage_pct > PREFS.max_slippage_pct
    assert swap.status is StrategyStatus.REJECTED_HIGH_SLIPPAGE
    assert "exceeds" in swap.rejection_reason
    assert swap.is_executable is False


def test_raising_the_slippage_tolerance_makes_the_swap_viable_again():
    shallow = MarketConditions(
        eth_price=2700.0, dex_liquidity_usd=30_000.0, max_pool_utilisation=0.95
    )
    tolerant = RiskPreferences(max_slippage_pct=25.0)
    swap = _by_type(
        strategy_engine.generate(DROPPED, tolerant, shallow),
        StrategyType.COLLATERAL_SWAP,
    )
    assert swap.status is StrategyStatus.VIABLE


# ---------------------------------------------------------------------------
# Edge case 4: insufficient DEX liquidity
# ---------------------------------------------------------------------------

def test_thin_liquidity_is_rejected():
    thin = MarketConditions(eth_price=2700.0, dex_liquidity_usd=5_000.0)
    strategies = strategy_engine.generate(DROPPED, PREFS, thin)
    swap = _by_type(strategies, StrategyType.COLLATERAL_SWAP)

    assert swap.status is StrategyStatus.REJECTED_INSUFFICIENT_LIQUIDITY
    assert "routable DEX depth" in swap.rejection_reason


def test_liquidity_is_checked_before_slippage():
    """A trade the agent will not route is reported as a depth problem, not a
    price-impact problem -- the binding constraint is the useful one."""
    thin = MarketConditions(eth_price=2700.0, dex_liquidity_usd=5_000.0)
    swap = _by_type(
        strategy_engine.generate(DROPPED, PREFS, thin), StrategyType.COLLATERAL_SWAP
    )
    assert swap.status is StrategyStatus.REJECTED_INSUFFICIENT_LIQUIDITY


def test_decision_reports_insufficient_liquidity_when_nothing_can_run():
    thin = MarketConditions(eth_price=2700.0, dex_liquidity_usd=5_000.0)
    broke = RiskPreferences(available_capital=0.0)
    decision = strategy_engine.evaluate(DROPPED, broke, thin)

    assert decision.selected_strategy is None
    assert decision.execution_status is ExecutionStatus.SKIPPED_NO_VIABLE_STRATEGY
    assert decision.shield_state is ShieldState.SKIPPED
    assert decision.explanation.startswith(strategy_engine.SKIP_INSUFFICIENT_LIQUIDITY)


# ---------------------------------------------------------------------------
# Insufficient wallet capital
# ---------------------------------------------------------------------------

def test_externally_funded_strategies_are_rejected_without_capital():
    broke = RiskPreferences(available_capital=100.0)
    strategies = strategy_engine.generate(DROPPED, broke, MARKET)
    repay = _by_type(strategies, StrategyType.REPAY_DEBT)

    assert repay.status is StrategyStatus.REJECTED_INSUFFICIENT_CAPITAL
    assert "available" in repay.rejection_reason


def test_self_funded_rescue_still_runs_when_the_wallet_is_empty():
    broke = RiskPreferences(available_capital=0.0)
    decision = strategy_engine.evaluate(DROPPED, broke, MARKET)

    assert decision.selected_strategy is not None
    assert decision.selected_strategy.required_capital == 0.0
    assert decision.execution_status is ExecutionStatus.EXECUTED


# ---------------------------------------------------------------------------
# Edge case 7: cannot restore the target Health Factor
# ---------------------------------------------------------------------------

def test_partial_repayment_is_marked_invalid():
    partial = _by_type(
        strategy_engine.generate(DROPPED, PREFS, MARKET),
        StrategyType.PARTIAL_DELEVERAGE,
    )
    assert partial.status is StrategyStatus.INVALID_CANNOT_REACH_TARGET
    assert partial.resulting_health_factor < PREFS.target_health_factor
    assert "short of" in partial.rejection_reason
    assert partial.score == 0.0


def test_deleveraging_cannot_save_an_insolvent_position():
    """Once collateral is worth less than the debt it secures, selling
    collateral to repay can never close the gap -- the swap gives up more value
    than it retires. Externally funded rescues still work, so this is a
    per-strategy invalidation, not a dead end."""
    insolvent = SEED.with_price(1200.0)  # $4,000 collateral against $5,000 debt
    assert risk_engine.health_factor(insolvent) < 1.0

    strategies = strategy_engine.generate(insolvent, PREFS, MarketConditions(eth_price=1200.0))
    swap = _by_type(strategies, StrategyType.COLLATERAL_SWAP)
    flash = _by_type(strategies, StrategyType.FLASH_LOAN_DELEVERAGE)

    assert swap.status is StrategyStatus.INVALID_CANNOT_REACH_TARGET
    assert flash.status is StrategyStatus.INVALID_CANNOT_REACH_TARGET
    assert _by_type(strategies, StrategyType.REPAY_DEBT).status is StrategyStatus.VIABLE


def test_deleveraging_can_reach_an_aggressive_target_on_a_solvent_position():
    """Guards the test above: the invalidation is about solvency, not about
    the target being large."""
    strict = RiskPreferences(target_health_factor=4.0, trigger_health_factor=3.0)
    swap = _by_type(
        strategy_engine.generate(DROPPED, strict, MARKET), StrategyType.COLLATERAL_SWAP
    )
    assert swap.status is StrategyStatus.VIABLE
    assert swap.resulting_health_factor >= 4.0 - 1e-6


# ---------------------------------------------------------------------------
# Scoring and selection
# ---------------------------------------------------------------------------

def test_scores_are_bounded_and_only_viable_candidates_score():
    strategies = strategy_engine.score_all(
        strategy_engine.generate(DROPPED, PREFS, MARKET), DROPPED, PREFS, MARKET
    )
    for s in strategies:
        assert 0.0 <= s.score <= 1.0
        if not s.is_executable:
            assert s.score == 0.0
            assert s.score_breakdown == {}
        else:
            assert set(s.score_breakdown) == {
                "safety", "cost", "slippage", "liquidity", "capital"
            }


def test_score_all_returns_viable_candidates_first():
    strategies = strategy_engine.score_all(
        strategy_engine.generate(DROPPED, PREFS, MARKET), DROPPED, PREFS, MARKET
    )
    executable = [s.is_executable for s in strategies]
    assert executable == sorted(executable, reverse=True)


def test_selection_picks_the_highest_scoring_viable_strategy():
    strategies = strategy_engine.score_all(
        strategy_engine.generate(DROPPED, PREFS, MARKET), DROPPED, PREFS, MARKET
    )
    best = strategy_engine.select_best(strategies)
    assert best is not None
    assert best.score == max(s.score for s in strategies if s.is_executable)
    assert sum(1 for s in strategies if s.selected) == 1


def test_default_profile_selects_the_wallet_repayment():
    """The balanced profile picks `Repay debt from wallet` over the strictly
    cheaper collateral top-up, because the top-up locks up $3,000 of idle
    capital against the repayment's $1,250. Cost is one term in the composite,
    not the whole of it -- this test exists so that stays true."""
    decision = strategy_engine.evaluate(DROPPED, PREFS, MARKET)
    winner = decision.selected_strategy
    topup = _by_type(decision.strategies, StrategyType.ADD_COLLATERAL)

    assert winner.strategy_type is StrategyType.REPAY_DEBT
    assert topup.total_cost < winner.total_cost          # top-up is cheaper...
    assert topup.score < winner.score                    # ...and still loses
    assert winner.score_breakdown["capital"] > topup.score_breakdown["capital"]


def test_capital_averse_preferences_switch_the_selection_to_a_self_funded_route():
    """Turning the capital weight up should change what the agent picks --
    proof the score is actually driving selection, not a hard-coded ranking."""
    capital_averse = RiskPreferences(
        weight_safety=0.20,
        weight_cost=0.05,
        weight_slippage=0.05,
        weight_liquidity=0.05,
        weight_capital=0.65,
    )
    decision = strategy_engine.evaluate(DROPPED, capital_averse, MARKET)
    assert decision.selected_strategy.required_capital == 0.0


def test_weights_are_normalised_so_they_need_not_sum_to_one():
    doubled = RiskPreferences(
        weight_safety=0.80,
        weight_cost=0.50,
        weight_slippage=0.30,
        weight_liquidity=0.20,
        weight_capital=0.20,
    )
    a = strategy_engine.evaluate(DROPPED, RiskPreferences(), MARKET)
    b = strategy_engine.evaluate(DROPPED, doubled, MARKET)
    assert a.selected_strategy.score == pytest.approx(b.selected_strategy.score)


def test_explanation_names_the_strategy_and_the_deciding_factor():
    decision = strategy_engine.evaluate(DROPPED, PREFS, MARKET)
    assert decision.selected_strategy.name in decision.explanation
    assert "selected" in decision.explanation
    assert "scored" in decision.explanation or "only candidate" in decision.explanation


# ---------------------------------------------------------------------------
# Edge cases 1 and 6: nothing to do
# ---------------------------------------------------------------------------

def test_safe_position_needs_no_rescue():
    decision = strategy_engine.evaluate(SEED, PREFS, MarketConditions())

    assert decision.assessment.risk_level is RiskLevel.WARNING
    assert decision.execution_status is ExecutionStatus.NO_ACTION_REQUIRED
    assert decision.shield_state is ShieldState.ARMED
    assert decision.strategies == []
    assert decision.selected_strategy is None


def test_minimum_repayment_is_zero_above_the_target():
    """Edge case 6: a position already at or above the target needs no
    repayment at all, and the sizing function says so rather than returning a
    small positive placeholder."""
    comfortable = Position(debt_amount=2_000.0)  # HF 3.125, well above target
    assert risk_engine.assess(comfortable, PREFS).requires_action is False
    assert (
        risk_engine.minimum_repayment_to_target(comfortable, PREFS.target_health_factor)
        == 0.0
    )
    decision = strategy_engine.evaluate(comfortable, PREFS, MarketConditions())
    assert decision.execution_status is ExecutionStatus.NO_ACTION_REQUIRED


def test_zero_debt_position_needs_no_rescue():
    decision = strategy_engine.evaluate(Position(debt_amount=0.0), PREFS, MARKET)
    assert decision.execution_status is ExecutionStatus.NO_ACTION_REQUIRED
    assert "No outstanding debt" in decision.explanation


# ---------------------------------------------------------------------------
# Edge case 2: risky position -> autonomous rescue
# ---------------------------------------------------------------------------

def test_risky_position_auto_selects_a_strategy():
    decision = strategy_engine.evaluate(DROPPED, PREFS, MARKET)

    assert decision.assessment.requires_action is True
    assert decision.selected_strategy is not None
    assert decision.execution_status is ExecutionStatus.EXECUTED
    assert decision.shield_state is ShieldState.PROTECTING


def test_executing_the_selected_strategy_restores_the_target():
    decision = strategy_engine.evaluate(DROPPED, PREFS, MARKET)
    after = strategy_engine.apply_strategy(DROPPED, decision.selected_strategy)
    assert risk_engine.health_factor(after) >= PREFS.target_health_factor - 1e-6


def test_advisory_mode_waits_for_confirmation():
    advisory = RiskPreferences(mode=ProtectionMode.ADVISORY)
    decision = strategy_engine.evaluate(DROPPED, advisory, MARKET)

    assert decision.selected_strategy is not None
    assert decision.execution_status is ExecutionStatus.AWAITING_CONFIRMATION
    assert decision.shield_state is ShieldState.ALERT
    assert "awaiting confirmation" in decision.explanation.lower()


def test_both_modes_choose_the_same_strategy():
    """Advisory mode changes who pulls the trigger, never the reasoning."""
    auto = strategy_engine.evaluate(DROPPED, RiskPreferences(), MARKET)
    advisory = strategy_engine.evaluate(
        DROPPED, RiskPreferences(mode=ProtectionMode.ADVISORY), MARKET
    )
    assert (
        auto.selected_strategy.strategy_type
        is advisory.selected_strategy.strategy_type
    )


# ---------------------------------------------------------------------------
# Edge case 5: rescue costs more than the liquidation would
# ---------------------------------------------------------------------------

SMALL = Position(collateral_amount=0.3, debt_amount=500.0, collateral_price=3000.0)
EXPENSIVE_GAS = MarketConditions(eth_price=3000.0, gas_price_gwei=60.0)


def test_the_small_position_is_genuinely_at_risk():
    """Guards the test below: this must be a real rescue decision, not a
    position that was safe all along."""
    assert risk_engine.health_factor(SMALL) == pytest.approx(1.125, abs=1e-6)
    assert risk_engine.assess(SMALL, PREFS).requires_action is True


def test_rescue_is_skipped_when_uneconomical():
    decision = strategy_engine.evaluate(SMALL, PREFS, EXPENSIVE_GAS)

    assert decision.execution_status is ExecutionStatus.SKIPPED_UNECONOMICAL
    assert decision.shield_state is ShieldState.SKIPPED
    assert decision.selected_strategy is None
    assert decision.explanation.startswith(strategy_engine.SKIP_UNECONOMICAL)
    assert decision.economics["net_benefit"] < 0


def test_the_same_position_is_rescued_when_gas_is_cheap():
    """The viability gate is a real comparison, not a permanent veto."""
    cheap = MarketConditions(eth_price=3000.0, gas_price_gwei=1.0)
    decision = strategy_engine.evaluate(SMALL, PREFS, cheap)
    assert decision.execution_status is ExecutionStatus.EXECUTED


def test_viability_check_reports_both_sides_of_the_comparison():
    strategies = strategy_engine.score_all(
        strategy_engine.generate(DROPPED, PREFS, MARKET), DROPPED, PREFS, MARKET
    )
    best = strategy_engine.select_best(strategies)
    ok, economics = strategy_engine.check_economic_viability(best, DROPPED)

    assert ok is True
    assert economics["potential_loss"] == pytest.approx(125.0)
    assert economics["net_benefit"] == pytest.approx(
        economics["potential_loss"] - economics["rescue_cost"], abs=0.01
    )


# ---------------------------------------------------------------------------
# Edge case 8: invalid input
# ---------------------------------------------------------------------------

def test_invalid_position_is_rejected():
    with pytest.raises(ValidationError):
        strategy_engine.evaluate(Position(collateral_amount=-5.0), PREFS, MARKET)


def test_invalid_preferences_are_rejected():
    with pytest.raises(ValidationError):
        strategy_engine.evaluate(DROPPED, RiskPreferences(target_health_factor=0.9), MARKET)


def test_zero_weights_are_rejected():
    zeroed = RiskPreferences(
        weight_safety=0.0,
        weight_cost=0.0,
        weight_slippage=0.0,
        weight_liquidity=0.0,
        weight_capital=0.0,
    )
    with pytest.raises(ValidationError):
        strategy_engine.evaluate(DROPPED, zeroed, MARKET)


# ---------------------------------------------------------------------------
# Serialisation (the API layer depends on this)
# ---------------------------------------------------------------------------

def test_decision_serialises_to_json_safe_primitives():
    import json

    decision = strategy_engine.evaluate(DROPPED, PREFS, MARKET)
    payload = json.dumps(decision.to_dict())
    assert "PROTECTING" in payload
    assert "EXECUTED" in payload

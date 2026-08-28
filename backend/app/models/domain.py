"""Core domain objects for the Automated Liquidation Shield.

Everything in this module is protocol-agnostic and pure data. No I/O, no
blockchain calls, no framework imports -- so the engines that consume these
objects stay unit-testable in isolation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    """Risk classification for a lending position.

    Bands are expressed in Health Factor terms. See risk_engine.classify_risk
    for the exact thresholds.
    """

    SAFE = "SAFE"
    WARNING = "WARNING"
    DANGER = "DANGER"
    LIQUIDATABLE = "LIQUIDATABLE"


class ShieldState(str, Enum):
    """State machine driven by the agent and mirrored in the UI status bar.

    The backend is the only authority on this value. The UI renders whatever
    state the engine reports for a stage; it never asserts one of its own.
    """

    ARMED = "ARMED"              # watching, nothing to do
    ALERT = "ALERT"              # risk detected, strategies being generated
    PROTECTING = "PROTECTING"    # a rescue is executing
    PROTECTED = "PROTECTED"      # the rescue landed, target restored
    SKIPPED = "SKIPPED"          # risk detected, rescue deliberately not run


class CycleStage(str, Enum):
    """Ordered stages of one agent cycle, as reported in the decision trace."""

    MONITOR = "MONITOR"
    SHOCK = "SHOCK"
    ASSESS = "ASSESS"
    GENERATE = "GENERATE"
    SCORE = "SCORE"
    SELECT = "SELECT"
    HOLD = "HOLD"                # advisory mode, waiting on the user
    STAND_DOWN = "STAND_DOWN"    # no viable or worthwhile rescue
    EXECUTE = "EXECUTE"
    SETTLE = "SETTLE"
    REARM = "REARM"


class StrategyType(str, Enum):
    REPAY_DEBT = "REPAY_DEBT"
    ADD_COLLATERAL = "ADD_COLLATERAL"
    COLLATERAL_SWAP = "COLLATERAL_SWAP"
    FLASH_LOAN_DELEVERAGE = "FLASH_LOAN_DELEVERAGE"
    PARTIAL_DELEVERAGE = "PARTIAL_DELEVERAGE"


class StrategyStatus(str, Enum):
    """Why a candidate strategy is, or is not, executable."""

    VIABLE = "VIABLE"
    REJECTED_HIGH_SLIPPAGE = "REJECTED_HIGH_SLIPPAGE"
    REJECTED_INSUFFICIENT_LIQUIDITY = "REJECTED_INSUFFICIENT_LIQUIDITY"
    REJECTED_INSUFFICIENT_CAPITAL = "REJECTED_INSUFFICIENT_CAPITAL"
    INVALID_CANNOT_REACH_TARGET = "INVALID_CANNOT_REACH_TARGET"
    NOT_REQUIRED = "NOT_REQUIRED"


class ExecutionStatus(str, Enum):
    NO_ACTION_REQUIRED = "NO_ACTION_REQUIRED"
    EXECUTED = "EXECUTED"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    SKIPPED_UNECONOMICAL = "SKIPPED_UNECONOMICAL"
    SKIPPED_NO_VIABLE_STRATEGY = "SKIPPED_NO_VIABLE_STRATEGY"


class ProtectionMode(str, Enum):
    AUTONOMOUS = "AUTONOMOUS"
    ADVISORY = "ADVISORY"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Position:
    """A single-collateral / single-debt lending position.

    A real deployment carries a basket of collaterals and debts; the MVP models
    the single-asset case the demo exercises. collateral_amount is denominated
    in units of the collateral asset (e.g. ETH), never in USD, so a price move
    re-values it automatically.

    liquidation_threshold is the fraction of collateral value that counts
    toward solvency. The default 0.625 is the demo market tier and is what
    makes the seed position report HF 1.25 exactly:
    $10,000 x 0.625 / $5,000 = 1.25. Real Aave v3 ETH sits at 0.825; override
    per position to model a different market.
    """

    collateral_asset: str = "ETH"
    collateral_amount: float = 10_000.0 / 3_000.0   # ~3.3333 ETH == $10,000
    debt_asset: str = "USDC"
    debt_amount: float = 5_000.0                    # stablecoin debt, 1 unit = $1
    collateral_price: float = 3_000.0
    liquidation_threshold: float = 0.625
    liquidation_bonus: float = 0.05                 # liquidator discount, 5%
    close_factor: float = 0.5                       # max debt repaid per call
    owner_id: Optional[str] = None
    id: Optional[str] = None

    @property
    def collateral_value(self) -> float:
        return self.collateral_amount * self.collateral_price

    @property
    def debt_value(self) -> float:
        """Debt in USD. The debt asset is a stablecoin in this MVP."""
        return self.debt_amount

    def with_price(self, price: float) -> "Position":
        """Return a copy of this position re-priced at the given price."""
        return replace(self, collateral_price=price)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["collateral_value"] = self.collateral_value
        d["debt_value"] = self.debt_value
        return d


@dataclass(frozen=True)
class RiskPreferences:
    """User-tunable knobs, surfaced on the Settings page."""

    target_health_factor: float = 1.5
    trigger_health_factor: float = 1.20
    max_slippage_pct: float = 1.5
    mode: ProtectionMode = ProtectionMode.AUTONOMOUS
    available_capital: float = 4_000.0   # idle wallet funds the agent may use

    # Composite-score weights; validated to sum to 1.0 by the strategy engine.
    weight_safety: float = 0.40
    weight_cost: float = 0.25
    weight_slippage: float = 0.15
    weight_liquidity: float = 0.10
    weight_capital: float = 0.10

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["mode"] = self.mode.value
        return d


@dataclass(frozen=True)
class MarketConditions:
    """Simulated on-chain conditions.

    This is the seam where real data goes later: swap this for a provider that
    reads a Chainlink feed, the DEX subgraph and a gas oracle. Nothing
    downstream knows the numbers are synthetic.
    """

    eth_price: float = 3_000.0
    """Price of ETH in USD.

    Used for exactly one thing: converting a gas estimate (denominated in ETH)
    into dollars. It is NOT the collateral price. A position collateralised in
    BTC still pays gas in ETH, so costing that rescue at the BTC price would
    overstate gas by a factor of twenty.
    """

    gas_price_gwei: float = 20.0
    dex_liquidity_usd: float = 2_000_000.0   # depth of the swap pool
    dex_base_fee_pct: float = 0.05           # static pool fee, percent
    max_pool_utilisation: float = 0.25       # refuse trades above this share
    flash_loan_fee_pct: float = 0.09         # Aave v3 premium, percent

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HealthAssessment:
    health_factor: float
    risk_level: RiskLevel
    collateral_value: float
    debt_value: float
    liquidation_price: float
    price_drop_to_liquidation_pct: float
    safety_buffer_pct: float
    potential_liquidation_loss: float
    requires_action: bool
    message: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["risk_level"] = self.risk_level.value
        return d


@dataclass
class Scenario:
    label: str
    price_drop_pct: float
    new_price: float
    new_collateral_value: float
    health_factor: float
    risk_level: RiskLevel
    liquidatable: bool
    requires_intervention: bool
    """True when this rung sits at or below the user's intervention trigger.

    Distinct from `liquidatable`: the agent acts *before* the liquidation line,
    so a scenario can require intervention while still being solvent.
    """

    required_repayment: float
    required_collateral_topup: float
    intervention_summary: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["risk_level"] = self.risk_level.value
        return d


@dataclass
class Strategy:
    strategy_type: StrategyType
    name: str
    description: str
    action_amount: float
    required_capital: float
    resulting_health_factor: float
    resulting_risk_level: RiskLevel
    slippage_pct: float
    slippage_cost: float
    gas_cost: float
    flash_loan_fee: float
    total_cost: float
    status: StrategyStatus
    rejection_reason: Optional[str] = None
    acceptance_reason: Optional[str] = None
    score: float = 0.0
    score_breakdown: Dict[str, float] = field(default_factory=dict)
    selected: bool = False

    @property
    def is_executable(self) -> bool:
        return self.status is StrategyStatus.VIABLE

    @property
    def score_100(self) -> int:
        """The composite score on a 0-100 scale, for display.

        The same deterministic number as `score`, rescaled. Rejected candidates
        score zero and are never selectable.
        """
        return round(self.score * 100)

    @property
    def safety_level(self) -> Optional[str]:
        """Plain-language reading of the safety sub-score.

        Derived from the same figure that feeds the composite, so the label can
        never disagree with the ranking. None for non-viable candidates, which
        have no meaningful safety at all.
        """
        if not self.is_executable:
            return None
        safety = self.score_breakdown.get("safety")
        if safety is None:
            return None
        if safety >= 0.90:
            return "HIGH"
        if safety >= 0.75:
            return "MEDIUM"
        return "LOW"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["strategy_type"] = self.strategy_type.value
        d["resulting_risk_level"] = self.resulting_risk_level.value
        d["status"] = self.status.value
        d["is_executable"] = self.is_executable
        d["score_100"] = self.score_100
        d["safety_level"] = self.safety_level
        return d


@dataclass
class TraceStep:
    """One stage of the agent cycle, with the state the engine was in for it.

    The UI walks these in order to animate the status bar. Both the state and
    the numbers quoted in the text are computed here, so the transition the
    user watches is the transition the engine actually performed.
    """

    stage: CycleStage
    shield_state: ShieldState
    label: str
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage.value,
            "shield_state": self.shield_state.value,
            "label": self.label,
            "detail": self.detail,
        }


@dataclass
class ProtectionDecision:
    """The agent's full reasoning trace for one evaluation cycle."""

    assessment: HealthAssessment
    strategies: List[Strategy]
    selected_strategy: Optional[Strategy]
    execution_status: ExecutionStatus
    shield_state: ShieldState
    explanation: str
    economics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assessment": self.assessment.to_dict(),
            "strategies": [s.to_dict() for s in self.strategies],
            "selected_strategy": (
                self.selected_strategy.to_dict() if self.selected_strategy else None
            ),
            "execution_status": self.execution_status.value,
            "shield_state": self.shield_state.value,
            "explanation": self.explanation,
            "economics": self.economics,
        }


class ValidationError(ValueError):
    """Raised for structurally invalid position or preference input."""

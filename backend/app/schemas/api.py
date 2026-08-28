"""Pydantic request/response schemas.

The schemas own input validation of *shape* (types, ranges a value can never
sensibly take). Domain validation -- whether a combination of values makes
economic sense -- stays in the risk engine, so the rules are enforced once and
tested once. See `edge case 8` handling in both layers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..services import assets

#: The seed demo holding: ~3.3333 ETH, worth $10,000 at $3,000.
DEFAULT_COLLATERAL_AMOUNT = 10_000.0 / 3_000.0
from ..models.domain import (
    MarketConditions,
    Position,
    ProtectionMode,
    RiskPreferences,
)


# ---------------------------------------------------------------------------
# Inbound
# ---------------------------------------------------------------------------

class PositionIn(BaseModel):
    """A lending position as supplied by the client.

    The risk parameters (liquidation threshold, penalty, close factor) are
    properties of the lending market, not of the borrower. A user picks an
    asset; the server resolves the parameters from the asset catalogue. Sending
    them explicitly is still allowed -- that is how you model a market other
    than the simulated one -- but the browser never has to know them.
    """

    model_config = ConfigDict(extra="forbid")

    collateral_asset: str = "ETH"
    collateral_amount: Optional[float] = Field(
        default=None,
        ge=0,
        description="Units of the collateral asset, not dollars.",
    )
    collateral_value: Optional[float] = Field(
        default=None,
        ge=0,
        description=(
            "Collateral in USD, as an alternative to collateral_amount. "
            "The server converts it to units at collateral_price, because the "
            "engines must hold units -- that is what lets a price shock "
            "re-value the position. Supply one or the other, not both."
        ),
    )
    debt_asset: str = "USDC"
    debt_amount: float = Field(default=5_000.0, ge=0)
    collateral_price: float = Field(default=3_000.0, gt=0)

    # Resolved from the asset catalogue when omitted.
    liquidation_threshold: Optional[float] = Field(default=None, gt=0, le=1)
    liquidation_bonus: Optional[float] = Field(default=None, ge=0, lt=1)
    close_factor: Optional[float] = Field(default=None, gt=0, le=1)
    id: Optional[str] = None

    @field_validator("collateral_asset")
    @classmethod
    def _known_collateral(cls, value: str) -> str:
        if not assets.is_supported(value):
            supported = ", ".join(assets.ASSETS)
            raise ValueError(f"Unsupported collateral asset. Choose one of: {supported}.")
        return value.strip().upper()

    @field_validator("debt_asset")
    @classmethod
    def _stable_debt(cls, value: str) -> str:
        symbol = value.strip().upper()
        if symbol not in assets.DEBT_ASSETS:
            allowed = ", ".join(assets.DEBT_ASSETS)
            raise ValueError(
                "Debt must be a stablecoin in this simulation, because the risk "
                f"engine values debt at $1 per unit. Choose one of: {allowed}."
            )
        return symbol

    @property
    def resolved_collateral_amount(self) -> float:
        """Collateral in UNITS, however the client chose to express it.

        Units are the engine's currency, not dollars: a price shock re-values a
        holding automatically only if the holding is stored as a quantity. A
        dollar figure would be frozen at the price it was entered at, which
        would quietly break every scenario projection.
        """
        if self.collateral_amount is not None:
            return self.collateral_amount
        if self.collateral_value is not None:
            return self.collateral_value / self.collateral_price
        return DEFAULT_COLLATERAL_AMOUNT

    @model_validator(mode="after")
    def _one_way_of_expressing_collateral(self) -> "PositionIn":
        if self.collateral_amount is not None and self.collateral_value is not None:
            raise ValueError(
                "Give either collateral_amount (units) or collateral_value "
                "(USD), not both -- two sources of truth would silently "
                "disagree the moment the price moved."
            )
        return self

    @model_validator(mode="after")
    def _debt_needs_collateral(self) -> "PositionIn":
        if self.resolved_collateral_amount <= 0 and self.debt_amount > 0:
            raise ValueError(
                "A position with debt must have collateral securing it. Enter a "
                "collateral amount greater than zero."
            )
        return self

    def to_domain(self, owner_id: Optional[str] = None) -> Position:
        spec = assets.get(self.collateral_asset)
        return Position(
            collateral_asset=spec.symbol,
            collateral_amount=self.resolved_collateral_amount,
            debt_asset=self.debt_asset,
            debt_amount=self.debt_amount,
            collateral_price=self.collateral_price,
            liquidation_threshold=(
                self.liquidation_threshold
                if self.liquidation_threshold is not None
                else spec.liquidation_threshold
            ),
            liquidation_bonus=(
                self.liquidation_bonus
                if self.liquidation_bonus is not None
                else spec.liquidation_bonus
            ),
            close_factor=(
                self.close_factor if self.close_factor is not None else spec.close_factor
            ),
            owner_id=owner_id,
            id=self.id,
        )


class PreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_health_factor: float = Field(default=1.5, gt=1.0, le=10.0)
    trigger_health_factor: float = Field(default=1.20, gt=1.0, le=10.0)
    max_slippage_pct: float = Field(default=1.5, gt=0, le=100)
    mode: ProtectionMode = ProtectionMode.AUTONOMOUS
    available_capital: float = Field(default=4_000.0, ge=0)
    weight_safety: float = Field(default=0.40, ge=0, le=1)
    weight_cost: float = Field(default=0.25, ge=0, le=1)
    weight_slippage: float = Field(default=0.15, ge=0, le=1)
    weight_liquidity: float = Field(default=0.10, ge=0, le=1)
    weight_capital: float = Field(default=0.10, ge=0, le=1)

    def to_domain(self) -> RiskPreferences:
        return RiskPreferences(**self.model_dump())


class MarketIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eth_price: Optional[float] = Field(default=None, gt=0)
    gas_price_gwei: float = Field(default=20.0, gt=0)
    dex_liquidity_usd: float = Field(default=2_000_000.0, gt=0)
    dex_base_fee_pct: float = Field(default=0.05, ge=0, le=100)
    max_pool_utilisation: float = Field(default=0.25, gt=0, le=1)
    flash_loan_fee_pct: float = Field(default=0.09, ge=0, le=100)

    def to_domain(self, fallback_price: float) -> MarketConditions:
        """`fallback_price` is the configured ETH price, NOT the collateral
        price -- gas is paid in ETH whatever the collateral happens to be."""
        data = self.model_dump()
        data["eth_price"] = self.eth_price or fallback_price
        return MarketConditions(**data)


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: PositionIn = Field(default_factory=PositionIn)
    preferences: PreferencesIn = Field(default_factory=PreferencesIn)
    persist: bool = True


class ScenarioRequest(AnalyzeRequest):
    price_drops: Optional[List[float]] = Field(
        default=None,
        description="Percentage drops to simulate. Defaults to 0/5/10/15/20.",
    )


class StrategyRequest(AnalyzeRequest):
    market: MarketIn = Field(default_factory=MarketIn)


class RescueRequest(StrategyRequest):
    """Autonomous execution request.

    `confirm` is only consulted in Advisory mode: it is the user pressing the
    button on a recommendation the agent already made.
    """

    confirm: bool = False


# ---------------------------------------------------------------------------
# Outbound
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    persistence: str
    engines: Dict[str, str]


class AnalyzeResponse(BaseModel):
    position: Dict[str, Any]
    assessment: Dict[str, Any]
    preferences: Dict[str, Any]


class ScenarioResponse(BaseModel):
    position: Dict[str, Any]
    scenarios: List[Dict[str, Any]]
    summary: str
    first_breaking_scenario: Optional[Dict[str, Any]] = None
    thresholds: Dict[str, float] = Field(
        default_factory=dict,
        description="The lines the chart marks: liquidation, trigger, target.",
    )


class StrategiesResponse(BaseModel):
    position: Dict[str, Any]
    assessment: Dict[str, Any]
    strategies: List[Dict[str, Any]]
    selected_strategy: Optional[Dict[str, Any]] = None
    explanation: str
    market: Dict[str, Any]


class ComparisonRow(BaseModel):
    strategy_type: str
    name: str
    description: str
    action_amount: float
    resulting_health_factor: float
    resulting_risk_level: str
    required_capital: float
    slippage_pct: float
    gas_cost: float
    flash_loan_fee: float
    total_cost: float
    status: str
    score: float
    score_breakdown: Dict[str, float]
    selected: bool
    rejection_reason: Optional[str] = None


class ComparisonResponse(BaseModel):
    rows: List[ComparisonRow]
    selected_strategy: Optional[Dict[str, Any]] = None
    explanation: str
    weights: Dict[str, float]


class ValidationResponse(BaseModel):
    """Result of the pre-flight economic and constraint checks."""

    can_execute: bool
    reason: str
    execution_status: str
    shield_state: str
    economics: Dict[str, Any]
    selected_strategy: Optional[Dict[str, Any]] = None


class RescueResponse(BaseModel):
    executed: bool
    simulated: bool = True
    execution_status: str
    shield_state: str
    explanation: str
    economics: Dict[str, Any]
    selected_strategy: Optional[Dict[str, Any]] = None
    strategies: List[Dict[str, Any]] = []
    assessment_before: Dict[str, Any]
    assessment_after: Optional[Dict[str, Any]] = None
    position_after: Optional[Dict[str, Any]] = None
    transaction: Optional[Dict[str, Any]] = None


class CycleRequest(StrategyRequest):
    """Run one full agent cycle against a price shock.

    The shock is applied server-side: the client sends a percentage, never a
    recalculated price.
    """

    price_drop_pct: float = Field(
        default=10.0,
        ge=0,
        lt=100,
        description="Percentage drop to apply to the collateral price.",
    )
    confirm: bool = Field(
        default=False,
        description="Advisory mode only: authorise the recommendation.",
    )


class HistoryResponse(BaseModel):
    transactions: List[Dict[str, Any]]
    persistence: str


class ErrorResponse(BaseModel):
    detail: str
    error_type: str = "validation_error"

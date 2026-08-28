"""Supported collateral assets and their simulated market parameters.

WHY THIS EXISTS
---------------
A user entering their own position picks an asset, not a liquidation
threshold. The threshold, liquidation penalty and close factor are properties
of the lending market, not of the borrower -- so they live here and are
resolved server-side. The browser never chooses a risk parameter.

SIMULATED TIERS -- READ THIS
---------------------------
`liquidation_threshold` below is the tier used by *this simulation*. It is not
scraped from a live protocol. Each entry carries `real_world_threshold` for
comparison, and every asset here is deliberately more conservative than its
mainnet counterpart, so a position that looks safe in the simulator would look
safer still on Aave.

The ETH tier of 0.625 in particular is what makes the seed demo position report
Health Factor 1.25 on $10,000 of collateral against $5,000 of debt. Aave v3
uses 0.825 for ETH; a user who wants to model the real market can override the
threshold per position via the API's `liquidation_threshold` field.

Swapping this module for a live `getReserveConfigurationData` read is the whole
of the work needed to make these numbers real.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from ..models.domain import ValidationError


@dataclass(frozen=True)
class AssetSpec:
    symbol: str
    name: str
    liquidation_threshold: float
    """Fraction of this asset's value that counts toward solvency."""

    liquidation_bonus: float
    """Discount a liquidator receives on seized collateral."""

    close_factor: float
    """Maximum fraction of debt one liquidation call may repay."""

    reference_price: float
    """Seed price for the input form. The user can type any price they like."""

    real_world_threshold: float
    """The equivalent Aave v3 mainnet tier, for comparison in the UI."""

    is_stable: bool = False
    price_decimals: int = 2
    """Display precision. A $0.80 token needs more than a $60,000 one."""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Ordered as the form's dropdown renders them: most-used first.
ASSETS: Dict[str, AssetSpec] = {
    a.symbol: a
    for a in (
        AssetSpec(
            symbol="ETH",
            name="Ether",
            liquidation_threshold=0.625,
            liquidation_bonus=0.05,
            close_factor=0.5,
            reference_price=3_000.0,
            real_world_threshold=0.825,
            price_decimals=0,
        ),
        AssetSpec(
            symbol="BTC",
            name="Bitcoin (wrapped)",
            liquidation_threshold=0.65,
            liquidation_bonus=0.06,
            close_factor=0.5,
            reference_price=60_000.0,
            real_world_threshold=0.78,
            price_decimals=0,
        ),
        AssetSpec(
            symbol="USDC",
            name="USD Coin",
            liquidation_threshold=0.85,
            liquidation_bonus=0.04,
            close_factor=0.5,
            reference_price=1.0,
            real_world_threshold=0.87,
            is_stable=True,
            price_decimals=4,
        ),
        AssetSpec(
            symbol="DAI",
            name="Dai",
            liquidation_threshold=0.80,
            liquidation_bonus=0.05,
            close_factor=0.5,
            reference_price=1.0,
            real_world_threshold=0.82,
            is_stable=True,
            price_decimals=4,
        ),
        AssetSpec(
            symbol="SOL",
            name="Solana",
            liquidation_threshold=0.55,
            liquidation_bonus=0.08,
            close_factor=0.5,
            reference_price=150.0,
            real_world_threshold=0.65,
        ),
        AssetSpec(
            symbol="LINK",
            name="Chainlink",
            liquidation_threshold=0.55,
            liquidation_bonus=0.07,
            close_factor=0.5,
            reference_price=15.0,
            real_world_threshold=0.68,
        ),
        AssetSpec(
            symbol="ARB",
            name="Arbitrum",
            liquidation_threshold=0.45,
            liquidation_bonus=0.09,
            close_factor=0.5,
            reference_price=0.80,
            real_world_threshold=0.55,
            price_decimals=4,
        ),
    )
}

DEFAULT_ASSET = "ETH"

#: Assets that may be borrowed. The risk engine assumes debt is worth exactly
#: $1 per unit, so only stablecoins qualify until a debt price feed exists.
DEBT_ASSETS = [symbol for symbol, spec in ASSETS.items() if spec.is_stable]
DEFAULT_DEBT_ASSET = "USDC"


def get(symbol: Optional[str]) -> AssetSpec:
    """Look up an asset, with a friendly error for anything unsupported."""
    if not symbol:
        return ASSETS[DEFAULT_ASSET]
    spec = ASSETS.get(symbol.strip().upper())
    if spec is None:
        supported = ", ".join(ASSETS)
        raise ValidationError(
            f"{symbol} is not a supported collateral asset. Choose one of: {supported}."
        )
    return spec


def is_supported(symbol: Optional[str]) -> bool:
    return bool(symbol) and symbol.strip().upper() in ASSETS


def catalogue() -> List[Dict[str, Any]]:
    """The full list, in dropdown order, for the input form."""
    return [spec.to_dict() for spec in ASSETS.values()]

"""Settlement layer: where a protection strategy becomes a transaction.

WHAT THIS IS
------------
The seam between "the agent decided what to do" and "it was done". Today the
only implementation is `SimulatedSettlement`, which produces a receipt without
touching any network. It exists as a separate layer -- rather than a few lines
inline in a route -- so that adding a real testnet adapter later is a matter of
writing one class and changing one factory, with no route, engine or frontend
change.

WHY NOT A REAL CHAIN
--------------------
This build has no wallet, no signer, no RPC endpoint and no contract. Rather
than half-build one for a demo, execution is simulated and labelled as such
everywhere it surfaces:

  * every hash is prefixed `0xSIM`, which is not a valid transaction hash
  * `simulated` is True and `settlement` is "SIMULATED" on every receipt
  * `network` is "simulated", never a chain name

Nothing here should ever be mistakable for a confirmation. A simulated receipt
does not claim a block number, a confirmation count or a gas receipt, because
inventing those is precisely the kind of fake that makes a demo dishonest.

ADDING A TESTNET LATER
----------------------
Implement `Settlement.execute` against a testnet signer and return a receipt
with `simulated=False`, `settlement="TESTNET"`, `network="sepolia"` and the
real hash. `get_settlement()` picks the implementation; everything upstream is
already written against the interface. Never wire a mainnet signer or a real
user key into this.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol

from ..models.domain import Position, Strategy

#: Prefix that marks a hash as fabricated. Deliberately not valid hex-64.
SIMULATED_HASH_PREFIX = "0xSIM"

STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
SETTLEMENT_SIMULATED = "SIMULATED"


@dataclass
class ExecutionReceipt:
    """The record of one protection execution.

    Deliberately flat: it is written straight to the rescue history and read
    straight by the dashboard.
    """

    tx_hash: str
    network: str
    settlement: str
    status: str
    simulated: bool
    executed_at: str

    strategy_type: Optional[str]
    strategy_name: Optional[str]
    action_amount: float
    total_cost: float

    health_factor_before: float
    health_factor_after: float
    collateral_price: float

    mode: Optional[str] = None
    reason: str = ""
    #: True when a human pressed the button rather than the agent acting alone.
    user_initiated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Settlement(Protocol):
    """Anything that can turn a chosen strategy into a receipt."""

    name: str

    def execute(
        self,
        *,
        position: Position,
        strategy: Strategy,
        health_factor_before: float,
        health_factor_after: float,
        mode: Optional[str] = None,
        reason: str = "",
        user_initiated: bool = False,
    ) -> ExecutionReceipt: ...


class SimulatedSettlement:
    """Produces a receipt without touching a network.

    The Health Factors are passed in rather than recomputed here: the risk
    engine is the single authority on what a position is worth, and a
    settlement layer that did its own arithmetic could disagree with it.
    """

    name = "simulated"

    def execute(
        self,
        *,
        position: Position,
        strategy: Strategy,
        health_factor_before: float,
        health_factor_after: float,
        mode: Optional[str] = None,
        reason: str = "",
        user_initiated: bool = False,
    ) -> ExecutionReceipt:
        return ExecutionReceipt(
            tx_hash=SIMULATED_HASH_PREFIX + uuid.uuid4().hex[:58],
            network="simulated",
            settlement=SETTLEMENT_SIMULATED,
            status=STATUS_SUCCESS,
            simulated=True,
            executed_at=datetime.now(timezone.utc).isoformat(),
            strategy_type=strategy.strategy_type.value,
            strategy_name=strategy.name,
            action_amount=strategy.action_amount,
            total_cost=strategy.total_cost,
            health_factor_before=round(health_factor_before, 4),
            health_factor_after=round(health_factor_after, 4),
            collateral_price=position.collateral_price,
            mode=mode,
            reason=reason,
            user_initiated=user_initiated,
        )


_settlement: Optional[Settlement] = None


def get_settlement() -> Settlement:
    """The active settlement layer.

    One line changes when a testnet adapter arrives. Until then this build has
    exactly one implementation, and it never leaves memory.
    """
    global _settlement
    if _settlement is None:
        _settlement = SimulatedSettlement()
    return _settlement


def describe() -> Dict[str, Any]:
    """What the health endpoint reports about execution."""
    return {
        "settlement": SETTLEMENT_SIMULATED,
        "network": get_settlement().name,
        "signs_transactions": False,
        "uses_real_funds": False,
        "note": (
            "Execution is simulated. No wallet, signer, RPC endpoint or "
            "contract is involved, and no transaction is broadcast."
        ),
    }

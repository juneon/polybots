# core/contracts.py
"""Runtime contracts for the executor/account pair.

runner wires Strategy -> Executor -> Account by duck typing (no inheritance);
these Protocols document the required surface so a new implementation or a
test mock can verify conformance:

    from core.contracts import Account, Executor
    assert isinstance(my_account, Account)     # runtime_checkable: checks
    assert isinstance(my_executor, Executor)   # member PRESENCE, not signatures

Implementations: SimAccount/LiveAccount + SimExecutor/LiveExecutor (core),
ReplayAccount/ReplayExecutor (backtest/engine.py).
Invariants the implementations must keep (SPEC §2.3):
- only status == "filled" trades mutate account state
- executor holds no position state of its own
- account.position is the single source of truth strategies read
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class Executor(Protocol):
    def fill(self, intent: Dict[str, Any], quote_ev: Dict[str, Any], account: Any) -> Dict[str, Any]:
        """Execute one intent, return a trade dict (status: filled|submitted|rejected)."""
        ...


@runtime_checkable
class Account(Protocol):
    cash: float
    position: Optional[Dict[str, Any]]
    state: Dict[str, Any]

    def reset_state(self, slug_idx: int = 0) -> None: ...
    def apply(self, trade: Dict[str, Any]) -> None: ...
    def has_position(self) -> bool: ...
    def position_qty(self) -> float: ...

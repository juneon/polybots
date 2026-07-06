# strategies/base.py
"""Strategy interface.

Core invariants (see SPEC.md):
- The strategy DECIDES only. It never assumes a fill: position truth lives in
  the account (SOT), which the runner passes into on_event.
- Fill feedback arrives via on_trade(trade) — internal counters/locks/cooldowns
  must be updated there (on status "filled"), never at intent time.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List


def make_intent(kind: str, slug: str, tick: int, side: str, price: float,
                qty_tokens: float, time_left_sec: int) -> Dict[str, Any]:
    """Standard intent dict. kind: buy | exit_tp | exit_sl | exit_time."""
    return {
        "type": "intent",
        "kind": kind,
        "slug": slug,
        "tick": int(tick),
        "side": side,
        "price": float(price),
        "qty_tokens": float(qty_tokens),
        "time_left_sec": int(time_left_sec),
        "ts": int(time.time()),  # log-only; decisions must use time_left_sec
    }


class BaseStrategy:
    def on_event(self, ev: Dict[str, Any], account) -> List[Dict[str, Any]]:
        """Consume one event; return 0..n intents. Must not mutate account."""
        return []

    def on_trade(self, trade: Dict[str, Any]) -> None:
        """Fill feedback from the executor. Update internal state on confirmed fills only."""

    def debug_state(self, slug: str) -> Dict[str, Any]:
        """Optional read-only state for the printer (e.g. MA values, locks)."""
        return {}

# core/executor_sim.py
"""Simulated executor: fills every intent at the intent price (100% fill assumption)."""
from __future__ import annotations

import time
from typing import Any, Dict


def _now() -> int:
    return int(time.time())


class SimExecutor:
    def __init__(self, guard: bool = True):
        self.guard = bool(guard)

    def fill(self, intent: Dict[str, Any], quote_ev: Dict[str, Any], account=None) -> Dict[str, Any]:
        kind = str(intent.get("kind", ""))
        side = str(intent.get("side", ""))
        slug = str(quote_ev.get("slug") or intent.get("slug") or "")
        tick = int(quote_ev.get("tick") or intent.get("tick") or 0)

        q = quote_ev.get("quote") or {}
        book = q.get(side) or {}
        token_id = str(book.get("token_id") or "")

        px = float(intent.get("price") or 0.0)
        if self.guard and px <= 0:
            return self._trade(kind, slug, tick, side, "rejected", "bad_price", token_id, 0.0, 0.0)

        qty = float(intent.get("qty_tokens") or 10.0)
        return self._trade(kind, slug, tick, side, "filled", "", token_id, qty, px)

    def _trade(
        self,
        kind: str,
        slug: str,
        tick: int,
        side: str,
        status: str,
        reason: str,
        token_id: str,
        qty_tokens: float,
        fill_price: float,
    ) -> Dict[str, Any]:
        return {
            "type": "trade",
            "kind": kind,
            "slug": slug,
            "tick": int(tick),
            "side": side,
            "ts": _now(),
            "status": status,
            "reason": reason,
            "token_id": token_id,
            "qty_tokens": float(qty_tokens),
            "fill_price": float(fill_price),
            "data": {},
            "debug": {},
        }

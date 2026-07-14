# core/account_sim.py
"""Simulated account (SOT for sim mode). Persists to sim_account.json between runs."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# below this token quantity a position is considered closed (kept consistent with LiveAccount)
DUST_CLEAR_TOKENS = 0.01


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return default if x is None else float(x)
    except Exception:
        return default


class SimAccount:
    """
    Interface expected by runner/strategy/printer/logger:
      - cash: float
      - position: Optional[dict]  ({"side","entry","qty_tokens","notional_usd"})
      - state: dict
      - reset_state(slug_idx)
      - apply(trade)
      - has_position() / position_qty()
    """

    def __init__(self, path: str = "sim_account.json"):
        self.path = str(path)
        self.cash: float = 0.0
        self.position: Optional[Dict[str, Any]] = None
        self.state: Dict[str, Any] = {
            "slug_idx": 0,
            "entries": {"up": 0, "down": 0},
            "tp_done": False,
        }
        self._load()

    def _load(self) -> None:
        p = Path(self.path)
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("sim_account load failed (%s): %r", self.path, e)
            return
        self.cash = _f(data.get("cash"), 0.0)
        self.position = data.get("position") or None
        st = data.get("state") or {}
        if isinstance(st, dict):
            self.state.update(st)

    def _save(self) -> None:
        try:
            Path(self.path).write_text(
                json.dumps(
                    {"cash": self.cash, "position": self.position, "state": self.state},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning("sim_account save failed (%s): %r", self.path, e)

    def reset_state(self, slug_idx: int = 0) -> None:
        self.state = {
            "slug_idx": int(slug_idx),
            "entries": {"up": 0, "down": 0},
            "tp_done": False,
        }

    def drop_position(self) -> Optional[Dict[str, Any]]:
        """Write off a stale carried position (no cash effect — settlement price
        is unknowable after its slug is gone; the slug stays 'unclosed' in
        metrics, which excludes it from realized PnL by definition D10)."""
        dropped, self.position = self.position, None
        self._save()
        return dropped

    def has_position(self) -> bool:
        return bool(self.position) and self.position_qty() > DUST_CLEAR_TOKENS

    def position_qty(self) -> float:
        if not self.position:
            return 0.0
        return _f(self.position.get("qty_tokens"), 0.0)

    def apply(self, trade: Dict[str, Any]) -> None:
        # only confirmed fills mutate the account (core invariant)
        if not isinstance(trade, dict) or trade.get("type") != "trade" or trade.get("status") != "filled":
            return

        kind = str(trade.get("kind", ""))
        side = str(trade.get("side", ""))
        qty = _f(trade.get("qty_tokens"), 0.0)
        px = _f(trade.get("fill_price", trade.get("price")), 0.0)

        if kind == "buy" and qty > 0 and px > 0:
            notional = qty * px
            self.cash -= notional
            # slug pins the position to its own 15-min market: tokens are
            # worthless outside it, so exits against another slug are refused
            self.position = {
                "side": side, "entry": px, "qty_tokens": qty, "notional_usd": notional,
                "slug": str(trade.get("slug", "")),
            }

            ent = self.state.get("entries") or {}
            if isinstance(ent, dict) and side in ent:
                ent[side] = int(ent.get(side, 0)) + 1
                self.state["entries"] = ent

            self._save()
            return

        # EXIT
        if qty <= 0 or not self.position:
            return
        if self.position.get("side") != side:
            return
        # cross-slug exit guard: a carried position must not be "sold" at the
        # next slug's (different token) price — settle/drop happens in runner
        pos_slug = str(self.position.get("slug") or "")
        trade_slug = str(trade.get("slug") or "")
        if pos_slug and trade_slug and pos_slug != trade_slug:
            log.warning("ignoring cross-slug exit: position %s vs trade %s", pos_slug, trade_slug)
            return

        remain = _f(self.position.get("qty_tokens"), 0.0) - qty
        proceeds = qty * (px if px > 0 else _f(trade.get("price"), 0.0))
        self.cash += proceeds

        # consistent with live: dust threshold clears the position
        if remain <= DUST_CLEAR_TOKENS:
            self.position = None
        else:
            entry = _f(self.position.get("entry"), 0.0)
            self.position["qty_tokens"] = remain
            self.position["notional_usd"] = remain * entry

        if kind == "exit_tp":
            self.state["tp_done"] = True

        self._save()

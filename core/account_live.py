# core/account_live.py
"""Live account state (SOT for live mode).

- Only trades with status == "filled" mutate state.
- sync_position(): corrects quantity from CLOB balance right before a SELL
  (balance <= dust is treated as reporting lag unless our own position is dust too).
- reconcile_from_clob(): full position reconciliation at slug boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return default if x is None else float(x)
    except Exception:
        return default


@dataclass
class LivePosition:
    side: str = ""
    token_id: str = ""
    qty_tokens: float = 0.0
    entry_price: float = 0.0

    def is_open(self) -> bool:
        return self.qty_tokens > 0 and bool(self.side) and bool(self.token_id)


class LiveAccount:
    # positions at or below this token quantity are considered closed
    DUST_CLEAR_TOKENS = 0.01

    def __init__(self, cfg: Dict[str, Any]):
        acfg = cfg.get("account", {}) or {}
        self.user = str(acfg.get("user", ""))

        self.live_size_shares = float(acfg.get("buy_size_tokens", 10.0))
        self.cash = float(acfg.get("cash", 0.0) or 0.0)

        self.dust_clear_tokens = float(self.DUST_CLEAR_TOKENS)

        self._pos = LivePosition()
        self.reset_state(0)

    @property
    def position(self) -> Optional[Dict[str, Any]]:
        if not self._pos.is_open():
            return None
        if self._pos.qty_tokens <= self.dust_clear_tokens:
            return None
        return {
            "side": self._pos.side,
            "token_id": self._pos.token_id,
            "entry": float(self._pos.entry_price),
            "qty_tokens": float(self._pos.qty_tokens),
            "notional_usd": float(self._pos.qty_tokens) * float(self._pos.entry_price),
        }

    def reset_state(self, slug_idx: int = 0) -> None:
        self.state = {"slug_idx": int(slug_idx), "entries": {"up": 0, "down": 0}, "tp_done": False}

    def has_position(self) -> bool:
        return self._pos.is_open() and self._pos.qty_tokens > self.dust_clear_tokens

    def position_qty(self) -> float:
        return float(self._pos.qty_tokens)

    def sync_position(self, token_id: str, balance_tokens: float) -> None:
        """Correct quantity from CLOB balance right before a SELL.

        Lagging guard: balance <= dust (especially 0) may just be reporting lag,
        so only clear when our own recorded position is also dust.
        """
        if not self._pos.is_open():
            return
        if str(self._pos.token_id) != str(token_id):
            return

        b = float(balance_tokens)

        if b <= self.dust_clear_tokens:
            if self._pos.qty_tokens <= self.dust_clear_tokens:
                self._pos = LivePosition()
            return

        self._pos.qty_tokens = b

    def reconcile_from_clob(self, quote_updown: Dict[str, Any], up_balance_tokens: float, down_balance_tokens: float) -> None:
        """Slug-boundary reconciliation from up/down CLOB balances.

        Keeps the existing entry price when known; otherwise falls back to that side's bid.
        """
        q = quote_updown or {}
        up = q.get("up") or {}
        dn = q.get("down") or {}

        up_tid = str(up.get("token_id") or "")
        dn_tid = str(dn.get("token_id") or "")

        up_bal = float(up_balance_tokens or 0.0)
        dn_bal = float(down_balance_tokens or 0.0)

        if up_bal <= self.dust_clear_tokens:
            up_bal = 0.0
        if dn_bal <= self.dust_clear_tokens:
            dn_bal = 0.0

        if up_bal <= 0.0 and dn_bal <= 0.0:
            self._pos = LivePosition()
            return

        if up_bal >= dn_bal:
            side, token_id, qty = "up", up_tid, up_bal
            bid = _f(up.get("bid"), 0.0)
        else:
            side, token_id, qty = "down", dn_tid, dn_bal
            bid = _f(dn.get("bid"), 0.0)

        if not token_id or qty <= 0.0:
            return

        entry = float(self._pos.entry_price) if self._pos.is_open() else 0.0
        if entry <= 0.0 and bid > 0.0:
            entry = bid

        self._pos = LivePosition(side=side, token_id=token_id, qty_tokens=float(qty), entry_price=float(entry))

    def apply(self, trade: Dict[str, Any]) -> None:
        # only confirmed fills mutate the account (core invariant)
        if not isinstance(trade, dict) or trade.get("type") != "trade" or trade.get("status") != "filled":
            return

        kind = str(trade.get("kind", ""))
        side = str(trade.get("side", ""))
        token_id = str(trade.get("token_id", ""))

        qty = _f(trade.get("qty_tokens"), 0.0)
        px = _f(trade.get("fill_price"), 0.0)
        if qty <= 0:
            return

        if kind == "buy":
            if px > 0:
                self.cash -= qty * px

            if not self._pos.is_open():
                self._pos = LivePosition(side=side, token_id=token_id, qty_tokens=qty, entry_price=px)
            elif self._pos.side == side and self._pos.token_id == token_id:
                old = self._pos.qty_tokens
                new = old + qty
                if new > 0:
                    if self._pos.entry_price > 0 and px > 0:
                        self._pos.entry_price = (self._pos.entry_price * old + px * qty) / new
                    elif px > 0:
                        self._pos.entry_price = px
                    self._pos.qty_tokens = new
            else:
                self._pos = LivePosition(side=side, token_id=token_id, qty_tokens=qty, entry_price=px)

            ent = self.state.get("entries") or {}
            if isinstance(ent, dict) and side in ent:
                ent[side] = int(ent.get(side, 0)) + 1
                self.state["entries"] = ent
            return

        # SELL / EXIT
        if not (self._pos.is_open() and self._pos.side == side and self._pos.token_id == token_id):
            return

        if px > 0:
            self.cash += qty * px

        remain = self._pos.qty_tokens - qty
        if remain <= self.dust_clear_tokens:
            self._pos = LivePosition()
        else:
            self._pos.qty_tokens = remain

        if kind == "exit_tp":
            self.state["tp_done"] = True

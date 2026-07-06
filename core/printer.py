# core/printer.py
"""Human-readable per-tick console output (read-only view of account/strategy)."""
from __future__ import annotations

from typing import Any, Dict, Optional


def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip()
        if s == "":
            return None
        try:
            return float(s)
        except ValueError:
            return None
    try:
        return float(x)
    except Exception:
        return None


def _fmt(x: Any, nd: int = 2) -> str:
    v = _to_float(x)
    if v is None:
        return "-"
    return f"{v:.{nd}f}"


class Printer:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.print_every = int(cfg.get("print_every", 1))
        self._last_print_tick = -10**18

    def on_quote(self, ev: Dict[str, Any], account, strategy=None) -> None:
        if ev.get("type") != "quote":
            return

        tick = int(ev.get("tick") or 0)
        if self.print_every <= 0:
            return
        if tick - self._last_print_tick < self.print_every:
            return
        self._last_print_tick = tick

        slug = str(ev.get("slug") or "")
        tleft = ev.get("time_left_sec")

        q = ev.get("quote") or {}
        up = q.get("up") or {}
        dn = q.get("down") or {}

        up_ask, up_bid = up.get("ask"), up.get("bid")
        dn_ask, dn_bid = dn.get("ask"), dn.get("bid")

        # strategy debug (e.g. MA values) — optional, strategy-defined
        dbg: Dict[str, Any] = {}
        if strategy is not None and slug:
            try:
                dbg = strategy.debug_state(slug) or {}
            except Exception:
                dbg = {}

        ma = dbg.get("ma") or {}
        ma_up = ma.get("up") or {}
        ma_dn = ma.get("down") or {}

        # --- position summary (account is the SOT) ---
        pos = getattr(account, "position", None)
        has_pos = isinstance(pos, dict) and bool(pos)

        flags = []
        if dbg.get("tp_done"):
            flags.append("TP_LOCK")
        extra_flags = f" [{','.join(flags)}]" if flags else ""

        # --- header ---
        slug_idx = None
        st = getattr(account, "state", None)
        if isinstance(st, dict):
            slug_idx = st.get("slug_idx")
        slug_idx_txt = f"{slug_idx}" if slug_idx is not None else "?"
        print(f"[{slug_idx_txt}] {slug} | tleft {tleft}")

        # --- quotes (ask/bid) ---
        if ma_up or ma_dn:
            print(f"UP  a/b {_fmt(up_ask)}/{_fmt(up_bid)} | MA(a/b) {_fmt(ma_up.get('ask'))}/{_fmt(ma_up.get('bid'))}")
            print(f"DN  a/b {_fmt(dn_ask)}/{_fmt(dn_bid)} | MA(a/b) {_fmt(ma_dn.get('ask'))}/{_fmt(ma_dn.get('bid'))}")
        else:
            print(f"UP  a/b {_fmt(up_ask)}/{_fmt(up_bid)}")
            print(f"DN  a/b {_fmt(dn_ask)}/{_fmt(dn_bid)}")

        # --- position line ---
        if has_pos:
            parts = [f"POS {str(pos.get('side', '?')).upper()}"]
            if pos.get("entry") is not None:
                parts.append(f"entry {_fmt(pos.get('entry'), 4)}")
            if pos.get("qty_tokens") is not None:
                parts.append(f"qty {_fmt(pos.get('qty_tokens'))}")
            if pos.get("notional_usd") is not None:
                parts.append(f"notional {_fmt(pos.get('notional_usd'))}")
            print(" | ".join(parts) + extra_flags)
        else:
            print("POS FLAT" + extra_flags)

        print("-" * 80)

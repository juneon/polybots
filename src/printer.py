# src/printer.py
from __future__ import annotations

from typing import Any, Dict, Optional


def _f(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except Exception:
        return None


class Printer:
    def __init__(self, cfg: Dict[str, Any]):
        self.print_every = max(1, int(cfg.get("print_every", 1)))

    def on_event(self, ev: Dict[str, Any], state: Dict[str, Any]) -> None:
        t = ev.get("type")

        if t == "intent":
            print(f"  -> {ev['kind']} {ev['side']} @ {ev['price']}")
            return

        if t != "quote":
            return

        tick = int(ev.get("tick", 0))
        if tick % self.print_every != 0:
            return

        slug = ev["slug"]
        q = ev.get("quote") or {}

        up = q.get("up") or {}
        dn = q.get("down") or {}

        ua, ub = _f(up.get("ask")), _f(up.get("bid"))
        da, db = _f(dn.get("ask")), _f(dn.get("bid"))

        print(f"\n[{tick:06d}] {slug}")
        print("Up   :", "-" if ua is None else f"ask {ua:.2f} / bid {ub:.2f}")
        print("Down :", "-" if da is None else f"ask {da:.2f} / bid {db:.2f}")

        pos = state.get("position")
        ent = state.get("entries")
        lock = " TP_LOCK" if state.get("tp_done") else ""

        if isinstance(pos, dict):
            print(
                f"position : BUY {pos['side']} {pos['entry']:.2f} "
                f"(try {ent[pos['side']]}){lock}"
            )
        else:
            print(f"position : -{lock}")

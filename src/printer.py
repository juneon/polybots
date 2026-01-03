from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

STATE = Path("state.json")


def jload(p: Path) -> Dict[str, Any]:
    if not p.exists():
        return {"version": 1, "slugs": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "slugs": {}}


def f(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except Exception:
        return None


class Printer:
    def __init__(self):
        pass

    def on_event(self, ev: Dict[str, Any]) -> None:
        t = ev.get("type")
        if t != "quote":
            # slug/warn/intent 같은 건 필요하면 여기서 추가
            return

        slug = str(ev.get("slug", ""))
        tick = int(ev.get("tick", 0))
        q = ev.get("quote") or {}
        ua, ub = f((q.get("up") or {}).get("ask")), f((q.get("up") or {}).get("bid"))
        da, db = f((q.get("down") or {}).get("ask")), f((q.get("down") or {}).get("bid"))

        print(f"\n[{tick:06d}] {slug}")
        print("Up   :", "-" if ua is None or ub is None else f"ask {ua:.2f} / bid {ub:.2f}")
        print("Down :", "-" if da is None or db is None else f"ask {da:.2f} / bid {db:.2f}")

        st = jload(STATE)
        ss = (st.get("slugs") or {}).get(slug) or {}
        pos = ss.get("position")
        ent = ss.get("entries") or {"up": 0, "down": 0}

        if isinstance(pos, dict) and pos.get("side") in ("up", "down"):
            side = pos["side"]
            entry = float(pos.get("entry", 0.0))
            qty = int(pos.get("qty", 0))
            tries = int(ent.get(side, 0))
            print(f"position : BUY {side} {entry:.2f} (qty {qty}) - try {tries}")
        else:
            print("position : -")

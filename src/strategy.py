# src/strategy.py
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


def _now() -> int:
    return int(time.time())


def _f(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except Exception:
        return None


def _slug_start_ts(slug: str) -> Optional[int]:
    try:
        return int(slug.split("-")[-1])
    except Exception:
        return None


class Strategy:
    def __init__(self, cfg: Dict[str, Any]):
        s = cfg.get("strategy", {})

        self.interval = int(cfg.get("interval_sec", 900))
        self.enter_time_left = int(s.get("enter_time_left_sec", 450))
        self.enter_p1 = float(s.get("enter_price_1", 0.8))
        self.enter_pre = float(s.get("enter_price_re", 0.9))
        self.stop_drop = float(s.get("stop_drop", 0.1))
        self.take_profit = float(s.get("take_profit", 0.99))
        self.max_entries = int(s.get("max_entries_per_slug", 2))
        self.qty = int(s.get("qty", 1))

    def _time_left(self, slug: str) -> Optional[int]:
        start = _slug_start_ts(slug)
        if start is None:
            return None
        return (start + self.interval) - _now()

    def _intent(self, kind: str, slug: str, tick: int, side: str, price: float) -> Dict[str, Any]:
        return {
            "type": "intent",   # logger가 trade로 취급
            "kind": kind,       # buy / exit_tp / exit_sl
            "slug": slug,
            "tick": tick,
            "side": side,
            "price": price,
            "qty": self.qty,
            "ts": _now(),
        }

    def on_event(self, ev: Dict[str, Any], state: Dict[str, Any]) -> List[Dict[str, Any]]:
        if ev["type"] != "quote":
            return []

        slug = ev["slug"]
        tick = int(ev.get("tick", 0))
        q = ev.get("quote") or {}

        up = q.get("up") or {}
        dn = q.get("down") or {}

        ua, ub = _f(up.get("ask")), _f(up.get("bid"))
        da, db = _f(dn.get("ask")), _f(dn.get("bid"))
        if None in (ua, ub, da, db):
            return []

        tleft = self._time_left(slug)
        if tleft is None:
            return []

        # ---------- EXIT ----------
        pos = state.get("position")
        if isinstance(pos, dict):
            side = pos["side"]
            entry = float(pos["entry"])
            cur_bid = ub if side == "up" else db

            if cur_bid >= self.take_profit:
                it = self._intent("exit_tp", slug, tick, side, cur_bid)
                state["position"] = None
                state["last_intent"] = it
                state["tp_done"] = True
                return [it]

            if cur_bid <= entry - self.stop_drop:
                it = self._intent("exit_sl", slug, tick, side, cur_bid)
                state["position"] = None
                state["last_intent"] = it
                return [it]

            return []

        # ---------- ENTER ----------
        if state.get("tp_done"):
            return []

        if tleft > self.enter_time_left:
            return []

        ent = state["entries"]
        candidates = []

        if ent["up"] < self.max_entries:
            thr = self.enter_p1 if ent["up"] == 0 else self.enter_pre
            if ua >= thr:
                candidates.append(("up", ua))

        if ent["down"] < self.max_entries:
            thr = self.enter_p1 if ent["down"] == 0 else self.enter_pre
            if da >= thr:
                candidates.append(("down", da))

        if not candidates:
            return []

        side, ask = max(candidates, key=lambda x: x[1])
        it = self._intent("buy", slug, tick, side, ask)

        ent[side] += 1
        state["position"] = {
            "side": side,
            "qty": self.qty,
            "entry": ask,
            "entry_tick": tick,
            "entry_time": _now(),
        }
        state["last_intent"] = it

        return [it]

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

STATE = Path("state.json")


# -------------------------
# util
# -------------------------
def now() -> int:
    return int(time.time())


def jload(p: Path) -> Dict[str, Any]:
    if not p.exists():
        return {"version": 1, "slugs": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "slugs": {}}


def jdump(p: Path, obj: Dict[str, Any]) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def f(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except Exception:
        return None


def slug_start_ts(slug: str) -> Optional[int]:
    try:
        return int(slug.split("-")[-1])
    except Exception:
        return None


# -------------------------
# Strategy
# -------------------------
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

    # -------------------------
    # state helpers
    # -------------------------
    def _state(self) -> Dict[str, Any]:
        st = jload(STATE)
        st.setdefault("slugs", {})
        return st

    def _slug_state(self, st: Dict[str, Any], slug: str) -> Dict[str, Any]:
        ss = st["slugs"].get(slug)
        if not ss:
            ss = {
                "entries": {"up": 0, "down": 0},
                "position": None,
                "last_intent": None,
                "tp_done": False,   # 🔒 익절 후 재진입 하드락
            }
            st["slugs"][slug] = ss
        return ss

    def _time_left(self, slug: str) -> Optional[int]:
        start = slug_start_ts(slug)
        if start is None:
            return None
        return (start + self.interval) - now()

    def _intent(
        self, kind: str, slug: str, tick: int, side: str, price: float
    ) -> Dict[str, Any]:
        return {
            "type": "intent",
            "kind": kind,
            "slug": slug,
            "tick": tick,
            "side": side,
            "price": float(price),
            "qty": self.qty,
            "ts": now(),
        }

    # -------------------------
    # core
    # -------------------------
    def on_event(self, ev: Dict[str, Any]) -> List[Dict[str, Any]]:
        if ev.get("type") != "quote":
            return []

        slug = str(ev.get("slug", ""))
        tick = int(ev.get("tick", 0))
        q = ev.get("quote") or {}

        ua = f((q.get("up") or {}).get("ask"))
        ub = f((q.get("up") or {}).get("bid"))
        da = f((q.get("down") or {}).get("ask"))
        db = f((q.get("down") or {}).get("bid"))

        if None in (ua, ub, da, db):
            return []

        tleft = self._time_left(slug)
        if tleft is None:
            return []

        st = self._state()
        ss = self._slug_state(st, slug)

        intents: List[Dict[str, Any]] = []

        # ==================================================
        # 1) EXIT (포지션이 있을 때만)
        # ==================================================
        pos = ss.get("position")
        if isinstance(pos, dict):
            side = pos["side"]
            entry = float(pos["entry"])
            cur_bid = ub if side == "up" else db

            # 익절 → slug 종료
            if cur_bid >= self.take_profit:
                it = self._intent("exit_tp", slug, tick, side, cur_bid)
                ss["position"] = None
                ss["last_intent"] = it
                ss["tp_done"] = True   # 🔒 하드락
                jdump(STATE, st)
                return [it]

            # 손절 → 재진입 허용
            if cur_bid <= max(0.0, entry - self.stop_drop):
                it = self._intent("exit_sl", slug, tick, side, cur_bid)
                ss["position"] = None
                ss["last_intent"] = it
                jdump(STATE, st)
                return [it]

            jdump(STATE, st)
            return []

        # ==================================================
        # 2) ENTER
        # ==================================================

        # 🔒 익절 이후에는 절대 재진입 안 함
        if ss.get("tp_done"):
            jdump(STATE, st)
            return []

        # 진입 가능 시간 조건
        if tleft > self.enter_time_left:
            jdump(STATE, st)
            return []

        up_n = int(ss["entries"].get("up", 0))
        dn_n = int(ss["entries"].get("down", 0))

        up_thr = self.enter_p1 if up_n == 0 else self.enter_pre
        dn_thr = self.enter_p1 if dn_n == 0 else self.enter_pre

        candidates = []
        if up_n < self.max_entries and ua >= up_thr:
            candidates.append(("up", ua))
        if dn_n < self.max_entries and da >= dn_thr:
            candidates.append(("down", da))

        if not candidates:
            jdump(STATE, st)
            return []

        # 동시에 충족되면 ask 큰 쪽
        side, ask = max(candidates, key=lambda x: x[1])

        it = self._intent("buy", slug, tick, side, ask)

        ss["entries"][side] += 1
        ss["position"] = {
            "side": side,
            "qty": self.qty,
            "entry": float(ask),
            "entry_tick": tick,
            "entry_time": now(),
        }
        ss["last_intent"] = it

        jdump(STATE, st)
        return [it]

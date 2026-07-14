# strategies/ma.py
"""MA breakout + cap strategy (backtest-derived: cap=0.5, ma_len=300, tick_confirm=0).

Registry name: "ma" (renamed from "ma_breakout" 2026-07-14 — old run_ids in
logs/*.csv keep the long name; readers normalize via ui.metrics).

Entry (flat only):
  - a side qualifies when its ask <= cap AND the ask crosses UP through its ask-SMA
  - tick_confirm == 0: enter on the crossing tick (cheaper qualifying side wins)
  - tick_confirm > 0: require N consecutive ticks of (ask <= cap and ask > SMA)
  - entry_slope_max (optional): the SMA's slope over the last entry_slope_window_sec
    must be <= this value — e.g. 0.0 keeps only dip-bounce crosses (rising-MA
    chase entries were the toxic bucket: 2026-07-14 screening, complete 203 slugs,
    slope<=-0.005 lifted the replay +2.96 -> +43.40 across all three sources).
    Blocks entries until enough SMA history exists. None (default) disables.
  - suppressed inside no_entry_last_sec window and during cooldown_sec after a fill

Exit (holding only; position truth = account.position):
  - TP: held side's bid >= tp_abs -> exit_tp (level-triggered, retries naturally)
  - MA: held side's bid crosses DOWN through its bid-SMA -> exit_time
    (edge-triggered, so the signal is LATCHED via exit_armed and the sell intent
     is re-emitted every tick until the fill is confirmed)

v2.2 correctness fixes vs the old polybots_MA version:
  - no optimistic self.position at intent time — account is the single source of truth
  - cooldown / tp_done / exit_armed are updated in on_trade (confirmed fills only)
  - a "submitted" (resting, unconfirmed) BUY latches buy_inflight to prevent
    duplicate stacked orders within the slug
  - per-slug SMA state of past slugs is dropped on slug change (no unbounded growth)
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional

from .base import BaseStrategy, make_intent

log = logging.getLogger(__name__)


@dataclass
class MAConfig:
    qty_tokens: float = 10.0
    cap: float = 0.5
    ma_len: int = 300
    tick_confirm: int = 0            # 0: crossing tick only, >0: consecutive above-MA confirm
    cooldown_sec: int = 0
    no_entry_last_sec: Optional[int] = None   # None disables
    tp_abs: Optional[float] = None            # e.g. 0.98: exit when held side's bid >= 0.98
    entry_slope_max: Optional[float] = None   # e.g. 0.0: enter only through a non-rising SMA
    entry_slope_window_sec: int = 60          # slope lookback (ticks ~ seconds)


class RollingSMA:
    def __init__(self, window: int):
        if window <= 0:
            raise ValueError("window must be > 0")
        self.window = window
        self.values: Deque[float] = deque(maxlen=window)
        self.total = 0.0

    def push(self, x: float) -> Optional[float]:
        if len(self.values) == self.window:
            self.total -= self.values[0]
        self.values.append(x)
        self.total += x
        if len(self.values) < self.window:
            return None   # not warmed up yet (no signal for the first `window` ticks)
        return self.total / self.window


class MAStrategy(BaseStrategy):
    def __init__(self, cfg: Dict[str, Any]):
        scfg = cfg.get("strategy") or {}
        self.cfg = MAConfig(
            qty_tokens=float(scfg.get("qty_tokens", 10.0)),
            cap=float(scfg.get("cap", 0.5)),
            ma_len=int(scfg.get("ma_len", 300)),
            tick_confirm=int(scfg.get("tick_confirm", 0)),
            cooldown_sec=int(scfg.get("cooldown_sec", 0)),
            no_entry_last_sec=scfg.get("no_entry_last_sec"),
            tp_abs=(None if scfg.get("tp_abs") is None else float(scfg["tp_abs"])),
            entry_slope_max=(None if scfg.get("entry_slope_max") is None
                             else float(scfg["entry_slope_max"])),
            entry_slope_window_sec=int(scfg.get("entry_slope_window_sec", 60)),
        )
        self._state: Dict[str, Dict[str, Any]] = {}   # slug -> state
        self._next_entry_ts: float = float("-inf")    # cooldown gate (set on buy fill)

    # ---------- state ----------

    def _slug_state(self, slug: str) -> Dict[str, Any]:
        st = self._state.get(slug)
        if st is None:
            st = {
                "up_ask_sma": RollingSMA(self.cfg.ma_len),
                "dn_ask_sma": RollingSMA(self.cfg.ma_len),
                "up_bid_sma": RollingSMA(self.cfg.ma_len),
                "dn_bid_sma": RollingSMA(self.cfg.ma_len),

                "prev_up_ask": None, "prev_dn_ask": None,
                "prev_up_bid": None, "prev_dn_bid": None,
                "prev_up_ask_ma": None, "prev_dn_ask_ma": None,
                "prev_up_bid_ma": None, "prev_dn_bid_ma": None,

                "above_count": {"up": 0, "down": 0},

                # ask-SMA history for the entry slope filter (window+1 samples
                # so hist[0] is exactly window ticks before hist[-1])
                "ask_ma_hist": {
                    "up": deque(maxlen=self.cfg.entry_slope_window_sec + 1),
                    "down": deque(maxlen=self.cfg.entry_slope_window_sec + 1),
                } if self.cfg.entry_slope_max is not None else None,

                "buy_inflight": False,   # resting unconfirmed BUY -> block re-entry
                "exit_armed": False,     # MA cross-down latched -> re-emit sell until filled
                "tp_done": False,
            }
            self._state[slug] = st
        return st

    def _on_slug_change(self, new_slug: str) -> None:
        # carrying positions across slugs is unsafe; also drop stale slug states (memory)
        for k in [k for k in self._state if k != new_slug]:
            del self._state[k]
        self._next_entry_ts = float("-inf")

    @staticmethod
    def _cross_up(prev_x, prev_ma, x, ma) -> bool:
        if prev_x is None or prev_ma is None or x is None or ma is None:
            return False
        return (prev_x <= prev_ma) and (x > ma)

    @staticmethod
    def _cross_down(prev_x, prev_ma, x, ma) -> bool:
        if prev_x is None or prev_ma is None or x is None or ma is None:
            return False
        return (prev_x >= prev_ma) and (x < ma)

    def _slope_ok(self, st: Dict[str, Any], side: str) -> bool:
        """entry_slope_max gate: SMA slope over the lookback must be <= max.
        Conservative while history is short (warmup) — no entry."""
        if self.cfg.entry_slope_max is None:
            return True
        hist = st["ask_ma_hist"][side]
        if len(hist) < hist.maxlen:
            return False
        old, new = hist[0], hist[-1]
        if old is None or new is None:
            return False
        return (new - old) <= self.cfg.entry_slope_max

    # ---------- interface ----------

    def debug_state(self, slug: str) -> Dict[str, Any]:
        st = self._state.get(slug)
        if not st:
            return {}
        return {
            "ma": {
                "up": {"ask": st.get("prev_up_ask_ma"), "bid": st.get("prev_up_bid_ma")},
                "down": {"ask": st.get("prev_dn_ask_ma"), "bid": st.get("prev_dn_bid_ma")},
            },
            "tp_abs": self.cfg.tp_abs,
            "tp_done": bool(st.get("tp_done")),
            "exit_armed": bool(st.get("exit_armed")),
            "buy_inflight": bool(st.get("buy_inflight")),
        }

    def on_trade(self, trade: Dict[str, Any]) -> None:
        if not isinstance(trade, dict) or trade.get("type") != "trade":
            return
        slug = str(trade.get("slug") or "")
        st = self._state.get(slug)
        if st is None:
            return

        kind = str(trade.get("kind", ""))
        status = str(trade.get("status", ""))

        if kind == "buy":
            if status == "filled":
                st["buy_inflight"] = False
                if self.cfg.cooldown_sec > 0:
                    self._next_entry_ts = float(trade.get("ts") or time.time()) + float(self.cfg.cooldown_sec)
            elif status == "submitted":
                # resting order we cannot track -> block further entries this slug
                st["buy_inflight"] = True
                log.warning("buy submitted but not confirmed (slug=%s) — blocking re-entry this slug", slug)
            else:  # rejected
                st["buy_inflight"] = False
            return

        if kind in ("exit_tp", "exit_sl", "exit_time") and status == "filled":
            st["exit_armed"] = False
            if kind == "exit_tp":
                st["tp_done"] = True

    def on_event(self, ev: Dict[str, Any], account) -> List[Dict[str, Any]]:
        et = ev.get("type")

        if et in ("slug_init", "slug_change"):
            slug = str(ev.get("slug") or "")
            if slug:
                self._on_slug_change(slug)
            return []

        if et != "quote":
            return []

        slug = str(ev.get("slug") or "")
        tick = int(ev.get("tick") or 0)
        tleft = int(ev.get("time_left_sec") or 0)
        # event time: replay engines inject historical "ts"; live falls back to wall clock
        now = float(ev.get("ts") or time.time())
        q = ev.get("quote") or {}

        try:
            up_bid = float((q.get("up") or {}).get("bid"))
            up_ask = float((q.get("up") or {}).get("ask"))
            dn_bid = float((q.get("down") or {}).get("bid"))
            dn_ask = float((q.get("down") or {}).get("ask"))
        except (TypeError, ValueError):
            log.warning("bad quote prices (slug=%s tick=%s) — skipping tick", slug, tick)
            return []

        st = self._slug_state(slug)

        # update SMAs / prevs
        up_ask_ma = st["up_ask_sma"].push(up_ask)
        dn_ask_ma = st["dn_ask_sma"].push(dn_ask)
        up_bid_ma = st["up_bid_sma"].push(up_bid)
        dn_bid_ma = st["dn_bid_sma"].push(dn_bid)

        prev = {k: st[k] for k in (
            "prev_up_ask", "prev_dn_ask", "prev_up_bid", "prev_dn_bid",
            "prev_up_ask_ma", "prev_dn_ask_ma", "prev_up_bid_ma", "prev_dn_bid_ma",
        )}

        st.update(
            prev_up_ask=up_ask, prev_dn_ask=dn_ask,
            prev_up_bid=up_bid, prev_dn_bid=dn_bid,
            prev_up_ask_ma=up_ask_ma, prev_dn_ask_ma=dn_ask_ma,
            prev_up_bid_ma=up_bid_ma, prev_dn_bid_ma=dn_bid_ma,
        )

        if st["ask_ma_hist"] is not None:
            st["ask_ma_hist"]["up"].append(up_ask_ma)
            st["ask_ma_hist"]["down"].append(dn_ask_ma)

        pos = account.position  # SOT: dict {"side","entry",...} or None

        # ---- EXIT (holding) ----
        if pos:
            side = str(pos.get("side") or "")
            bid = up_bid if side == "up" else dn_bid

            # TP: level-triggered (re-fires by itself until filled)
            if self.cfg.tp_abs is not None and bid >= float(self.cfg.tp_abs):
                return [make_intent("exit_tp", slug, tick, side, bid, self.cfg.qty_tokens, tleft)]

            # MA cross-down: edge-triggered -> latch, then re-emit until filled
            if side == "up":
                crossed = self._cross_down(prev["prev_up_bid"], prev["prev_up_bid_ma"], up_bid, up_bid_ma)
            else:
                crossed = self._cross_down(prev["prev_dn_bid"], prev["prev_dn_bid_ma"], dn_bid, dn_bid_ma)
            if crossed:
                st["exit_armed"] = True

            if st["exit_armed"]:
                return [make_intent("exit_time", slug, tick, side, bid, self.cfg.qty_tokens, tleft)]

            return []

        # ---- ENTRY (flat) ----
        st["exit_armed"] = False
        st["tp_done"] = False    # next entry in this slug can TP again

        if st["buy_inflight"]:
            return []
        if now < self._next_entry_ts:
            return []
        if self.cfg.no_entry_last_sec is not None and tleft <= int(self.cfg.no_entry_last_sec):
            return []

        if self.cfg.tick_confirm > 0:
            ac = st["above_count"]
            ac["up"] = ac["up"] + 1 if (up_ask_ma is not None and up_ask <= self.cfg.cap and up_ask > up_ask_ma) else 0
            ac["down"] = ac["down"] + 1 if (dn_ask_ma is not None and dn_ask <= self.cfg.cap and dn_ask > dn_ask_ma) else 0

            need = int(self.cfg.tick_confirm)
            ok_up, ok_dn = ac["up"] >= need, ac["down"] >= need
            if not (ok_up or ok_dn):
                return []

            side = "up" if (ok_up and (not ok_dn or up_ask <= dn_ask)) else "down"
            px = up_ask if side == "up" else dn_ask
            if px > self.cfg.cap:
                return []
            if not self._slope_ok(st, side):
                return []   # counters stay: the gate re-evaluates next tick

            ac["up"] = ac["down"] = 0
            return [make_intent("buy", slug, tick, side, px, self.cfg.qty_tokens, tleft)]

        # tick_confirm == 0: crossing tick only, cheaper qualifying side wins
        candidates = []
        if up_ask <= self.cfg.cap and self._cross_up(prev["prev_up_ask"], prev["prev_up_ask_ma"], up_ask, up_ask_ma) \
           and self._slope_ok(st, "up"):
            candidates.append(("up", up_ask))
        if dn_ask <= self.cfg.cap and self._cross_up(prev["prev_dn_ask"], prev["prev_dn_ask_ma"], dn_ask, dn_ask_ma) \
           and self._slope_ok(st, "down"):
            candidates.append(("down", dn_ask))

        if not candidates:
            return []

        side, px = min(candidates, key=lambda x: x[1])
        return [make_intent("buy", slug, tick, side, px, self.cfg.qty_tokens, tleft)]

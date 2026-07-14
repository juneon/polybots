# strategies/threshold.py
"""Buy-the-favorite threshold strategy with stop-loss re-entry (ex-polybots_pre).

All timing uses time_left_sec (tleft) — never wall-clock (ts is log-only).

Entry (flat only, inside the window t_deadline < tleft <= t_enter):
  - side = the MORE expensive side (the market favorite)
  - reject if ask > entry_cap
  - first entry (n == 0):  ask >= enter_price_1
  - re-entry (n >= 1):     only after a confirmed stop-loss, ask >= enter_price_re,
                           and (optional) drawdown filter: current bid must sit at least
                           |reentry_dd_min| below the peak bid of the last dd_window_sec
  - at most max_entries_per_slug entries per slug (counted on CONFIRMED buy fills)

Exit (holding; position truth = account.position), priority order:
  1. tleft <= force_exit_left_sec           -> exit_time
  2. bid >= take_profit                     -> exit_tp   (locks the slug: no more entries)
  3. bid <= entry - stop_drop               -> exit_sl   (enables one re-entry)
     stop_confirm_sec > 0 delays the SL: the breach must hold CONTINUOUSLY for
     that many seconds (tleft-based) before exit_sl fires; a recovery above the
     stop level resets the clock. 0 = fire on the first breach tick (legacy).
     Motivation: 71% of sim stops were whipsaws — a momentary dip through the
     stop that recovered and settled at 0.99 (2026-07-13 analysis).
  All exit conditions are level-triggered, so they re-fire until the fill confirms.

v2.2 correctness fixes vs the old polybots_pre version:
  - n / stopped / lock now update in on_trade on CONFIRMED fills, not at intent time
    (a rejected buy no longer consumes an entry slot; a rejected TP no longer locks)
  - a "submitted" (resting, unconfirmed) BUY conservatively consumes an entry slot
    to prevent duplicate stacked orders
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Any, Dict, List

from .base import BaseStrategy, make_intent

log = logging.getLogger(__name__)


class ThresholdStrategy(BaseStrategy):
    def __init__(self, cfg: Dict[str, Any]):
        s = cfg["strategy"]

        # timing
        self.t_enter = int(s["enter_time_left_sec"])
        self.t_deadline = int(s.get("enter_deadline_left_sec", 0))

        # prices
        self.p1 = float(s["enter_price_1"])
        self.pre = float(s["enter_price_re"])
        self.cap = float(s.get("entry_cap", 1.0))

        # risk
        self.sl_drop = float(s["stop_drop"])
        self.sl_confirm = int(s.get("stop_confirm_sec", 0))   # 0 = instant (legacy)
        self.tp = float(s["take_profit"])
        self.t_force = int(s["force_exit_left_sec"])

        # limits
        self.maxn = int(s["max_entries_per_slug"])
        self.qty = float(s.get("qty_tokens", 10.0))

        # dd filter (re-entry only, optional)
        self.dd_win_sec = int(s.get("dd_window_sec", 120))     # tleft-based window
        dd = s.get("reentry_dd_min")
        self.dd_min = float(dd) if dd is not None else None

        # per-slug state
        self.slug = None
        self.n = 0              # confirmed entries this slug
        self.stopped = False    # a stop-loss fill confirmed -> re-entry allowed
        self.lock = False       # a TP fill confirmed -> slug hard-locked
        self._sl_breach_tleft = None   # tleft when the current stop breach began

        # dd history: (tleft, bid) per side — unified time axis
        self._bid_hist = {"up": deque(), "down": deque()}

    # ---------- interface ----------

    def debug_state(self, slug: str) -> Dict[str, Any]:
        if slug != self.slug:
            return {}
        return {"entries": self.n, "stopped": self.stopped, "tp_done": self.lock,
                "sl_breach_tleft": self._sl_breach_tleft}

    def on_trade(self, trade: Dict[str, Any]) -> None:
        if not isinstance(trade, dict) or trade.get("type") != "trade":
            return
        if str(trade.get("slug") or "") != (self.slug or ""):
            return

        kind = str(trade.get("kind", ""))
        status = str(trade.get("status", ""))

        if kind == "buy":
            if status == "filled":
                self.n += 1
            elif status == "submitted":
                # resting order we cannot track — conservatively consume the entry slot
                self.n += 1
                log.warning("buy submitted but not confirmed (slug=%s) — counting entry slot", self.slug)
            return

        if status != "filled":
            return
        if kind == "exit_sl":
            self.stopped = True
        elif kind == "exit_tp":
            self.lock = True

    def on_event(self, ev: Dict[str, Any], account) -> List[Dict[str, Any]]:
        if ev.get("type") != "quote":
            return []

        slug = ev["slug"]
        tick = ev["tick"]
        tleft = int(ev["time_left_sec"])
        q = ev["quote"]
        pos = account.position

        # reset on slug change
        if slug != self.slug:
            self.slug = slug
            self.n = 0
            self.stopped = False
            self.lock = False
            self._sl_breach_tleft = None
            self._bid_hist["up"].clear()
            self._bid_hist["down"].clear()

        # dd history: when the filter is on, record every quote (pre- and post-SL)
        # so the "peak of the last dd_window_sec before the stop" is available
        if self.dd_min is not None:
            for s in ("up", "down"):
                dq = self._bid_hist[s]
                dq.append((tleft, float(q[s]["bid"])))
                while dq and (dq[0][0] - tleft) > self.dd_win_sec:
                    dq.popleft()

        # ---- EXIT (level-triggered: re-fires until the fill confirms) ----
        if pos:
            side = pos["side"]
            entry = float(pos["entry"])
            bid = float(q[side]["bid"])

            if tleft <= self.t_force:
                return [make_intent("exit_time", slug, tick, side, bid, self.qty, tleft)]

            if bid >= self.tp:
                return [make_intent("exit_tp", slug, tick, side, bid, self.qty, tleft)]

            if bid <= entry - self.sl_drop:
                # whipsaw guard: the breach must hold for stop_confirm_sec
                # (tleft-based dwell) before the stop fires; recovery resets it
                if self.sl_confirm > 0:
                    if self._sl_breach_tleft is None:
                        self._sl_breach_tleft = tleft
                    if (self._sl_breach_tleft - tleft) < self.sl_confirm:
                        return []
                return [make_intent("exit_sl", slug, tick, side, bid, self.qty, tleft)]

            self._sl_breach_tleft = None   # recovered above the stop level
            return []

        # ---- ENTRY (flat: no live breach to track) ----
        self._sl_breach_tleft = None
        if self.lock or self.n >= self.maxn:
            return []

        # entry window
        if tleft > self.t_enter:
            return []
        if self.t_deadline and tleft <= self.t_deadline:
            return []

        up_ask = float(q["up"]["ask"])
        dn_ask = float(q["down"]["ask"])

        # the favorite: the more expensive side
        side, price = ("up", up_ask) if up_ask >= dn_ask else ("down", dn_ask)

        if price > self.cap:
            return []

        if self.n == 0:
            # first entry
            if price < self.p1:
                return []
        else:
            # re-entry: only after a confirmed stop-loss
            if not self.stopped:
                return []
            if price < self.pre:
                return []

            # dd filter (optional): require a real drawdown vs the recent peak
            if self.dd_min is not None:
                dq = self._bid_hist[side]
                if len(dq) < 2:   # one sample would make dd=0 and meaningless
                    return []
                cur_bid = dq[-1][1]
                prev_peak = max(b for _, b in list(dq)[:-1])   # exclude current sample
                dd = cur_bid - prev_peak
                if dd > self.dd_min:   # e.g. dd_min=-0.15: allow only when dd <= -0.15
                    return []

        return [make_intent("buy", slug, tick, side, price, self.qty, tleft)]

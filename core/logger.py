# core/logger.py
"""CSV sink (long-term memory).

- Files are opened in APPEND mode — history survives across runs.
  Every row carries a run_id so runs can be separated in analysis.
- intent/trade rows flush immediately (loss prevention);
  events/snapshots flush at slug boundaries only (performance).
- events rotate per UTC day: events_<YYYYMMDD>.csv (2026-07-18 — the single
  events.csv grew unbounded, 43MB in a week). The legacy events.csv is frozen
  history; readers (data_prep, ui.metrics, ui.jobs) consume legacy + dated
  files together. trades/snapshots stay single files (fills only, small).
"""
import csv
import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)


def events_filename(utc_day: str) -> str:
    return f"events_{utc_day}.csv"


def _utc_day() -> str:
    return time.strftime("%Y%m%d", time.gmtime())

# CSV schemas — the single source for column names. Consumers (ui/metrics,
# backtest, tests) import these instead of re-typing header strings.
EVENTS_FIELDS = ["run_id", "type", "slug", "tick", "ts", "data"]
TRADES_FIELDS = [
    "run_id", "ts", "slug", "tick", "trade_id",
    "intent_kind", "side", "qty", "intent_price", "time_left_sec",
    "status", "reason", "fill_price",
    "qty_tokens", "notional_usd", "proceeds_usd",
    "data",
]
SNAPSHOTS_FIELDS = [
    "run_id", "ts", "slug", "tick",
    "cash", "position_side", "position_entry", "position_qty_tokens", "position_notional_usd",
    "entries_up", "entries_down", "tp_done",
    "quote_up_bid", "quote_up_ask", "quote_down_bid", "quote_down_ask",
    "data",
]


class Logger:
    def __init__(self, cfg: dict, run_id: str = "", logs_dir: str = "logs"):
        lcfg = cfg.get("logging", {}) or {}
        self.on_events = bool(lcfg.get("events", False))
        self.on_trades = bool(lcfg.get("trades", True))
        self.on_snaps = bool(lcfg.get("snapshots", True))
        self.run_id = str(run_id)

        d = Path(logs_dir)
        d.mkdir(parents=True, exist_ok=True)
        self._dir = d

        self._pending_intent = None
        self._trade_id = 0

        self._fe = self._we = None
        self._ft = self._wt = None
        self._fs = self._ws = None
        self._events_day = ""

        if self.on_events:
            self._open_events(_utc_day())

        if self.on_trades:
            self._ft, self._wt = self._open(d / "trades.csv", TRADES_FIELDS)

        if self.on_snaps:
            self._fs, self._ws = self._open(d / "snapshots.csv", SNAPSHOTS_FIELDS)

    @staticmethod
    def _open(path: Path, fieldnames: list):
        """Open in append mode; write the header only for a new/empty file."""
        is_new = (not path.exists()) or path.stat().st_size == 0
        f = path.open("a", newline="", encoding="utf-8")
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if is_new:
            w.writeheader()
        return f, w

    def _open_events(self, day: str) -> None:
        """(Re)open the dated events file, closing the previous day's file."""
        if self._fe:
            try:
                self._fe.flush()
                self._fe.close()
            except Exception as e:
                log.warning("events file close on rollover failed: %r", e)
        self._events_day = day
        self._fe, self._we = self._open(self._dir / events_filename(day), EVENTS_FIELDS)

    def handle(self, ev: dict) -> None:
        et = ev.get("type")

        if self.on_events and et in ("slug_init", "slug_change", "quote", "warn", "exit"):
            day = _utc_day()
            if day != self._events_day:  # midnight UTC rollover
                self._open_events(day)
            self._we.writerow({
                "run_id": self.run_id,
                "type": et,
                "slug": ev.get("slug", ""),
                "tick": ev.get("tick", ""),
                "ts": ev.get("ts", ""),
                "data": json.dumps(ev, ensure_ascii=False),
            })

        # intent: cache + flush immediately (paired with the following trade)
        if et == "intent":
            self._pending_intent = ev
            self.flush()
            return

        # trade: write intent+trade as one row, flush immediately
        if self.on_trades and et == "trade":
            self._trade_id += 1
            it = self._pending_intent or {}
            self._pending_intent = None

            self._wt.writerow({
                "run_id": self.run_id,
                "ts": ev.get("ts", it.get("ts", "")),
                "slug": ev.get("slug", it.get("slug", "")),
                "tick": ev.get("tick", it.get("tick", "")),
                "trade_id": self._trade_id,
                "intent_kind": it.get("kind", ""),
                "side": it.get("side", ev.get("side", "")),
                "qty": it.get("qty_tokens", it.get("qty", "")),
                "intent_price": it.get("price", ""),
                "time_left_sec": it.get("time_left_sec", ""),
                "status": ev.get("status", ""),
                "reason": ev.get("reason", ""),
                "fill_price": ev.get("fill_price", ev.get("price", "")),
                "qty_tokens": ev.get("qty_tokens", ""),
                "notional_usd": ev.get("notional_usd", ""),
                "proceeds_usd": ev.get("proceeds_usd", ""),
                "data": json.dumps({"intent": it, "trade": ev}, ensure_ascii=False),
            })
            self.flush()
            return

        # flush only at slug boundaries (never per quote/warn)
        if et in ("slug_change", "exit"):
            self.flush()

    def snapshot(self, account, quote_ev: dict) -> None:
        if not self.on_snaps:
            return
        if quote_ev.get("type") != "quote":
            return

        pos = account.position or {}
        st = getattr(account, "state", {}) or {}
        q = quote_ev.get("quote") or {}
        up = q.get("up") or {}
        dn = q.get("down") or {}

        self._ws.writerow({
            "run_id": self.run_id,
            "ts": quote_ev.get("ts", ""),
            "slug": quote_ev.get("slug", ""),
            "tick": quote_ev.get("tick", ""),
            "cash": getattr(account, "cash", ""),
            "position_side": pos.get("side", ""),
            "position_entry": pos.get("entry", ""),
            "position_qty_tokens": pos.get("qty_tokens", ""),
            "position_notional_usd": pos.get("notional_usd", ""),
            "entries_up": (st.get("entries") or {}).get("up", ""),
            "entries_down": (st.get("entries") or {}).get("down", ""),
            "tp_done": st.get("tp_done", ""),
            "quote_up_bid": up.get("bid", ""),
            "quote_up_ask": up.get("ask", ""),
            "quote_down_bid": dn.get("bid", ""),
            "quote_down_ask": dn.get("ask", ""),
            "data": json.dumps({"quote": quote_ev, "account": {"position": pos, "state": st}}, ensure_ascii=False),
        })

    def flush(self) -> None:
        for f in (self._fe, self._ft, self._fs):
            if f:
                f.flush()

    def close(self) -> None:
        try:
            self.flush()
        except Exception as e:
            log.warning("logger flush on close failed: %r", e)
        for f in (self._fe, self._ft, self._fs):
            if f:
                try:
                    f.close()
                except Exception as e:
                    log.warning("logger close failed: %r", e)

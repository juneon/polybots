from __future__ import annotations

import csv, json, time
from pathlib import Path
from typing import Any, Dict


def _now() -> int:
    return int(time.time())


class Logger:
    """
    logging:
      - events:    bool -> events.csv (debug, overwrite)
      - trades:    bool -> trades.csv (append)
      - snapshots: bool -> snapshots.csv (append, type=='snapshot')
    """

    def __init__(self, cfg: Dict[str, Any]):
        logcfg = cfg.get("logging") or {}

        self.log_events = bool(logcfg.get("events", False))
        self.log_trades = bool(logcfg.get("trades", False))
        self.log_snaps  = bool(logcfg.get("snapshots", False))

        self.dir = Path("logs")
        self.dir.mkdir(parents=True, exist_ok=True)

        self._events_f = self._trades_f = self._snaps_f = None
        self._events_w = self._trades_w = self._snaps_w = None

        if self.log_events:
            self._open_events()

        if self.log_trades:
            self._open_trades()

        if self.log_snaps:
            self._open_snapshots()

    # ---------- open files ----------

    def _open_events(self) -> None:
        path = self.dir / "events.csv"
        self._events_f = path.open("w", newline="", encoding="utf-8")  # overwrite
        self._events_w = csv.DictWriter(
            self._events_f,
            fieldnames=["ts", "type", "slug", "tick", "data_json"],
        )
        self._events_w.writeheader()

    def _open_trades(self) -> None:
        path = self.dir / "trades.csv"
        new = not path.exists()
        self._trades_f = path.open("a", newline="", encoding="utf-8")
        self._trades_w = csv.DictWriter(
            self._trades_f,
            fieldnames=["ts", "slug", "tick", "kind", "side", "price", "qty"],
        )
        if new:
            self._trades_w.writeheader()

    def _open_snapshots(self) -> None:
        path = self.dir / "snapshots.csv"
        new = not path.exists()
        self._snaps_f = path.open("a", newline="", encoding="utf-8")
        self._snaps_w = csv.DictWriter(
            self._snaps_f,
            fieldnames=["ts", "slug", "tick", "data_json"],
        )
        if new:
            self._snaps_w.writeheader()

    # ---------- handle event ----------

    def handle(self, ev: Dict[str, Any]) -> None:
        et = ev.get("type")
        ts = int(ev.get("ts") or _now())

        # 1) events (debug)
        if self._events_w is not None:
            self._events_w.writerow(
                {
                    "ts": ts,
                    "type": et,
                    "slug": ev.get("slug"),
                    "tick": ev.get("tick"),
                    "data_json": json.dumps(ev, ensure_ascii=False, separators=(",", ":")),
                }
            )

        # 2) trades (intent 포함, strategy 수정 최소화)
        if self._trades_w is not None and et in ("trade", "intent"):
            self._trades_w.writerow(
                {
                    "ts": ts,
                    "slug": ev.get("slug"),
                    "tick": ev.get("tick"),
                    "kind": ev.get("kind") or ev.get("action") or "",
                    "side": ev.get("side"),
                    "price": ev.get("price"),
                    "qty": ev.get("qty"),
                }
            )

        # 3) snapshots
        if self._snaps_w is not None and et == "snapshot":
            self._snaps_w.writerow(
                {
                    "ts": ts,
                    "slug": ev.get("slug"),
                    "tick": ev.get("tick"),
                    "data_json": json.dumps(ev, ensure_ascii=False, separators=(",", ":")),
                }
            )

        # flush는 단순화 우선 (성능 문제 생기면 옵션화)
        if self._events_f: self._events_f.flush()
        if self._trades_f: self._trades_f.flush()
        if self._snaps_f:  self._snaps_f.flush()

    def close(self) -> None:
        for f in (self._events_f, self._trades_f, self._snaps_f):
            try:
                if f:
                    f.close()
            except Exception:
                pass

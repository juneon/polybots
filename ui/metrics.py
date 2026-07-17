# ui/metrics.py
"""Log-derived metrics for the UI.

- SlugCollection (Phase A): slug-collection progress from events.csv
  slug_init/slug_change rows. Append-only file -> byte-offset incremental
  parse; events.csv is the biggest log and must not be re-read every poll.
- PerfReport (Phase B): realized-PnL aggregation from trades.csv
  (per strategy+mode / run / slug, plus a cash-flow equity curve).
  trades.csv stays small (fills only) -> full re-parse, cached on mtime+size.
"""
from __future__ import annotations

import csv
import io
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.logger import EVENTS_FIELDS

ROOT = Path(__file__).resolve().parents[1]
EVENTS_CSV = ROOT / "logs" / "events.csv"
TRADES_CSV = ROOT / "logs" / "trades.csv"

# events.csv column positions, derived from the logger schema (no magic indices)
_EV_RUN_ID = EVENTS_FIELDS.index("run_id")
_EV_TYPE = EVENTS_FIELDS.index("type")
_EV_SLUG = EVENTS_FIELDS.index("slug")
_EV_DATA = EVENTS_FIELDS.index("data")

# slug completeness rule (D22) — keep in sync with backtest/data_prep.py
# (equality is test-enforced; not imported so the server stays pandas-free)
COMPLETE_FIRST_TLEFT = 870
COMPLETE_LAST_TLEFT = 15
COMPLETE_MAX_GAP_SEC = 60

# below this remaining quantity a slug's round-trip counts as closed
# (aligned with core.account DUST_CLEAR_TOKENS)
DUST_TOKENS = 0.011

# run_id format: YYYYMMDD_HHMMSS_<strategy>_<mode>  (strategy itself may contain '_')
_MODES = ("sim", "live")

# strategies renamed over time — old run_ids in append-only logs keep the old
# name; normalize at read time so history and new runs aggregate as one group
LEGACY_STRATEGY_NAMES = {"ma_breakout": "ma"}


def strategy_of_run_id(run_id: str) -> str:
    parts = run_id.split("_")
    if len(parts) >= 4 and parts[-1] in _MODES:
        name = "_".join(parts[2:-1])
        return LEGACY_STRATEGY_NAMES.get(name, name)
    return run_id


def mode_of_run_id(run_id: str) -> str:
    tail = run_id.rsplit("_", 1)[-1]
    return tail if tail in _MODES else "?"


_TLEFT_KEY = '"time_left_sec":'


def _tleft_of(data: str) -> Optional[int]:
    """Extract time_left_sec from a quote row's data JSON without a full parse
    (events.csv is tens of MB; json.loads per row would dominate the startup scan)."""
    i = data.find(_TLEFT_KEY)
    if i < 0:
        return None
    j = i + len(_TLEFT_KEY)
    end = data.find(",", j)
    if end < 0:
        end = data.find("}", j)
    try:
        return int(float(data[j:end]))
    except (TypeError, ValueError):
        return None


class SlugCollection:
    """Collection progress = COMPLETE slugs (D22), deduped across strategies.

    Two bots recording the same slug is one collected slug — the asset is the
    quote stream, not the run. Completeness mirrors data_prep.flag_complete
    exactly: unique time_left values per slug, first >= 870, last <= 15, no
    sorted-gap > 60s. Only slugs touched since the last poll are re-judged.

    Reads the legacy events.csv (frozen history) plus the daily rotation files
    events_<YYYYMMDD>.csv next to it (core.logger, 2026-07-18), each with its
    own byte-offset incremental cursor. A slug spanning midnight is merged
    naturally — coverage is keyed by slug, not by file.
    """

    def __init__(self, path: Path = EVENTS_CSV):
        self.path = path
        self._lock = threading.Lock()
        self._cursors: Dict[str, list] = {}    # file -> [offset, tail carry-over]
        self._slugs: Dict[str, Set[str]] = {}  # per-strategy observed slugs
        self._cov: Dict[str, Set[int]] = {}    # slug -> unique time_left values seen
        self._complete: Dict[str, bool] = {}
        self._dirty: Set[str] = set()

    def _files(self) -> List[Path]:
        out = [self.path] if self.path.exists() else []
        out += sorted(self.path.parent.glob("events_*.csv"))
        return out

    def progress(self) -> Dict[str, Any]:
        with self._lock:
            self._ingest()
            for slug in self._dirty:
                self._complete[slug] = self._judge(self._cov[slug])
            self._dirty.clear()
            return {
                "complete": sum(self._complete.values()),
                "total": len(self._cov),
                "by_strategy": {s: len(v) for s, v in sorted(self._slugs.items())},
            }

    @staticmethod
    def _judge(tlefts: Set[int]) -> bool:
        t = sorted(tlefts, reverse=True)
        gap = max((a - b for a, b in zip(t, t[1:])), default=0)
        return (t[0] >= COMPLETE_FIRST_TLEFT
                and t[-1] <= COMPLETE_LAST_TLEFT
                and gap <= COMPLETE_MAX_GAP_SEC)

    def _ingest(self) -> None:
        for fp in self._files():
            self._ingest_file(fp)

    def _ingest_file(self, path: Path) -> None:
        try:
            size = path.stat().st_size
        except OSError:
            return
        cur = self._cursors.setdefault(str(path), [0, ""])
        if size < cur[0]:  # truncated -> coverage sets can't be unwound: full rescan
            self._cursors = {str(path): [0, ""]}
            self._slugs, self._cov, self._complete, self._dirty = {}, {}, {}, set()
            cur = self._cursors[str(path)]
        if size == cur[0]:
            return

        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            f.seek(cur[0])
            chunk = f.read()
            cur[0] = f.tell()

        text = cur[1] + chunk
        lines = text.split("\n")
        cur[1] = lines.pop()  # incomplete (or empty) last piece

        for line in lines:
            line = line.rstrip("\r")
            if not line or line.startswith(EVENTS_FIELDS[0] + ","):
                continue
            try:
                row = next(csv.reader(io.StringIO(line)))
            except (csv.Error, StopIteration):
                continue
            if len(row) <= _EV_DATA:
                continue
            etype, slug = row[_EV_TYPE], row[_EV_SLUG]
            if not slug:
                continue
            if etype == "quote":
                t = _tleft_of(row[_EV_DATA])
                if t is None:
                    continue
                seen = self._cov.setdefault(slug, set())
                if t not in seen:
                    seen.add(t)
                    self._dirty.add(slug)
            elif etype in ("slug_init", "slug_change"):
                self._slugs.setdefault(strategy_of_run_id(row[_EV_RUN_ID]), set()).add(slug)


# ---------------------------------------------------------------- PerfReport

def _f(x: Any, default: float = 0.0) -> float:
    try:
        return default if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return default


def _local_date(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


class PerfReport:
    """Aggregate trades.csv into per-(strategy, mode) performance groups."""

    EQUITY_MAX_POINTS = 500

    def __init__(self, path: Path = TRADES_CSV):
        self.path = path
        self._lock = threading.Lock()
        self._stamp: Optional[Tuple[float, int]] = None
        self._cache: Dict[str, Any] = {"generated_ts": 0, "groups": []}

    def report(self) -> Dict[str, Any]:
        with self._lock:
            try:
                st = self.path.stat()
                stamp = (st.st_mtime, st.st_size)
            except OSError:
                return {"generated_ts": int(time.time()), "groups": []}
            if stamp != self._stamp:
                self._cache = self._build()
                self._stamp = stamp
            return self._cache

    # ---- internals ----

    def _build(self) -> Dict[str, Any]:
        groups: Dict[Tuple[str, str], Dict[str, Any]] = {}

        with self.path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("status") != "filled":
                    continue
                run_id = row.get("run_id", "")
                key = (strategy_of_run_id(run_id), mode_of_run_id(run_id))
                g = groups.setdefault(key, {
                    "slugs": {}, "runs": {}, "equity": [], "fills": 0,
                    "buy_cost": 0.0, "buy_qty": 0.0, "exit_proceeds": 0.0, "exit_qty": 0.0,
                })

                kind = row.get("intent_kind", "")
                ts = int(_f(row.get("ts")))
                qty = _f(row.get("qty_tokens"))
                px = _f(row.get("fill_price"))
                usd = qty * px
                is_buy = (kind == "buy")

                g["fills"] += 1
                slug = row.get("slug", "")
                s = g["slugs"].setdefault(slug, {
                    "buy_cost": 0.0, "buy_qty": 0.0, "exit_proceeds": 0.0, "exit_qty": 0.0,
                    "first_ts": ts, "last_ts": ts, "run_id": run_id,
                })
                r = g["runs"].setdefault(run_id, {
                    "fills": 0, "buy_cost": 0.0, "exit_proceeds": 0.0,
                    "first_ts": ts, "last_ts": ts, "slugs": set(),
                })
                r["fills"] += 1
                r["slugs"].add(slug)
                for d in (s, r):
                    d["first_ts"] = min(d["first_ts"], ts)
                    d["last_ts"] = max(d["last_ts"], ts)

                if is_buy:
                    for d in (g, s):
                        d["buy_cost"] += usd
                        d["buy_qty"] += qty
                    r["buy_cost"] += usd
                    delta = -usd
                else:
                    for d in (g, s):
                        d["exit_proceeds"] += usd
                        d["exit_qty"] += qty
                    r["exit_proceeds"] += usd
                    delta = usd

                prev = g["equity"][-1][1] if g["equity"] else 0.0
                g["equity"].append([ts, round(prev + delta, 4)])

        today = _local_date(int(time.time()))
        out = []
        for (strategy, mode), g in sorted(groups.items()):
            out.append(self._finalize_group(strategy, mode, g, today))
        return {"generated_ts": int(time.time()), "groups": out}

    def _finalize_group(self, strategy: str, mode: str, g: Dict[str, Any], today: str) -> Dict[str, Any]:
        realized = today_pnl = unclosed_tokens = 0.0
        wins = losses = open_slugs = 0
        slug_rows: List[Dict[str, Any]] = []

        for slug, s in g["slugs"].items():
            remaining = s["buy_qty"] - s["exit_qty"]
            closed = remaining <= DUST_TOKENS
            pnl = round(s["exit_proceeds"] - s["buy_cost"], 4)
            if closed:
                realized += pnl
                wins += 1 if pnl > 0 else 0
                losses += 1 if pnl <= 0 else 0
                if _local_date(s["last_ts"]) == today:
                    today_pnl += pnl
            else:
                open_slugs += 1
                unclosed_tokens += remaining
            slug_rows.append({
                "slug": slug, "run_id": s["run_id"],
                "ts": s["last_ts"], "closed": closed,
                "pnl": pnl if closed else None,
                "remaining_tokens": round(remaining, 2) if not closed else 0,
            })
        slug_rows.sort(key=lambda x: x["ts"], reverse=True)

        run_rows = [{
            "run_id": rid, "fills": r["fills"],
            "slugs": len(r["slugs"]),
            "first_ts": r["first_ts"], "last_ts": r["last_ts"],
            "cash_delta": round(r["exit_proceeds"] - r["buy_cost"], 4),
        } for rid, r in g["runs"].items()]
        run_rows.sort(key=lambda x: x["first_ts"], reverse=True)

        equity = g["equity"]
        if len(equity) > self.EQUITY_MAX_POINTS:
            stride = len(equity) // self.EQUITY_MAX_POINTS + 1
            equity = equity[::stride] + [equity[-1]]

        return {
            "strategy": strategy, "mode": mode,
            "realized_pnl": round(realized, 4),
            "today_pnl": round(today_pnl, 4),
            "wins": wins, "losses": losses,
            "open_slugs": open_slugs,
            "unclosed_tokens": round(unclosed_tokens, 2),
            "fills": g["fills"],
            "avg_entry": round(g["buy_cost"] / g["buy_qty"], 4) if g["buy_qty"] else None,
            "avg_exit": round(g["exit_proceeds"] / g["exit_qty"], 4) if g["exit_qty"] else None,
            "account": _read_sim_account(strategy) if mode == "sim" else None,
            "runs": run_rows[:20],
            "slug_rows": slug_rows[:30],
            "equity": equity,
        }


def _read_sim_account(strategy: str) -> Optional[Dict[str, Any]]:
    # state/ is current (2026-07-12); root is the pre-migration location —
    # a bot started with old code keeps writing there until its next restart
    for p in (ROOT / "state" / f"sim_account_{strategy}.json",
              ROOT / f"sim_account_{strategy}.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return {"cash": data.get("cash"), "position": data.get("position")}
        except (OSError, ValueError):
            continue
    return None

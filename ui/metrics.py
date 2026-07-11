# ui/metrics.py
"""Log-derived metrics for the UI.

Phase A: slug-collection progress (distinct slugs observed per strategy,
counted from events.csv slug_init/slug_change rows). The file is append-only,
so we keep a byte offset and only parse what was added since the last poll —
events.csv is the biggest log and must not be re-read every 2 seconds.

Phase B will add PnL aggregation here (from trades.csv/snapshots.csv).
"""
from __future__ import annotations

import csv
import io
import threading
from pathlib import Path
from typing import Dict, Set

ROOT = Path(__file__).resolve().parents[1]
EVENTS_CSV = ROOT / "logs" / "events.csv"

# run_id format: YYYYMMDD_HHMMSS_<strategy>_<mode>  (strategy itself may contain '_')
_MODES = ("sim", "live")


def strategy_of_run_id(run_id: str) -> str:
    parts = run_id.split("_")
    if len(parts) >= 4 and parts[-1] in _MODES:
        return "_".join(parts[2:-1])
    return run_id


class SlugCollection:
    def __init__(self, path: Path = EVENTS_CSV):
        self.path = path
        self._lock = threading.Lock()
        self._offset = 0
        self._tail = ""  # carry-over of an incomplete trailing line
        self._slugs: Dict[str, Set[str]] = {}

    def counts(self) -> Dict[str, int]:
        with self._lock:
            self._ingest()
            return {s: len(v) for s, v in self._slugs.items()}

    def _ingest(self) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self._offset:  # rotated/truncated -> full rescan
            self._offset, self._tail, self._slugs = 0, "", {}
        if size == self._offset:
            return

        with self.path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            f.seek(self._offset)
            chunk = f.read()
            self._offset = f.tell()

        text = self._tail + chunk
        lines = text.split("\n")
        self._tail = lines.pop()  # incomplete (or empty) last piece

        for line in lines:
            line = line.rstrip("\r")
            if not line or line.startswith("run_id,"):
                continue
            try:
                row = next(csv.reader(io.StringIO(line)))
            except (csv.Error, StopIteration):
                continue
            if len(row) < 3 or row[1] not in ("slug_init", "slug_change"):
                continue
            run_id, slug = row[0], row[2]
            if not slug:
                continue
            self._slugs.setdefault(strategy_of_run_id(run_id), set()).add(slug)

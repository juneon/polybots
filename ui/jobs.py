# ui/jobs.py
"""Backtest job runner for the UI (Phase D).

One job = one backtest script subprocess (cwd=backtest/):
  data_prep / engine --strategy X / sweep_threshold / run_grid

Jobs run strictly ONE at a time (run_grid itself fans out over a process
pool; overlapping two would saturate the machine) — extra submits queue.
stdout streams to logs/ctl/bt_<job_id>.log for UI tail-polling. Results come
from the scripts' --json flag, written straight into the archive
backtest/results/<ts>_<kind>_<strategy>.json (+ the full rows CSV alongside
for sweep/grid) — no stdout parsing anywhere.

The in-memory job list does not survive a server restart; the archive and
log files do. A running subprocess is NOT killed when the server dies.
"""
from __future__ import annotations

import glob
import json
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
BACKTEST = ROOT / "backtest"
RESULTS = BACKTEST / "results"
CTL_DIR = ROOT / "logs" / "ctl"
PARQUET = BACKTEST / "data" / "quotes_all.parquet"

KINDS = ("data_prep", "engine", "sweep_threshold", "run_grid")
FIXED_STRATEGY = {"sweep_threshold": "threshold", "run_grid": "ma_breakout"}
NEEDS_PARQUET = ("engine", "sweep_threshold", "run_grid")

MAX_PENDING = 5
TAIL_BYTES = 16384


class JobError(Exception):
    pass


def data_status() -> Dict[str, Any]:
    """data_prep output presence/freshness — precondition for engine/sweep/grid."""
    sources = [ROOT / "logs" / "events.csv", ROOT / "archive" / "polybots_MA" / "logs" / "events.csv"]
    sources += [Path(p) for p in glob.glob(str(BACKTEST / "data" / "*_events.csv"))]
    newest_src = max((p.stat().st_mtime for p in sources if p.exists()), default=None)

    exists = PARQUET.exists()
    pq_mtime = PARQUET.stat().st_mtime if exists else None
    return {
        "parquet_exists": exists,
        "parquet_mtime": int(pq_mtime) if pq_mtime else None,
        "stale": bool(exists and newest_src and newest_src > pq_mtime),
    }


def results_list(limit: int = 50) -> List[Dict[str, Any]]:
    """Archived result JSONs, newest first (filename = <ts>_<kind>_<strategy>.json)."""
    out = []
    if not RESULTS.exists():
        return out
    for p in sorted(RESULTS.glob("*.json"), reverse=True)[:limit]:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({
            "file": p.name,
            "mtime": int(p.stat().st_mtime),
            "kind": data.get("kind"),
            "strategy": data.get("strategy"),
            "data": data,
        })
    return out


def _num(params: Dict[str, Any], key: str, default: float) -> float:
    v = params.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise JobError(f"{key}: 숫자여야 함")
    return float(v)


class JobManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._order: List[str] = []          # newest first
        self._q: "queue.Queue[str]" = queue.Queue()
        self._current: Optional[tuple] = None  # (job_id, Popen)
        self._seq = 0
        CTL_DIR.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._worker, daemon=True, name="bt-jobs").start()

    # ---------- public ----------

    def submit(self, kind: str, strategy: Optional[str], params: Dict[str, Any],
               known_strategies: List[str]) -> Dict[str, Any]:
        if kind not in KINDS:
            raise JobError(f"알 수 없는 종류: {kind}")
        strategy = FIXED_STRATEGY.get(kind, strategy if kind == "engine" else None)
        if kind == "engine":
            if not strategy or strategy not in known_strategies:
                raise JobError(f"engine에는 유효한 strategy 필요 (got {strategy!r})")
        if kind in NEEDS_PARQUET and not PARQUET.exists():
            raise JobError("data/quotes_all.parquet 없음 — data_prep을 먼저 실행")

        with self._lock:
            pending = sum(1 for j in self._jobs.values() if j["state"] in ("queued", "running"))
            if pending >= MAX_PENDING:
                raise JobError(f"대기열 가득참 ({pending}개 진행/대기 중)")
            self._seq += 1
            job_id = time.strftime("%Y%m%d_%H%M%S") + f"_{self._seq}_{kind}"

            # seq prevents same-second collisions (would silently overwrite an archive)
            archive_base = time.strftime("%Y%m%d_%H%M%S") + f"_{self._seq}_{kind}" + (f"_{strategy}" if strategy else "")
            archive_json = RESULTS / f"{archive_base}.json" if kind != "data_prep" else None
            archive_csv = RESULTS / f"{archive_base}.csv"

            job = {
                "id": job_id, "kind": kind, "strategy": strategy,
                "params": dict(params), "state": "queued",
                "created_ts": int(time.time()), "started_ts": None, "ended_ts": None,
                "returncode": None, "pid": None, "error": None,
                "log": f"logs/ctl/bt_{job_id}.log",
                "result_file": archive_json.name if archive_json else None,
                "data_stale": data_status()["stale"] if kind in NEEDS_PARQUET else False,
                "_cmd": self._build_cmd(kind, strategy, params, archive_json, archive_csv),
            }
            self._jobs[job_id] = job
            self._order.insert(0, job_id)
            del self._order[50:]
        self._q.put(job_id)
        return self._public(job)

    def status(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self._public(self._jobs[i]) for i in self._order if i in self._jobs]

    def get(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            raise JobError(f"없는 job: {job_id}")
        out = self._public(job)
        out["log_tail"] = self._tail(ROOT / job["log"])
        return out

    def cancel(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobError(f"없는 job: {job_id}")
            if job["state"] == "queued":
                job["state"] = "cancelled"
                job["ended_ts"] = int(time.time())
            elif job["state"] == "running" and self._current and self._current[0] == job_id:
                self._current[1].terminate()   # worker records the final state
            return self._public(job)

    # ---------- internals ----------

    @staticmethod
    def _public(job: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in job.items() if not k.startswith("_")}

    @staticmethod
    def _tail(path: Path, max_bytes: int = TAIL_BYTES) -> str:
        try:
            with path.open("rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - max_bytes))
                return f.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    @staticmethod
    def _build_cmd(kind: str, strategy: Optional[str], params: Dict[str, Any],
                   archive_json: Optional[Path], archive_csv: Path) -> List[str]:
        py = sys.executable
        if kind == "data_prep":
            return [py, "data_prep.py"]

        cost = ["--haircut", str(_num(params, "haircut", 0.01)),
                "--pfail", str(_num(params, "pfail", 0.2)),
                "--seed", str(int(_num(params, "seed", 42)))]
        js = ["--json", str(archive_json)]

        if kind == "engine":
            cmd = [py, "engine.py", "--strategy", strategy] + cost + js
            for k, v in (params.get("set") or {}).items():
                if not re.fullmatch(r"[a-z_][a-z0-9_]*", str(k)):
                    raise JobError(f"override 키 형식 오류: {k}")
                if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float, str))):
                    raise JobError(f"override 값은 스칼라만: {k}")
                cmd += ["--set", f"{k}={json.dumps(v)}"]
            return cmd
        if kind == "sweep_threshold":
            return [py, "sweep_threshold.py"] + cost + js + ["--out", str(archive_csv)]
        # run_grid
        cmd = [py, "run_grid.py"] + cost + js + ["--out", str(archive_csv)]
        if params.get("quick"):
            cmd.append("--quick")
        return cmd

    def _worker(self) -> None:
        while True:
            job_id = self._q.get()
            with self._lock:
                job = self._jobs.get(job_id)
                if not job or job["state"] != "queued":
                    continue
                job["state"] = "running"
                job["started_ts"] = int(time.time())
                cmd = job["_cmd"]

            RESULTS.mkdir(parents=True, exist_ok=True)
            log_path = ROOT / job["log"]
            try:
                with log_path.open("a", encoding="utf-8") as log_f:
                    log_f.write(f"$ {' '.join(cmd)}\n")
                    log_f.flush()
                    proc = subprocess.Popen(
                        cmd, cwd=str(BACKTEST),
                        stdout=log_f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                    )
                    with self._lock:
                        job["pid"] = proc.pid
                        self._current = (job_id, proc)
                    rc = proc.wait()
            except OSError as e:
                rc = -1
                job["error"] = repr(e)

            with self._lock:
                self._current = None
                job["returncode"] = rc
                job["ended_ts"] = int(time.time())
                if rc != 0:
                    job["state"] = "failed"
                    job["error"] = job["error"] or f"exit code {rc}"
                elif job["result_file"] and not (RESULTS / job["result_file"]).exists():
                    job["state"] = "failed"
                    job["error"] = "정상 종료했지만 결과 JSON이 없음"
                else:
                    job["state"] = "done"

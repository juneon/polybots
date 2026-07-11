# ui/procman.py
"""Bot process manager for the control UI.

One bot process per strategy. Lifecycle:
  start: spawn `python -m core.runner --strategy S --mode sim --run-id RID`
         (stdout/stderr -> logs/ctl/RID.out.log)
  stop:  create the stop file -> the bot exits gracefully on its next tick;
         terminate() only as a fallback after STOP_GRACE_SEC.
  status: liveness from the process handle, detail from the heartbeat file
          (logs/ctl/RID.status.json, written by core.control.RunControl).

Heartbeat files whose pid we don't manage (e.g. a sim started from a plain
terminal) are still reported, flagged managed=False.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
CTL_DIR = ROOT / "logs" / "ctl"

STOP_GRACE_SEC = 15.0     # graceful-exit wait before terminate()
HB_FRESH_SEC = 5          # heartbeat older than this while running -> "stale"
HB_EXTERNAL_SEC = 10      # unmanaged heartbeat newer than this -> probably an external live bot


class ProcManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._procs: Dict[str, Dict[str, Any]] = {}  # strategy -> {proc, run_id, mode, started_ts, out_path}
        CTL_DIR.mkdir(parents=True, exist_ok=True)

    # ---------- lifecycle ----------

    def start(self, strategy: str, mode: str = "sim") -> Dict[str, Any]:
        if mode != "sim":
            # hard server-side guard until Phase E; UI disables the option as well
            raise PermissionError("live mode is disabled in the UI (Phase E)")

        with self._lock:
            self._reap_locked()
            if strategy in self._procs:
                raise RuntimeError(f"{strategy} is already running (run_id={self._procs[strategy]['run_id']})")

            run_id = time.strftime("%Y%m%d_%H%M%S") + f"_{strategy}_{mode}"
            out_path = CTL_DIR / f"{run_id}.out.log"
            out_f = out_path.open("a", encoding="utf-8")
            proc = subprocess.Popen(
                [sys.executable, "-m", "core.runner",
                 "--strategy", strategy, "--mode", mode, "--run-id", run_id],
                cwd=str(ROOT),
                stdout=out_f, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
            out_f.close()  # child holds its own handle

            self._procs[strategy] = {
                "proc": proc,
                "run_id": run_id,
                "mode": mode,
                "started_ts": int(time.time()),
                "out_path": str(out_path),
            }
            return {"run_id": run_id, "pid": proc.pid}

    def stop(self, strategy: str) -> Dict[str, Any]:
        with self._lock:
            info = self._procs.get(strategy)
        if not info:
            raise RuntimeError(f"{strategy} is not managed by this server")

        proc: subprocess.Popen = info["proc"]
        run_id = info["run_id"]
        stop_path = CTL_DIR / f"{run_id}.stop"
        stop_path.touch()

        deadline = time.time() + STOP_GRACE_SEC
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.5)

        forced = False
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            forced = True

        try:
            stop_path.unlink(missing_ok=True)
        except OSError:
            pass

        with self._lock:
            self._procs.pop(strategy, None)
        return {"run_id": run_id, "forced": forced, "returncode": proc.poll()}

    def stop_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            names = list(self._procs)
        return [dict(self.stop(s), strategy=s) for s in names]

    # ---------- status ----------

    def status(self) -> List[Dict[str, Any]]:
        """Managed processes + fresh unmanaged heartbeats (e.g. a terminal-started sim)."""
        now = int(time.time())
        out: List[Dict[str, Any]] = []

        with self._lock:
            self._reap_locked()
            managed = {s: dict(i) for s, i in self._procs.items()}

        seen_run_ids = set()
        for strategy, info in managed.items():
            hb = _read_heartbeat(info["run_id"])
            seen_run_ids.add(info["run_id"])
            out.append({
                "strategy": strategy,
                "managed": True,
                "run_id": info["run_id"],
                "mode": info["mode"],
                "pid": info["proc"].pid,
                "uptime_sec": now - info["started_ts"],
                "heartbeat": hb,
                "heartbeat_stale": bool(hb) and (now - hb.get("hb_ts", 0) > HB_FRESH_SEC),
                "out_log": info["out_path"],
            })

        for hb in _scan_heartbeats():
            if hb.get("run_id") in seen_run_ids:
                continue
            if hb.get("state") != "running" or now - hb.get("hb_ts", 0) > HB_EXTERNAL_SEC:
                continue
            out.append({
                "strategy": hb.get("strategy", "?"),
                "managed": False,
                "run_id": hb.get("run_id"),
                "mode": hb.get("mode", "?"),
                "pid": hb.get("pid"),
                "uptime_sec": None,
                "heartbeat": hb,
                "heartbeat_stale": False,
                "out_log": None,
            })
        return out

    def _reap_locked(self) -> None:
        """Drop entries whose process already exited (crash or self-exit)."""
        dead = [s for s, i in self._procs.items() if i["proc"].poll() is not None]
        for s in dead:
            self._procs.pop(s, None)


def _read_heartbeat(run_id: str) -> Optional[Dict[str, Any]]:
    p = CTL_DIR / f"{run_id}.status.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _scan_heartbeats() -> List[Dict[str, Any]]:
    out = []
    for p in CTL_DIR.glob("*.status.json"):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out

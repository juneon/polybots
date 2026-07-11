# core/control.py
"""File-based run control (UI <-> bot process bridge).

The UI server and the bot run as separate processes; they talk through
small files in logs/ctl/ (chosen over signals, which are unreliable for
subprocesses on Windows):

  <run_id>.stop         존재하면 다음 tick에 그레이스풀 종료 (UI가 생성, 종료 후 UI가 정리)
  <run_id>.status.json  heartbeat — 매 tick 현재 상태를 원자적으로 갱신 (UI가 폴링)

A bot without a controller (plain CLI run) behaves identically: the stop
file simply never appears, and the heartbeat is just extra observability.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


class RunControl:
    def __init__(self, run_id: str, ctl_dir: str):
        self.run_id = str(run_id)
        self.dir = Path(ctl_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.stop_path = self.dir / f"{self.run_id}.stop"
        self.status_path = self.dir / f"{self.run_id}.status.json"
        self._tmp_path = self.dir / f"{self.run_id}.status.tmp"

    def stop_requested(self) -> bool:
        return self.stop_path.exists()

    def heartbeat(self, payload: Dict[str, Any]) -> None:
        """Write status atomically (tmp + replace) so a polling reader never sees a partial file."""
        data = dict(payload)
        data["run_id"] = self.run_id
        data["hb_ts"] = int(time.time())
        try:
            self._tmp_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(self._tmp_path, self.status_path)
        except Exception as e:  # heartbeat must never take the bot down
            log.warning("heartbeat write failed: %r", e)


def snapshot_status(
    state: str,
    *,
    strategy: str,
    mode: str,
    ev: Optional[Dict[str, Any]] = None,
    account=None,
    slug_count: int = 0,
    stop_reason: str = "",
) -> Dict[str, Any]:
    """Build a heartbeat payload from the current event/account."""
    out: Dict[str, Any] = {
        "state": state,  # running | stopped
        "strategy": strategy,
        "mode": mode,
        "slug_count": slug_count,
        "pid": os.getpid(),
    }
    if stop_reason:
        out["stop_reason"] = stop_reason
    if ev:
        out["slug"] = ev.get("slug", "")
        out["tick"] = ev.get("tick", "")
        out["time_left_sec"] = ev.get("time_left_sec", "")
    if account is not None:
        out["cash"] = getattr(account, "cash", None)
        out["position"] = getattr(account, "position", None)
    return out

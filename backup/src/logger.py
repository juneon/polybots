# src/logger.py
import csv
import json
import os
import time
from typing import Any, Dict

Event = Dict[str, Any]


class Logger:
    """
    v0 Logger
    - event(dict)를 logs/events.csv에 그대로 append
    - 절대 시스템을 죽이지 않음(로깅 실패는 무시)
    """

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        self.path = os.path.join(log_dir, "events.csv")
        self._ensure_file()

    def handle(self, event: Event) -> None:
        row = {
            "ts": time.time(),
            "type": event.get("type"),
            "slug": event.get("slug"),
            "tick": event.get("tick"),
            "data": json.dumps(event, ensure_ascii=False, default=str),
        }
        try:
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["ts", "type", "slug", "tick", "data"])
                writer.writerow(row)
        except Exception:
            pass

    def _ensure_file(self) -> None:
        os.makedirs(self.log_dir, exist_ok=True)
        if not os.path.exists(self.path):
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["ts", "type", "slug", "tick", "data"])
                writer.writeheader()

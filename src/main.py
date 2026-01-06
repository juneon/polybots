# src/main.py
from __future__ import annotations

import json
from typing import Any, Dict

from .adapters_polymarket import PolymarketAdapter
from .slug_loop import run_slug_loop
from .printer import Printer
from .logger import Logger
from .strategy import Strategy


def load_config(path: str = "config.json") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def default_state() -> Dict[str, Any]:
    return {
        "entries": {"up": 0, "down": 0},
        "position": None,
        "last_intent": None,
        "tp_done": False,
    }


def main() -> None:
    cfg = load_config()

    pm = PolymarketAdapter(cfg)
    logger = Logger(cfg)
    printer = Printer(cfg)
    strategy = Strategy(cfg)

    # ✅ slug는 event에서만 본다
    current_slug: str | None = None
    state: Dict[str, Any] = default_state()

    for ev in run_slug_loop(pm, cfg):
        et = ev["type"]

        # quote 기준으로 slug 확정 + 변경 감지
        if et == "quote":
            slug = ev["slug"]
            if slug != current_slug:
                current_slug = slug
                state = default_state()

        # sink는 항상 먼저
        printer.on_event(ev, state)
        logger.handle(ev)

        # 전략 판단
        if et == "quote":
            for it in strategy.on_event(ev, state):
                printer.on_event(it, state)
                logger.handle(it)

        elif et == "exit":
            break

    logger.close()


if __name__ == "__main__":
    main()

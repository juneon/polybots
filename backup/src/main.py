from __future__ import annotations

import json

from .adapters_polymarket import PolymarketAdapter
from .slug_loop import run_slug_loop
from .printer import Printer
from .logger import Logger
from .strategy import Strategy


def load_config(path: str = "config.json") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    cfg = load_config()

    # --- components ---
    pm = PolymarketAdapter(cfg)
    strategy = Strategy(cfg)

    printer = Printer()
    logger = Logger()

    # --- event loop ---
    for ev in run_slug_loop(pm, cfg):
        # 1) market / system events
        printer.on_event(ev)
        logger.handle(ev)

        # 2) strategy decisions
        intents = strategy.on_event(ev) or []
        for it in intents:
            printer.on_event(it)
            logger.handle(it)


if __name__ == "__main__":
    main()

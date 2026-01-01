# src/main.py

import json
from .adapters_polymarket import PolymarketAdapter
from .slug_loop import run_slug_loop
from .printer import Printer


def load_config(path="config.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    cfg = load_config()

    pm = PolymarketAdapter(cfg)
    pr = Printer()

    # slug_loop는 이벤트를 yield, printer는 이벤트를 출력
    for ev in run_slug_loop(pm, cfg):
        pr.handle(ev)


if __name__ == "__main__":
    main()

import json
from .adapters_polymarket import PolymarketAdapter


def load_config(path="config.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    cfg = load_config()
    pm = PolymarketAdapter(cfg)
    pm.poll_rolling()


if __name__ == "__main__":
    main()

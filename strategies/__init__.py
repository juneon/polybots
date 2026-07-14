# strategies: pluggable strategy implementations (1 strategy = 1 module)
from .ma import MAStrategy
from .threshold import ThresholdStrategy

REGISTRY = {
    "ma": MAStrategy,
    "threshold": ThresholdStrategy,
}


def create_strategy(name: str, cfg: dict):
    cls = REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown strategy: {name!r} (available: {sorted(REGISTRY)})")
    return cls(cfg)

# tests/helpers.py
"""Shared fixtures-in-code for strategy tests: a minimal SOT stub and quote events."""
from typing import Any, Dict, Optional


class FakeAccount:
    """Only what strategies read: the .position SOT."""

    def __init__(self, position: Optional[Dict[str, Any]] = None):
        self.position = position


def quote_ev(slug="s1", tick=1, tleft=300, ts=1000.0,
             up=(0.79, 0.82), dn=(0.15, 0.18)) -> Dict[str, Any]:
    return {
        "type": "quote", "slug": slug, "tick": tick,
        "time_left_sec": tleft, "ts": ts, "slug_start_ts": 0,
        "quote": {
            "up": {"outcome": "Up", "token_id": "TU", "bid": up[0], "ask": up[1]},
            "down": {"outcome": "Down", "token_id": "TD", "bid": dn[0], "ask": dn[1]},
        },
    }


def trade(kind, status, slug="s1", side="up", qty=10.0, px=0.82) -> Dict[str, Any]:
    return {
        "type": "trade", "kind": kind, "status": status, "slug": slug,
        "side": side, "qty_tokens": qty, "fill_price": px,
        "tick": 0, "ts": 1000.0, "reason": "", "token_id": "", "data": {}, "debug": {},
    }

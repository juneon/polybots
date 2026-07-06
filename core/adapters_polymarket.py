# core/adapters_polymarket.py
"""Polymarket data adapter.

- Gamma: GET /events/slug/{slug} -> event metadata (slug -> Up/Down token ids).
  Called once per slug (cached).
- CLOB:  GET /price?token_id=...&side=buy|sell -> {"price": "<str>"}.
  Called every tick.

Verified convention (checked against /book on 2026-07-06):
  /price?side=buy  == best BID (highest resting buy order)
  /price?side=sell == best ASK (lowest resting sell order)
so: bid = _price(side="buy"), ask = _price(side="sell").
"""
import json
import logging
import time
from typing import Any, Dict, Tuple

import requests

log = logging.getLogger(__name__)


class PolymarketAdapter:
    # transient-network retry policy for every HTTP GET
    RETRIES = 2
    BACKOFF_SEC = 0.2

    def __init__(self, cfg: Dict[str, Any]):
        self.gamma = str(cfg["gamma_base"]).rstrip("/")
        self.clob = str(cfg["clob_base"]).rstrip("/")
        self.tmo = float(cfg.get("timeout_sec", 5))

        self.prefix = str(cfg["event_slug_prefix"])
        self.interval_sec = int(cfg.get("interval_sec", 900))

        self.sess = requests.Session()

        # slug -> (up_token_id, down_token_id)
        self._token_cache: Dict[str, Tuple[str, str]] = {}

    # --- time/slug helpers (used by slug_loop) ---
    def slug_now(self) -> Tuple[str, int]:
        start = (int(time.time()) // self.interval_sec) * self.interval_sec
        return f"{self.prefix}-{start}", start

    # --- http ---
    def get(self, url: str, **params) -> Any:
        """GET with a small retry/backoff for transient network errors."""
        last_err: Exception | None = None
        for attempt in range(self.RETRIES + 1):
            try:
                r = self.sess.get(url, params=params or None, timeout=self.tmo)
                r.raise_for_status()
                return r.json()
            except requests.RequestException as e:
                last_err = e
                if attempt < self.RETRIES:
                    wait = self.BACKOFF_SEC * (attempt + 1)
                    log.warning("HTTP retry %d/%d for %s (%r), waiting %.1fs",
                                attempt + 1, self.RETRIES, url, e, wait)
                    time.sleep(wait)
        assert last_err is not None
        raise last_err

    # --- gamma ---
    def event_by_slug(self, slug: str) -> Dict[str, Any]:
        return self.get(f"{self.gamma}/events/slug/{slug}")

    def _resolve_tokens_for_slug(self, slug: str) -> Tuple[str, str]:
        """Returns (up_token_id, down_token_id). Cached per slug -> Gamma is hit only on slug change."""
        cached = self._token_cache.get(slug)
        if cached is not None:
            return cached

        ev = self.event_by_slug(slug)
        market = ev["markets"][0]

        outcomes = json.loads(market["outcomes"])         # ["Up","Down"]
        token_ids = json.loads(market["clobTokenIds"])    # ["<up>","<down>"]

        up_token = str(token_ids[outcomes.index("Up")])
        dn_token = str(token_ids[outcomes.index("Down")])

        self._token_cache[slug] = (up_token, dn_token)
        return up_token, dn_token

    def clear_cache(self) -> None:
        self._token_cache.clear()

    # --- clob ---
    def _price(self, token_id: str, side: str) -> str:
        data = self.get(f"{self.clob}/price", token_id=token_id, side=side)
        return str(data["price"])

    def best_bid_ask(self, token_id: str) -> Tuple[str, str]:
        bid = self._price(token_id, "buy")    # best bid  (verified, see module docstring)
        ask = self._price(token_id, "sell")   # best ask
        return bid, ask

    # --- public (used by slug_loop) ---
    def quote_updown(self, slug: str) -> Dict[str, Any]:
        up_token, dn_token = self._resolve_tokens_for_slug(slug)

        up_bid, up_ask = self.best_bid_ask(up_token)
        dn_bid, dn_ask = self.best_bid_ask(dn_token)

        return {
            "slug": slug,
            "up": {"outcome": "Up", "token_id": up_token, "bid": up_bid, "ask": up_ask},
            "down": {"outcome": "Down", "token_id": dn_token, "bid": dn_bid, "ask": dn_ask},
        }

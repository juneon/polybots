import time
import json
import requests


class PolymarketAdapter:
    def __init__(self, cfg: dict):
        # --- infra / network ---
        self.gamma = cfg["gamma_base"]
        self.clob = cfg["clob_base"]
        self.tmo = cfg.get("timeout_sec", 10)
        self.sess = requests.Session()

        # --- execution config (loop는 slug_loop가 담당하지만, 기존 필드는 유지) ---
        self.prefix = cfg["event_slug_prefix"]
        self.interval_sec = int(cfg["interval_sec"])

    # --------------------
    # basic http
    # --------------------
    def get(self, url, **params):
        r = self.sess.get(url, params=params or None, timeout=self.tmo)
        r.raise_for_status()
        return r.json()

    # --------------------
    # slug util
    # --------------------
    def slug_now(self):
        start = (int(time.time()) // self.interval_sec) * self.interval_sec
        return f"{self.prefix}-{start}", start

    # --------------------
    # parsing helpers
    # --------------------
    def _as_list(self, x):
        if x is None:
            return []
        if isinstance(x, list):
            return [str(v) for v in x]
        if isinstance(x, str):
            try:
                j = json.loads(x)
                if isinstance(j, list):
                    return [str(v) for v in j]
            except Exception:
                pass
            return [p.strip() for p in x.split(",")] if "," in x else [x]
        return [str(x)]

    # --------------------
    # gamma
    # --------------------
    def event_by_slug(self, slug):
        return self.get(f"{self.gamma}/events/slug/{slug}")

    def pick_market(self, markets):
        for m in markets:
            if m.get("enableOrderBook") and m.get("active"):
                return m
        for m in markets:
            if m.get("enableOrderBook"):
                return m
        return markets[0]

    def outcome_token_pairs(self, market):
        outcomes = market.get("outcomes")
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except Exception:
                outcomes = None

        token_ids = self._as_list(market.get("clobTokenIds"))
        if isinstance(outcomes, list) and len(outcomes) >= 2 and len(token_ids) >= 2:
            return [
                (str(outcomes[0]), token_ids[0]),
                (str(outcomes[1]), token_ids[1]),
            ]
        raise RuntimeError("Cannot extract outcome/token pairs")

    # --------------------
    # clob
    # --------------------
    def best_bid_ask(self, token_id):
        best_bid = self.get(
            f"{self.clob}/price", token_id=token_id, side="buy"
        ).get("price")
        best_ask = self.get(
            f"{self.clob}/price", token_id=token_id, side="sell"
        ).get("price")
        return best_bid, best_ask

    # --------------------
    # slug -> token binding
    # --------------------
    def resolve_pairs_for_slug(self, slug):
        event = self.event_by_slug(slug)
        markets = event.get("markets") or []
        if not markets:
            raise RuntimeError(f"event.markets empty (slug={slug})")
        market = self.pick_market(markets)
        return self.outcome_token_pairs(market)

    # --------------------
    # convenience: slug에서 Up/Down bid/ask 묶어서 반환
    # --------------------
    def quote_updown(self, slug):
        """
        return:
          {
            "slug": slug,
            "up":   {"outcome": "Up",   "token_id": "...", "bid": x, "ask": y},
            "down": {"outcome": "Down", "token_id": "...", "bid": x, "ask": y},
          }
        """
        pairs = self.resolve_pairs_for_slug(slug)

        result = {"slug": slug, "up": None, "down": None}

        for outcome, token_id in pairs:
            o = outcome.lower()
            if o == "up":
                bid, ask = self.best_bid_ask(token_id)
                result["up"] = {"outcome": outcome, "token_id": token_id, "bid": bid, "ask": ask}
            elif o == "down":
                bid, ask = self.best_bid_ask(token_id)
                result["down"] = {"outcome": outcome, "token_id": token_id, "bid": bid, "ask": ask}

        # Up/Down 둘 중 하나라도 못 얻으면 예외로 올려서 상위에서 warn 처리
        if not result["up"] or not result["down"]:
            raise RuntimeError("Up/Down quote not ready yet")

        return result

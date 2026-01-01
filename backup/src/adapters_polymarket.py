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

        # --- execution config ---
        self.prefix = cfg["event_slug_prefix"]
        self.interval_sec = int(cfg["interval_sec"])
        self.loop_mode = cfg.get("loop_mode", "rolling").lower()
        self.run_seconds = int(cfg.get("run_seconds", 0))
        self.max_slugs = int(cfg.get("max_slugs", 0))
        self.print_every = int(cfg.get("print_every", 1))

        # polling rule (합의 사항)
        self.poll_interval = 1  # 항상 1초

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
    # rolling poll (FINAL)
    # --------------------
    def poll_rolling(self):
        start_time = time.time()
        deadline = (
            start_time + self.run_seconds
            if self.loop_mode == "duration" and self.run_seconds > 0
            else None
        )

        last_slug = None
        rollover_count = 0
        tick = 0

        while True:
            now = time.time()

            # duration 종료
            if deadline and now >= deadline:
                print("exit: duration reached")
                return

            slug, _ = self.slug_now()

            # --- slug 변화 감지 ---
            if last_slug is None:
                last_slug = slug
                print("\n=== SLUG INIT ===")
                print(f"slug : {slug}")

            elif slug != last_slug:
                if self.loop_mode == "one":
                    pass
                else:
                    last_slug = slug
                    rollover_count += 1

                    print("\n=== SLUG CHANGE ===")
                    print(f"slug : {slug}")
                    print(f"rollover_count : {rollover_count}")

                    if self.max_slugs > 0 and rollover_count >= self.max_slugs:
                        print("exit: max_slugs reached")
                        return

            # --- 출력 ---
            if tick % self.print_every == 0:
                try:
                    pairs = self.resolve_pairs_for_slug(slug)
                    slug_prefix = slug.rsplit("-", 1)[0]
                    print(f"\n[{tick:06d}] {slug_prefix}")

                    for label in ("Up", "Down"):
                        for outcome, token_id in pairs:
                            if outcome.lower() == label.lower():
                                bid, ask = self.best_bid_ask(token_id)
                                print(
                                    f"{label:<5}: "
                                    f"best_ask(market buy) / best_bid(market sell) : "
                                    f"{ask} / {bid}"
                                )
                except Exception as e:
                    print(f"[warn] data not ready yet: {e}")

            tick += 1
            time.sleep(self.poll_interval)

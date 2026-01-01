import time, json, requests

GAMMA = "https://gamma-api.polymarket.com"
CLOB  = "https://clob.polymarket.com"
PREFIX = "btc-updown-15m"
TMO = 10

def get(url, **params):
    r = requests.get(url, params=params or None, timeout=TMO)
    r.raise_for_status()
    return r.json()

def slug_now(interval=900):
    start = (int(time.time()) // interval) * interval
    return f"{PREFIX}-{start}", start

def as_list(x):
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

def pick_market(markets):
    for m in markets:
        if m.get("enableOrderBook") and m.get("active"):
            return m
    for m in markets:
        if m.get("enableOrderBook"):
            return m
    return markets[0]

def outcome_token_pairs(market):
    outcomes = market.get("outcomes")
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            outcomes = None

    token_ids = as_list(market.get("clobTokenIds"))
    if isinstance(outcomes, list) and len(outcomes) >= 2 and len(token_ids) >= 2:
        return [(str(outcomes[0]), token_ids[0]), (str(outcomes[1]), token_ids[1])]

    raise RuntimeError("Cannot extract outcome/token pairs")

def best_bid_ask_from_price(token_id: str):
    # 정의 고정:
    # - best_ask: market buy 시 체결 가격
    # - best_bid: market sell 시 체결 가격
    best_bid = get(f"{CLOB}/price", token_id=token_id, side="buy").get("price")
    best_ask = get(f"{CLOB}/price", token_id=token_id, side="sell").get("price")
    return best_bid, best_ask

def main():
    slug, start = slug_now()
    print(f"slug: {slug} start_epoch: {start}")

    event = get(f"{GAMMA}/events/slug/{slug}")
    markets = event.get("markets") or []
    if not markets:
        raise RuntimeError("event.markets empty")

    market = pick_market(markets)
    pairs = outcome_token_pairs(market)

    print("\n=== Best Bid/Ask via /price ===")
    for outcome, token_id in pairs:
        best_bid, best_ask = best_bid_ask_from_price(token_id)

        print(f"[{outcome}] token_id={token_id}")
        print(f"  best_ask (market buy) : {best_ask}")
        print(f"  best_bid (market sell): {best_bid}")

if __name__ == "__main__":
    main()

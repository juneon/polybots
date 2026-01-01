import time, json, requests
from typing import Any, Dict, List, Optional, Tuple

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE  = "https://clob.polymarket.com"
EVENT_SLUG_PREFIX = "btc-updown-15m"
HTTP_TIMEOUT = 10

def http_get_json(url: str, params: Optional[dict] = None) -> Any:
    r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()

def floor_to_interval(epoch_sec: int, interval_sec: int) -> int:
    return (epoch_sec // interval_sec) * interval_sec

def build_slug() -> Tuple[str, int]:
    now = int(time.time())
    start = floor_to_interval(now, 900)
    return f"{EVENT_SLUG_PREFIX}-{start}", start

def gamma_event_by_slug(slug: str) -> Dict[str, Any]:
    return http_get_json(f"{GAMMA_BASE}/events/slug/{slug}")

def parse_clob_token_ids(raw: Any) -> List[str]:
    if raw is None: return []
    if isinstance(raw, list): return [str(x) for x in raw]
    if isinstance(raw, str):
        s = raw.strip()
        try:
            j = json.loads(s)
            if isinstance(j, list): return [str(x) for x in j]
        except Exception:
            pass
        if "," in s: return [p.strip() for p in s.split(",") if p.strip()]
        return [s]
    return [str(raw)]

def select_market(markets: List[dict]) -> dict:
    # enableOrderBook True 우선, active True 우선
    tradable = [m for m in markets if m.get("enableOrderBook") is True] or markets
    active = [m for m in tradable if m.get("active") is True]
    return (active[0] if active else tradable[0])

def extract_outcome_token_pairs(market: dict) -> List[Tuple[str, str]]:
    clob_ids = parse_clob_token_ids(market.get("clobTokenIds"))
    outcomes = market.get("outcomes")

    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            outcomes = None

    if isinstance(outcomes, list) and len(outcomes) >= 2 and len(clob_ids) >= 2:
        return [(str(outcomes[0]), clob_ids[0]), (str(outcomes[1]), clob_ids[1])]

    # fallback (tokens 필드)
    tokens = market.get("tokens")
    if isinstance(tokens, list):
        out = []
        for t in tokens:
            if not isinstance(t, dict): 
                continue
            outcome = str(t.get("outcome") or t.get("title") or t.get("name") or "")
            token_id = str(t.get("token_id") or t.get("tokenId") or t.get("id") or "")
            if outcome and token_id:
                out.append((outcome, token_id))
        if out: 
            return out

    raise RuntimeError("Cannot extract outcome/token_id pairs from market")

def clob_get_price(token_id: str, side: str) -> str:
    # side: "buy" or "sell"  (docs) :contentReference[oaicite:2]{index=2}
    data = http_get_json(f"{CLOB_BASE}/price", params={"token_id": token_id, "side": side})
    return str(data.get("price"))

def run():
    slug, start = build_slug()
    print("slug:", slug, "start_epoch:", start)
    event = gamma_event_by_slug(slug)
    markets = event.get("markets") or []
    if not markets:
        raise RuntimeError("event.markets empty")

    market = select_market(markets)
    pairs = extract_outcome_token_pairs(market)

    print("\n=== Best Bid/Ask via /price ===")
    for outcome, token_id in pairs:
        bid = clob_get_price(token_id, "sell")  # best bid (someone buys from you)
        ask = clob_get_price(token_id, "buy")   # best ask (you buy from someone)
        print(f"[{outcome}] token_id={token_id}")
        print(f"  best_bid={bid}  best_ask={ask}")

if __name__ == "__main__":
    run()

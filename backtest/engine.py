# backtest/engine.py
"""Exact-replay backtest engine — runs the REAL strategy classes over recorded quotes.

This is the ONLY backtest engine: it replays `strategies/<name>.py` through the
same on_event/on_trade pipeline as core/runner.py, so strategy semantics
(exit_armed latch, buy_inflight, on_trade counters, ...) are exercised exactly.
Sweeps (run_grid.py, sweep_threshold.py) fan this replay out over parameter
combos — there is no separate reimplementation of strategy logic to keep in sync.

Cost model (calibrated 2026-03-03 live session):
  - BUY fills at intent price (ask)      — measured slip ~= 0
  - SELL fills at intent bid - haircut   — default 0.01
  - each SELL attempt fails with prob p_fail (default 0.2, seeded RNG);
    the strategy's retry logic must recover (exactly like live rejects)
  - slug end: open position force-closes at last bid (~resolution value)

Usage (from backtest/):
    python engine.py --strategy ma_breakout                       # config defaults
    python engine.py --strategy ma_breakout --set cap=0.4 ma_len=200
    python engine.py --strategy threshold --haircut 0.02 --pfail 0.3
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategies import create_strategy  # noqa: E402


class ReplayAccount:
    """SimAccount-compatible account without file I/O."""

    DUST_CLEAR_TOKENS = 0.01

    def __init__(self):
        self.cash = 0.0
        self.position: Optional[Dict[str, Any]] = None
        self.state: Dict[str, Any] = {"slug_idx": 0, "entries": {"up": 0, "down": 0}, "tp_done": False}

    def reset_state(self, slug_idx: int = 0) -> None:
        self.state = {"slug_idx": int(slug_idx), "entries": {"up": 0, "down": 0}, "tp_done": False}

    def has_position(self) -> bool:
        return bool(self.position)

    def position_qty(self) -> float:
        return float(self.position.get("qty_tokens", 0.0)) if self.position else 0.0

    def apply(self, trade: Dict[str, Any]) -> None:
        if trade.get("status") != "filled":
            return
        kind = trade["kind"]
        side = trade["side"]
        qty = float(trade["qty_tokens"])
        px = float(trade["fill_price"])
        if qty <= 0:
            return

        if kind == "buy":
            self.cash -= qty * px
            self.position = {"side": side, "entry": px, "qty_tokens": qty, "notional_usd": qty * px}
            ent = self.state["entries"]
            ent[side] = ent.get(side, 0) + 1
            return

        if not self.position or self.position.get("side") != side:
            return
        self.cash += qty * px
        remain = float(self.position["qty_tokens"]) - qty
        if remain <= self.DUST_CLEAR_TOKENS:
            self.position = None
        else:
            self.position["qty_tokens"] = remain
        if kind == "exit_tp":
            self.state["tp_done"] = True


class ReplayExecutor:
    """Cost-model executor: buy at intent px, sell at bid-haircut with failure prob."""

    def __init__(self, haircut: float = 0.01, p_fail: float = 0.2, seed: int = 42):
        self.haircut = float(haircut)
        self.p_fail = float(p_fail)
        self.rng = np.random.default_rng(seed)
        self.sell_attempts = 0
        self.sell_fails = 0

    def fill(self, intent: Dict[str, Any], quote_ev: Dict[str, Any], account) -> Dict[str, Any]:
        kind = intent["kind"]
        side = intent["side"]
        px = float(intent["price"])
        qty = float(intent.get("qty_tokens") or 10.0)

        base = {
            "type": "trade", "kind": kind, "slug": intent["slug"], "tick": intent["tick"],
            "side": side, "ts": intent.get("ts", 0), "token_id": "", "data": {}, "debug": {},
        }

        if kind == "buy":
            return {**base, "status": "filled", "reason": "", "qty_tokens": qty, "fill_price": px}

        # SELL
        self.sell_attempts += 1
        if self.rng.random() < self.p_fail:
            self.sell_fails += 1
            return {**base, "status": "rejected", "reason": "sim_sell_fail", "qty_tokens": 0.0, "fill_price": 0.0}

        want = account.position_qty() or qty
        fill_px = max(px - self.haircut, 0.0)
        return {**base, "status": "filled", "reason": "", "qty_tokens": want, "fill_price": fill_px}


def prepare_slugs(quotes: pd.DataFrame) -> List[tuple]:
    """Group + sort the quotes table once, for repeated replay() calls (sweeps).

    Returns [(slug, source, sorted_df), ...]; pass the list as replay()'s
    `quotes` argument to skip the per-call groupby.
    """
    out = []
    for slug, s in quotes.groupby("slug", sort=False):
        # sort on ts (built from time_left_sec) — tick is a per-run counter and
        # interleaves wrongly when two runs recorded the same slug (2026-07-13)
        out.append((slug, s["source"].iloc[0], s.sort_values("ts")))
    return out


def replay(strategy_name: str, cfg: Dict[str, Any], quotes,
           haircut: float = 0.01, p_fail: float = 0.2, seed: int = 42) -> Dict[str, Any]:
    """Replay one strategy config over the quotes. Returns stats dict.

    `quotes` is either the raw DataFrame or the output of prepare_slugs().
    """
    strategy = create_strategy(strategy_name, cfg)
    account = ReplayAccount()
    executor = ReplayExecutor(haircut=haircut, p_fail=p_fail, seed=seed)

    slug_groups = quotes if isinstance(quotes, list) else prepare_slugs(quotes)

    per_slug: Dict[str, float] = {}
    per_source: Dict[str, float] = {}
    n_fills = 0
    slug_idx = 0

    for slug, source, s in slug_groups:
        slug_idx += 1
        account.reset_state(slug_idx)

        ev0 = {"type": "slug_init" if slug_idx == 1 else "slug_change", "slug": slug,
               "slug_start_ts": 0, "time_left_sec": int(s["time_left_sec"].iloc[0]),
               "slug_count": slug_idx, "tick": int(s["tick"].iloc[0])}
        strategy.on_event(ev0, account)

        cash0 = account.cash
        last_up_bid = last_dn_bid = 0.0

        for row in s.itertuples(index=False):
            ev = {
                "type": "quote", "slug": slug, "slug_start_ts": 0,
                "time_left_sec": int(row.time_left_sec), "tick": int(row.tick),
                "ts": float(row.ts),   # historical time (strategies prefer ev ts over wall clock)
                "quote": {
                    "slug": slug,
                    "up": {"outcome": "Up", "token_id": "TU", "bid": str(row.up_bid), "ask": str(row.up_ask)},
                    "down": {"outcome": "Down", "token_id": "TD", "bid": str(row.down_bid), "ask": str(row.down_ask)},
                },
            }
            last_up_bid, last_dn_bid = float(row.up_bid), float(row.down_bid)

            for it in strategy.on_event(ev, account):
                tr = executor.fill(it, ev, account)
                account.apply(tr)
                strategy.on_trade(tr)
                if tr["status"] == "filled":
                    n_fills += 1

        # slug end: force-close at last bid (~resolution), no haircut
        if account.position:
            pos = account.position
            bid = last_up_bid if pos["side"] == "up" else last_dn_bid
            tr = {"type": "trade", "kind": "exit_time", "slug": slug, "tick": -1, "side": pos["side"],
                  "ts": 0, "status": "filled", "reason": "slug_end", "token_id": "",
                  "qty_tokens": pos["qty_tokens"], "fill_price": bid, "data": {}, "debug": {}}
            account.apply(tr)
            strategy.on_trade(tr)
            n_fills += 1

        pnl = account.cash - cash0
        per_slug[slug] = pnl
        per_source[source] = per_source.get(source, 0.0) + pnl

    pnls = list(per_slug.values())
    eq = peak = mdd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)

    return {
        "total_pnl": float(np.sum(pnls)),
        "mdd": float(mdd),
        "score": float(np.sum(pnls)) - 0.5 * abs(float(mdd)),
        "slugs": len(per_slug),
        "wins": int(sum(1 for p in pnls if p > 1e-9)),
        "losses": int(sum(1 for p in pnls if p < -1e-9)),
        "fills": n_fills,
        "sell_fail_rate": (executor.sell_fails / executor.sell_attempts) if executor.sell_attempts else 0.0,
        "per_source": {k: round(v, 2) for k, v in per_source.items()},
        "per_slug": per_slug,
    }


def main():
    ap = argparse.ArgumentParser(description="exact-replay backtest")
    ap.add_argument("--strategy", default="ma_breakout")
    ap.add_argument("--config", default=None, help="config path (default: ../configs/<strategy>.json)")
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VAL",
                    help="strategy param overrides, e.g. cap=0.4 ma_len=200")
    ap.add_argument("--haircut", type=float, default=0.01)
    ap.add_argument("--pfail", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--data", default="data/quotes_all.parquet")
    ap.add_argument("--json", default=None, metavar="PATH",
                    help="result JSON path (default: results/<ts>_engine_<strategy>.json)")
    ap.add_argument("--no-save", action="store_true", help="print only, skip the results/ archive")
    args = ap.parse_args()

    cfg_path = Path(args.config) if args.config else ROOT / "configs" / f"{args.strategy}.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    for kv in args.set:
        k, v = kv.split("=", 1)
        try:
            v = json.loads(v)
        except json.JSONDecodeError:
            pass
        cfg["strategy"][k] = v

    quotes = pd.read_parquet(args.data)
    t0 = time.time()
    r = replay(args.strategy, cfg, quotes, haircut=args.haircut, p_fail=args.pfail, seed=args.seed)
    dt = time.time() - t0

    print(f"strategy={args.strategy} overrides={args.set} haircut={args.haircut} p_fail={args.pfail}")
    print(f"replayed {r['slugs']} slugs, {r['fills']} fills in {dt:.1f}s "
          f"(sell_fail_rate={r['sell_fail_rate']:.2f})")
    print(f"TOTAL PnL: {r['total_pnl']:+.2f} USD | MDD {r['mdd']:.2f} | score {r['score']:.2f} "
          f"| slug W/L {r['wins']}/{r['losses']}")
    print(f"per source: {r['per_source']}")

    json_path = args.json
    if json_path is None and not args.no_save:
        ts = time.strftime("%Y%m%d_%H%M%S")
        json_path = str(Path(__file__).parent / "results" / f"{ts}_engine_{args.strategy}.json")
    if json_path:
        out = {
            "kind": "engine", "strategy": args.strategy, "overrides": args.set,
            "cost_model": {"haircut": args.haircut, "p_fail": args.pfail, "seed": args.seed},
            "data": args.data, "elapsed_sec": round(dt, 2), **r,
        }
        Path(json_path).parent.mkdir(parents=True, exist_ok=True)
        Path(json_path).write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"json: {json_path}")


if __name__ == "__main__":
    main()

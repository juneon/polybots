# core/runner.py
"""Orchestrator: wires config -> adapter -> slug_loop -> strategy -> executor -> account -> logger/printer.

Usage (from the polybots root):
    python -m core.runner --strategy ma_breakout --mode sim
    python -m core.runner --strategy threshold   --mode sim
    python -m core.runner --strategy ma_breakout --mode live      # REAL ORDERS

- mode defaults to "sim"; live trading requires an explicit --mode live.
- config defaults to configs/<strategy>.json (override with --config).
- every run gets a run_id (logged in every CSV row).
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from .adapters_polymarket import PolymarketAdapter
from .slug_loop import slug_loop
from .executor_sim import SimExecutor
from .account_sim import SimAccount
from .logger import Logger
from .printer import Printer
from strategies import REGISTRY, create_strategy

log = logging.getLogger("core.runner")

ROOT = Path(__file__).resolve().parents[1]


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_account_executor(mode: str, cfg: dict, pm: PolymarketAdapter):
    if mode == "live":
        # imported lazily: live deps (py_clob_client, .env keys) are not needed for sim
        from .account_live import LiveAccount
        from .executor_live import LiveExecutor
        return LiveAccount(cfg), LiveExecutor(cfg, pm)
    return SimAccount(str(ROOT / "sim_account.json")), SimExecutor(guard=True)


def run(cfg: dict, mode: str, strategy_name: str, run_id: str) -> None:
    pm = PolymarketAdapter(cfg)
    account, executor = build_account_executor(mode, cfg, pm)
    strategy = create_strategy(strategy_name, cfg)
    logger = Logger(cfg, run_id=run_id, logs_dir=str(ROOT / "logs"))
    printer = Printer(cfg)

    cur_slug = None
    slug_idx = 0

    try:
        for ev in slug_loop(pm, cfg):
            et = ev.get("type")
            logger.handle(ev)

            if et in ("slug_init", "slug_change"):
                slug = ev.get("slug")
                if slug and slug != cur_slug:
                    cur_slug = slug
                    slug_idx += 1
                    account.reset_state(slug_idx=slug_idx)
                    strategy.on_event(ev, account)

                    # live: reconcile position from CLOB balances at each slug boundary
                    if mode == "live":
                        try:
                            executor.reconcile_on_slug(slug, account)
                        except Exception as e:
                            log.warning("reconcile_on_slug failed for %s: %r", slug, e)

            elif et == "quote":
                intents = strategy.on_event(ev, account)
                filled = False

                for it in intents:
                    logger.handle(it)

                    tr = executor.fill(it, ev, account)

                    account.apply(tr)        # SOT update (filled only)
                    strategy.on_trade(tr)    # fill feedback (counters/locks/cooldowns)
                    logger.handle(tr)

                    if tr.get("status") == "filled":
                        filled = True

                if filled:
                    logger.snapshot(account, ev)

                printer.on_quote(ev, account, strategy)

            elif et == "warn":
                log.warning("quote failed (slug=%s tick=%s): %s", ev.get("slug"), ev.get("tick"), ev.get("error"))

            elif et == "exit":
                log.info("loop exit: %s", ev.get("reason"))
                break
    except KeyboardInterrupt:
        log.info("interrupted by user — closing logs")
    finally:
        logger.close()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="polybots runner")
    ap.add_argument("--strategy", default="ma_breakout", choices=sorted(REGISTRY),
                    help="strategy name (default: ma_breakout)")
    ap.add_argument("--mode", default="sim", choices=["sim", "live"],
                    help="sim (default) or live — live places REAL orders")
    ap.add_argument("--config", default=None,
                    help="config path (default: configs/<strategy>.json)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg_path = Path(args.config) if args.config else ROOT / "configs" / f"{args.strategy}.json"
    cfg = load_config(cfg_path)

    run_id = time.strftime("%Y%m%d_%H%M%S") + f"_{args.strategy}_{args.mode}"

    if args.mode == "live":
        print("=" * 70)
        print("  LIVE MODE — REAL ORDERS WILL BE PLACED ON POLYMARKET")
        print(f"  strategy={args.strategy}  config={cfg_path.name}  run_id={run_id}")
        print("=" * 70)
    else:
        print(f"[sim] strategy={args.strategy} config={cfg_path.name} run_id={run_id}")

    run(cfg, args.mode, args.strategy, run_id)


if __name__ == "__main__":
    main()

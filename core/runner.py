# core/runner.py
"""Orchestrator: wires config -> adapter -> slug_loop -> strategy -> executor -> account -> logger/printer.

Usage (from the polybots root):
    python -m core.runner --strategy ma        --mode sim
    python -m core.runner --strategy threshold --mode sim
    python -m core.runner --strategy ma        --mode live        # REAL ORDERS

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
from .control import RunControl, snapshot_status
from .config_schema import validate_config
from strategies import REGISTRY, create_strategy

log = logging.getLogger("core.runner")

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"   # runtime state files (sim accounts), gitignored


# strategies renamed over time: current name -> old state/log name
LEGACY_STRATEGY_NAMES = {"ma": "ma_breakout"}


def _sim_account_path(strategy_name: str) -> Path:
    """state/sim_account_<strategy>.json — migrates old locations/names once."""
    STATE_DIR.mkdir(exist_ok=True)
    path = STATE_DIR / f"sim_account_{strategy_name}.json"
    old_name = LEGACY_STRATEGY_NAMES.get(strategy_name)
    legacies = [ROOT / f"sim_account_{strategy_name}.json"]
    if old_name:
        legacies += [STATE_DIR / f"sim_account_{old_name}.json", ROOT / f"sim_account_{old_name}.json"]
    for legacy in legacies:
        if path.exists():
            break
        if legacy.exists():
            legacy.replace(path)
            log.info("migrated %s -> %s", legacy.name, path)
    return path


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_account_executor(mode: str, cfg: dict, pm: PolymarketAdapter, strategy_name: str):
    if mode == "live":
        # imported lazily: live deps (py_clob_client, .env keys) are not needed for sim
        from .account_live import LiveAccount
        from .executor_live import LiveExecutor
        return LiveAccount(cfg), LiveExecutor(cfg, pm)
    # per-strategy account file: concurrent sims must not share cash/position
    return SimAccount(str(_sim_account_path(strategy_name))), SimExecutor(guard=True)


def settle_open_position(account, last_quote_ev: dict, logger, reason: str) -> None:
    """Sim book-close: force-exit the open position at the last seen bid.

    The account persists across slugs/runs but a slug's tokens don't — without
    this, a carried position got "sold" at the next slug's (different token)
    price (P2 bug, 3 cases measured 2026-07-14). Near expiry the last bid ~=
    settlement, mirroring the backtest engine's force-close.
    """
    pos = account.position or {}
    side = str(pos.get("side", ""))
    qty = account.position_qty()
    book = (last_quote_ev.get("quote") or {}).get(side) or {}
    bid = _f(book.get("bid"))
    common = {
        "kind": "exit_expiry",
        "slug": str(last_quote_ev.get("slug", "")),
        "tick": int(last_quote_ev.get("tick") or 0),
        "side": side,
        "ts": int(time.time()),
        "reason": reason,
    }
    intent = {**common, "type": "intent", "qty_tokens": qty, "price": bid,
              "time_left_sec": last_quote_ev.get("time_left_sec", "")}
    trade = {**common, "type": "trade", "status": "filled",
             "token_id": str(book.get("token_id") or ""),
             "qty_tokens": qty, "fill_price": bid, "data": {}, "debug": {}}
    logger.handle(intent)
    logger.handle(trade)
    account.apply(trade)
    logger.snapshot(account, last_quote_ev)
    log.info("settled open position at last bid: %s %.2ftk @ %.3f (%s, slug=%s)",
             side, qty, bid, reason, common["slug"])


def _f(x, default: float = 0.0) -> float:
    try:
        return default if x is None else float(x)
    except (TypeError, ValueError):
        return default


def run(cfg: dict, mode: str, strategy_name: str, run_id: str) -> None:
    pm = PolymarketAdapter(cfg)
    account, executor = build_account_executor(mode, cfg, pm, strategy_name)
    strategy = create_strategy(strategy_name, cfg)
    logger = Logger(cfg, run_id=run_id, logs_dir=str(ROOT / "logs"))
    printer = Printer(cfg)
    ctl = RunControl(run_id, ctl_dir=str(ROOT / "logs" / "ctl"))

    cur_slug = None
    slug_idx = 0
    stop_reason = "loop_exit"
    last_quote = None  # last quote event, prices the sim settlement at slug/run end

    try:
        for ev in slug_loop(pm, cfg):
            et = ev.get("type")
            logger.handle(ev)

            if ctl.stop_requested():
                stop_reason = "stop_requested"
                log.info("stop file detected — shutting down gracefully")
                break

            if et in ("slug_init", "slug_change"):
                slug = ev.get("slug")
                if slug and slug != cur_slug:
                    if mode == "sim" and account.has_position():
                        # legacy positions (pre-2026-07-14 state files) carry no slug
                        pos_slug = (account.position or {}).get("slug") or cur_slug
                        if last_quote is not None and last_quote.get("slug") == pos_slug:
                            settle_open_position(account, last_quote, logger, "slug_end")
                        elif pos_slug != slug:
                            # carried from a dead slug and no quote to price it:
                            # write off instead of selling at another slug's price
                            log.warning("dropping stale carried position (pos slug=%s, now=%s): %s",
                                        pos_slug, slug, account.drop_position())
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

                ctl.heartbeat(snapshot_status(
                    "running", strategy=strategy_name, mode=mode,
                    ev=ev, account=account, slug_count=slug_idx,
                ))

            elif et == "quote":
                last_quote = ev
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
                ctl.heartbeat(snapshot_status(
                    "running", strategy=strategy_name, mode=mode,
                    ev=ev, account=account, slug_count=slug_idx,
                ))

            elif et == "warn":
                log.warning("quote failed (slug=%s tick=%s): %s", ev.get("slug"), ev.get("tick"), ev.get("error"))

            elif et == "exit":
                log.info("loop exit: %s", ev.get("reason"))
                break
    except KeyboardInterrupt:
        stop_reason = "keyboard_interrupt"
        log.info("interrupted by user — closing logs")
    finally:
        # run-end book close (crash without finally = next start's stale-drop path)
        if mode == "sim" and account.has_position() and last_quote is not None:
            pos_slug = (account.position or {}).get("slug") or cur_slug
            if last_quote.get("slug") == pos_slug:
                try:
                    settle_open_position(account, last_quote, logger, "run_end")
                except Exception as e:
                    log.warning("run-end settlement failed: %r", e)
        ctl.heartbeat(snapshot_status(
            "stopped", strategy=strategy_name, mode=mode,
            account=account, slug_count=slug_idx, stop_reason=stop_reason,
        ))
        logger.close()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="polybots runner")
    ap.add_argument("--strategy", default="ma", choices=sorted(REGISTRY),
                    help="strategy name (default: ma)")
    ap.add_argument("--mode", default="sim", choices=["sim", "live"],
                    help="sim (default) or live — live places REAL orders")
    ap.add_argument("--config", default=None,
                    help="config path (default: configs/<strategy>.json)")
    ap.add_argument("--run-id", default=None,
                    help="run id override (used by the UI server so it can address ctl files)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg_path = Path(args.config) if args.config else ROOT / "configs" / f"{args.strategy}.json"
    cfg = load_config(cfg_path)

    # fail fast on a bad (e.g. hand-edited) config instead of booting a bot with it
    errors = validate_config(cfg)
    if errors:
        for e in errors:
            log.error("config invalid: %s", e)
        raise SystemExit(f"config validation failed ({cfg_path}): {len(errors)} error(s)")

    run_id = args.run_id or (time.strftime("%Y%m%d_%H%M%S") + f"_{args.strategy}_{args.mode}")

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

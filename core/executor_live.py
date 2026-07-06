# core/executor_live.py
"""Live executor for the Polymarket CLOB (py_clob_client).

- BUY: single GTC shot.
- SELL: IOC sweep — polls CLOB balance every sell_sweep_poll_sec for up to
  sell_sweep_window_sec, selling whatever balance has settled each pass.
  This works around CLOB balance-reporting lag after a buy.
"""
from __future__ import annotations

import logging
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .adapters_polymarket import PolymarketAdapter

log = logging.getLogger(__name__)


def _now() -> int:
    return int(time.time())


def _f(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except Exception:
        return None


def _must_pm_env(name: str) -> str:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        raise RuntimeError(f"Missing env: {name}")
    return str(v).strip()


def _norm_privkey(pk: str) -> str:
    pk = pk.strip().strip('"').strip("'")
    return pk if pk.startswith("0x") else "0x" + pk


def load_dotenv_root_fixed() -> str:
    """Load only the repo-root .env (core/.. == polybots root)."""
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        log.warning("python-dotenv not installed; relying on process env vars")
        return ""

    root_env = Path(__file__).resolve().parents[1] / ".env"
    if root_env.exists():
        load_dotenv(dotenv_path=str(root_env), override=False)
        return str(root_env)
    return ""


def build_clob_client(cfg: Dict[str, Any]):
    _ = load_dotenv_root_fixed()

    host = str(cfg.get("clob_base", "https://clob.polymarket.com")).rstrip("/")

    private_key = _norm_privkey(_must_pm_env("PM_PRIVATE_KEY"))
    funder = _must_pm_env("PM_USER")

    acfg = cfg.get("account", {}) or {}
    chain_id = int(acfg.get("chain_id", 137))
    signature_type = int(acfg.get("signature_type", 2))

    from py_clob_client.client import ClobClient  # type: ignore

    try:
        c = ClobClient(host=host, key=private_key, chain_id=chain_id, signature_type=signature_type, funder=funder)
    except TypeError:
        c = ClobClient(host=host, private_key=private_key, chain_id=chain_id, signature_type=signature_type, funder=funder)

    try:
        creds = c.create_or_derive_api_creds()
        c.set_api_creds(creds)
    except Exception as e:
        # a mis-signed client would fail on every order later — surface it loudly
        log.error("API credential derivation FAILED — live orders will likely be rejected: %r", e)

    return c


class LiveExecutor:
    COND_DECIMALS = 6
    EPS = 1e-6
    SELL_STEP_TOKENS = 0.01

    def __init__(self, cfg: Dict[str, Any], pm: Optional[PolymarketAdapter] = None):
        self.cfg = cfg
        self.pm = pm
        self.ecfg = cfg.get("execution", {}) or {}
        self.acfg = cfg.get("account", {}) or {}

        self.slippage = float(self.ecfg.get("slippage", 0.05))
        self.buy_cap = float(self.ecfg.get("buy_cap", 0.99))
        self.sell_floor = float(self.ecfg.get("sell_floor", 0.01))

        self.sell_sweep_window_sec = float(self.ecfg.get("sell_sweep_window_sec", 10))
        self.sell_sweep_poll_sec = float(self.ecfg.get("sell_sweep_poll_sec", 0.5))

        self._client = build_clob_client(cfg)

    def _mode_for_kind(self, kind: str) -> str:
        if kind == "buy":
            return str(self.ecfg.get("buy", "market"))
        if kind == "exit_tp":
            return str(self.ecfg.get("tp", "limit"))
        if kind == "exit_sl":
            return str(self.ecfg.get("sl", "market"))
        if kind == "exit_time":
            return str(self.ecfg.get("time", "market"))
        return "limit"

    def _exec_price(self, kind: str, intent_px: float, book: Dict[str, Any]) -> Optional[float]:
        mode = self._mode_for_kind(kind).lower().strip()
        if mode == "limit":
            return intent_px if intent_px > 0 else None

        is_buy = (kind == "buy")
        if is_buy:
            ask = _f(book.get("ask"))
            if not ask or ask <= 0:
                return None
            px = min(ask + self.slippage, self.buy_cap)
            return px if px > 0 else None

        bid = _f(book.get("bid"))
        if not bid or bid <= 0:
            return None
        px = max(bid - self.slippage, self.sell_floor)
        return px if px > 0 else None

    def _atomic_to_tokens(self, atomic: float) -> float:
        return float(atomic) / (10 ** self.COND_DECIMALS)

    def _parse_allowance(self, raw: Dict[str, Any]) -> float:
        if "allowance" in raw:
            try:
                return float(raw.get("allowance") or 0)
            except Exception:
                return 0.0
        al = raw.get("allowances")
        if isinstance(al, dict) and al:
            best = 0.0
            for v in al.values():
                try:
                    best = max(best, float(v))
                except Exception:
                    pass
            return best
        return 0.0

    def _get_balance_allowance(self, token_id: str) -> Tuple[float, float]:
        from py_clob_client.clob_types import BalanceAllowanceParams  # type: ignore

        r = self._client.get_balance_allowance(BalanceAllowanceParams(asset_type="CONDITIONAL", token_id=str(token_id)))
        raw = dict(r)
        try:
            bal_atomic = float(raw.get("balance", 0.0) or 0.0)
        except Exception:
            bal_atomic = 0.0
        return self._atomic_to_tokens(bal_atomic), self._parse_allowance(raw)

    def reconcile_on_slug(self, slug: str, account) -> None:
        if self.pm is None:
            return
        try:
            quote = self.pm.quote_updown(slug)
        except Exception as e:
            log.warning("reconcile: quote fetch failed for %s: %r", slug, e)
            return

        up = quote.get("up") or {}
        dn = quote.get("down") or {}
        up_tid = str(up.get("token_id") or "")
        dn_tid = str(dn.get("token_id") or "")
        if not up_tid or not dn_tid:
            return

        try:
            up_bal, _ = self._get_balance_allowance(up_tid)
            dn_bal, _ = self._get_balance_allowance(dn_tid)
        except Exception as e:
            log.warning("reconcile: balance fetch failed for %s: %r", slug, e)
            return

        if hasattr(account, "reconcile_from_clob"):
            try:
                account.reconcile_from_clob(quote, up_bal, dn_bal)
            except Exception as e:
                log.warning("reconcile: account update failed for %s: %r", slug, e)

    def _extract_fill(self, is_buy: bool, resp: Dict[str, Any]) -> Tuple[float, float, float]:
        """Returns (avg_price, token_filled, usdc_filled).

        buy:  token=takingAmount, usdc=makingAmount
        sell: token=makingAmount, usdc=takingAmount
        """
        taking = float(resp.get("takingAmount") or 0.0)
        making = float(resp.get("makingAmount") or 0.0)
        token = taking if is_buy else making
        usdc = making if is_buy else taking
        return (usdc / token, token, usdc) if token > 0 else (0.0, token, usdc)

    @staticmethod
    def _floor_to_step(x: float, step: float) -> float:
        if step <= 0:
            return float(x)
        k = math.floor((float(x) + 1e-12) / float(step))
        return float(k) * float(step)

    def _choose_ioc_enum(self):
        """py_clob_client OrderType differs across versions: prefer IOC, then FAK/FOK, else GTC."""
        from py_clob_client.clob_types import OrderType  # type: ignore

        for name in ("IOC", "FAK", "FOK", "GTC"):
            if hasattr(OrderType, name):
                return getattr(OrderType, name)
        return OrderType.GTC

    def _post_order(self, is_buy: bool, token_id: str, px: float, size_tokens: float) -> Dict[str, Any]:
        from py_clob_client.clob_types import OrderArgs  # type: ignore
        from py_clob_client.order_builder.constants import BUY, SELL  # type: ignore

        order_args = OrderArgs(
            token_id=str(token_id),
            price=float(px),
            size=float(size_tokens),
            side=(BUY if is_buy else SELL),
        )
        signed = self._client.create_order(order_args)

        # BUY stays GTC; SELL goes IOC (or closest available).
        if is_buy:
            from py_clob_client.clob_types import OrderType  # type: ignore
            return self._client.post_order(signed, OrderType.GTC, post_only=bool(self.acfg.get("post_only", False)))

        ioc_type = self._choose_ioc_enum()
        return self._client.post_order(signed, ioc_type, post_only=False)

    def _sell_sweep_ioc(
        self,
        kind: str,
        slug: str,
        tick: int,
        side: str,
        token_id: str,
        px: float,
        want_tokens: float,
        account,
    ) -> Dict[str, Any]:
        """SELL sweep: repeat for up to sell_sweep_window_sec —
        read balance -> floor size to step -> IOC sell; stop when balance < step (dust).
        Multiple orders are aggregated into a single trade dict.
        """
        t0 = time.time()
        step = float(self.SELL_STEP_TOKENS)

        attempts: List[Dict[str, Any]] = []
        total_tokens = 0.0
        total_usdc = 0.0
        last_err = ""
        last_status = "rejected"

        # allowance is checked once up-front (0 -> abort immediately)
        bal0, alw0 = self._get_balance_allowance(token_id)
        if alw0 <= 0:
            debug = {
                "allowance": alw0,
                "balance_tokens": bal0,
                "want_tokens": want_tokens,
                "step_tokens": step,
                "sweep_window_sec": self.sell_sweep_window_sec,
                "sweep_poll_sec": self.sell_sweep_poll_sec,
            }
            return self._trade(kind, slug, tick, side, "rejected", "sell_not_ready:allowance_zero", token_id, 0.0, 0.0, {}, debug)

        while True:
            elapsed = time.time() - t0
            if elapsed >= self.sell_sweep_window_sec:
                last_err = last_err or "sell_sweep_timeout"
                break

            bal_t, _alw = self._get_balance_allowance(token_id)

            if hasattr(account, "sync_position"):
                try:
                    account.sync_position(token_id, bal_t)
                except Exception as e:
                    log.warning("sell sweep: sync_position failed: %r", e)

            size = min(float(want_tokens), max(0.0, float(bal_t)))
            size = self._floor_to_step(size, step)
            if size + self.EPS < step:
                # dust / zero -> done
                if total_tokens > 0:
                    last_status = "filled"
                else:
                    last_err = last_err or "sell_dust:below_step"
                break

            try:
                resp = self._post_order(is_buy=False, token_id=token_id, px=px, size_tokens=size)
                if resp.get("success") is False:
                    s = "rejected"
                    err = str(resp.get("errorMsg") or "post_order_failed")
                    fp, tok, usd = (0.0, 0.0, 0.0)
                else:
                    sraw = resp.get("status") or resp.get("orderStatus") or ""
                    s = "filled" if str(sraw).lower() in ("matched", "filled") else "submitted"
                    fp, tok, usd = self._extract_fill(is_buy=False, resp=resp)
                    if tok > 0:
                        total_tokens += float(tok)
                        total_usdc += float(usd)
                        last_status = "filled"
                    elif last_status != "filled":
                        # IOC with zero fill behaves like a cancel
                        last_status = "rejected"

                    err = str(resp.get("errorMsg") or "")
                attempts.append({
                    "attempt_ts": _now(),
                    "balance_tokens": bal_t,
                    "try_size": size,
                    "status": s,
                    "error": err,
                    "fill_price": fp,
                    "filled_tokens": tok,
                    "proceeds_usd": usd,
                    "order_id": resp.get("orderID") or resp.get("orderId") or resp.get("order_id") or "",
                })
                last_err = err or last_err
            except Exception as e:
                last_err = str(e)
                log.warning("sell sweep: order failed: %r", e)
                attempts.append({
                    "attempt_ts": _now(),
                    "balance_tokens": bal_t,
                    "try_size": size,
                    "status": "rejected",
                    "error": last_err,
                    "fill_price": 0.0,
                    "filled_tokens": 0.0,
                    "proceeds_usd": 0.0,
                    "order_id": "",
                })

            # wait for the next balance settlement
            time.sleep(max(0.05, float(self.sell_sweep_poll_sec)))

        avg_px = (total_usdc / total_tokens) if total_tokens > 0 else 0.0

        debug = {
            "want_tokens": want_tokens,
            "step_tokens": step,
            "sweep_window_sec": self.sell_sweep_window_sec,
            "sweep_poll_sec": self.sell_sweep_poll_sec,
            "attempts": attempts,
        }

        trade = self._trade(
            kind=kind,
            slug=slug,
            tick=tick,
            side=side,
            status=("filled" if total_tokens > 0 else "rejected"),
            reason=(last_err or ""),
            token_id=token_id,
            qty_tokens=float(total_tokens),
            fill_price=float(avg_px),
            data={"attempts": attempts, "total_proceeds_usd": total_usdc, "total_tokens": total_tokens},
            debug=debug,
        )

        if total_tokens > 0:
            trade["proceeds_usd"] = float(total_usdc)

        return trade

    def fill(self, intent: Dict[str, Any], quote_ev: Dict[str, Any], account) -> Dict[str, Any]:
        kind = str(intent.get("kind", ""))
        side = str(intent.get("side", ""))
        slug = str(quote_ev.get("slug") or intent.get("slug") or "")
        tick = int(quote_ev.get("tick") or intent.get("tick") or 0)

        q = quote_ev.get("quote") or {}
        book = (q.get(side) or {})
        token_id = str(book.get("token_id") or "")
        if not token_id:
            return self._trade(kind, slug, tick, side, "rejected", "bad_token_id", token_id, 0.0, 0.0, {}, {})

        px = self._exec_price(kind, float(intent.get("price") or 0.0), book)
        if px is None or px <= 0:
            return self._trade(kind, slug, tick, side, "rejected", "bad_exec_price", token_id, 0.0, 0.0, {}, {})

        is_buy = (kind == "buy")
        if is_buy:
            size_tokens = float(intent.get("qty_tokens") or getattr(account, "live_size_shares", 0.0) or 0.0)
        else:
            size_tokens = float(intent.get("qty_tokens") or (account.position_qty() if hasattr(account, "position_qty") else 0.0))

        if size_tokens <= 0:
            return self._trade(kind, slug, tick, side, "rejected", "bad_size_tokens", token_id, 0.0, 0.0, {}, {})

        # --- SELL: IOC sweep ---
        if not is_buy:
            return self._sell_sweep_ioc(
                kind=kind,
                slug=slug,
                tick=tick,
                side=side,
                token_id=token_id,
                px=float(px),
                want_tokens=float(size_tokens),
                account=account,
            )

        # --- BUY: single GTC shot ---
        try:
            resp = self._post_order(is_buy=True, token_id=token_id, px=float(px), size_tokens=float(size_tokens))
        except Exception as e:
            log.warning("buy order failed: %r", e)
            return self._trade(kind, slug, tick, side, "rejected", str(e), token_id, 0.0, 0.0, {}, {})

        if resp.get("success") is False:
            status = "rejected"
        else:
            sraw = resp.get("status") or resp.get("orderStatus") or ""
            status = "filled" if str(sraw).lower() in ("matched", "filled") else "submitted"

        fill_price, token_filled, usdc_filled = self._extract_fill(is_buy=True, resp=resp)

        trade = self._trade(
            kind=kind,
            slug=slug,
            tick=tick,
            side=side,
            status=status,
            reason=(resp.get("errorMsg") or ""),
            token_id=token_id,
            qty_tokens=float(token_filled),
            fill_price=float(fill_price),
            data=resp,
            debug={},
        )

        oid = resp.get("orderID") or resp.get("orderId") or resp.get("order_id") or ""
        if oid:
            trade["order_id"] = str(oid)

        if status == "filled":
            trade["notional_usd"] = float(usdc_filled)

        return trade

    def _trade(
        self,
        kind: str,
        slug: str,
        tick: int,
        side: str,
        status: str,
        reason: str,
        token_id: str,
        qty_tokens: float,
        fill_price: float,
        data: Dict[str, Any],
        debug: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "type": "trade",
            "kind": kind,
            "slug": slug,
            "tick": int(tick),
            "side": side,
            "ts": _now(),
            "status": status,
            "reason": reason,
            "token_id": token_id,
            "qty_tokens": float(qty_tokens),
            "fill_price": float(fill_price),
            "data": data or {},
            "debug": debug or {},
        }

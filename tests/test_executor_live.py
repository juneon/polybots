# tests/test_executor_live.py
"""LiveExecutor routing/pricing rules (no CLOB client, no network):
every SELL kind goes through the IOC sweep; exit_tp is priced at the intent
price (trigger-time bid, limit mode) while exit_sl/exit_time take bid-slippage;
the sweep aggregates partial fills across balance-lag passes and reports
sell_dust:below_step when the settled balance never reaches one step.

The sweep runs on a worker thread (P2, 2026-07-18): fill() returns "submitted"
immediately, the final aggregated trade arrives via drain_completed(), and a
second SELL for the same token while one is in flight is rejected
("sell_inflight")."""
import time

import pytest

from core.executor_live import LiveExecutor


class FakeAccount:
    def __init__(self, qty=10.0):
        self._qty = qty
        self.synced = []

    def position_qty(self):
        return self._qty

    def sync_position(self, token_id, bal):
        self.synced.append((token_id, bal))


def make_exec():
    """Build a LiveExecutor without __init__ (skips .env / py_clob_client)."""
    ex = LiveExecutor.__new__(LiveExecutor)
    ex.cfg = {}
    ex.pm = None
    ex.ecfg = {"buy": "market", "tp": "limit", "sl": "market", "time": "market"}
    ex.acfg = {}
    ex.slippage = 0.05
    ex.buy_cap = 0.99
    ex.sell_floor = 0.01
    ex.sell_sweep_window_sec = 2.0
    ex.sell_sweep_poll_sec = 0.01
    ex._client = None
    ex._init_sweep_state()
    return ex


def wire(ex, balances, fill=True):
    """Stub the two client touchpoints: balance polling and order posting.

    balances: consumed one per _get_balance_allowance call; the last value
    repeats once exhausted. Returns the list of posted (px, size) sells.
    """
    seq = list(balances)
    posted = []

    def get_bal(token_id):
        bal = seq.pop(0) if len(seq) > 1 else seq[0]
        return float(bal), 1e9

    def post_order(is_buy, token_id, px, size_tokens):
        assert not is_buy
        posted.append((px, size_tokens))
        if not fill:
            return {"status": "unmatched", "takingAmount": "0", "makingAmount": "0"}
        return {"status": "matched",
                "takingAmount": str(px * size_tokens),   # usdc
                "makingAmount": str(size_tokens)}        # tokens

    ex._get_balance_allowance = get_bal
    ex._post_order = post_order
    return posted


def intent(kind, price, qty=10.0):
    return {"kind": kind, "side": "up", "price": price, "qty_tokens": qty}


def quote_ev(bid=0.98, ask=0.99):
    return {"slug": "s1", "tick": 5,
            "quote": {"up": {"token_id": "tok-up", "bid": bid, "ask": ask}}}


def sell(ex, it, ev, account, timeout=5.0):
    """fill() a SELL and wait for the worker's final trade via drain_completed."""
    tr = ex.fill(it, ev, account)
    assert tr["status"] == "submitted"
    assert tr["reason"] == "sell_sweep_started"
    t0 = time.time()
    while time.time() - t0 < timeout:
        done = ex.drain_completed()
        if done:
            assert len(done) == 1
            return done[0]
        time.sleep(0.005)
    raise AssertionError("sweep did not deliver a final trade in time")


def test_exit_tp_goes_through_sweep_at_intent_price():
    ex = make_exec()
    posted = wire(ex, balances=[10.0, 10.0, 0.0])
    tr = sell(ex, intent("exit_tp", price=0.98), quote_ev(bid=0.98), FakeAccount())

    assert tr["status"] == "filled"
    assert tr["kind"] == "exit_tp"
    assert tr["qty_tokens"] == pytest.approx(10.0)
    assert tr["fill_price"] == pytest.approx(0.98)
    assert tr["proceeds_usd"] == pytest.approx(9.8)
    # limit mode: posted at the intent price (trigger-time bid), no slippage
    assert posted == [(0.98, 10.0)]
    # sweep path evidence: attempt trail is recorded
    assert len(tr["debug"]["attempts"]) == 1


def test_exit_sl_priced_at_bid_minus_slippage():
    ex = make_exec()
    posted = wire(ex, balances=[10.0, 10.0, 0.0])
    tr = sell(ex, intent("exit_sl", price=0.75), quote_ev(bid=0.75), FakeAccount())

    assert tr["status"] == "filled"
    assert posted[0][0] == pytest.approx(0.70)   # 0.75 - slippage 0.05


def test_sweep_aggregates_partial_fills_across_balance_lag():
    ex = make_exec()
    # settles 4 tokens first, then the remaining 6 on the next pass
    posted = wire(ex, balances=[4.0, 4.0, 6.0, 0.0])
    tr = sell(ex, intent("exit_tp", price=0.98), quote_ev(bid=0.98), FakeAccount())

    assert tr["status"] == "filled"
    assert [s for _, s in posted] == [pytest.approx(4.0), pytest.approx(6.0)]
    assert tr["qty_tokens"] == pytest.approx(10.0)
    assert tr["fill_price"] == pytest.approx(0.98)
    assert len(tr["debug"]["attempts"]) == 2


def test_sweep_below_step_reports_sell_dust():
    ex = make_exec()
    posted = wire(ex, balances=[0.005, 0.005])
    tr = sell(ex, intent("exit_tp", price=0.98), quote_ev(bid=0.98), FakeAccount())

    assert tr["status"] == "rejected"
    assert tr["reason"] == "sell_dust:below_step"
    assert posted == []


def test_sweep_no_match_times_out_rejected():
    ex = make_exec()
    ex.sell_sweep_window_sec = 0.05   # keep the timeout path fast
    wire(ex, balances=[10.0, 10.0], fill=False)
    tr = sell(ex, intent("exit_tp", price=0.98), quote_ev(bid=0.98), FakeAccount())

    assert tr["status"] == "rejected"
    assert tr["reason"] == "sell_sweep_timeout"


def test_allowance_zero_aborts_before_posting():
    ex = make_exec()
    posted = wire(ex, balances=[10.0, 10.0, 0.0])
    ex._get_balance_allowance = lambda token_id: (10.0, 0.0)
    tr = sell(ex, intent("exit_tp", price=0.98), quote_ev(bid=0.98), FakeAccount())

    assert tr["status"] == "rejected"
    assert tr["reason"] == "sell_not_ready:allowance_zero"
    assert posted == []


def test_fill_returns_before_sweep_window_elapses():
    ex = make_exec()
    ex.sell_sweep_window_sec = 1.0
    ex.sell_sweep_poll_sec = 0.05
    wire(ex, balances=[10.0, 10.0], fill=False)   # no-match: sweep burns the window

    t0 = time.time()
    tr = ex.fill(intent("exit_tp", price=0.98), quote_ev(bid=0.98), FakeAccount())
    elapsed = time.time() - t0

    assert tr["status"] == "submitted"
    assert elapsed < 0.5, f"fill blocked for {elapsed:.2f}s"   # main loop must not stall
    ex.shutdown()
    done = ex.drain_completed()
    assert len(done) == 1 and done[0]["reason"] == "sell_sweep_timeout"


def test_second_sell_while_inflight_is_rejected():
    ex = make_exec()
    ex.sell_sweep_window_sec = 1.0
    ex.sell_sweep_poll_sec = 0.05
    wire(ex, balances=[10.0, 10.0], fill=False)

    first = ex.fill(intent("exit_sl", price=0.75), quote_ev(bid=0.75), FakeAccount())
    assert first["status"] == "submitted"

    second = ex.fill(intent("exit_sl", price=0.75), quote_ev(bid=0.75), FakeAccount())
    assert second["status"] == "rejected"
    assert second["reason"] == "sell_inflight"

    ex.shutdown()
    assert len(ex.drain_completed()) == 1   # only one sweep actually ran


def test_shutdown_joins_and_final_trade_is_drainable():
    ex = make_exec()
    wire(ex, balances=[10.0, 10.0, 0.0])
    tr = ex.fill(intent("exit_time", price=0.9), quote_ev(bid=0.9), FakeAccount())
    assert tr["status"] == "submitted"

    ex.shutdown()
    done = ex.drain_completed()
    assert len(done) == 1
    assert done[0]["status"] == "filled"
    assert done[0]["qty_tokens"] == pytest.approx(10.0)


def test_runner_routes_drained_trades_through_sink():
    from core.runner import route_completed_trades

    class FakeExec:
        def __init__(self, trades):
            self._t = list(trades)

        def drain_completed(self):
            t, self._t = self._t, []
            return t

    class FakeAcct:
        def __init__(self):
            self.applied = []

        def apply(self, tr):
            self.applied.append(tr)

    class FakeStrat:
        def __init__(self):
            self.seen = []

        def on_trade(self, tr):
            self.seen.append(tr)

    class FakeLogger:
        def __init__(self):
            self.rows = []
            self.snaps = 0

        def handle(self, ev):
            self.rows.append(ev)

        def snapshot(self, account, ev):
            self.snaps += 1

    tr = {"type": "trade", "status": "filled", "kind": "exit_tp"}
    ex, ac, st, lg = FakeExec([tr]), FakeAcct(), FakeStrat(), FakeLogger()
    assert route_completed_trades(ex, ac, st, lg, ev={"type": "quote"}) is True
    assert ac.applied == [tr] and st.seen == [tr] and lg.rows == [tr]
    assert lg.snaps == 1

    class SimLike:   # sim executor has no drain_completed -> no-op
        pass

    assert route_completed_trades(SimLike(), ac, st, lg) is False

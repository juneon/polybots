# tests/test_executor_live.py
"""LiveExecutor routing/pricing rules (no CLOB client, no network):
every SELL kind goes through the IOC sweep; exit_tp is priced at the intent
price (trigger-time bid, limit mode) while exit_sl/exit_time take bid-slippage;
the sweep aggregates partial fills across balance-lag passes and reports
sell_dust:below_step when the settled balance never reaches one step."""
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


def test_exit_tp_goes_through_sweep_at_intent_price():
    ex = make_exec()
    posted = wire(ex, balances=[10.0, 10.0, 0.0])
    tr = ex.fill(intent("exit_tp", price=0.98), quote_ev(bid=0.98), FakeAccount())

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
    tr = ex.fill(intent("exit_sl", price=0.75), quote_ev(bid=0.75), FakeAccount())

    assert tr["status"] == "filled"
    assert posted[0][0] == pytest.approx(0.70)   # 0.75 - slippage 0.05


def test_sweep_aggregates_partial_fills_across_balance_lag():
    ex = make_exec()
    # settles 4 tokens first, then the remaining 6 on the next pass
    posted = wire(ex, balances=[4.0, 4.0, 6.0, 0.0])
    tr = ex.fill(intent("exit_tp", price=0.98), quote_ev(bid=0.98), FakeAccount())

    assert tr["status"] == "filled"
    assert [s for _, s in posted] == [pytest.approx(4.0), pytest.approx(6.0)]
    assert tr["qty_tokens"] == pytest.approx(10.0)
    assert tr["fill_price"] == pytest.approx(0.98)
    assert len(tr["debug"]["attempts"]) == 2


def test_sweep_below_step_reports_sell_dust():
    ex = make_exec()
    posted = wire(ex, balances=[0.005, 0.005])
    tr = ex.fill(intent("exit_tp", price=0.98), quote_ev(bid=0.98), FakeAccount())

    assert tr["status"] == "rejected"
    assert tr["reason"] == "sell_dust:below_step"
    assert posted == []


def test_sweep_no_match_times_out_rejected():
    ex = make_exec()
    ex.sell_sweep_window_sec = 0.05   # keep the timeout path fast
    wire(ex, balances=[10.0, 10.0], fill=False)
    tr = ex.fill(intent("exit_tp", price=0.98), quote_ev(bid=0.98), FakeAccount())

    assert tr["status"] == "rejected"
    assert tr["reason"] == "sell_sweep_timeout"


def test_allowance_zero_aborts_before_posting():
    ex = make_exec()
    posted = wire(ex, balances=[10.0, 10.0, 0.0])
    ex._get_balance_allowance = lambda token_id: (10.0, 0.0)
    tr = ex.fill(intent("exit_tp", price=0.98), quote_ev(bid=0.98), FakeAccount())

    assert tr["status"] == "rejected"
    assert tr["reason"] == "sell_not_ready:allowance_zero"
    assert posted == []

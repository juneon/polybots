# tests/test_account_sim.py
"""SimAccount (SOT): only confirmed fills mutate state; dust threshold clears
the position; state survives a reload from disk."""
import pytest

from core.account_sim import SimAccount


def make(tmp_path):
    return SimAccount(path=str(tmp_path / "acct.json"))


def buy(qty=10.0, px=0.8, side="up"):
    return {"type": "trade", "kind": "buy", "status": "filled",
            "side": side, "qty_tokens": qty, "fill_price": px}


def sell(kind="exit_sl", qty=10.0, px=0.9, side="up"):
    return {"type": "trade", "kind": kind, "status": "filled",
            "side": side, "qty_tokens": qty, "fill_price": px}


def test_buy_fill_sets_position_and_cash(tmp_path):
    a = make(tmp_path)
    a.apply(buy())
    assert a.cash == -8.0
    assert a.position == {"side": "up", "entry": 0.8, "qty_tokens": 10.0, "notional_usd": 8.0}
    assert a.state["entries"]["up"] == 1


def test_non_filled_never_mutates(tmp_path):
    a = make(tmp_path)
    a.apply({**buy(), "status": "rejected"})
    a.apply({**buy(), "status": "submitted"})
    assert a.cash == 0.0 and a.position is None


def test_partial_exit_keeps_remainder(tmp_path):
    a = make(tmp_path)
    a.apply(buy())
    a.apply(sell(qty=4.0, px=0.9))
    assert a.cash == pytest.approx(-4.4)
    assert a.position["qty_tokens"] == 6.0


def test_dust_remainder_clears_position(tmp_path):
    a = make(tmp_path)
    a.apply(buy())
    a.apply(sell(qty=9.995, px=0.9))    # remainder 0.005 <= DUST_CLEAR_TOKENS
    assert a.position is None
    assert a.has_position() is False


def test_wrong_side_exit_ignored(tmp_path):
    a = make(tmp_path)
    a.apply(buy(side="up"))
    a.apply(sell(side="down"))
    assert a.position["qty_tokens"] == 10.0
    assert a.cash == -8.0


def test_exit_tp_marks_state_and_persists(tmp_path):
    a = make(tmp_path)
    a.apply(buy())
    a.apply(sell(kind="exit_tp", qty=10.0, px=0.99))
    assert a.state["tp_done"] is True

    # reload from disk: cash/position/state round-trip
    b = SimAccount(path=a.path)
    assert b.cash == a.cash
    assert b.position is None
    assert b.state["tp_done"] is True

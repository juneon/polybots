# tests/test_runner_settle.py
"""settle_open_position (P2 carry-over fix): at slug/run end an open sim
position is force-closed at the last seen bid of its own side — never carried
into the next slug's (different token) prices."""
import pytest

from core.account_sim import SimAccount
from core.runner import settle_open_position


class DummyLogger:
    def __init__(self):
        self.rows = []
        self.snapshots = []

    def handle(self, ev):
        self.rows.append(ev)

    def snapshot(self, account, quote_ev):
        self.snapshots.append((account.cash, quote_ev.get("slug")))


def quote_ev(slug="s1", up_bid=0.97, tick=880, tleft=8):
    return {"type": "quote", "slug": slug, "tick": tick, "time_left_sec": tleft,
            "quote": {"up": {"bid": up_bid, "ask": up_bid + 0.01, "token_id": "tokU"},
                      "down": {"bid": round(1 - up_bid - 0.01, 2), "ask": round(1 - up_bid, 2),
                               "token_id": "tokD"}}}


def make_account(tmp_path, side="up", qty=10.0, entry=0.8, slug="s1"):
    a = SimAccount(path=str(tmp_path / "acct.json"))
    a.apply({"type": "trade", "kind": "buy", "status": "filled", "slug": slug,
             "side": side, "qty_tokens": qty, "fill_price": entry})
    return a


def test_settles_at_last_bid_of_position_side(tmp_path):
    a = make_account(tmp_path)
    lg = DummyLogger()
    settle_open_position(a, quote_ev(up_bid=0.97), lg, "slug_end")

    assert a.position is None
    assert a.cash == pytest.approx(-8.0 + 10.0 * 0.97)

    intent, trade = lg.rows
    assert intent["type"] == "intent" and trade["type"] == "trade"
    for ev in (intent, trade):
        assert ev["kind"] == "exit_expiry"
        assert ev["slug"] == "s1" and ev["side"] == "up"
        assert ev["reason"] == "slug_end"
    assert trade["status"] == "filled"
    assert trade["fill_price"] == 0.97 and trade["qty_tokens"] == 10.0
    assert trade["token_id"] == "tokU"
    assert lg.snapshots  # account snapshot after the fill


def test_settles_down_side_at_down_bid(tmp_path):
    a = make_account(tmp_path, side="down", entry=0.4)
    lg = DummyLogger()
    settle_open_position(a, quote_ev(up_bid=0.97), lg, "run_end")
    assert a.position is None
    assert lg.rows[-1]["fill_price"] == 0.02  # down bid


def test_missing_book_settles_at_zero(tmp_path):
    # empty/one-sided book near expiry: worthless side realizes 0, position closed
    a = make_account(tmp_path)
    lg = DummyLogger()
    ev = quote_ev()
    ev["quote"].pop("up")
    settle_open_position(a, ev, lg, "run_end")
    assert a.position is None
    assert a.cash == pytest.approx(-8.0)
    assert lg.rows[-1]["fill_price"] == 0.0

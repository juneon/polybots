# tests/test_threshold_strategy.py
"""threshold: entry window/favorite selection, rejected-buy retry, SL re-entry,
TP slug lock, force exit — counters only move on CONFIRMED fills (on_trade)."""
from strategies.threshold import ThresholdStrategy

from helpers import FakeAccount, quote_ev, trade

CFG = {"strategy": {
    "name": "threshold", "qty_tokens": 10,
    "enter_time_left_sec": 450, "enter_deadline_left_sec": 80,
    "enter_price_1": 0.8, "enter_price_re": 0.8, "entry_cap": 0.9,
    "stop_drop": 0.06, "take_profit": 0.99,
    "max_entries_per_slug": 2, "force_exit_left_sec": 50,
    "dd_window_sec": 120, "reentry_dd_min": None,
}}


def make():
    return ThresholdStrategy(CFG), FakeAccount()


def test_enters_favorite_inside_window():
    st, acc = make()
    out = st.on_event(quote_ev(tleft=300, up=(0.79, 0.82), dn=(0.15, 0.18)), acc)
    assert len(out) == 1
    it = out[0]
    assert (it["kind"], it["side"], it["price"]) == ("buy", "up", 0.82)


def test_no_entry_outside_window_or_above_cap_or_below_threshold():
    st, acc = make()
    assert st.on_event(quote_ev(tleft=500), acc) == []                     # before window
    assert st.on_event(quote_ev(tleft=80), acc) == []                      # past deadline
    assert st.on_event(quote_ev(up=(0.90, 0.92)), acc) == []               # above entry_cap
    assert st.on_event(quote_ev(up=(0.70, 0.75)), acc) == []               # below enter_price_1


def test_rejected_buy_does_not_consume_slot_and_retries():
    st, acc = make()
    assert st.on_event(quote_ev(tick=1), acc)[0]["kind"] == "buy"
    st.on_trade(trade("buy", "rejected"))
    assert st.n == 0
    # still flat -> the same signal fires again next tick
    assert st.on_event(quote_ev(tick=2), acc)[0]["kind"] == "buy"
    st.on_trade(trade("buy", "filled"))
    assert st.n == 1


def test_submitted_buy_conservatively_consumes_slot():
    st, acc = make()
    st.on_event(quote_ev(), acc)
    st.on_trade(trade("buy", "submitted"))
    assert st.n == 1


def test_exit_priority_and_level_triggered_retry():
    st, acc = make()
    st.on_event(quote_ev(tick=1), acc)          # bind slug
    acc.position = {"side": "up", "entry": 0.82, "qty_tokens": 10.0}

    # force-exit outranks everything
    out = st.on_event(quote_ev(tick=2, tleft=50, up=(0.99, 1.0)), acc)
    assert out[0]["kind"] == "exit_time"

    # TP fires and re-fires until the fill confirms (level-triggered)
    for tick in (3, 4):
        out = st.on_event(quote_ev(tick=tick, up=(0.99, 1.0)), acc)
        assert out[0]["kind"] == "exit_tp"

    # SL when bid drops entry - stop_drop
    out = st.on_event(quote_ev(tick=5, up=(0.76, 0.80)), acc)
    assert out[0]["kind"] == "exit_sl"


def test_stop_loss_enables_reentry_and_tp_locks_slug():
    st, acc = make()
    st.on_event(quote_ev(tick=1), acc)
    st.on_trade(trade("buy", "filled"))          # n=1
    acc.position = {"side": "up", "entry": 0.82, "qty_tokens": 10.0}

    # confirmed SL -> flat again, re-entry allowed (n < max)
    st.on_trade(trade("exit_sl", "filled", px=0.76))
    acc.position = None
    assert st.stopped is True
    out = st.on_event(quote_ev(tick=2, up=(0.79, 0.82)), acc)
    assert out and out[0]["kind"] == "buy"

    # confirmed TP -> slug hard-locked, no further entries
    st.on_trade(trade("exit_tp", "filled", px=0.99))
    assert st.lock is True
    assert st.on_event(quote_ev(tick=3), acc) == []


def test_rejected_exit_does_not_mutate_state():
    st, acc = make()
    st.on_event(quote_ev(tick=1), acc)
    st.on_trade(trade("exit_sl", "rejected"))
    st.on_trade(trade("exit_tp", "rejected"))
    assert st.stopped is False and st.lock is False


def test_stop_confirm_dwell_delays_sl_and_recovery_resets():
    cfg = {"strategy": dict(CFG["strategy"], stop_confirm_sec=10)}
    st, acc = ThresholdStrategy(cfg), FakeAccount()
    st.on_event(quote_ev(tick=1), acc)          # bind slug
    acc.position = {"side": "up", "entry": 0.82, "qty_tokens": 10.0}

    # breach begins (bid 0.76 <= 0.82-0.06) but dwell not yet satisfied -> no SL
    assert st.on_event(quote_ev(tick=2, tleft=300, up=(0.76, 0.80)), acc) == []
    assert st.on_event(quote_ev(tick=3, tleft=295, up=(0.76, 0.80)), acc) == []

    # recovery above the stop level resets the dwell clock
    assert st.on_event(quote_ev(tick=4, tleft=290, up=(0.80, 0.84)), acc) == []
    assert st._sl_breach_tleft is None

    # new breach: fires only once it has held for stop_confirm_sec
    assert st.on_event(quote_ev(tick=5, tleft=280, up=(0.76, 0.80)), acc) == []
    assert st.on_event(quote_ev(tick=6, tleft=271, up=(0.76, 0.80)), acc) == []   # 9s < 10s
    out = st.on_event(quote_ev(tick=7, tleft=270, up=(0.76, 0.80)), acc)          # 10s
    assert out and out[0]["kind"] == "exit_sl"


def test_stop_confirm_zero_keeps_instant_sl():
    st, acc = make()                             # CFG has no stop_confirm_sec -> 0
    st.on_event(quote_ev(tick=1), acc)
    acc.position = {"side": "up", "entry": 0.82, "qty_tokens": 10.0}
    out = st.on_event(quote_ev(tick=2, up=(0.76, 0.80)), acc)
    assert out and out[0]["kind"] == "exit_sl"


def test_max_entries_per_slug_and_slug_reset():
    st, acc = make()
    st.on_event(quote_ev(tick=1), acc)
    st.on_trade(trade("buy", "filled"))
    st.on_trade(trade("exit_sl", "filled"))
    st.on_event(quote_ev(tick=2), acc)
    st.on_trade(trade("buy", "filled"))
    assert st.n == 2
    st.on_trade(trade("exit_sl", "filled"))
    assert st.on_event(quote_ev(tick=3), acc) == []      # n == max_entries_per_slug

    # new slug resets counters
    out = st.on_event(quote_ev(slug="s2", tick=1), acc)
    assert st.n == 0 and out[0]["kind"] == "buy"

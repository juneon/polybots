# tests/test_ma_strategy.py
"""ma: entry on ask cross-up under cap, exit_armed latch re-emits the
sell until the fill confirms, buy_inflight blocks stacking but a rejected buy
retries — all state transitions happen in on_trade (confirmed feedback only)."""
from strategies.ma import MAStrategy

from helpers import FakeAccount, quote_ev, trade

CFG = {"strategy": {
    "name": "ma", "qty_tokens": 10,
    "cap": 0.5, "ma_len": 2, "tick_confirm": 0,
    "cooldown_sec": 0, "no_entry_last_sec": None, "tp_abs": None,
}}

# down side stays out of play: ask above cap
DN = (0.15, 0.95)


def make():
    return MAStrategy(CFG), FakeAccount()


def feed(st, acc, tick, up):
    return st.on_event(quote_ev(tick=tick, ts=1000.0 + tick, up=up, dn=DN), acc)


def test_entry_on_ask_cross_up_under_cap():
    st, acc = make()
    assert feed(st, acc, 1, (0.38, 0.40)) == []            # SMA warming up
    assert feed(st, acc, 2, (0.38, 0.40)) == []            # ma ready, no cross
    out = feed(st, acc, 3, (0.43, 0.45))                   # 0.40<=0.40 -> 0.45>0.425
    assert out and (out[0]["kind"], out[0]["side"]) == ("buy", "up")


def test_no_entry_above_cap():
    st, acc = make()
    feed(st, acc, 1, (0.50, 0.52))
    feed(st, acc, 2, (0.50, 0.52))
    assert feed(st, acc, 3, (0.55, 0.57)) == []            # crosses, but ask > cap


def test_exit_latch_reemits_until_fill():
    st, acc = make()
    acc.position = {"side": "up", "entry": 0.45, "qty_tokens": 10.0}

    assert feed(st, acc, 1, (0.60, 0.62)) == []
    assert feed(st, acc, 2, (0.60, 0.62)) == []
    out = feed(st, acc, 3, (0.50, 0.52))                   # bid cross-down -> latch
    assert out and out[0]["kind"] == "exit_time"

    # no fresh cross on the next tick, but the latch re-emits
    out = feed(st, acc, 4, (0.50, 0.52))
    assert out and out[0]["kind"] == "exit_time"

    # confirmed fill releases the latch
    st.on_trade(trade("exit_time", "filled", px=0.50))
    acc.position = None
    assert feed(st, acc, 5, (0.50, 0.90)) == []            # flat, no signal


def test_tp_abs_outranks_ma_exit():
    st, acc = make()
    st_cfg = dict(CFG["strategy"], tp_abs=0.98)
    st = MAStrategy({"strategy": st_cfg})
    acc.position = {"side": "up", "entry": 0.45, "qty_tokens": 10.0}
    feed(st, acc, 1, (0.97, 0.99))
    out = feed(st, acc, 2, (0.98, 0.99))
    assert out and out[0]["kind"] == "exit_tp"


def test_buy_inflight_blocks_stacking_and_rejected_buy_retries():
    st, acc = make()
    feed(st, acc, 1, (0.38, 0.40))
    feed(st, acc, 2, (0.38, 0.40))
    assert feed(st, acc, 3, (0.43, 0.45))[0]["kind"] == "buy"

    # resting unconfirmed BUY -> block re-entry within the slug
    st.on_trade(trade("buy", "submitted", px=0.45))
    feed(st, acc, 4, (0.38, 0.40))                          # dips below ma
    assert feed(st, acc, 5, (0.43, 0.45)) == []             # crosses again, but inflight

    # rejected -> unblocked, the next signal retries
    st.on_trade(trade("buy", "rejected", px=0.45))
    feed(st, acc, 6, (0.38, 0.40))
    assert feed(st, acc, 7, (0.43, 0.45))[0]["kind"] == "buy"


def slope_strategy(slope_max=0.0, window=2):
    st_cfg = dict(CFG["strategy"], entry_slope_max=slope_max, entry_slope_window_sec=window)
    return MAStrategy({"strategy": st_cfg}), FakeAccount()


def test_slope_filter_blocks_rising_ma_cross():
    st, acc = slope_strategy()
    # rising asks -> rising SMA; the cross-up at t5 comes through a rising MA
    feed(st, acc, 1, (0.36, 0.38))
    feed(st, acc, 2, (0.36, 0.38))
    feed(st, acc, 3, (0.40, 0.42))
    feed(st, acc, 4, (0.38, 0.40))                          # dip below the MA (re-arms)
    assert feed(st, acc, 5, (0.43, 0.45)) == []             # cross-up, but slope > 0


def test_slope_filter_allows_falling_ma_cross():
    st, acc = slope_strategy()
    # falling asks -> falling SMA; the bounce at t5 crosses a falling MA
    feed(st, acc, 1, (0.55, 0.57))
    feed(st, acc, 2, (0.50, 0.52))
    feed(st, acc, 3, (0.44, 0.46))
    feed(st, acc, 4, (0.40, 0.42))                          # below the MA
    out = feed(st, acc, 5, (0.43, 0.45))                    # dip-bounce cross-up
    assert out and (out[0]["kind"], out[0]["side"]) == ("buy", "up")


def test_slope_filter_blocks_during_short_history():
    st, acc = slope_strategy(window=10)
    feed(st, acc, 1, (0.38, 0.40))
    feed(st, acc, 2, (0.38, 0.40))
    assert feed(st, acc, 3, (0.43, 0.45)) == []             # cross-up, history too short


def test_slug_change_drops_stale_state():
    st, acc = make()
    feed(st, acc, 1, (0.38, 0.40))
    st.on_event({"type": "slug_change", "slug": "s2", "slug_start_ts": 0,
                 "time_left_sec": 900, "slug_count": 2, "tick": 1}, acc)
    assert "s1" not in st._state

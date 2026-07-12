# tests/test_engine.py
"""Replay engine: cost-model executor semantics and (data permitting)
deterministic replay of the real strategies over the recorded quotes."""
from pathlib import Path

import pytest

from engine import ReplayAccount, ReplayExecutor, replay

PARQUET = Path(__file__).resolve().parents[1] / "backtest" / "data" / "quotes_all.parquet"


def intent(kind, side="up", price=0.8, qty=10.0):
    return {"kind": kind, "side": side, "price": price, "qty_tokens": qty,
            "slug": "s1", "tick": 1, "ts": 0}


def test_buy_fills_at_intent_price():
    ex = ReplayExecutor(haircut=0.01, p_fail=0.0)
    tr = ex.fill(intent("buy"), {}, ReplayAccount())
    assert tr["status"] == "filled" and tr["fill_price"] == 0.8


def test_sell_fills_at_bid_minus_haircut_for_full_position():
    acc = ReplayAccount()
    acc.apply({**intent("buy"), "type": "trade", "status": "filled", "fill_price": 0.8})
    ex = ReplayExecutor(haircut=0.01, p_fail=0.0)
    tr = ex.fill(intent("exit_tp", price=0.9), {}, acc)
    assert tr["status"] == "filled"
    assert tr["fill_price"] == pytest.approx(0.89)
    assert tr["qty_tokens"] == 10.0                     # sweeps the whole position


def test_sell_failure_probability_and_stats():
    acc = ReplayAccount()
    ex = ReplayExecutor(p_fail=1.0)
    tr = ex.fill(intent("exit_sl", price=0.9), {}, acc)
    assert tr["status"] == "rejected" and tr["reason"] == "sim_sell_fail"
    assert (ex.sell_attempts, ex.sell_fails) == (1, 1)


def test_replay_account_dust_clear():
    acc = ReplayAccount()
    acc.apply({**intent("buy"), "type": "trade", "status": "filled", "fill_price": 0.8})
    acc.apply({**intent("exit_time", qty=9.995), "type": "trade", "status": "filled", "fill_price": 0.9})
    assert acc.position is None


@pytest.mark.skipif(not PARQUET.exists(), reason="recorded quotes not present (gitignored data)")
def test_replay_is_deterministic_for_fixed_seed():
    import json

    import pandas as pd

    from engine import ROOT, prepare_slugs

    cfg = json.loads((ROOT / "configs" / "threshold.json").read_text(encoding="utf-8"))
    slugs = prepare_slugs(pd.read_parquet(PARQUET))
    r1 = replay("threshold", cfg, slugs, seed=42)
    r2 = replay("threshold", cfg, slugs, seed=42)
    assert r1["total_pnl"] == r2["total_pnl"]
    assert r1["per_slug"] == r2["per_slug"]
    assert r1["fills"] == r2["fills"]

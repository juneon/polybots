# tests/test_logger.py
"""Logger: append mode across runs (single header, run_id separates runs),
intent+trade paired into one trades.csv row."""
import csv

from core.logger import Logger

CFG = {"logging": {"events": True, "trades": True, "snapshots": False}}


def emit_pair(lg, slug, price, status="filled"):
    lg.handle({"type": "intent", "kind": "buy", "slug": slug, "tick": 1,
               "side": "up", "price": price, "qty_tokens": 10, "time_left_sec": 300, "ts": 1})
    lg.handle({"type": "trade", "kind": "buy", "slug": slug, "tick": 1, "side": "up",
               "status": status, "reason": "", "fill_price": price, "qty_tokens": 10,
               "notional_usd": 10 * price, "ts": 1})


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_append_across_runs_single_header(tmp_path):
    lg1 = Logger(CFG, run_id="run1", logs_dir=str(tmp_path))
    emit_pair(lg1, "s1", 0.8)
    lg1.close()

    lg2 = Logger(CFG, run_id="run2", logs_dir=str(tmp_path))
    emit_pair(lg2, "s2", 0.7)
    lg2.close()

    trades = tmp_path / "trades.csv"
    text = trades.read_text(encoding="utf-8")
    assert text.count("run_id,") == 1                     # header written exactly once

    rows = read_rows(trades)
    assert [r["run_id"] for r in rows] == ["run1", "run2"]
    assert rows[0]["intent_kind"] == "buy"
    assert rows[0]["intent_price"] == "0.8"               # intent paired into the trade row
    assert rows[0]["fill_price"] == "0.8"
    assert rows[1]["slug"] == "s2"


def test_events_rows_carry_run_id(tmp_path):
    lg = Logger(CFG, run_id="runX", logs_dir=str(tmp_path))
    lg.handle({"type": "slug_init", "slug": "s1", "tick": 0, "ts": 1})
    lg.handle({"type": "quote", "slug": "s1", "tick": 1, "ts": 2, "quote": {}})
    lg.close()

    rows = read_rows(tmp_path / "events.csv")
    assert [(r["run_id"], r["type"]) for r in rows] == [("runX", "slug_init"), ("runX", "quote")]


def test_disabled_sinks_write_nothing(tmp_path):
    lg = Logger({"logging": {"events": False, "trades": False, "snapshots": False}},
                run_id="r", logs_dir=str(tmp_path))
    emit_pair(lg, "s1", 0.8)
    lg.close()
    assert not (tmp_path / "trades.csv").exists()
    assert not (tmp_path / "events.csv").exists()

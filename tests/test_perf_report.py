# tests/test_perf_report.py
"""PerfReport: (strategy, mode) groups never mix, realized PnL counts only
closed slugs (dust rule), open slugs are reported separately, equity is the
cumulative fill cash-flow. Plus run_id parsing with '_' in strategy names."""
import csv

import ui.metrics as metrics
from core.logger import TRADES_FIELDS as FIELDS
from ui.metrics import PerfReport, mode_of_run_id, strategy_of_run_id


def write_trades(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def row(run_id, slug, kind, qty, px, ts=1000, status="filled"):
    return {"run_id": run_id, "ts": ts, "slug": slug, "intent_kind": kind,
            "status": status, "fill_price": px, "qty_tokens": qty}


def test_run_id_parsing_with_underscored_strategy():
    # legacy name in old logs normalizes to the current registry name
    assert strategy_of_run_id("20260711_120000_ma_breakout_sim") == "ma"
    assert strategy_of_run_id("20260714_120000_ma_sim") == "ma"
    assert mode_of_run_id("20260711_120000_ma_breakout_sim") == "sim"
    assert mode_of_run_id("20260711_120000_threshold_live") == "live"
    assert strategy_of_run_id("weird") == "weird"
    assert mode_of_run_id("weird") == "?"


def test_groups_realized_open_and_equity(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, "ROOT", tmp_path)   # don't read real sim_account files
    trades = tmp_path / "trades.csv"
    sim = "20260711_120000_threshold_sim"
    live = "20260711_130000_threshold_live"
    write_trades(trades, [
        row(sim, "slugA", "buy", 10, 0.8, ts=1000),
        row(sim, "slugA", "exit_tp", 10, 0.9, ts=1060),           # closed, pnl +1.0
        row(sim, "slugB", "buy", 10, 0.85, ts=2000),              # open (no exit)
        row(sim, "slugB", "buy", 0, 0, ts=2001, status="rejected"),  # ignored
        row(live, "slugC", "buy", 10, 0.8, ts=3000),
        row(live, "slugC", "exit_sl", 10, 0.7, ts=3060),          # closed, pnl -1.0
    ])

    groups = {(g["strategy"], g["mode"]): g for g in PerfReport(trades).report()["groups"]}
    assert set(groups) == {("threshold", "sim"), ("threshold", "live")}

    g = groups[("threshold", "sim")]
    assert g["realized_pnl"] == 1.0                # only the closed slug
    assert (g["wins"], g["losses"]) == (1, 0)
    assert g["open_slugs"] == 1
    assert g["unclosed_tokens"] == 10
    assert g["fills"] == 3                         # rejected row excluded
    assert [p[1] for p in g["equity"]] == [-8.0, 1.0, -7.5]   # cumulative cash flow

    assert groups[("threshold", "live")]["realized_pnl"] == -1.0


def test_dust_remainder_counts_as_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, "ROOT", tmp_path)
    trades = tmp_path / "trades.csv"
    sim = "20260711_120000_threshold_sim"
    write_trades(trades, [
        row(sim, "slugA", "buy", 10, 0.8),
        row(sim, "slugA", "exit_time", 9.995, 0.9),   # remainder 0.005 <= dust
    ])
    g = PerfReport(trades).report()["groups"][0]
    assert g["open_slugs"] == 0
    assert g["wins"] == 1


def test_cache_invalidates_when_file_grows(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, "ROOT", tmp_path)
    trades = tmp_path / "trades.csv"
    sim = "20260711_120000_threshold_sim"
    rows = [row(sim, "slugA", "buy", 10, 0.8)]
    write_trades(trades, rows)

    pr = PerfReport(trades)
    assert pr.report()["groups"][0]["fills"] == 1
    rows.append(row(sim, "slugA", "exit_tp", 10, 0.9))
    write_trades(trades, rows)
    assert pr.report()["groups"][0]["fills"] == 2

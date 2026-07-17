# tests/test_run_grid_checkpoint.py
"""run_grid incremental checkpoint: combo keys survive the CSV round-trip
(None <-> 'none', int/float coercion) so a rerun with the same --out skips
exactly the combos already computed."""
import csv

import pandas as pd
import pytest

import run_grid as rg

PARAMS_A = {"cap": 0.7, "ma_len": 600, "tick_confirm": 0, "tp_abs": None,
            "cooldown_sec": 0, "no_entry_last_sec": 80, "entry_slope_max": -0.005}
PARAMS_B = {"cap": 0.5, "ma_len": 300, "tick_confirm": 0, "tp_abs": 0.98,
            "cooldown_sec": 60, "no_entry_last_sec": None, "entry_slope_max": 0}


def _row(params, haircut=0.01):
    row = {k: ("none" if params[k] is None else params[k]) for k in rg.PARAM_COLS}
    row.update({"haircut": haircut, "trades": 10, "train_pnl": 1.5, "train_mdd": -0.5,
                "train_score": 1.25, "mar03_pnl": 0.1, "sim_pnl": -0.2, "val_pnl": -0.1,
                "total_pnl": 1.4, "sell_fail_rate": 0.2})
    return row


def _write_ckpt(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rg.FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def test_key_survives_csv_roundtrip(tmp_path):
    p = tmp_path / "ckpt.csv"
    _write_ckpt(p, [_row(PARAMS_A), _row(PARAMS_B)])
    loaded = rg._load_checkpoint(p)
    done = {rg._combo_key(r, r["haircut"]) for r in loaded}
    assert rg._combo_key(PARAMS_A, 0.01) in done
    assert rg._combo_key(PARAMS_B, 0.01) in done


def test_key_distinguishes_combos_and_haircut():
    assert rg._combo_key(PARAMS_A, 0.01) != rg._combo_key(PARAMS_B, 0.01)
    assert rg._combo_key(PARAMS_A, 0.01) != rg._combo_key(PARAMS_A, 0.02)


def test_key_normalizes_equivalent_forms():
    # 'none' string (CSV) == None (grid); "0"/0.0 (CSV) == int 0 (grid)
    assert rg._combo_key(dict(PARAMS_A, tp_abs="none"), 0.01) == rg._combo_key(PARAMS_A, 0.01)
    assert rg._combo_key(dict(PARAMS_B, entry_slope_max="0", cooldown_sec=60.0), 0.01) \
        == rg._combo_key(PARAMS_B, 0.01)


def test_canon_row_restores_eval_combo_shape(tmp_path):
    p = tmp_path / "ckpt.csv"
    _write_ckpt(p, [_row(PARAMS_B)])
    (row,) = rg._load_checkpoint(p)
    assert row["tp_abs"] == 0.98 and row["no_entry_last_sec"] == "none"
    assert isinstance(row["ma_len"], int) and isinstance(row["trades"], int)
    assert row["train_score"] == pytest.approx(1.25)


def test_missing_or_empty_checkpoint_is_fresh_start(tmp_path):
    assert rg._load_checkpoint(tmp_path / "nope.csv") == []
    empty = tmp_path / "empty.csv"
    empty.touch()
    assert rg._load_checkpoint(empty) == []


def test_old_format_checkpoint_refused(tmp_path):
    p = tmp_path / "old.csv"
    pd.DataFrame([{"cap": 0.5, "train_pnl": 1.0}]).to_csv(p, index=False)
    with pytest.raises(SystemExit):
        rg._load_checkpoint(p)


def test_torn_last_line_is_dropped(tmp_path):
    p = tmp_path / "ckpt.csv"
    _write_ckpt(p, [_row(PARAMS_A)])
    with open(p, "a", encoding="utf-8", newline="") as f:
        f.write("0.5,300,0,0.98,60")  # hard-kill mid-row: only 5 of 17 fields
    loaded = rg._load_checkpoint(p)
    assert len(loaded) == 1
    assert rg._combo_key(loaded[0], loaded[0]["haircut"]) == rg._combo_key(PARAMS_A, 0.01)

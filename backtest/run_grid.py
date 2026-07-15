# backtest/run_grid.py
"""Realistic grid search for ma — fans out the exact-replay engine (multiprocess).

v2 (2026-07-12): the old vectorized MA reimplementation was removed (together with
backtest.py). Every combo now replays the REAL strategies/ma.py through
engine.replay, so grid semantics cannot drift from sim/live behavior. The grid
axes are the strategy's actual config keys — note the old grid searched a
relative tp/sl axis the real strategy cannot even run; it is replaced by tp_abs.

Cost model = engine.ReplayExecutor (calibrated from the 2026-03-03 live session):
  - BUY fills at intent ask (measured slip ~= 0)
  - SELL fills at bid - haircut (default 0.01)
  - each SELL attempt fails with prob p_fail (default 0.2, seeded RNG)
  - slug end: open position force-closes at last bid (~resolution value)

Train/validation split:
  - TRAIN = grid_jan_feb source          -> parameter selection
  - VAL   = live_mar03 + sim_* sources   -> out-of-sample check (mar03_pnl / sim_pnl split out)

Run from backtest/ (after data_prep.py):
    python run_grid.py                   # full grid (~24k combos, ~1.1s each / pool)
    python run_grid.py --quick           # 32-combo smoke grid, no sensitivity pass
    python run_grid.py --json out.json   # machine-readable summary (for UI jobs)
Output: grid_results_realistic.csv + report tables.
"""
import argparse
import json
import os
import time
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from engine import ROOT, prepare_slugs, replay

DATA_PATH = "data/quotes_all.parquet"
OUT_CSV = "results/grid_results_realistic.csv"

# ====== grid axes — REAL strategy config keys (strategies/ma.py) ======
GRID = {
    "cap": [0.7, 0.6, 0.5, 0.45, 0.4, 0.35, 0.3],
    "ma_len": [120, 200, 240, 300, 480, 600],
    "tick_confirm": [0, 2, 3],
    "tp_abs": [None, 0.95, 0.98, 0.99],
    "cooldown_sec": [0, 30, 60, 90],
    "no_entry_last_sec": [None, 80, 100],
    "entry_slope_max": [None, 0, -0.005, -0.01],
}
QUICK_GRID = {
    "cap": [0.5, 0.4],
    "ma_len": [300],
    "tick_confirm": [0],
    "tp_abs": [None, 0.98],
    "cooldown_sec": [0, 60],
    "no_entry_last_sec": [None, 80],
    "entry_slope_max": [None, -0.005],
}

# the old frictionless optimum — always evaluated for comparison
OLD_OPTIMUM = {"cap": 0.5, "ma_len": 300, "tick_confirm": 0, "tp_abs": None,
               "cooldown_sec": 0, "no_entry_last_sec": None,
               "entry_slope_max": None}

# sell_haircut sensitivity sweep for the top candidates
HAIRCUT_SENS = [0.0, 0.005, 0.01, 0.02, 0.03]
TOP_N_SENS = 15

PARAM_COLS = list(GRID.keys())
REPORT_COLS = PARAM_COLS + ["haircut", "trades", "train_pnl", "train_mdd", "train_score",
                            "mar03_pnl", "sim_pnl", "val_pnl"]


def calc_mdd(pnls):
    eq = peak = mdd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return mdd


# ====== worker globals (populated once per process by _init_worker) ======
_G = {}


def _init_worker(data_path, p_fail, seed, include_partial=False):
    quotes = pd.read_parquet(data_path)
    _G["slugs"] = prepare_slugs(quotes, include_partial=include_partial)
    by_src = quotes.drop_duplicates("slug")[["slug", "source"]]
    _G["train"] = set(by_src.loc[by_src["source"] == "grid_jan_feb", "slug"])
    _G["mar03"] = set(by_src.loc[by_src["source"] == "live_mar03", "slug"])
    _G["sim"] = set(by_src.loc[by_src["source"].str.startswith("sim"), "slug"])
    _G["base_cfg"] = json.loads((ROOT / "configs" / "ma.json").read_text(encoding="utf-8"))
    _G["p_fail"] = p_fail
    _G["seed"] = seed


def _eval_combo(job):
    """job = (params_dict, haircut). Replays the real strategy with overrides."""
    params, haircut = job
    cfg = json.loads(json.dumps(_G["base_cfg"]))
    cfg["strategy"].update(params)
    r = replay("ma", cfg, _G["slugs"],
               haircut=haircut, p_fail=_G["p_fail"], seed=_G["seed"])

    # per_slug preserves slug order -> MDD over an ordered equity path
    tr = [v for s, v in r["per_slug"].items() if s in _G["train"]]
    m3 = [v for s, v in r["per_slug"].items() if s in _G["mar03"]]
    si = [v for s, v in r["per_slug"].items() if s in _G["sim"]]
    tr_pnl, m3_pnl, si_pnl = float(np.sum(tr)), float(np.sum(m3)), float(np.sum(si))
    tr_mdd = calc_mdd(tr)

    row = {k: ("none" if params[k] is None else params[k]) for k in params}
    row.update({
        "haircut": haircut, "trades": r["fills"],
        "train_pnl": tr_pnl, "train_mdd": tr_mdd,
        "train_score": tr_pnl - 0.5 * abs(tr_mdd),
        "mar03_pnl": m3_pnl, "sim_pnl": si_pnl,
        "val_pnl": m3_pnl + si_pnl, "total_pnl": r["total_pnl"],
        "sell_fail_rate": round(r["sell_fail_rate"], 3),
    })
    return row


def _params_from_row(row):
    """Inverse of the 'none' normalization in _eval_combo, for re-running a row."""
    out = {}
    for k in PARAM_COLS:
        v = row[k]
        if isinstance(v, str) and v == "none":
            out[k] = None
        elif k in ("ma_len", "tick_confirm", "cooldown_sec", "no_entry_last_sec"):
            out[k] = int(v)
        else:
            out[k] = float(v)
    return out


def run(args):
    grid = QUICK_GRID if args.quick else GRID
    combos = [dict(zip(grid.keys(), vals)) for vals in product(*grid.values())]
    if OLD_OPTIMUM not in combos:
        combos.append(OLD_OPTIMUM)
    jobs = [(c, args.haircut) for c in combos]
    total = len(jobs)

    from multiprocessing import Pool
    print(f"grid: {total} combos (exact replay of strategies/ma.py), "
          f"workers={args.workers}, cost model: haircut={args.haircut}, p_fail={args.pfail}", flush=True)

    rows = []
    t0 = time.time()
    with Pool(args.workers, initializer=_init_worker,
              initargs=(args.data, args.pfail, args.seed, args.include_partial)) as pool:
        for k, row in enumerate(pool.imap_unordered(_eval_combo, jobs, chunksize=2), 1):
            rows.append(row)
            if k % 25 == 0 or k == total:
                el = time.time() - t0
                rate = k / el
                eta = (total - k) / rate
                best = max(rows, key=lambda r: r["train_score"])
                print(f"[{k/total*100:5.1f}%] {k}/{total} rate={rate:.1f}/s eta={eta/60:.1f}m "
                      f"| best train_score={best['train_score']:.2f} val={best['val_pnl']:+.2f} "
                      f"(cap={best['cap']} ma={best['ma_len']} tc={best['tick_confirm']} "
                      f"tp_abs={best['tp_abs']} cd={best['cooldown_sec']} ban={best['no_entry_last_sec']})",
                      flush=True)

        res = pd.DataFrame(rows)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        res.to_csv(args.out, index=False)
        print(f"\nsaved: {args.out}", flush=True)

        print("\n===== TOP 20 by train_score (exact replay, realistic costs) =====")
        top = res.sort_values("train_score", ascending=False).head(20)
        print(top[REPORT_COLS].to_string(index=False), flush=True)

        print("\n===== OLD frictionless optimum under realistic costs =====")
        mask = pd.Series(True, index=res.index)
        for k, v in OLD_OPTIMUM.items():
            mask &= res[k] == ("none" if v is None else v)
        old = res[mask]
        print(old[REPORT_COLS].to_string(index=False))
        rank = int((res["train_score"] > old["train_score"].iloc[0]).sum()) + 1
        print(f"-> rank {rank} / {total}", flush=True)

        # ===== haircut sensitivity for top-N (reuses the same pool) =====
        sens_table = []
        if not args.quick:
            print(f"\n===== sell_haircut sensitivity (top {TOP_N_SENS} by train_score) =====")
            sens_jobs, sens_meta = [], []
            for _, r in res.sort_values("train_score", ascending=False).head(TOP_N_SENS).iterrows():
                params = _params_from_row(r)
                for hc in HAIRCUT_SENS:
                    sens_jobs.append((params, hc))
                    sens_meta.append((tuple(r[k] for k in PARAM_COLS), hc))

            sens_res = pool.map(_eval_combo, sens_jobs, chunksize=4)
            srows = {}
            for (key, hc), sr in zip(sens_meta, sens_res):
                srows.setdefault(key, dict(zip(PARAM_COLS, key)))
                srows[key][f"hc{hc}"] = round(sr["train_pnl"] + sr["val_pnl"], 2)  # full-period pnl
            sens_table = list(srows.values())
            print(pd.DataFrame(sens_table).to_string(index=False), flush=True)

    if args.json:
        summary = {
            "kind": "grid", "strategy": "ma", "data": args.data,
            "include_partial": args.include_partial,
            "cost_model": {"haircut": args.haircut, "p_fail": args.pfail, "seed": args.seed},
            "combos": total, "elapsed_sec": round(time.time() - t0, 1),
            "results_csv": args.out,
            "top": top[REPORT_COLS].to_dict(orient="records"),
            "old_optimum": {**old[REPORT_COLS].to_dict(orient="records")[0], "rank": rank},
            "haircut_sensitivity": sens_table,
        }
        Path(args.json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"json: {args.json}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="realistic ma grid (exact-replay fan-out)")
    ap.add_argument("--data", default=DATA_PATH)
    ap.add_argument("--out", default=OUT_CSV, help="results CSV path")
    ap.add_argument("--haircut", type=float, default=0.01)
    ap.add_argument("--pfail", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=max(2, min(10, (os.cpu_count() or 4) - 2)))
    ap.add_argument("--quick", action="store_true", help="16-combo smoke grid, skip sensitivity")
    ap.add_argument("--include-partial", action="store_true",
                    help="also replay partial slugs (pre-2026-07-14 behavior)")
    ap.add_argument("--json", default=None, metavar="PATH",
                    help="also write a machine-readable summary (for UI jobs)")
    args = ap.parse_args()
    run(args)


if __name__ == "__main__":
    main()

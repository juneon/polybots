# backtest/sweep_threshold.py
"""Parameter sweep for the threshold strategy using the exact-replay engine.

threshold trades are rare (~400 fills over 241 slugs) so the exact engine is
fast enough to sweep directly, without a process pool.

Validation: janfeb is the train set; `val` = live_mar03 + sim_* (everything
recorded after the parameters were chosen). Rank by score but read `val` —
a combo that only wins on janfeb is curve-fit.

Run from backtest/:
    python sweep_threshold.py                   # archives results/<ts>_sweep_threshold.{csv,json}
    python sweep_threshold.py --json out.json --out out.csv   # explicit paths (UI jobs)
"""
import argparse
import json
import time
from itertools import product
from pathlib import Path

import pandas as pd

from engine import ROOT, prepare_slugs, replay

# sweep axes — current config is read live from configs/threshold.json below.
# t_enter(enter_time_left_sec) probes whipsaw exposure: entering later leaves
# less time for the favorite to dip through the stop and recover (2026-07-13).
ENTER_1 = [0.80, 0.85, 0.90]
STOP_DROP = [0.06, 0.08, 0.10, 0.12]
TAKE_PROFIT = [0.98, 0.99]
ENTRY_CAP = [0.90, 0.95]
T_ENTER = [450, 300, 180]


def main():
    ap = argparse.ArgumentParser(description="threshold sweep (exact-replay engine)")
    ap.add_argument("--data", default="data/quotes_all.parquet")
    ap.add_argument("--out", default=None, help="results CSV path (default: results/<ts>_sweep_threshold.csv)")
    ap.add_argument("--haircut", type=float, default=0.01)
    ap.add_argument("--pfail", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--json", default=None, metavar="PATH",
                    help="summary JSON path (default: results/<ts>_sweep_threshold.json)")
    ap.add_argument("--include-partial", action="store_true",
                    help="also replay partial slugs (pre-2026-07-14 behavior)")
    args = ap.parse_args()

    ts = time.strftime("%Y%m%d_%H%M%S")
    results_dir = Path(__file__).parent / "results"
    out_csv = args.out or str(results_dir / f"{ts}_sweep_threshold.csv")
    out_json = args.json or str(results_dir / f"{ts}_sweep_threshold.json")

    base_cfg = json.loads((ROOT / "configs" / "threshold.json").read_text(encoding="utf-8"))
    slugs = prepare_slugs(pd.read_parquet(args.data), include_partial=args.include_partial)

    rows = []
    combos = list(product(ENTER_1, STOP_DROP, TAKE_PROFIT, ENTRY_CAP, T_ENTER))
    for i, (p1, sl, tp, cap, t_enter) in enumerate(combos, 1):
        cfg = json.loads(json.dumps(base_cfg))
        s = cfg["strategy"]
        s["enter_price_1"] = p1
        s["enter_price_re"] = p1          # keep re-entry threshold aligned
        s["stop_drop"] = sl
        s["take_profit"] = tp
        s["entry_cap"] = cap
        s["enter_time_left_sec"] = t_enter

        r = replay("threshold", cfg, slugs, haircut=args.haircut, p_fail=args.pfail, seed=args.seed)
        sim = round(sum(v for k, v in r["per_source"].items() if k.startswith("sim_")), 2)
        mar03 = r["per_source"].get("live_mar03", 0.0)
        rows.append({
            "enter_1": p1, "stop_drop": sl, "take_profit": tp, "entry_cap": cap, "t_enter": t_enter,
            "pnl": round(r["total_pnl"], 2), "mdd": round(r["mdd"], 2),
            "score": round(r["score"], 2),
            "janfeb": r["per_source"].get("grid_jan_feb", 0.0),
            "mar03": mar03, "sim": sim, "val": round(mar03 + sim, 2),
            "W": r["wins"], "L": r["losses"], "fills": r["fills"],
        })
        if i % 24 == 0:
            print(f"{i}/{len(combos)} done", flush=True)

    df = pd.DataFrame(rows).sort_values("score", ascending=False)
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    print("\n===== TOP 15 (realistic costs, sorted by score) =====")
    print(df.head(15).to_string(index=False))
    print("\n===== TOP 5 by val (mar03 + sim, the out-of-sample side) =====")
    print(df.sort_values("val", ascending=False).head(5).to_string(index=False))

    bs = base_cfg["strategy"]
    print(f"\n===== current config ({bs['enter_price_1']:.2f} / {bs['stop_drop']:.2f}"
          f" / {bs['take_profit']:.2f} / {bs['entry_cap']:.2f} / t{bs['enter_time_left_sec']}) =====")
    cur = df[(df["enter_1"] == bs["enter_price_1"]) & (df["stop_drop"] == bs["stop_drop"])
             & (df["take_profit"] == bs["take_profit"]) & (df["entry_cap"] == bs["entry_cap"])
             & (df["t_enter"] == bs["enter_time_left_sec"])]
    rank = None
    if len(cur):
        print(cur.to_string(index=False))
        rank = int((df["score"] > cur["score"].iloc[0]).sum()) + 1
        print(f"-> rank {rank} / {len(df)}")
    else:
        print("(current config is off the sweep grid)")

    summary = {
        "kind": "sweep", "strategy": "threshold", "data": args.data,
        "include_partial": args.include_partial, "slugs": len(slugs),
        "cost_model": {"haircut": args.haircut, "p_fail": args.pfail, "seed": args.seed},
        "combos": len(combos), "results_csv": out_csv,
        "top": df.head(15).to_dict(orient="records"),
        "top_val": df.sort_values("val", ascending=False).head(5).to_dict(orient="records"),
        "current_config": {**cur.to_dict(orient="records")[0], "rank": rank} if len(cur) else None,
    }
    Path(out_json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"csv: {out_csv}\njson: {out_json}")


if __name__ == "__main__":
    main()

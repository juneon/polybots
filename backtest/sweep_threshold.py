# backtest/sweep_threshold.py
"""Parameter sweep for the threshold strategy using the exact-replay engine.

threshold trades are rare (~340 fills over 209 slugs) so the exact engine is
fast enough to sweep directly, without a process pool.

Run from backtest/:
    python sweep_threshold.py
    python sweep_threshold.py --json out.json   # machine-readable summary (for UI jobs)
"""
import argparse
import json
from itertools import product
from pathlib import Path

import pandas as pd

from engine import ROOT, prepare_slugs, replay

# sweep axes around the current config (enter=0.8, sl=0.06, tp=0.98, cap=0.9)
ENTER_1 = [0.75, 0.80, 0.85]
STOP_DROP = [0.04, 0.06, 0.08, 0.10]
TAKE_PROFIT = [0.96, 0.98, 0.99]
ENTRY_CAP = [0.90, 0.95]

OUT_CSV = "results/sweep_threshold_results.csv"


def main():
    ap = argparse.ArgumentParser(description="threshold sweep (exact-replay engine)")
    ap.add_argument("--data", default="data/quotes_all.parquet")
    ap.add_argument("--out", default=OUT_CSV, help="results CSV path")
    ap.add_argument("--haircut", type=float, default=0.01)
    ap.add_argument("--pfail", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--json", default=None, metavar="PATH",
                    help="also write a machine-readable summary (for UI jobs)")
    args = ap.parse_args()

    base_cfg = json.loads((ROOT / "configs" / "threshold.json").read_text(encoding="utf-8"))
    slugs = prepare_slugs(pd.read_parquet(args.data))

    rows = []
    combos = list(product(ENTER_1, STOP_DROP, TAKE_PROFIT, ENTRY_CAP))
    for i, (p1, sl, tp, cap) in enumerate(combos, 1):
        cfg = json.loads(json.dumps(base_cfg))
        s = cfg["strategy"]
        s["enter_price_1"] = p1
        s["enter_price_re"] = p1          # keep re-entry threshold aligned
        s["stop_drop"] = sl
        s["take_profit"] = tp
        s["entry_cap"] = cap

        r = replay("threshold", cfg, slugs, haircut=args.haircut, p_fail=args.pfail, seed=args.seed)
        rows.append({
            "enter_1": p1, "stop_drop": sl, "take_profit": tp, "entry_cap": cap,
            "pnl": round(r["total_pnl"], 2), "mdd": round(r["mdd"], 2),
            "score": round(r["score"], 2),
            "janfeb": r["per_source"].get("grid_jan_feb", 0.0),
            "mar03": r["per_source"].get("live_mar03", 0.0),
            "W": r["wins"], "L": r["losses"], "fills": r["fills"],
        })
        if i % 12 == 0:
            print(f"{i}/{len(combos)} done", flush=True)

    df = pd.DataFrame(rows).sort_values("score", ascending=False)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print("\n===== TOP 15 (realistic costs, sorted by score) =====")
    print(df.head(15).to_string(index=False))
    print("\n===== current config (0.80 / 0.06 / 0.98 / 0.90) =====")
    cur = df[(df["enter_1"] == 0.80) & (df["stop_drop"] == 0.06)
             & (df["take_profit"] == 0.98) & (df["entry_cap"] == 0.90)]
    print(cur.to_string(index=False))
    rank = int((df["score"] > cur["score"].iloc[0]).sum()) + 1
    print(f"-> rank {rank} / {len(df)}")

    if args.json:
        summary = {
            "kind": "sweep", "strategy": "threshold", "data": args.data,
            "cost_model": {"haircut": args.haircut, "p_fail": args.pfail, "seed": args.seed},
            "combos": len(combos), "results_csv": args.out,
            "top": df.head(15).to_dict(orient="records"),
            "current_config": {**cur.to_dict(orient="records")[0], "rank": rank} if len(cur) else None,
        }
        Path(args.json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"json: {args.json}")


if __name__ == "__main__":
    main()

# backtest/sweep_threshold.py
"""Parameter sweep for the threshold strategy using the exact-replay engine.

The vectorized grid (run_grid.py) covers ma_breakout; threshold trades are rare
(~340 fills over 209 slugs) so the exact engine is fast enough to sweep directly.

Run from backtest/:  python sweep_threshold.py
"""
import json
from itertools import product
from pathlib import Path

import pandas as pd

from engine import replay, ROOT

# sweep axes around the current config (enter=0.8, sl=0.06, tp=0.98, cap=0.9)
ENTER_1 = [0.75, 0.80, 0.85]
STOP_DROP = [0.04, 0.06, 0.08, 0.10]
TAKE_PROFIT = [0.96, 0.98, 0.99]
ENTRY_CAP = [0.90, 0.95]

HAIRCUT = 0.01
P_FAIL = 0.2


def main():
    base_cfg = json.loads((ROOT / "configs" / "threshold.json").read_text(encoding="utf-8"))
    quotes = pd.read_parquet("data/quotes_all.parquet")

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

        r = replay("threshold", cfg, quotes, haircut=HAIRCUT, p_fail=P_FAIL, seed=42)
        rows.append({
            "enter_1": p1, "stop_drop": sl, "take_profit": tp, "entry_cap": cap,
            "pnl": round(r["total_pnl"], 2), "mdd": round(r["mdd"], 2),
            "score": round(r["score"], 2),
            "janfeb": r["per_source"].get("grid_jan_feb", 0.0),
            "mar03": r["per_source"].get("live_mar03", 0.0),
            "W": r["wins"], "L": r["losses"], "fills": r["fills"],
        })
        if i % 12 == 0:
            print(f"{i}/{len(combos)} done")

    df = pd.DataFrame(rows).sort_values("score", ascending=False)
    df.to_csv("sweep_threshold_results.csv", index=False)
    print("\n===== TOP 15 (realistic costs, sorted by score) =====")
    print(df.head(15).to_string(index=False))
    print("\n===== current config (0.80 / 0.06 / 0.98 / 0.90) =====")
    cur = df[(df["enter_1"] == 0.80) & (df["stop_drop"] == 0.06)
             & (df["take_profit"] == 0.98) & (df["entry_cap"] == 0.90)]
    print(cur.to_string(index=False))
    print(f"-> rank {int((df['score'] > cur['score'].iloc[0]).sum()) + 1} / {len(df)}")


if __name__ == "__main__":
    main()

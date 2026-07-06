# backtest/run_grid.py
"""Realistic grid search for the MA-breakout strategy (multiprocess).

Execution cost model — CALIBRATED from the 2026-03-03 live session (122 fills):
  - BUY  fills at the intent ask            (measured slip ~= 0)
  - SELL fills at bid - SELL_HAIRCUT        (measured: mean +0.44c, median +0.9c, p90 +3c)
  - DUST_FRAC of the position fails to sell (measured ~1.3%/round trip) and is
    carried to slug end, closing at the last bid (~resolution value)
  - end-of-slug: any open position closes at the last bid

Train/validation split:
  - TRAIN = grid_jan_feb source (189 slugs) -> parameter selection
  - VAL   = live_mar03 source   (18 slugs)  -> out-of-sample check

Run from backtest/ (after data_prep.py):  python run_grid.py
Output: grid_results_realistic.csv + report tables.

NOTE: the inner replay is a pure-Python loop (~2.5s/combo x 3600 combos), so the
grid fans out over a process pool (single-core would take ~2.5h; ~15min on 10 cores).
"""
import os
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

# ====== calibrated cost model (see module docstring) ======
SELL_HAIRCUT = 0.01
DUST_FRAC = 0.013

QTY = 10.0
DATA_PATH = "data/quotes_all.parquet"

# ====== grid axes (superset of the original frictionless grid) ======
CAP_LIST = [0.5, 0.45, 0.4, 0.35, 0.3]
MA_LIST = [120, 200, 240, 300, 480]
TICK_CONFIRM_LIST = [0, 2, 3]
TP_SL_LIST = [None, (0.15, 0.05), (0.10, 0.10), (0.10, 0.05)]
COOLDOWN_LIST = [0, 30, 60, 90]
BAN_LAST_SEC_LIST = [None, 80, 100]

# sensitivity sweep for the top candidates
HAIRCUT_SENS = [0.0, 0.005, 0.01, 0.02, 0.03]
TOP_N_SENS = 15

# the old frictionless optimum — always evaluated for comparison
OLD_OPTIMUM = dict(cap=0.5, ma=300, tick_confirm=0, tp_sl="none", cooldown_sec=0, ban_last_sec="none")

WORKERS = max(2, min(10, (os.cpu_count() or 4) - 2))


def prepare(quotes: pd.DataFrame):
    """Precompute per-slug arrays and per-ma_len SMA columns ONCE per worker."""
    slugs = []
    for slug, s in quotes.groupby("slug", sort=False):
        s = s.sort_values("tick").reset_index(drop=True)
        if len(s) < 2:
            continue
        d = {
            "slug": slug,
            "source": s["source"].iloc[0],
            "ts": s["ts"].to_numpy(),
            "tleft": s["time_left_sec"].to_numpy(),
            "up_ask": s["up_ask"].to_numpy(),
            "dn_ask": s["down_ask"].to_numpy(),
            "up_bid": s["up_bid"].to_numpy(),
            "dn_bid": s["down_bid"].to_numpy(),
            "ma": {},
        }
        for ma in MA_LIST:
            d["ma"][ma] = {
                "up_ask": s["up_ask"].rolling(ma).mean().to_numpy(),
                "dn_ask": s["down_ask"].rolling(ma).mean().to_numpy(),
                "up_bid": s["up_bid"].rolling(ma).mean().to_numpy(),
                "dn_bid": s["down_bid"].rolling(ma).mean().to_numpy(),
            }
        slugs.append(d)
    return slugs


def backtest_one(slugs, ma, cap, tick_confirm, tp_sl, cooldown_sec, ban_last_sec,
                 sell_haircut=SELL_HAIRCUT, dust_frac=DUST_FRAC):
    """Returns dict: slug -> pnl, plus trade count."""
    tp, sl = tp_sl if tp_sl is not None else (None, None)
    per_slug = {}
    ntr = 0

    for d in slugs:
        ts = d["ts"]; tleft = d["tleft"]
        up_ask = d["up_ask"]; dn_ask = d["dn_ask"]
        up_bid = d["up_bid"]; dn_bid = d["dn_bid"]
        m = d["ma"][ma]
        up_ma_ask = m["up_ask"]; dn_ma_ask = m["dn_ask"]
        up_ma_bid = m["up_bid"]; dn_ma_bid = m["dn_bid"]
        n = len(ts)

        pnl = 0.0
        dust_qty_up = 0.0
        dust_qty_dn = 0.0
        in_pos = False
        side = 0
        entry = 0.0
        next_entry_ts = -1e18
        up_cnt = dn_cnt = 0

        def sell(bid_px, qty):
            """Sweep sell with haircut; dust carried to slug end."""
            nonlocal dust_qty_up, dust_qty_dn
            sold = qty * (1.0 - dust_frac)
            if side == 0:
                dust_qty_up += qty - sold
            else:
                dust_qty_dn += qty - sold
            return sold * (max(bid_px - sell_haircut, 0.0) - entry)

        for i in range(1, n):
            if in_pos:
                bid = up_bid[i] if side == 0 else dn_bid[i]

                if tp is not None and bid >= entry + tp:
                    pnl += sell(bid, QTY); ntr += 1
                    in_pos = False; next_entry_ts = ts[i] + cooldown_sec; up_cnt = dn_cnt = 0
                    continue

                if sl is not None and bid <= entry - sl:
                    pnl += sell(bid, QTY); ntr += 1
                    in_pos = False; next_entry_ts = ts[i] + cooldown_sec; up_cnt = dn_cnt = 0
                    continue

                ma_now = up_ma_bid[i] if side == 0 else dn_ma_bid[i]
                ma_prev = up_ma_bid[i - 1] if side == 0 else dn_ma_bid[i - 1]
                bid_prev = up_bid[i - 1] if side == 0 else dn_bid[i - 1]
                if not np.isnan(ma_now) and not np.isnan(ma_prev):
                    if bid_prev >= ma_prev and bid < ma_now:
                        pnl += sell(bid, QTY); ntr += 1
                        in_pos = False; next_entry_ts = ts[i] + cooldown_sec; up_cnt = dn_cnt = 0
                        continue
                continue

            # flat
            if ts[i] < next_entry_ts:
                continue
            if ban_last_sec is not None and tleft[i] <= ban_last_sec:
                continue

            if not np.isnan(up_ma_ask[i]) and not np.isnan(up_ma_ask[i - 1]):
                up_cnt = (1 if up_ask[i - 1] <= up_ma_ask[i - 1] else up_cnt + 1) if up_ask[i] > up_ma_ask[i] else 0
            else:
                up_cnt = 0
            if not np.isnan(dn_ma_ask[i]) and not np.isnan(dn_ma_ask[i - 1]):
                dn_cnt = (1 if dn_ask[i - 1] <= dn_ma_ask[i - 1] else dn_cnt + 1) if dn_ask[i] > dn_ma_ask[i] else 0
            else:
                dn_cnt = 0

            best_side = None
            best_ask = 1e9
            if tick_confirm == 0:
                if (not np.isnan(up_ma_ask[i]) and not np.isnan(up_ma_ask[i - 1])
                        and up_ask[i - 1] <= up_ma_ask[i - 1] and up_ask[i] > up_ma_ask[i] and up_ask[i] <= cap):
                    best_side, best_ask = 0, up_ask[i]
                if (not np.isnan(dn_ma_ask[i]) and not np.isnan(dn_ma_ask[i - 1])
                        and dn_ask[i - 1] <= dn_ma_ask[i - 1] and dn_ask[i] > dn_ma_ask[i] and dn_ask[i] <= cap):
                    if dn_ask[i] < best_ask:
                        best_side, best_ask = 1, dn_ask[i]
            else:
                if up_cnt == tick_confirm and up_ask[i] <= cap:
                    best_side, best_ask = 0, up_ask[i]
                if dn_cnt == tick_confirm and dn_ask[i] <= cap:
                    if dn_ask[i] < best_ask:
                        best_side, best_ask = 1, dn_ask[i]

            if best_side is not None:
                in_pos = True
                side = best_side
                entry = best_ask   # calibrated: buys fill at intent ask
                up_cnt = dn_cnt = 0

        # slug end: open position + accumulated dust close at last bid (~resolution)
        if in_pos:
            last_bid = up_bid[-1] if side == 0 else dn_bid[-1]
            pnl += (last_bid - entry) * QTY
            ntr += 1
        if dust_qty_up > 0:
            pnl += dust_qty_up * up_bid[-1]
        if dust_qty_dn > 0:
            pnl += dust_qty_dn * dn_bid[-1]

        per_slug[d["slug"]] = pnl

    return per_slug, ntr


def calc_mdd(pnls):
    eq = peak = mdd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return mdd


# ====== worker globals (populated once per process by _init_worker) ======
_SLUGS = None
_TRAIN = None
_VAL = None


def _init_worker(data_path):
    global _SLUGS, _TRAIN, _VAL
    quotes = pd.read_parquet(data_path)
    _SLUGS = prepare(quotes)
    by_src = quotes.drop_duplicates("slug")[["slug", "source"]]
    _TRAIN = set(by_src.loc[by_src["source"] == "grid_jan_feb", "slug"])
    _VAL = set(by_src.loc[by_src["source"] == "live_mar03", "slug"])


def _score_split(per_slug):
    tr = [per_slug[s] for s in _TRAIN if s in per_slug]
    va = [per_slug[s] for s in _VAL if s in per_slug]
    tr_pnl, va_pnl = float(np.sum(tr)), float(np.sum(va))
    tr_mdd = calc_mdd(tr)
    return tr_pnl, tr_mdd, tr_pnl - 0.5 * abs(tr_mdd), va_pnl


def _eval_combo(job):
    cap, ma, tc, tpsl, cd, ban, haircut = job
    per_slug, ntr = backtest_one(_SLUGS, ma, cap, tc, tpsl, cd, ban, sell_haircut=haircut)
    tr_pnl, tr_mdd, tr_score, va_pnl = _score_split(per_slug)
    return {
        "cap": cap, "ma": ma, "tick_confirm": tc,
        "tp_sl": "none" if tpsl is None else f"{tpsl[0]:.2f}/{tpsl[1]:.2f}",
        "cooldown_sec": cd, "ban_last_sec": "none" if ban is None else ban,
        "haircut": haircut, "trades": ntr,
        "train_pnl": tr_pnl, "train_mdd": tr_mdd, "train_score": tr_score,
        "val_pnl": va_pnl,
    }


def run():
    combos = [(cap, ma, tc, tpsl, cd, ban, SELL_HAIRCUT)
              for cap in CAP_LIST for ma in MA_LIST for tc in TICK_CONFIRM_LIST
              for tpsl in TP_SL_LIST for cd in COOLDOWN_LIST for ban in BAN_LAST_SEC_LIST]
    total = len(combos)
    print(f"grid: {total} combos, workers={WORKERS}, cost model: "
          f"sell_haircut={SELL_HAIRCUT}, dust_frac={DUST_FRAC}", flush=True)

    rows = []
    t0 = time.time()
    with Pool(WORKERS, initializer=_init_worker, initargs=(DATA_PATH,)) as pool:
        for k, row in enumerate(pool.imap_unordered(_eval_combo, combos, chunksize=8), 1):
            rows.append(row)
            if k % 100 == 0 or k == total:
                el = time.time() - t0
                rate = k / el
                eta = (total - k) / rate
                best = max(rows, key=lambda r: r["train_score"])
                print(f"[{k/total*100:5.1f}%] {k}/{total} rate={rate:.1f}/s eta={eta/60:.1f}m "
                      f"| best train_score={best['train_score']:.2f} val={best['val_pnl']:+.2f} "
                      f"(cap={best['cap']} ma={best['ma']} tc={best['tick_confirm']} "
                      f"tp_sl={best['tp_sl']} cd={best['cooldown_sec']} ban={best['ban_last_sec']})",
                      flush=True)

        res = pd.DataFrame(rows)
        res.to_csv("grid_results_realistic.csv", index=False)
        print("\nsaved: grid_results_realistic.csv", flush=True)

        cols = ["cap", "ma", "tick_confirm", "tp_sl", "cooldown_sec", "ban_last_sec",
                "trades", "train_pnl", "train_mdd", "train_score", "val_pnl"]

        print("\n===== TOP 20 by train_score (realistic costs) =====")
        top = res.sort_values("train_score", ascending=False).head(20)
        print(top[cols].to_string(index=False), flush=True)

        print("\n===== OLD frictionless optimum under realistic costs =====")
        o = OLD_OPTIMUM
        old = res[(res["cap"] == o["cap"]) & (res["ma"] == o["ma"])
                  & (res["tick_confirm"] == o["tick_confirm"]) & (res["tp_sl"] == o["tp_sl"])
                  & (res["cooldown_sec"] == o["cooldown_sec"]) & (res["ban_last_sec"] == o["ban_last_sec"])]
        print(old[cols].to_string(index=False))
        rank = int((res["train_score"] > old["train_score"].iloc[0]).sum()) + 1
        print(f"-> rank {rank} / {total}", flush=True)

        # ===== haircut sensitivity for top-N (reuses the same pool) =====
        print(f"\n===== sell_haircut sensitivity (top {TOP_N_SENS} by train_score) =====")
        sens_jobs = []
        sens_meta = []
        for _, r in res.sort_values("train_score", ascending=False).head(TOP_N_SENS).iterrows():
            tpsl = None if r["tp_sl"] == "none" else tuple(float(x) for x in r["tp_sl"].split("/"))
            ban = None if r["ban_last_sec"] == "none" else int(r["ban_last_sec"])
            for hc in HAIRCUT_SENS:
                sens_jobs.append((r["cap"], int(r["ma"]), int(r["tick_confirm"]), tpsl,
                                  int(r["cooldown_sec"]), ban, hc))
                sens_meta.append((r["cap"], int(r["ma"]), int(r["tick_confirm"]), r["tp_sl"],
                                  int(r["cooldown_sec"]), r["ban_last_sec"], hc))

        sens_res = pool.map(_eval_combo, sens_jobs, chunksize=4)
        srows = {}
        for meta, sr in zip(sens_meta, sens_res):
            key = meta[:6]
            srows.setdefault(key, {"cap": key[0], "ma": key[1], "tc": key[2],
                                   "tp_sl": key[3], "cd": key[4], "ban": key[5]})
            srows[key][f"hc{meta[6]}"] = round(sr["train_pnl"] + sr["val_pnl"], 2)  # full-period pnl
        print(pd.DataFrame(list(srows.values())).to_string(index=False), flush=True)


if __name__ == "__main__":
    run()

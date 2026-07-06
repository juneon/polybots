# backtest/backtest.py
"""Grid-search backtest for the MA-breakout strategy over recorded events CSVs.

Run from the backtest/ directory:  python backtest.py
Input:  data/*_events.csv  (events.csv dumps from live/sim runs)
Output: grid_results.csv + top-20 / best-by-MA / best-by-cap summaries

NOTE: this re-implements the MA strategy in vectorized-ish form for grid speed.
If strategies/ma_breakout.py semantics change, keep this file in sync
(entry: ask cross-up through SMA under cap; exit: TP / bid cross-down).
"""
import glob
import json
import time

import numpy as np
import pandas as pd

# ====== grid config ======
EVENT_GLOB = "./data/*_events.csv"
QTY = 10.0

CAP_LIST = [0.5, 0.45, 0.4, 0.35, 0.3]
MA_LIST = [120, 200, 240, 300, 480]
TICK_CONFIRM_LIST = [0, 2, 3]

TP_SL_LIST = [
    None,
    (0.15, 0.05),
    (0.10, 0.10),
    (0.10, 0.05),
]

COOLDOWN_LIST = [0, 30, 60, 90]
BAN_LAST_SEC_LIST = [None, 80, 100]   # entry ban only (no forced exit)

PROGRESS_EVERY = 25


def load_quotes(files):
    rows = []
    for fp in files:
        df = pd.read_csv(fp)
        q = df[df["type"] == "quote"]["data"]
        for s in q:
            d = json.loads(s)
            qt = d["quote"]
            up = qt["up"]
            dn = qt["down"]

            tleft = int(d["time_left_sec"])
            slug_start = int(d["slug_start_ts"])
            tick = int(d["tick"])

            # monotonic time axis (for cooldown)
            ts = slug_start + (900 - tleft) + tick * 1e-3

            rows.append({
                "slug": d["slug"],
                "tick": tick,
                "ts": ts,
                "time_left_sec": tleft,
                "up_bid": float(up["bid"]),
                "up_ask": float(up["ask"]),
                "down_bid": float(dn["bid"]),
                "down_ask": float(dn["ask"]),
            })
    out = pd.DataFrame(rows)
    out.sort_values(["slug", "tick"], inplace=True)
    return out


def calc_mdd(pnls):
    eq = peak = mdd = 0.0
    for p in pnls:
        eq += p
        if eq > peak:
            peak = eq
        dd = eq - peak
        if dd < mdd:
            mdd = dd
    return mdd


def backtest_one(quotes, ma, cap, tick_confirm, tp_sl, cooldown_sec, ban_last_sec):
    g = quotes.copy()
    g["up_ma_ask"] = g.groupby("slug")["up_ask"].transform(lambda x: x.rolling(ma).mean())
    g["dn_ma_ask"] = g.groupby("slug")["down_ask"].transform(lambda x: x.rolling(ma).mean())
    g["up_ma_bid"] = g.groupby("slug")["up_bid"].transform(lambda x: x.rolling(ma).mean())
    g["dn_ma_bid"] = g.groupby("slug")["down_bid"].transform(lambda x: x.rolling(ma).mean())

    pnls = []
    slugs = g.groupby("slug", sort=False)

    tp, sl = tp_sl if tp_sl is not None else (None, None)

    for _, s in slugs:
        s = s.reset_index(drop=True)
        n = len(s)
        if n < 2:
            continue

        ts = s["ts"].to_numpy()
        tleft = s["time_left_sec"].to_numpy()

        up_ask = s["up_ask"].to_numpy()
        dn_ask = s["down_ask"].to_numpy()
        up_bid = s["up_bid"].to_numpy()
        dn_bid = s["down_bid"].to_numpy()

        up_ma_ask = s["up_ma_ask"].to_numpy()
        dn_ma_ask = s["dn_ma_ask"].to_numpy()
        up_ma_bid = s["up_ma_bid"].to_numpy()
        dn_ma_bid = s["dn_ma_bid"].to_numpy()

        in_pos = False
        side = 0
        entry = 0.0
        next_entry_ts = -1e18
        up_cnt = 0
        dn_cnt = 0

        for i in range(1, n):
            if in_pos:
                bid = up_bid[i] if side == 0 else dn_bid[i]

                # TP/SL first
                if tp is not None and bid >= entry + tp:
                    pnls.append((bid - entry) * QTY)
                    in_pos = False
                    next_entry_ts = ts[i] + cooldown_sec
                    up_cnt = dn_cnt = 0
                    continue

                if sl is not None and bid <= entry - sl:
                    pnls.append((bid - entry) * QTY)
                    in_pos = False
                    next_entry_ts = ts[i] + cooldown_sec
                    up_cnt = dn_cnt = 0
                    continue

                # MA cross-down exit (bid-based)
                ma_now = up_ma_bid[i] if side == 0 else dn_ma_bid[i]
                ma_prev = up_ma_bid[i - 1] if side == 0 else dn_ma_bid[i - 1]
                bid_prev = up_bid[i - 1] if side == 0 else dn_bid[i - 1]
                if not np.isnan(ma_now) and not np.isnan(ma_prev):
                    if bid_prev >= ma_prev and bid < ma_now:
                        pnls.append((bid - entry) * QTY)
                        in_pos = False
                        next_entry_ts = ts[i] + cooldown_sec
                        up_cnt = dn_cnt = 0
                        continue

                continue

            # flat: entry allowed?
            if ts[i] < next_entry_ts:
                continue
            if ban_last_sec is not None and tleft[i] <= ban_last_sec:
                continue

            # above-MA streak counters (ask-based)
            if not np.isnan(up_ma_ask[i]) and not np.isnan(up_ma_ask[i - 1]):
                if up_ask[i] > up_ma_ask[i]:
                    up_cnt = 1 if up_ask[i - 1] <= up_ma_ask[i - 1] else up_cnt + 1
                else:
                    up_cnt = 0
            else:
                up_cnt = 0

            if not np.isnan(dn_ma_ask[i]) and not np.isnan(dn_ma_ask[i - 1]):
                if dn_ask[i] > dn_ma_ask[i]:
                    dn_cnt = 1 if dn_ask[i - 1] <= dn_ma_ask[i - 1] else dn_cnt + 1
                else:
                    dn_cnt = 0
            else:
                dn_cnt = 0

            # candidate selection (cheaper ask wins)
            best_side = None
            best_ask = 1e9

            if tick_confirm == 0:
                # crossing tick only
                if (not np.isnan(up_ma_ask[i]) and not np.isnan(up_ma_ask[i - 1])
                        and up_ask[i - 1] <= up_ma_ask[i - 1] and up_ask[i] > up_ma_ask[i] and up_ask[i] <= cap):
                    best_side, best_ask = 0, up_ask[i]

                if (not np.isnan(dn_ma_ask[i]) and not np.isnan(dn_ma_ask[i - 1])
                        and dn_ask[i - 1] <= dn_ma_ask[i - 1] and dn_ask[i] > dn_ma_ask[i] and dn_ask[i] <= cap):
                    if dn_ask[i] < best_ask:
                        best_side, best_ask = 1, dn_ask[i]

            else:
                # N-consecutive confirm
                if up_cnt == tick_confirm and up_ask[i] <= cap:
                    best_side, best_ask = 0, up_ask[i]
                if dn_cnt == tick_confirm and dn_ask[i] <= cap:
                    if dn_ask[i] < best_ask:
                        best_side, best_ask = 1, dn_ask[i]

            if best_side is not None:
                in_pos = True
                side = best_side
                entry = best_ask
                up_cnt = dn_cnt = 0

        # slug end: force close at last bid
        if in_pos:
            last_bid = up_bid[-1] if side == 0 else dn_bid[-1]
            pnls.append((last_bid - entry) * QTY)

    total_pnl = float(np.sum(pnls))
    mdd = float(calc_mdd(pnls))
    return total_pnl, mdd, len(pnls)


def fmt_eta(seconds):
    if seconds < 0 or np.isnan(seconds) or np.isinf(seconds):
        return "?"
    seconds = int(seconds)
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def run_grid():
    files = sorted(glob.glob(EVENT_GLOB))
    if not files:
        raise RuntimeError(f"No files matched: {EVENT_GLOB}")

    quotes = load_quotes(files)

    total = (len(CAP_LIST) * len(MA_LIST) * len(TICK_CONFIRM_LIST)
             * len(TP_SL_LIST) * len(COOLDOWN_LIST) * len(BAN_LAST_SEC_LIST))

    rows = []
    t0 = time.time()
    best = None  # (score, rowdict)
    done = 0

    for cap in CAP_LIST:
        for ma in MA_LIST:
            for tc in TICK_CONFIRM_LIST:
                for tpsl in TP_SL_LIST:
                    for cd in COOLDOWN_LIST:
                        for ban in BAN_LAST_SEC_LIST:
                            pnl, mdd, ntr = backtest_one(quotes, ma, cap, tc, tpsl, cd, ban)
                            score = pnl - 0.5 * abs(mdd)

                            row = {
                                "cap": cap,
                                "ma": ma,
                                "tick_confirm": tc,
                                "tp_sl": "none" if tpsl is None else f"{tpsl[0]:.2f}/{tpsl[1]:.2f}",
                                "cooldown_sec": cd,
                                "ban_last_sec": "none" if ban is None else ban,
                                "trades": ntr,
                                "pnl_usd": pnl,
                                "mdd_usd": mdd,
                                "score": score,
                            }
                            rows.append(row)

                            done += 1
                            if best is None or score > best[0]:
                                best = (score, row)

                            if done % PROGRESS_EVERY == 0 or done == total:
                                elapsed = time.time() - t0
                                rate = done / elapsed if elapsed > 0 else 0.0
                                remain = (total - done) / rate if rate > 0 else float("nan")
                                pct = done / total * 100.0
                                b = best[1]
                                print(
                                    f"[{pct:6.2f}%] {done}/{total}  "
                                    f"elapsed={fmt_eta(elapsed)}  eta={fmt_eta(remain)}  "
                                    f"rate={rate:0.2f} combos/s  "
                                    f"best(score={best[0]:.2f}, pnl={b['pnl_usd']:.2f}, mdd={b['mdd_usd']:.2f}, "
                                    f"cap={b['cap']}, ma={b['ma']}, tc={b['tick_confirm']}, tp_sl={b['tp_sl']}, "
                                    f"cd={b['cooldown_sec']}, ban={b['ban_last_sec']})"
                                )

    res = pd.DataFrame(rows)
    res.to_csv("grid_results.csv", index=False)
    print("\nSaved: grid_results.csv")

    print("\nTop 20 by score:")
    print(res.sort_values("score", ascending=False).head(20).to_string(index=False))

    for key in ("ma", "cap"):
        print(f"\nBest by {key}:")
        cols = ["ma", "cap", "tick_confirm", "tp_sl", "cooldown_sec", "ban_last_sec", "pnl_usd", "mdd_usd", "score"]
        print(res.sort_values("score", ascending=False).groupby(key).head(1)[cols].to_string(index=False))


if __name__ == "__main__":
    run_grid()

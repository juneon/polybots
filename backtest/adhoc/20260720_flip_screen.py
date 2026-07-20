"""Flip screen (2026-07-20): at the moment threshold would enter the favorite,
what is the hold-to-expiry EV of buying the favorite vs buying the OPPOSITE side?

Motivation: the 07-14 calibration study found July-sim favorites overpriced in
every band (-3.3~-6.9pp) -> if that regime effect is real and survives the
spread, the fully inverted play (buy underdog at ask, hold to expiry) should be
+EV on sim and -EV on janfeb. This is a screening study (no stops, one play per
slug); any adoption still requires an engine sweep + D23.

Entry model per slug (first event only):
  favorite side = first side whose ask >= ENTER while 60 <= tleft <= 450,
  after the ask has held >= ENTER for STABLE consecutive seconds (tleft-based).
  FAV  buys favorite at its ask; FLIP buys the other side at its ask.
Settlement = last bid of each side on the complete slug (engine expiry model),
net pnl subtracts 0.01 sell haircut (cost model's sell-side friction).

Run from repo root: python backtest/adhoc/20260720_flip_screen.py
"""
import pandas as pd

DATA = "backtest/data/quotes_all.parquet"
ENTER_LEVELS = [0.85, 0.90]
STABLES = [0, 60]
T_ENTER = 450          # enter only when tleft <= 450 (current config window)
T_FLOOR = 60           # no entries in the last minute
HAIRCUT = 0.01


def src_group(s: str) -> str:
    if s.startswith("sim_"):
        return "sim"
    return {"grid_jan_feb": "janfeb", "live_mar03": "mar03"}.get(s, s)


def first_entry(g: pd.DataFrame, enter: float, stable: int):
    """First (side, row) where side's ask has held >= enter for >= stable sec
    inside the entry window. g is sorted by time_left_sec desc."""
    held_since = {"up": None, "down": None}   # tleft when the hold started
    for r in g.itertuples():
        for side in ("up", "down"):
            ask = r.up_ask if side == "up" else r.down_ask
            if ask >= enter:
                if held_since[side] is None:
                    held_since[side] = r.time_left_sec
                held = held_since[side] - r.time_left_sec
                if T_FLOOR <= r.time_left_sec <= T_ENTER and held >= stable:
                    return side, r
            else:
                held_since[side] = None
    return None, None


def main():
    df = pd.read_parquet(DATA)
    df = df[df["complete"]].copy()
    df["grp"] = df["source"].map(src_group)

    rows = []
    for (grp, slug), g in df.groupby(["grp", "slug"], sort=False):
        g = g.sort_values("time_left_sec", ascending=False)
        last = g.iloc[-1]
        settle = {"up": last["up_bid"], "down": last["down_bid"]}
        for enter in ENTER_LEVELS:
            for stable in STABLES:
                side, r = first_entry(g, enter, stable)
                if side is None:
                    continue
                opp = "down" if side == "up" else "up"
                fav_ask = r.up_ask if side == "up" else r.down_ask
                opp_ask = r.down_ask if side == "up" else r.up_ask
                rows.append({
                    "grp": grp, "slug": slug, "enter": enter, "stable": stable,
                    "fav_pnl": settle[side] - fav_ask - HAIRCUT,
                    "flip_pnl": settle[opp] - opp_ask - HAIRCUT,
                    "opp_ask": opp_ask,
                    "fav_won": settle[side] >= 0.5,
                })

    res = pd.DataFrame(rows)
    if res.empty:
        print("no entries found")
        return

    for (enter, stable), sub in res.groupby(["enter", "stable"]):
        print(f"\n===== enter >= {enter} / stable {stable}s / hold to expiry, "
              f"net of ask spread + {HAIRCUT} haircut (per token $) =====")
        agg = sub.groupby("grp").agg(
            n=("slug", "count"),
            fav_ev=("fav_pnl", "mean"),
            flip_ev=("flip_pnl", "mean"),
            fav_win=("fav_won", "mean"),
            opp_ask=("opp_ask", "mean"),
            flip_se=("flip_pnl", "sem"),
        ).reindex(["janfeb", "mar03", "sim"]).dropna(how="all")
        agg["fav_win"] = (agg["fav_win"] * 100).round(1)
        for c in ("fav_ev", "flip_ev", "opp_ask", "flip_se"):
            agg[c] = agg[c].round(4)
        print(agg.to_string())
        tot = sub.groupby("grp")["flip_pnl"].sum().round(2)
        print("flip total pnl x10tk:", {k: round(v * 10, 1) for k, v in tot.items()})


if __name__ == "__main__":
    main()

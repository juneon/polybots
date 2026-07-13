# backtest/data_prep.py
"""Normalize all recorded events.csv sources into one quotes table (parquet).

Sources (old format: type,slug,tick,ts,data / new format adds run_id):
  - backtest/data/*_events.csv   (Jan-Feb grid-search collection, 7 days)
  - backtest/data/mar03_live.csv (2026-03-03 live session, promoted from archive/
                                  so a fresh clone gets the val set — name must NOT
                                  match the *_events.csv glob above)
  - logs/events.csv              (new monorepo sim runs — split per UTC day so the
                                  engine reports per-day PnL: sim_260712, sim_260713, ...)

Output: backtest/data/quotes_all.parquet
  columns: source, slug, tick, ts, time_left_sec, up_bid, up_ask, down_bid, down_ask
  deduped on (slug, time_left_sec), sorted by (slug, ts).

Time axis: time_left_sec is the only trustworthy clock. tick is a per-run global
counter — two bots recording the same slug, or a restart mid-slug, produce tick
ranges that interleave in the wrong order (found 2026-07-13: 31/34 sim slugs had
a non-monotonic axis under (slug, tick) dedup+sort). ts = slug_start - time_left.

Run from backtest/:  python data_prep.py
"""
import glob
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

SOURCES = [
    ("grid_jan_feb", str(Path(__file__).parent / "data" / "*_events.csv")),
    ("live_mar03", str(Path(__file__).parent / "data" / "mar03_live.csv")),
    ("sim_new", str(ROOT / "logs" / "events.csv")),
]

OUT = Path(__file__).parent / "data" / "quotes_all.parquet"


def _sim_day_source(slug_start: int) -> str:
    """sim_new is split per UTC day of the slug's interval start: sim_260712, ..."""
    return "sim_" + datetime.fromtimestamp(slug_start, tz=timezone.utc).strftime("%y%m%d")


def load_events_file(fp: str, source: str) -> list:
    rows = []
    try:
        df = pd.read_csv(fp)
    except Exception as e:
        print(f"  skip {fp}: {e}")
        return rows
    if "type" not in df.columns or "data" not in df.columns:
        print(f"  skip {fp}: unexpected columns {list(df.columns)}")
        return rows

    for s in df.loc[df["type"] == "quote", "data"]:
        try:
            d = json.loads(s)
            qt = d["quote"]
            up, dn = qt["up"], qt["down"]
            tleft = int(d["time_left_sec"])
            slug_start = int(d["slug_start_ts"])
            tick = int(d["tick"])
            rows.append({
                "source": _sim_day_source(slug_start) if source == "sim_new" else source,
                "slug": d["slug"],
                "tick": tick,
                # monotonic time axis, interval-agnostic (works for 5m/15m/1h markets):
                # consumers only use within-slug deltas (cooldown) and ordering,
                # so anchoring on slug_start - time_left needs no interval constant
                "ts": float(slug_start - tleft),
                "time_left_sec": tleft,
                "up_bid": float(up["bid"]),
                "up_ask": float(up["ask"]),
                "down_bid": float(dn["bid"]),
                "down_ask": float(dn["ask"]),
            })
        except Exception:
            continue  # tolerate malformed rows in raw logs
    return rows


def build() -> pd.DataFrame:
    all_rows = []
    for source, pattern in SOURCES:
        files = sorted(glob.glob(pattern))
        for fp in files:
            rows = load_events_file(fp, source)
            print(f"  {source}: {Path(fp).name} -> {len(rows)} quotes")
            all_rows.extend(rows)

    df = pd.DataFrame(all_rows)
    if df.empty:
        raise RuntimeError("no quotes loaded")

    before = len(df)
    # dedup on the real clock, NOT tick (see module docstring on the time axis)
    df = df.drop_duplicates(subset=["slug", "time_left_sec"], keep="first")
    df = df.sort_values(["slug", "ts"]).reset_index(drop=True)
    print(f"\ntotal {before} -> deduped {len(df)} quotes, {df['slug'].nunique()} slugs")
    print(df.groupby("source").agg(quotes=("slug", "size"), slugs=("slug", "nunique")).to_string())
    return df


if __name__ == "__main__":
    df = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(f"\nsaved: {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")

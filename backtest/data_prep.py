# backtest/data_prep.py
"""Normalize all recorded events.csv sources into one quotes table (parquet).

Sources (old format: type,slug,tick,ts,data / new format adds run_id):
  - backtest/data/*_events.csv   (Jan-Feb grid-search collection, 7 days)
  - backtest/data/mar03_live.csv (2026-03-03 live session, promoted from archive/
                                  so a fresh clone gets the val set — name must NOT
                                  match the *_events.csv glob above)
  - logs/events.csv              (monorepo sim runs up to 2026-07-18 — frozen)
  - logs/events_<YYYYMMDD>.csv   (daily rotation since 2026-07-18, core.logger)
    sim rows are split per UTC day of the slug start so the engine reports
    per-day PnL: sim_260712, sim_260713, ... (independent of the file's date)

Per-file parse cache (2026-07-18): parsed quotes are cached under
backtest/data/cache/ keyed by (mtime, size) — rotation makes past event files
immutable, so only the current day's file is re-parsed on a rebuild.

Output: backtest/data/quotes_all.parquet
  columns: source, slug, tick, ts, time_left_sec, up_bid, up_ask, down_bid, down_ask,
           complete (bool, per slug — see below)
  deduped on (slug, time_left_sec), sorted by (slug, ts).

Slug completeness (2026-07-14): a slug is `complete` when its recording covers
the whole 15-minute game — first quote at time_left >= 870 (observed within 30s
of open), last quote at time_left <= 15 (so the final bid ~= settlement), and no
internal gap > 60s (no mid-slug restart). The engine force-closes open positions
at the last bid as a settlement proxy, which is only truthful for complete
slugs; partial slugs are excluded from backtests by default (engine.prepare_slugs).

Time axis: time_left_sec is the only trustworthy clock. tick is a per-run global
counter — two bots recording the same slug, or a restart mid-slug, produce tick
ranges that interleave in the wrong order (found 2026-07-13: 31/34 sim slugs had
a non-monotonic axis under (slug, tick) dedup+sort). ts = slug_start - time_left.

Run from backtest/:  python data_prep.py
"""
import glob
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

SOURCES = [
    ("grid_jan_feb", str(Path(__file__).parent / "data" / "*_events.csv")),
    ("live_mar03", str(Path(__file__).parent / "data" / "mar03_live.csv")),
    ("sim_new", str(ROOT / "logs" / "events.csv")),
    ("sim_new", str(ROOT / "logs" / "events_*.csv")),   # daily rotation (2026-07-18)
]

OUT = Path(__file__).parent / "data" / "quotes_all.parquet"

CACHE_DIR = Path(__file__).parent / "data" / "cache"    # gitignored
MANIFEST = CACHE_DIR / "manifest.json"
QUOTE_COLS = ["source", "slug", "tick", "ts", "time_left_sec",
              "up_bid", "up_ask", "down_bid", "down_ask"]

# slug completeness rule (thresholds are insensitive: 200/243 slugs qualify
# under (870/15/60), 200-201 under (850/30/60) or (880/10/30) — 2026-07-14)
COMPLETE_FIRST_TLEFT = 870   # recording starts within 30s of slug open
COMPLETE_LAST_TLEFT = 15     # recording reaches within 15s of expiry
COMPLETE_MAX_GAP_SEC = 60    # no mid-slug hole (bot restart) longer than this


def flag_complete(df: pd.DataFrame) -> pd.DataFrame:
    """Add a per-slug `complete` bool column (df must be deduped on time_left)."""
    def _is_complete(t: pd.Series) -> bool:
        t = t.sort_values(ascending=False).to_numpy()
        gap = int((t[:-1] - t[1:]).max()) if len(t) > 1 else 0
        return bool(t[0] >= COMPLETE_FIRST_TLEFT and t[-1] <= COMPLETE_LAST_TLEFT
                    and gap <= COMPLETE_MAX_GAP_SEC)

    ok = df.groupby("slug")["time_left_sec"].apply(_is_complete)
    df["complete"] = df["slug"].map(ok)
    return df


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


def _load_cached(fp: str, source: str) -> pd.DataFrame:
    """Parse one events file through the per-file cache (validated by mtime+size)."""
    st = os.stat(fp)
    key = f"{source}__{Path(fp).name}"
    cache_fp = CACHE_DIR / f"{key}.parquet"

    manifest = {}
    if MANIFEST.exists():
        try:
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}

    ent = manifest.get(key)
    if ent and ent.get("mtime") == st.st_mtime and ent.get("size") == st.st_size and cache_fp.exists():
        return pd.read_parquet(cache_fp)

    df = pd.DataFrame(load_events_file(fp, source), columns=QUOTE_COLS)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_fp, index=False)
    manifest[key] = {"mtime": st.st_mtime, "size": st.st_size}
    MANIFEST.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return df


def build() -> pd.DataFrame:
    frames = []
    for source, pattern in SOURCES:
        files = sorted(glob.glob(pattern))
        for fp in files:
            part = _load_cached(fp, source)
            print(f"  {source}: {Path(fp).name} -> {len(part)} quotes")
            frames.append(part)

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=QUOTE_COLS)
    if df.empty:
        raise RuntimeError("no quotes loaded")

    before = len(df)
    # dedup on the real clock, NOT tick (see module docstring on the time axis)
    df = df.drop_duplicates(subset=["slug", "time_left_sec"], keep="first")
    df = df.sort_values(["slug", "ts"]).reset_index(drop=True)
    df = flag_complete(df)
    print(f"\ntotal {before} -> deduped {len(df)} quotes, {df['slug'].nunique()} slugs")
    per_slug = df.drop_duplicates("slug")
    print(df.groupby("source").agg(quotes=("slug", "size"), slugs=("slug", "nunique"))
            .join(per_slug.groupby("source")["complete"]
                  .agg(complete="sum", partial=lambda s: int((~s).sum()))).to_string())
    n_c = int(per_slug["complete"].sum())
    print(f"complete {n_c} / partial {len(per_slug) - n_c} "
          f"(rule: first tleft>={COMPLETE_FIRST_TLEFT}, last<={COMPLETE_LAST_TLEFT}, "
          f"gap<={COMPLETE_MAX_GAP_SEC}s)")
    return df


if __name__ == "__main__":
    df = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(f"\nsaved: {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")

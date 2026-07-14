# tests/test_data_prep.py
"""Slug completeness flag: a backtest may only settle a slug at its last bid
when the recording actually reaches expiry — partial slugs must be flagged
and excluded by prepare_slugs unless explicitly included."""
import pandas as pd

from data_prep import flag_complete
from engine import prepare_slugs


def quotes(slug, tlefts, source="src"):
    return pd.DataFrame({
        "source": source, "slug": slug, "tick": range(1, len(tlefts) + 1),
        "ts": [1000.0 - t for t in tlefts], "time_left_sec": tlefts,
        "up_bid": 0.5, "up_ask": 0.51, "down_bid": 0.49, "down_ask": 0.5,
    })


def flags(df):
    return df.drop_duplicates("slug").set_index("slug")["complete"].to_dict()


def test_full_coverage_is_complete():
    df = flag_complete(quotes("s1", list(range(895, 4, -1))))
    assert flags(df) == {"s1": True}


def test_late_start_early_end_and_gap_are_partial():
    late = quotes("late", list(range(600, 4, -1)))          # bot joined mid-slug
    early = quotes("early", list(range(895, 300, -1)))      # bot stopped early
    gappy = quotes("gap", list(range(895, 700, -1)) + list(range(500, 4, -1)))  # restart hole
    df = flag_complete(pd.concat([late, early, gappy], ignore_index=True))
    assert flags(df) == {"late": False, "early": False, "gap": False}


def test_prepare_slugs_excludes_partial_by_default():
    df = flag_complete(pd.concat(
        [quotes("full", list(range(895, 4, -1))), quotes("part", list(range(600, 4, -1)))],
        ignore_index=True))
    assert [s for s, _, _ in prepare_slugs(df)] == ["full"]
    assert {s for s, _, _ in prepare_slugs(df, include_partial=True)} == {"full", "part"}


def test_prepare_slugs_tolerates_legacy_parquet_without_flag():
    df = quotes("s1", list(range(600, 4, -1)))   # no `complete` column at all
    assert [s for s, _, _ in prepare_slugs(df)] == ["s1"]

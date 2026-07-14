# tests/test_slug_collection.py
"""SlugCollection: collection progress = COMPLETE slugs (D22), deduped across
strategies, judged from quote rows' time_left coverage — incremental ingest."""
import csv
import json

import pytest

from core.logger import EVENTS_FIELDS
from ui import metrics
from ui.metrics import SlugCollection


def write_events(path, rows, append=False):
    new = not (append and path.exists())
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EVENTS_FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)


def quote_row(slug, tleft, run_id="20260714_000000_threshold_sim", tick=1):
    data = {"type": "quote", "slug": slug, "time_left_sec": tleft, "tick": tick}
    return {"run_id": run_id, "type": "quote", "slug": slug, "tick": tick,
            "ts": "", "data": json.dumps(data, ensure_ascii=False)}


def init_row(slug, run_id="20260714_000000_threshold_sim"):
    return {"run_id": run_id, "type": "slug_init", "slug": slug, "tick": 1,
            "ts": "", "data": "{}"}


def cover(slug, start=899, end=2, step=30, **kw):
    """quote rows covering [start..end] in `step`-second hops (gap = step)."""
    return [quote_row(slug, t, **kw) for t in range(start, end - 1, -step)] + [quote_row(slug, end, **kw)]


def test_complete_and_partial_judgement(tmp_path):
    p = tmp_path / "events.csv"
    write_events(p, [init_row("full"), *cover("full")])                    # complete
    write_events(p, cover("late", start=700), append=True)                 # starts too late
    write_events(p, cover("early", end=120), append=True)                  # ends too early
    write_events(p, [*cover("gapped", end=500), *cover("gapped", start=380)], append=True)  # 120s hole

    col = SlugCollection(path=p)
    got = col.progress()
    assert got["complete"] == 1
    assert got["total"] == 4
    assert got["by_strategy"] == {"threshold": 1}  # only slug_init/slug_change rows count here


def test_dedup_across_strategies_and_runs(tmp_path):
    # two bots record the same slug, each covering half — one complete slug, not two
    p = tmp_path / "events.csv"
    a, b = "20260714_000000_threshold_sim", "20260714_000001_ma_sim"
    write_events(p, [init_row("s", a), init_row("s", b),
                     *cover("s", start=899, end=450, run_id=a),
                     *cover("s", start=470, end=3, run_id=b)])
    got = SlugCollection(path=p).progress()
    assert got == {"complete": 1, "total": 1, "by_strategy": {"ma": 1, "threshold": 1}}


def test_incremental_ingest_updates_judgement(tmp_path):
    p = tmp_path / "events.csv"
    write_events(p, cover("s", start=899, end=500))
    col = SlugCollection(path=p)
    assert col.progress()["complete"] == 0  # not finished yet

    write_events(p, cover("s", start=500, end=4), append=True)
    assert col.progress() == {"complete": 1, "total": 1, "by_strategy": {}}


def test_completeness_rule_matches_data_prep():
    dp = pytest.importorskip("backtest.data_prep")
    assert (metrics.COMPLETE_FIRST_TLEFT, metrics.COMPLETE_LAST_TLEFT, metrics.COMPLETE_MAX_GAP_SEC) == \
           (dp.COMPLETE_FIRST_TLEFT, dp.COMPLETE_LAST_TLEFT, dp.COMPLETE_MAX_GAP_SEC)

# tests/test_configstore.py
"""configstore: whitelist-only editing, value validation, mandatory pre-save
backup (same-second collision-safe), no-op saves touch nothing."""
import json

import pytest

import ui.configstore as cs

SAMPLE = {
    "gamma_base": "https://example.test",
    "event_slug_prefix": "btc-updown-15m",
    "interval_sec": 900,
    "loop_mode": "rolling",
    "max_slugs": 0,
    "strategy": {
        "name": "threshold", "qty_tokens": 10, "take_profit": 0.99,
        "enter_time_left_sec": 450, "max_entries_per_slug": 2,
        "reentry_dd_min": None,
    },
    "execution": {"buy": "market", "slippage": 0.05},
    "logging": {"events": True},
    "account": {"user": "0xabc", "chain_id": 137},
}


@pytest.fixture
def store(tmp_path, monkeypatch):
    configs = tmp_path / "configs"
    configs.mkdir()
    monkeypatch.setattr(cs, "CONFIGS", configs)
    monkeypatch.setattr(cs, "BACKUPS", configs / "backups")
    (configs / "dummy.json").write_text(json.dumps(SAMPLE, indent=2), encoding="utf-8")
    return configs


def saved(store):
    return json.loads((store / "dummy.json").read_text(encoding="utf-8"))


def backups(store):
    b = store / "backups"
    return sorted(p.name for p in b.glob("dummy.*.json")) if b.exists() else []


def test_valid_save_backs_up_and_applies(store):
    res = cs.apply_changes("dummy", {"strategy.take_profit": 0.98, "max_slugs": 5})
    assert res["saved"] is True
    assert {d["path"]: d["new"] for d in res["diff"]} == {"strategy.take_profit": 0.98, "max_slugs": 5}
    assert saved(store)["strategy"]["take_profit"] == 0.98
    assert len(backups(store)) == 1
    # the backup holds the PRE-save content
    backup = json.loads((store / "backups" / backups(store)[0]).read_text(encoding="utf-8"))
    assert backup["strategy"]["take_profit"] == 0.99


def test_noop_save_writes_nothing(store):
    before = (store / "dummy.json").read_text(encoding="utf-8")
    res = cs.apply_changes("dummy", {"strategy.take_profit": 0.99})
    assert res["saved"] is False and res["backup"] is None
    assert (store / "dummy.json").read_text(encoding="utf-8") == before
    assert backups(store) == []


def test_same_second_saves_get_distinct_backups(store):
    cs.apply_changes("dummy", {"strategy.take_profit": 0.98})
    cs.apply_changes("dummy", {"strategy.take_profit": 0.97})
    names = backups(store)
    assert len(names) == 2 and len(set(names)) == 2


@pytest.mark.parametrize("changes", [
    {"account.user": "0xdead"},                 # locked section
    {"gamma_base": "https://evil.test"},        # locked top key
    {"interval_sec": 60},                       # locked top key
    {"strategy.new_key": 1},                    # key must already exist
    {"strategy.qty_tokens": "abc"},             # type mismatch
    {"logging.events": 1},                      # bool field, non-bool value
    {"execution.buy": "stop"},                  # enum violation
    {"strategy.take_profit": 1.5},              # unit-interval range
    {"strategy.qty_tokens": 0},                 # must be positive
    {"strategy.enter_time_left_sec": -1},       # *_sec must be non-negative
    {"strategy.take_profit": None},             # null not allowed on numeric
    {"strategy.max_entries_per_slug": 2.5},     # int field, fractional value
])
def test_rejections_leave_file_untouched(store, changes):
    before = (store / "dummy.json").read_text(encoding="utf-8")
    with pytest.raises(cs.ConfigError):
        cs.apply_changes("dummy", changes)
    assert (store / "dummy.json").read_text(encoding="utf-8") == before
    assert backups(store) == []


def test_int_field_accepts_whole_float(store):
    cs.apply_changes("dummy", {"strategy.max_entries_per_slug": 3.0})
    v = saved(store)["strategy"]["max_entries_per_slug"]
    assert v == 3 and isinstance(v, int)


def test_nullable_field_accepts_number(store):
    cs.apply_changes("dummy", {"strategy.reentry_dd_min": -0.15})
    assert saved(store)["strategy"]["reentry_dd_min"] == -0.15

# tests/test_contracts_and_schema.py
"""core/contracts conformance of all executor/account pairs, and
core/config_schema: the shipped configs must validate; bad values must not."""
import json
from pathlib import Path

from core.account_sim import SimAccount
from core.config_schema import validate_config
from core.contracts import Account, Executor
from core.executor_sim import SimExecutor
from engine import ReplayAccount, ReplayExecutor

ROOT = Path(__file__).resolve().parents[1]


def test_sim_pair_conforms(tmp_path):
    assert isinstance(SimAccount(str(tmp_path / "a.json")), Account)
    assert isinstance(SimExecutor(), Executor)


def test_replay_pair_conforms():
    assert isinstance(ReplayAccount(), Account)
    assert isinstance(ReplayExecutor(), Executor)


def test_shipped_configs_are_valid():
    for p in (ROOT / "configs").glob("*.json"):
        cfg = json.loads(p.read_text(encoding="utf-8"))
        assert validate_config(cfg) == [], f"{p.name} failed validation"


def test_validate_config_catches_bad_values():
    cfg = {
        "interval_sec": 900, "loop_mode": "sideways",          # bad enum
        "strategy": {"cap": 1.5, "qty_tokens": 0,              # range, positive
                     "cooldown_sec": -3},                      # negative *_sec
        "execution": {"buy": "market"},
    }
    errs = validate_config(cfg)
    assert len(errs) == 4
    joined = " / ".join(errs)
    for path in ("loop_mode", "strategy.cap", "strategy.qty_tokens", "strategy.cooldown_sec"):
        assert path in joined

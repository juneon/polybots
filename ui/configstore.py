# ui/configstore.py
"""Config read/validate/backup/write for the UI (Phase C).

Edit model: the client sends {"dotted.path": new_value} changes; the server
applies them onto the current file. Only existing keys in whitelisted
sections are editable — the UI can never add keys, touch account.*, or
change market-structure fields (slug prefix, interval, API bases).

Every effective save first copies the current file to
configs/backups/<name>.<timestamp>.json (kept forever; runtime artifact,
gitignored). Config changes take effect on the next bot start.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ROOT / "configs"
BACKUPS = CONFIGS / "backups"

# editable scope (D14): whitelist, everything else locked
EDITABLE_TOP_SCALARS = {"loop_mode", "run_seconds", "max_slugs", "print_every", "timeout_sec"}
EDITABLE_SECTIONS = ("strategy", "execution", "logging")
LOCKED_TOP_KEYS = ("gamma_base", "clob_base", "event_slug_prefix", "interval_sec", "account")

# value rules by field name (leaf)
UNIT_INTERVAL_FIELDS = {
    "enter_price_1", "enter_price_re", "entry_cap", "stop_drop", "take_profit",
    "cap", "tp_abs", "slippage", "buy_cap", "sell_floor",
}
POSITIVE_FIELDS = {"qty_tokens", "ma_len", "timeout_sec"}
ENUM_FIELDS = {
    "loop_mode": ("one", "rolling", "duration"),
    "buy": ("market", "limit"), "tp": ("market", "limit"),
    "sl": ("market", "limit"), "time": ("market", "limit"),
}


class ConfigError(Exception):
    pass


def config_path(name: str) -> Path:
    return CONFIGS / f"{name}.json"


def load(name: str) -> Dict[str, Any]:
    p = config_path(name)
    if not p.exists():
        raise FileNotFoundError(str(p))
    return json.loads(p.read_text(encoding="utf-8"))


def describe(name: str) -> Dict[str, Any]:
    """Config + editability map for the form renderer."""
    cfg = load(name)
    return {
        "strategy": name,
        "config": cfg,
        "editable_top_scalars": sorted(EDITABLE_TOP_SCALARS & set(cfg)),
        "editable_sections": [s for s in EDITABLE_SECTIONS if s in cfg],
        "locked_keys": [k for k in LOCKED_TOP_KEYS if k in cfg],
        "enums": {k: list(v) for k, v in ENUM_FIELDS.items()},
    }


def apply_changes(name: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    cfg = load(name)
    diff: List[Dict[str, Any]] = []

    for path, new in changes.items():
        parts = str(path).split(".")
        _check_editable(parts)

        parent, leaf = _resolve(cfg, parts, path)
        old = parent[leaf]
        new = _validate_value(leaf, old, new, path)
        if new == old and type(new) is type(old):
            continue  # no-op
        parent[leaf] = new
        diff.append({"path": path, "old": old, "new": new})

    backup = None
    if diff:
        BACKUPS.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup = BACKUPS / f"{name}.{stamp}.json"
        seq = 1
        while backup.exists():  # same-second saves must not clobber earlier backups
            backup = BACKUPS / f"{name}.{stamp}_{seq}.json"
            seq += 1
        shutil.copy2(config_path(name), backup)
        config_path(name).write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {"saved": bool(diff), "diff": diff, "backup": str(backup) if backup else None}


# ---------------------------------------------------------------- internals

def _check_editable(parts: List[str]) -> None:
    if len(parts) == 1 and parts[0] in EDITABLE_TOP_SCALARS:
        return
    if len(parts) == 2 and parts[0] in EDITABLE_SECTIONS:
        return
    raise ConfigError(f"잠긴 항목이거나 편집 불가 경로: {'.'.join(parts)}")


def _resolve(cfg: Dict[str, Any], parts: List[str], path: str):
    parent: Any = cfg
    for key in parts[:-1]:
        parent = parent.get(key) if isinstance(parent, dict) else None
        if parent is None:
            raise ConfigError(f"존재하지 않는 경로: {path}")
    leaf = parts[-1]
    if not isinstance(parent, dict) or leaf not in parent:
        raise ConfigError(f"존재하지 않는 키: {path} (UI로 새 키 추가 불가)")
    return parent, leaf


def _validate_value(leaf: str, old: Any, new: Any, path: str) -> Any:
    # type conformance against the current value
    if isinstance(old, bool):
        if not isinstance(new, bool):
            raise ConfigError(f"{path}: true/false 여야 함")
        return new
    if old is None or isinstance(old, (int, float)):
        if new is None:
            if old is not None:
                raise ConfigError(f"{path}: null 불가 (숫자 필요)")
            return None
        if isinstance(new, bool) or not isinstance(new, (int, float)):
            raise ConfigError(f"{path}: 숫자여야 함 (현재 {new!r})")
        if isinstance(old, int) and isinstance(new, float) and not new.is_integer():
            raise ConfigError(f"{path}: 정수여야 함")
        new = int(new) if isinstance(old, int) and not isinstance(old, bool) else float(new) if isinstance(old, float) else new
        return _check_range(leaf, new, path)
    if isinstance(old, str):
        if not isinstance(new, str) or not new.strip():
            raise ConfigError(f"{path}: 문자열이어야 함")
        new = new.strip()
        if leaf in ENUM_FIELDS and new not in ENUM_FIELDS[leaf]:
            raise ConfigError(f"{path}: {ENUM_FIELDS[leaf]} 중 하나여야 함")
        return new
    raise ConfigError(f"{path}: 편집 불가 타입 ({type(old).__name__})")


def _check_range(leaf: str, v: float, path: str) -> float:
    if leaf in UNIT_INTERVAL_FIELDS and not (0.0 <= v <= 1.0):
        raise ConfigError(f"{path}: 0~1 범위여야 함")
    if leaf in POSITIVE_FIELDS and v <= 0:
        raise ConfigError(f"{path}: 양수여야 함")
    if (leaf.endswith("_sec") or leaf in ("run_seconds", "max_slugs", "print_every",
                                          "max_entries_per_slug", "tick_confirm")) and v < 0:
        raise ConfigError(f"{path}: 음수 불가")
    return v

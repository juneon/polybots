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

# value rules live in core so the runner validates the same schema at startup
from core.config_schema import ConfigError, ENUM_FIELDS, validate_change

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ROOT / "configs"
BACKUPS = CONFIGS / "backups"

# editable scope (D14): whitelist, everything else locked — UI-only policy
EDITABLE_TOP_SCALARS = {"loop_mode", "run_seconds", "max_slugs", "print_every", "timeout_sec"}
EDITABLE_SECTIONS = ("strategy", "execution", "logging")
LOCKED_TOP_KEYS = ("gamma_base", "clob_base", "event_slug_prefix", "interval_sec", "account")


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
        new = validate_change(leaf, old, new, path)
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

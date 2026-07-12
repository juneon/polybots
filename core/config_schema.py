# core/config_schema.py
"""Config value rules — single source for the runner AND the UI editor.

The config file itself is the schema: a value's TYPE must match what is
currently in the file, and its RANGE/ENUM is derived from the field name.
- runner: validate_config(cfg) at startup, so a hand-edited bad config fails
  fast instead of booting a bot with it.
- ui/configstore: validate_change() per edited field (adds type conformance
  against the current value, which the whole-config walk cannot know).
"""
from __future__ import annotations

from typing import Any, Dict, List

# value rules by field name (leaf)
UNIT_INTERVAL_FIELDS = {
    "enter_price_1", "enter_price_re", "entry_cap", "stop_drop", "take_profit",
    "cap", "tp_abs", "slippage", "buy_cap", "sell_floor",
}
POSITIVE_FIELDS = {"qty_tokens", "ma_len", "timeout_sec", "interval_sec"}
NONNEG_FIELDS = {"run_seconds", "max_slugs", "print_every", "max_entries_per_slug", "tick_confirm"}
ENUM_FIELDS = {
    "loop_mode": ("one", "rolling", "duration"),
    "buy": ("market", "limit"), "tp": ("market", "limit"),
    "sl": ("market", "limit"), "time": ("market", "limit"),
}


class ConfigError(Exception):
    pass


def check_value(leaf: str, v: Any, path: str = "") -> None:
    """Name-derived range/enum rules for a single scalar. None/bool pass."""
    path = path or leaf
    if v is None or isinstance(v, bool):
        return
    if isinstance(v, (int, float)):
        if leaf in UNIT_INTERVAL_FIELDS and not (0.0 <= v <= 1.0):
            raise ConfigError(f"{path}: 0~1 범위여야 함")
        if leaf in POSITIVE_FIELDS and v <= 0:
            raise ConfigError(f"{path}: 양수여야 함")
        if (leaf.endswith("_sec") or leaf in NONNEG_FIELDS) and v < 0:
            raise ConfigError(f"{path}: 음수 불가")
    elif isinstance(v, str):
        if leaf in ENUM_FIELDS and v not in ENUM_FIELDS[leaf]:
            raise ConfigError(f"{path}: {ENUM_FIELDS[leaf]} 중 하나여야 함")


def validate_change(leaf: str, old: Any, new: Any, path: str) -> Any:
    """Type conformance against the current value + check_value. Returns the
    (possibly int-coerced) new value. Used by the UI edit flow."""
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
        check_value(leaf, new, path)
        return new
    if isinstance(old, str):
        if not isinstance(new, str) or not new.strip():
            raise ConfigError(f"{path}: 문자열이어야 함")
        new = new.strip()
        check_value(leaf, new, path)
        return new
    raise ConfigError(f"{path}: 편집 불가 타입 ({type(old).__name__})")


def validate_config(cfg: Dict[str, Any]) -> List[str]:
    """Walk the whole config; return all rule violations (empty = valid)."""
    errs: List[str] = []

    def walk(d: Dict[str, Any], prefix: str) -> None:
        for k, v in d.items():
            path = f"{prefix}{k}"
            if isinstance(v, dict):
                walk(v, path + ".")
            else:
                try:
                    check_value(k, v, path)
                except ConfigError as e:
                    errs.append(str(e))

    walk(cfg, "")
    return errs

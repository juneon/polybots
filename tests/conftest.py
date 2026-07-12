# tests/conftest.py
"""Run from anywhere: put the repo root (packages) and backtest/ (flat scripts)
on sys.path, mirroring how they are executed (root `-m` / from backtest/)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "backtest")):
    if p not in sys.path:
        sys.path.insert(0, p)

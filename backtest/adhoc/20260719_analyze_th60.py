# 2026-07-19 sim 60 재판정 — threshold 풀 스윕 D23 판정 분석 (3소스 동시 양수 + R1/R2 이웃)
# 입력: backtest/results/20260719_205030_sweep_threshold.csv (커밋됨)
# 실행: python backtest/adhoc/20260719_analyze_th60.py [csv경로]
import sys
from pathlib import Path

import pandas as pd

DEFAULT = Path(__file__).resolve().parents[1] / "results" / "20260719_205030_sweep_threshold.csv"
CSV = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT)
df = pd.read_csv(CSV)
COLS = ["enter_1", "stop_drop", "take_profit", "entry_cap", "t_enter", "stop_confirm",
        "stable", "score", "janfeb", "mar03", "sim", "val", "W", "L", "fills"]

# 3소스 동시 양수 (janfeb>0 & mar03>0 & sim>0)
tri = df[(df.janfeb > 0) & (df.mar03 > 0) & (df.sim > 0)]
print(f"3소스 동시 양수: {len(tri)}/{len(df)} ({len(tri)/len(df)*100:.1f}%)")
if len(tri):
    print(tri[COLS].sort_values("score", ascending=False).to_string(index=False))

# janfeb>0 & val>0 (동시 양수, ma 그리드와 같은 기준)
both = df[(df.janfeb > 0) & (df.val > 0)]
print(f"\ntrain·val 동시 양수: {len(both)}/{len(df)} ({len(both)/len(df)*100:.1f}%)")
print(both[COLS].sort_values("score", ascending=False).head(15).to_string(index=False))

def neighbors(name, base, axes):
    print(f"\n########## {name}: {base} ##########")
    for axis in axes:
        m = pd.Series(True, index=df.index)
        for k, v in base.items():
            if k != axis:
                m &= df[k] == v
        sub = df[m].sort_values(axis)
        print(f"\n--- {axis} 이웃 ---")
        print(sub[COLS].to_string(index=False))

AXES = ["t_enter", "stop_confirm", "stable", "stop_drop", "enter_1", "entry_cap", "take_profit"]
# R1: score 1위 영역 대표 (기각됨 — 나이프엣지)
neighbors("R1 (score 1위, 기각)", dict(enter_1=0.85, stop_drop=0.10, take_profit=0.99,
                                        entry_cap=0.90, t_enter=180, stop_confirm=30, stable=30), AXES)
# R2: 채택 콤보 (configs/threshold.json 2026-07-19 반영분)
neighbors("R2 (채택)", dict(enter_1=0.90, stop_drop=0.12, take_profit=0.98,
                             entry_cap=0.90, t_enter=450, stop_confirm=30, stable=60), AXES)

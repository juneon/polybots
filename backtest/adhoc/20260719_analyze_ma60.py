# 2026-07-19 sim 60 재판정 — ma 부분 그리드 D23 ③ 판정 분석 (후보 A/B 이웃 안정성)
# 입력: backtest/results/20260719_205628_grid_ma_partial60.csv (커밋됨)
# 실행: python backtest/adhoc/20260719_analyze_ma60.py [csv경로]
import sys
from pathlib import Path

import pandas as pd

DEFAULT = Path(__file__).resolve().parents[1] / "results" / "20260719_205628_grid_ma_partial60.csv"
CSV = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT)
df = pd.read_csv(CSV)
COLS = ["cap", "ma_len", "tick_confirm", "tp_abs", "cooldown_sec", "entry_slope_max",
        "trades", "train_score", "mar03_pnl", "sim_pnl", "val_pnl"]

def show(title, sub):
    print(f"\n===== {title} =====")
    print(sub[COLS].sort_values("train_score", ascending=False).to_string(index=False))

A = dict(cap=0.5, ma_len=300, tick_confirm=0, tp_abs="none", cooldown_sec=0, entry_slope_max="-0.005")
B = dict(cap=0.5, ma_len=300, tick_confirm=0, tp_abs="0.98", cooldown_sec=0, entry_slope_max="-0.005")

df["tp_abs"] = df["tp_abs"].astype(str)
df["entry_slope_max"] = df["entry_slope_max"].astype(str)

def sel(base, vary):
    m = pd.Series(True, index=df.index)
    for k, v in base.items():
        if k == vary:
            continue
        m &= df[k].astype(str) == str(v)
    return df[m]

for name, cand in (("A", A), ("B", B)):
    print(f"\n########## 후보 {name}: {cand} ##########")
    for axis in ("ma_len", "cap", "entry_slope_max", "cooldown_sec", "tp_abs", "tick_confirm"):
        show(f"{name} — {axis} 이웃", sel(cand, axis))

# 등록 후보 영역(cap0.5~0.6 / ma300 / tc0~2 / cd0 / slope -0.005~-0.01) val 부호 지도
region = df[(df.cap.isin([0.5, 0.6])) & (df.ma_len == 300) & (df.cooldown_sec == 0)
            & (df.entry_slope_max.isin(["-0.005", "-0.01"]))]
print("\n===== 등록 후보 영역 전체 (val 부호 확인) =====")
print(region[COLS].sort_values("val_pnl", ascending=False).to_string(index=False))
pos = (region.val_pnl > 0).sum()
print(f"\n영역 내 val>0: {pos}/{len(region)}  |  train>0: {(region.train_score > 0).sum()}/{len(region)}")

# 2026-07-19 sim 60 재판정 — ma 후보 영역 부분 그리드 (WORKLOG 07-19 엔트리의 원 실행 스크립트)
# 후보 영역(cap0.5~0.6/ma300/tc0~2/cd0/slope−0.005~−0.01)
# + D23 ③(plateau) 판정용 이웃 축(cap 0.45/0.7, ma 240/480, cd 30, slope none/0)
# run_grid.py의 엔진/체크포인트/감도 기계를 그대로 재사용하고 GRID만 축소.
#
# 실행: python backtest/adhoc/20260719_ma_partial_grid.py --workers 8
# 산출(당시): backtest/results/20260719_205628_grid_ma_partial60.{csv,json}
import argparse
import os
import sys
import time
from pathlib import Path

BACKTEST = Path(__file__).resolve().parents[1]  # backtest/
sys.path.insert(0, str(BACKTEST))
os.chdir(BACKTEST)

import run_grid

run_grid.GRID = {
    "cap": [0.45, 0.5, 0.6, 0.7],
    "ma_len": [240, 300, 480],
    "tick_confirm": [0, 2],
    "tp_abs": [None, 0.98, 0.99],
    "cooldown_sec": [0, 30],
    "no_entry_last_sec": [None],
    "entry_slope_max": [None, 0, -0.005, -0.01],
}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    args_in = ap.parse_args()

    ts = time.strftime("%Y%m%d_%H%M%S")
    args = argparse.Namespace(
        data=run_grid.DATA_PATH,
        out=f"results/{ts}_grid_ma_partial60.csv",
        haircut=0.01, pfail=0.2, seed=42,
        workers=args_in.workers, quick=False, include_partial=False,
        json=f"results/{ts}_grid_ma_partial60.json",
    )
    run_grid.run(args)

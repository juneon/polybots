# backtest — 백테스트 환경

전략 개발 → 검증 → config 반영의 표준 파이프라인. **모든 결과는 비용 반영(realistic) 기준으로 판단한다.**

## 파이프라인

```
① 데이터 수집     운영/sim 실행 시 logging.events=true → logs/events.csv 축적
② 데이터 통합     python data_prep.py
                  → 모든 소스를 data/quotes_all.parquet로 정규화 (slug,tick 중복 제거)
③ 폭넓은 탐색     python run_grid.py            (ma_breakout 벡터화 그리드, 3,600조합)
                  python sweep_threshold.py     (threshold 엔진 스윕)
④ 정밀 검증       python engine.py --strategy <name> --set key=val ...
                  → 실제 strategies/ 코드를 그대로 리플레이 (래치/재시도 포함)
⑤ 반영            검증 통과 파라미터만 configs/<name>.json에 반영 → sim 재검증 → (최후) live
```

## 비용 모델 (2026-03-03 라이브 122건 체결로 캘리브레이션)

| 항목 | 실측 | 모델 기본값 |
|---|---|---|
| 매수 슬리피지 | 평균 ≈ 0 (intent ask 그대로 체결) | 0 |
| 매도 헤어컷 | 평균 +0.44c, 중앙값 +0.9c, p90 +3c | `haircut=0.01` |
| 매도 시도 실패율 | 22.1% (재시도로 회복) | `p_fail=0.2` |
| dust 미체결 | 왕복당 ~1.3% 수량 | `dust_frac=0.013` (grid만) |

## 검증 규칙

- **train/val 분리**: 1~2월(189 slugs)로 선정, 3/3 라이브(18 slugs)로 out-of-sample 확인.
  val이 음수인 조합은 train 점수가 높아도 탈락.
- 엔진 신뢰도 근거: 3/3 데이터 리플레이 −$29.92 ≈ 실거래 −$27.30 (2026-07-07 검증).
- 무비용 백테스트 수치는 참고용으로만 (구 grid_results.csv가 그 산물 — cap0.5/ma300이
  +$81.66이었지만 비용 반영 시 전 기간 −$5.18로 붕괴한 전례).

## 파일

| 파일 | 역할 |
|---|---|
| `data_prep.py` | 이벤트 CSV들 → `data/quotes_all.parquet` 통합 |
| `run_grid.py` | ma_breakout 현실화 그리드 (train/val 분리, 헤어컷 민감도) |
| `sweep_threshold.py` | threshold 엔진 기반 파라미터 스윕 |
| `engine.py` | 정밀 리플레이 (실제 전략 클래스 + 비용/실패 모델). import 가능: `from engine import replay` |
| `backtest.py` | (구) 무비용 벡터화 그리드 — 참고용 |
| `data/` | 원본 이벤트 CSV + 통합 parquet (gitignore) |

## 새 전략 백테스트 추가

1. `strategies/<이름>.py` 구현 + REGISTRY 등록 (CLAUDE.md 참조)
2. `engine.py --strategy <이름>`은 바로 동작 (전략 코드 재사용이므로 별도 작업 불필요)
3. 파라미터 스윕이 필요하면 `sweep_threshold.py`를 복제해 축만 교체

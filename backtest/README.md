# backtest — 백테스트 환경

전략 개발 → 검증 → config 반영의 표준 파이프라인. **모든 결과는 비용 반영(realistic) 기준으로 판단한다.**

## 파이프라인

```
① 데이터 수집     운영/sim 실행 시 logging.events=true → logs/events.csv 축적
② 데이터 통합     python data_prep.py
                  → 모든 소스를 data/quotes_all.parquet로 정규화
                  (시간축은 time_left_sec — tick은 run 전역 카운터라 다중 run/재시작 시
                   순서가 깨짐(2026-07-13). dedup·정렬 모두 time_left 기준.
                   sim 수집분은 UTC 일자별 소스로 분리: sim_260712, sim_260713, ...)
                  slug별 완전성 플래그(2026-07-14): complete = 시작 tleft≥870 ∧ 종료 tleft≤15
                   ∧ 내부 갭≤60s. 엔진의 만기 강제청산은 완전 slug에서만 참 →
                   ③④는 기본 complete-only, --include-partial로만 미완성 포함
③ 폭넓은 탐색     python run_grid.py            (ma 그리드, 3,600조합 — 엔진 fan-out)
                  python sweep_threshold.py     (threshold 스윕 — 엔진 직접 호출)
④ 정밀 검증       python engine.py --strategy <name> --set key=val ...

  ③④ 모두 같은 engine.replay — 실제 strategies/ 코드를 그대로 리플레이 (래치/재시도 포함).
  전략 로직 재구현 없음: 전략 코드가 바뀌면 그리드/스윕 결과도 자동으로 따라간다.
  모든 스크립트가 --json <path>로 기계가 읽을 요약을 출력 (UI Backtest 탭용).
⑤ 반영            검증 통과 파라미터만 configs/<name>.json에 반영 → sim 재검증 → (최후) live
```

## 비용 모델 (2026-03-03 라이브 122건 체결로 캘리브레이션)

| 항목 | 실측 | 모델 기본값 |
|---|---|---|
| 매수 슬리피지 | 평균 ≈ 0 (intent ask 그대로 체결) | 0 |
| 매도 헤어컷 | 평균 +0.44c, 중앙값 +0.9c, p90 +3c | `haircut=0.01` |
| 매도 시도 실패율 | 22.1% (재시도로 회복) | `p_fail=0.2` |

## 검증 규칙

- **train/val 분리**: 1~2월(완전 161 slugs)로 선정, 3/3 라이브 + sim 수집분으로 out-of-sample 확인.
  val이 음수인 조합은 train 점수가 높아도 탈락.
- **robust 3중 기준 (2026-07-14, config 반영 조건)**: ① train 점수 상위 ② val ≥ 0
  ③ 이웃 안정성 — 인접 조합(각 축 ±1스텝)이 급락하지 않을 것 (스파이크 최적값 배제).
  셋 다 만족해야 configs/ 반영. 미달이면 현행 유지 + 사유를 WORKLOG에 기록.
- 엔진 신뢰도 근거: 3/3 데이터 리플레이 −$29.92 ≈ 실거래 −$27.30 (2026-07-07 검증).
- 무비용 백테스트 수치는 참고용으로만 (구 grid_results.csv가 그 산물 — cap0.5/ma300이
  +$81.66이었지만 비용 반영 시 전 기간 −$5.18로 붕괴한 전례).

## 파일

| 파일 | 역할 |
|---|---|
| `engine.py` | 유일한 백테스트 엔진 — 실제 전략 클래스 리플레이 + 비용/실패 모델. `from engine import replay, prepare_slugs` (prepare_slugs가 완전성 필터 담당) |
| `data_prep.py` | 이벤트 CSV들 → `data/quotes_all.parquet` 통합 + slug 완전성 플래그 |
| `run_grid.py` | ma 그리드 = engine.replay를 프로세스풀로 fan-out (train/val 분리, 헤어컷 민감도, `--quick` 스모크) |
| `sweep_threshold.py` | threshold 스윕 = engine.replay 직접 호출 |
| `data/` | 원본 이벤트 CSV(git 추적: `*_events.csv` = 1~2월 그리드, `mar03_live.csv` = 3/3 라이브 승격본) + 통합 parquet(gitignore, 재생성 가능) |

> `backtest.py`(무비용 벡터화 그리드)는 2026-07-12 폐기 — MA 로직을 재구현해 전략 코드와
> sync가 필요했고, 실전략이 지원하지 않는 상대 tp/sl 축을 탐색했다. 필요 시 git 이력 참조.

## 새 전략 백테스트 추가

1. `strategies/<이름>.py` 구현 + REGISTRY 등록 (CLAUDE.md 참조)
2. `engine.py --strategy <이름>`은 바로 동작 (전략 코드 재사용이므로 별도 작업 불필요)
3. 파라미터 스윕이 필요하면 `sweep_threshold.py`를 복제해 축만 교체

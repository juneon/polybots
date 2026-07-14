# polybots

Polymarket BTC 15분 Up/Down 마켓 자동매매 봇. 공유 코어 엔진(`core/`) + 전략 플러그인(`strategies/`) 구조.

## 구조

```
core/         공유 엔진 — adapter, slug_loop, executor(sim/live), account(sim/live), logger, printer, runner
strategies/   전략 플러그인 — 1 전략 = 1 모듈. base.py의 BaseStrategy 인터페이스 구현
configs/      전략별 설정 — configs/<전략이름>.json
backtest/     백테스트 — engine.py(실전략 리플레이)가 유일한 엔진, 그리드/스윕은 그 fan-out
tests/        pytest 단위 테스트 — 전략/계좌/로거/집계/설정 검증 (python -m pytest tests/)
logs/         런타임 CSV 로그 (append + run_id) — csv는 git track(수집 자산), ctl/은 머신 로컬
state/        런타임 상태 파일 — sim 계좌 등 (gitignore)
reports/      작업 단위 보고서 HTML (git track) — <YYYYMMDD>_<주제>_{plan|result}.html
SPEC.md       아키텍처/스키마/전략 규칙 명세 (수정 시 함께 갱신할 것)
WORKLOG.md    결정·진행·로드맵의 단일 기록처 — 세션 재개는 여기부터
DOCS.md       문서 맵 — 문서는 5개가 전부. 새 .md 만들기 전에 볼 것

archive/      리팩토링 이전 레거시 3폴더 (읽기 전용, 각자 git) — 새 작업 금지
```

## 실행

```
python -m core.runner --strategy ma        --mode sim       # 시뮬레이션 (기본)
python -m core.runner --strategy threshold --mode sim
python -m core.runner --strategy ma        --mode live      # 실거래 ⚠️
```

- 루트(`polybots/`)에서 실행할 것 (모듈 경로 기준).
- `--mode` 기본값은 `sim`. config로는 live가 켜지지 않음 — CLI 플래그만이 live를 결정.

## ⚠️ 안전 규칙 (절대 준수)

1. **`--mode live`를 사용자 명시 요청 없이 절대 실행하지 말 것.** live는 실제 지갑으로 실주문을 낸다.
2. **`.env`는 지갑 개인키를 담고 있다.** 절대 읽거나, 출력하거나, 커밋하거나, 외부로 전송하지 말 것. (.gitignore에 등록됨)
3. `configs/*.json`의 `account.user`는 공개 지갑 주소(민감도 낮음)지만, 변경 시 사용자 확인 필요.
4. 전략 로직/executor 수정 후에는 반드시 sim 모드로 먼저 검증.

## 핵심 불변식 (수정 시 유지할 것)

- **단방향 스트림**: source(slug_loop) → decision(strategy) → execute(executor) → SOT(account) → sink(logger/printer)
- **Account가 단일 진실(SOT)**: 포지션 진실은 account.position. 전략은 이를 읽기만 하고, 자체 포지션을 낙관적으로 설정하지 않는다.
- **체결 피드백은 on_trade로**: 전략 내부 카운터/락/쿨다운은 `on_trade(trade)`에서 status="filled" 확인 후에만 갱신.
- **Executor는 무상태**, Strategy는 체결에 관여하지 않는다.
- 시간 판단은 `time_left_sec` 기준 (wall-clock `ts`는 로그용).

## 새 전략 추가

1. `strategies/<이름>.py`에 `BaseStrategy` 상속 클래스 작성 (`on_event`, `on_trade`, `debug_state`)
2. `strategies/__init__.py`의 `REGISTRY`에 등록
3. `configs/<이름>.json` 작성
4. `SPEC.md`에 전략 규칙 문서화
5. sim 모드로 검증 후 사용

## 의존성

`requests`, `numpy`, `pandas` (backtest), live 모드 추가: `py_clob_client`, `python-dotenv`, 테스트: `pytest`

## 테스트

전략 로직/executor/account/ui 집계 수정 후에는 `python -m pytest tests/ -q` (루트에서, 5초 이내). 새 전략을 추가하면 tests/에 전략 테스트도 추가할 것.

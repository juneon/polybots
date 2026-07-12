# WORKLOG — Control UI 프로젝트 진행/결정 기록

> 이 파일이 **결정사항과 진행 내역의 단일 기록처**다. 세션이 바뀌어도 여기서 이어서 읽으면 된다.
> 전체 계획 원문과 프로젝트 현황은 `REPORT.html`, 아키텍처 명세는 `SPEC.md`.

---

## 프로젝트: Total Control UI

**목표**: 봇 시작/정지, 전략 선택, config 편집, 수익률 조회, 백테스트 실행/비교를 한 화면에서.

### 확정된 결정 (2026-07-11, 사용자 승인)

| # | 결정 | 선택지 중 | 이유 |
|---|---|---|---|
| D1 | **로컬 웹 대시보드** (FastAPI, `127.0.0.1:8787` 전용) | 웹 / TUI / 웹+CLI | 표·차트·config 폼·백테스트 비교에 유리. 로컬 서빙이라 난이도 낮음. 외부 노출 없음 |
| D2 | **live(real) 버튼은 마지막 Phase E에서** 이중확인 가드와 함께 | 처음부터 / 마지막 / 제외 | 로드맵의 live 재개 기준(sim 30 slugs + 백테스트 유지 + P2)과 일치. 그 전까지 서버가 live 요청을 403으로 거부 |
| D3 | 백테스트 탭은 **실행 + 결과 조회** 둘 다 | 실행+조회 / 조회만 | "수집→재평가→config 반영" 사이클을 UI 안에서 완결 |
| D4 | 봇은 **별도 프로세스** 유지, UI 서버는 프로세스 매니저 역할 | (설계) | 크래시 격리. UI가 죽어도 봇 생존, 역도 성립 |
| D5 | 프로세스 제어는 **파일 기반** (stop-file + heartbeat JSON) | (설계) | Windows에서 subprocess로 Ctrl-C 전달이 불안정. 파일 방식이 확실 |
| D6 | 프런트는 **바닐라 HTML/JS 단일 파일**, 차트는 인라인 SVG | (설계) | 빌드 도구/CDN 없음 → 오프라인 동작, 유지보수 단순 |
| D7 | **sim 계좌 파일을 전략별 분리**: `sim_account_<strategy>.json` | (설계) | 기존 단일 `sim_account.json` 공유 시 두 전략 동시 sim에서 잔고 섞임 |
| D8 | UI 집계는 trades/snapshots만 사용, events.csv는 slug 수집 게이지(증분 읽기)만 | (설계) | events.csv는 계속 커지는 백테스트용 원본 |

### Phase 계획

- **Phase A — 골격 + Control 탭** ✅ 완료 (2026-07-11)
  - core: stop-file 체크 + heartbeat 기록 (`core/control.py`), `--run-id` 인자, sim 계좌 전략별 분리
  - ui: `server.py`(FastAPI) + `procman.py`(시작/정지/상태) + `static/index.html`(Control 탭)
  - 기능: 전략 선택, sim 시작/정지, 실행 상태 카드(heartbeat), slug 수집 게이지(n/30), 전체 정지
- **Phase B — Performance 탭** ✅ 완료 (2026-07-11): `ui/metrics.py` — 전략/run/slug별 실현 PnL, equity curve, 계좌 잔고, run 히스토리
- **Phase C — Config 탭** ✅ 완료 (2026-07-11): 스키마 기반 폼 + 검증 + `configs/backups/` 자동 백업 + diff. `account.*` 잠금
- **Phase D — Backtest 탭** ✅ 완료 (2026-07-12): `ui/jobs.py` — data_prep/engine/sweep/grid 백그라운드 실행 + 진행률 + 결과 아카이브(`backtest/results/`) 비교
- **Phase E — live + 마감**: live 시작 3단계 가드(모드 선택→확인 문구 타이핑→config 요약), kill switch 정식화, 로그 뷰어

### 안전 원칙 (전 Phase)

- 서버는 `127.0.0.1` 바인딩만. `.env`는 서버 코드에서 절대 읽지 않음
- Phase E 이전: 서버가 `mode != "sim"` 시작 요청을 거부 (UI에도 real 비활성)
- config 저장은 화이트리스트 필드만 + 저장 전 백업
- **UI가 있어도 live 실제 재개 기준은 불변**: sim 30 slugs 무결 + 현실화 백테스트 기대값 유지 + P2 실행품질 완료

### 미결/열린 항목

- [ ] live 정지 시 포지션 flatten 옵션 (Phase E에서 설계 — P2 실행품질과 연계)
- [ ] slug 수집 게이지의 목표치 30은 STATUS.md 기준 하드코딩 — config화 여부는 나중에
- [ ] 서버 재시작 시 events.csv 전체 재스캔 (현재 ~1.3MB로 무시 가능, 커지면 오프셋 캐시 파일 고려)

---

## 진행 로그

### 2026-07-11 — 세션 시작, 계획 수립 + Phase A 완료

- REPORT.html을 "진행 현황 리포트"로 갱신 (재개 가이드 + 단계 현황판 + 전략 현황판 추가)
- Control UI 계획 수립, 사용자 승인 (결정 D1~D3)

**Phase A 구현 완료** — 실행: `python -m ui.server` → http://127.0.0.1:8787

| 파일 | 내용 |
|---|---|
| `core/control.py` (신규) | `RunControl` — stop-file 감지 + heartbeat 원자적 기록(tmp→replace). CLI 단독 실행에도 무해 |
| `core/runner.py` (수정) | `--run-id` 인자 추가(UI가 ctl 파일 주소 지정용) · 매 tick stop 체크 + heartbeat · **sim 계좌 `sim_account_<strategy>.json`으로 분리(D7)** · 종료 시 최종 heartbeat(state=stopped, stop_reason) |
| `ui/procman.py` (신규) | 전략당 1프로세스 시작/정지/상태. 정지 = stop-file → 15초 대기 → terminate 폴백. 외부(터미널) 실행 봇도 heartbeat로 감지해 "외부 실행" 표시 |
| `ui/metrics.py` (신규) | slug 수집 카운터 — events.csv를 바이트 오프셋 증분 파싱(D8). Phase B에서 PnL 집계 추가 예정 |
| `ui/server.py` (신규) | FastAPI, 127.0.0.1:8787 고정. `/api/status`(2초 폴링), `/api/bot/start|stop|stop_all`, `/api/strategies`. **mode≠sim 요청은 403 (D2 가드)** |
| `ui/static/index.html` (신규) | 탭 4개(Control 동작, 나머지 placeholder). 봇 카드(상태/포지션/cash/남은시간) · 수집 게이지(n/30) · 전체 정지 버튼. live 옵션은 select에서 disabled |
| `.gitignore` | `sim_account*.json`으로 확대 (전략별 계좌 파일 커버) |
| `requirements.txt` | fastapi, uvicorn 추가 |

**검증 (전부 통과)**:
- 신규/수정 모듈 py_compile 통과
- SlugCollection이 기존 events.csv에서 threshold 3 slugs 산출 — 지난 세션 커밋 기록과 일치 (증분 재호출도 동일값)
- E2E: API로 threshold sim 시작 → heartbeat에 slug/tick/포지션(down 10tk @0.87 진입 발생)/cash 실시간 반영 → 수집 게이지 3→4 증분 → API 정지 → **forced=false, returncode=0** (그레이스풀), 최종 heartbeat `stopped/stop_requested`
- live 가드: `{"mode":"live"}` 시작 요청 → 403 거부 확인

**메모**:
- sim 정지 시 열린 포지션은 계좌 파일에 남음 — 다음 실행에서 같은 전략이 만기 강제청산으로 자연 해소 (기존 동작과 동일, live는 Phase E에서 flatten 설계)
- `AGENTS.md`는 IDE가 CLAUDE.md를 자동 미러링한 파일 — 커밋 제외

### 2026-07-11 (같은 세션) — Phase B 완료: Performance 탭

**추가 결정**:

| # | 결정 | 이유 |
|---|---|---|
| D9 | PnL 집계는 **(전략, 모드) 단위로 분리** — sim과 live 성과를 절대 합산하지 않음 | run_id 접미사(_sim/_live)로 구분. live 재개 시 sim 수치와 섞이면 판단 오염 |
| D10 | "실현 PnL"의 정의 = **청산 완료 slug**(잔량 ≤ dust 0.011tk)의 (매도대금 − 매수비용) 합. 미청산 slug는 합계에서 제외하고 별도 표시 | 부분 데이터로 수익률이 왜곡되지 않게. 만기 정산(0/1)은 기록에 없으므로 추정하지 않음 |
| D11 | equity curve는 **체결 기준 누적 현금흐름** (매수 −, 매도 +) | account.cash와 정의가 일치, 보유 중 낙폭도 보임. 미실현 평가손익은 스냅샷 기반이라 Phase B 범위 밖 |
| D12 | trades.csv는 작으므로(체결만 기록) 전체 재파싱 + mtime/size 캐시. events.csv 증분 방식(D8)과 구분 | 단순함 우선. equity는 500포인트 초과 시 다운샘플 |

**구현**:
- `ui/metrics.py` + `PerfReport` — (전략,모드)별: 실현 PnL/오늘/slug 승패/체결 수/평균 진입→청산가/미청산 잔량, run 히스토리(최근 20), slug별 결과(최근 30), equity 시계열, sim 계좌 파일(cash/position) 첨부
- `ui/server.py` + `GET /api/perf`
- `index.html` Performance 탭 — 그룹별 스탯 타일 + equity 라인차트(인라인 SVG, hover 툴팁+마커, $0 기준선, 라이트/다크 대비 3:1 검증 통과) + run/slug 테이블(차트의 데이터 테이블 뷰 겸용). 탭 활성 시 로드, 10초 갱신

**검증**: `/api/perf`가 기존 실데이터를 정확 집계 — ma_breakout sim 실현 −$2.40(2 slug 청산, 12체결), threshold sim −$0.80(1청산) + 오늘 스모크의 미청산 slug 1개(10tk)를 정확히 분리 감지. 프런트 JS는 node --check 통과, 페이지 200 OK.

**다음 작업**: **Phase C (Config 탭)** — 스키마 기반 폼 + 검증 + 백업/diff + account 잠금

### 2026-07-11 (같은 세션) — Phase C 완료: Config 탭

**추가 결정**:

| # | 결정 | 이유 |
|---|---|---|
| D13 | 편집 모델 = 클라이언트가 `{"dotted.path": 값}` 변경분만 전송, 서버가 현재 파일 위에 적용. **UI로 새 키 추가 불가, 존재하는 키만 수정** | 파일 전체 교체 방식보다 안전 — 검증·diff가 경로 단위로 명확 |
| D14 | 잠금 목록: `account.*`, `gamma_base`, `clob_base`, `event_slug_prefix`, `interval_sec`. 편집 가능: `strategy.*`, `execution.*`, `logging.*` + 루프 스칼라(loop_mode/run_seconds/max_slugs/print_every/timeout_sec) | account는 CLAUDE.md 규칙(변경 시 사용자 확인), 나머지는 마켓 구조 상수 |
| D15 | 저장 전 무조건 백업 `configs/backups/<이름>.<타임스탬프>.json`, 전부 보존(로테이션 없음), gitignore | config는 작고 이력 가치가 큼 |
| D16 | 값 검증 = 현재 값과 타입 일치 + 이름 기반 규칙: 가격류(0~1) / 양수(qty_tokens, ma_len) / 비음수(*_sec 등) / enum(loop_mode, 집행 방식 market·limit). nullable은 현재 null인 필드만 | 스키마 파일 별도 관리 없이 config 자체가 스키마 역할 |

**구현**: `ui/configstore.py` (검증/백업/diff) + `GET·PUT /api/config/<전략>` + Config 탭 폼(타입별 입력: checkbox/select/number/text, 변경 행 하이라이트, 저장 전 diff 미리보기, 실행 중이면 "재시작 필요" 배너, 잠긴 항목 읽기전용 표시)

**검증 (전부 통과)**: 유효 저장→파일 반영+백업 생성→되돌리기 / 같은 초 이중 저장 시 백업 파일명 충돌 버그 발견→`_1` 시퀀스로 수정 / 거부 6종(잠긴 경로·범위 초과·미존재 키·타입 불일치·enum 위반·양수 위반) 전부 400 / no-op 저장은 파일 안 씀

**메모**:
- UI로 저장하면 JSON 서식이 정규화됨(원본의 구분용 빈 줄 사라짐, indent 2 유지) — 값은 보존되므로 허용. 테스트로 발생한 서식 변화는 git checkout으로 원복함
- config는 봇 시작 시 1회 로드 → 저장해도 실행 중인 봇에는 미반영(UI가 배너로 경고)

**다음 작업**: **Phase D (Backtest 탭)** — `ui/jobs.py` 백그라운드 실행 + 진행률 + 결과 아카이브 비교

---

### 2026-07-11 — 세션 종료 기록: Phase D/E 상세 스펙 + 재개 순서

> 사용자 요청으로 미착수 Phase의 설계를 상세히 남김. 다음 세션은 여기서 이어서 시작.

#### Phase D — Backtest 탭 (미착수, 설계 확정)

목적: **"수집 → 재평가 → config 반영" 사이클을 UI 안에서 완결** (지금은 터미널에서 수동).

- **백엔드 `ui/jobs.py`** (신규):
  - job 1개 = backtest 스크립트 subprocess 1개. 종류: `data_prep` / `engine --strategy X` / `sweep_threshold` / `run_grid`
  - 상태 queued → running → done|failed. stdout은 `logs/ctl/bt_<job_id>.log`로 캡처, UI가 tail 폴링
  - **동시 실행 1개 제한** — run_grid는 자체가 10워커 병렬이라 겹치면 머신이 죽음
  - 완료 시 결과를 `backtest/results/<ts>_<kind>_<strategy>.json`으로 아카이브 (지표: 전체/검증셋 PnL, slug 승패, MDD, 체결 수, 사용한 파라미터·비용 모델)
  - 선행조건 체크: engine/sweep/grid 실행 전 data_prep 산출물 존재·최신성 확인
- **API**: `POST /api/backtest/run {kind, strategy, params}` (params = haircut/p_fail/dust 오버라이드), `GET /api/backtest/jobs[/{id}]` (+로그 tail), `GET /api/backtest/results`
- **UI 탭**: 실행 폼 → 진행 로그 뷰(폴링) → 결과 테이블 → **과거 결과 나란히 비교** → "1위 파라미터 config 반영" 버튼(Phase C의 PUT 재사용)
- **구현 주의**: 스크립트 stdout을 정규식 파싱하지 말 것 — backtest 스크립트에 `--json <경로>` 출력 옵션을 추가하는 쪽이 견고 (backtest/ 소폭 수정 필요). **착수 전에 아래 구조 감사 개선안 #1(엔진 통일)을 먼저 하는 게 좋음** — 그래야 UI가 하나의 엔진만 호출.

#### Phase E — live 가드 + 마감 (미착수, 설계 확정)

- **live 시작 3단계 가드**:
  1. 모드 live 선택 → 빨간 경고 + **재개 기준 체크리스트 자동 표시** (sim slug 수 n/30 · 최근 현실화 백테스트 결과 존재/부호 · P2 완료 여부 — 미충족 항목이 있으면 그대로 보여주고 진행은 막지 않되 명시)
  2. 확인 문구 직접 타이핑: `LIVE <전략명>` 정확 일치해야 버튼 활성
  3. 시작 전 요약 카드(전략/qty/공개 지갑주소/핵심 config 값) → 최종 확인
- **서버측**: `POST /api/bot/start`의 live 허용 조건 = body에 confirm 문구 동봉 + 서버 기동 플래그 `--allow-live` (기본 꺼짐 — 평소엔 서버 자체가 live 불가). 실행 중 상단 상시 빨간 배너
- **kill switch 정식화**: 전체 정지 + live 포지션 flatten 옵션 — flatten은 P2의 SELL 스윕 경로 재사용이므로 **P2 완료가 전제**
- **로그 뷰어**: run별 out.log tail + trades 최근 N건
- **불변 원칙**: UI 서버는 `.env`를 절대 읽지 않음 (live 자격증명은 봇 프로세스만 로드)

#### 작업 재개 순서 (UI Phase와 기존 로드맵의 결합)

1. **(상시)** 터미널에서 `python -m ui.server` → Control 탭에서 threshold sim 시작 → P0 수집 (목표 slug 30+, 현재 4). ⚠ Claude 세션이 띄운 서버는 세션 종료와 함께 꺼짐 — 오래 돌릴 땐 반드시 본인 터미널에서
2. **구조 개선 #1·#2** (backtest 엔진 통일, tests/) — Phase D의 기반
3. **Phase D 구현** → slug 30+ 도달 시 UI에서 재평가 (그 전이라도 터미널로 `data_prep`→`engine` 가능)
4. 재평가에서 threshold 기대값 유지 확인 → **P2 실행 품질** (SELL 스윕 스레드 분리 / TP 스윕화 / USDC 잔고 가드) — UI가 아닌 core 작업
5. **Phase E** (live 가드) — P2 완료 후
6. live 소액 재개 판단 — 기준 불변: sim 30+ 무결 + 백테스트 기대값 플러스 + P2 완료

---

### 구조 감사 (2026-07-11) — 현재 구조 / 평가 / 개선안

> 사용자 질문: "전역 모듈 + 전략별 모듈로 나뉘어야 할 것 같은데 이게 제대로 된 건지?"
> **결론: 그 분리가 정확히 현재 구조이고, 골격은 올바르다. 개선 여지는 골격이 아니라 ① backtest의 전략 로직 이중화 ② 검증/스키마의 위치 ③ 테스트 부재 ④ 런타임 상태 파일 산재에 있다.**

#### 현재 구조와 모듈 역할 (총 ~3.9k LOC)

```
core/        전역 엔진 — 전략을 모름. 단방향 스트림의 골격
  adapters_polymarket.py 112   시세·토큰ID (Gamma/CLOB, 재시도·백오프)
  slug_loop.py           128   이벤트 소스 (1s tick, 15분 slug 롤링)
  runner.py              165   조립 + CLI (config→adapter→loop→strategy→executor→account→sink)
  executor_sim.py     60 / executor_live.py 491   주문 집행 (무상태)
  account_sim.py     132 / account_live.py  184   포지션 단일 진실(SOT)
  logger.py              173   CSV sink (append + run_id)
  printer.py             111   콘솔 sink
  control.py              77   stop-file/heartbeat (UI 연동, Phase A에서 추가)

strategies/  전략 플러그인 — 1전략=1모듈, base.py 인터페이스(on_event/on_trade/debug_state)
  base.py 42 · threshold.py 192 · ma_breakout.py 281 · __init__.py(REGISTRY)

configs/     전략별 JSON (+ backups/ 자동 백업, gitignore)
backtest/    engine.py 241(실제 strategies/ 코드 리플레이 ✅) · run_grid.py 308 ·
             backtest.py 301 · sweep_threshold.py 66 · data_prep.py 93
ui/          server 142 · procman 177 · metrics 252 · configstore 160 · static/index.html
루트 상태     sim_account_<전략>.json · logs/(ctl/ 포함)
문서          SPEC(명세) · CLAUDE(운영규칙) · ANALYSIS(리팩토링 기록) · STATUS(구 로드맵) ·
             WORKLOG(본 기록) · REPORT.html(현황 리포트)
레거시        polybots_MA/ · polybots_pre/ · polybots_backtest/ (읽기 전용, 각자 git)
```

**의존 방향** (건강함 — 역방향 없음):
- strategies → base만 (core를 모름)
- core.runner → strategies.REGISTRY (조립 지점 한 곳)
- ui → core와 **프로세스/파일 경유로만** 결합 (subprocess + logs/ctl + configs) + REGISTRY import
- backtest.engine → strategies + core 일부 (리플레이용)

#### 평가 — 잘된 점

- 사용자의 직관("전역 + 전략별")과 구조가 일치. **새 전략 추가 비용 = 파일 1개 + config 1개 + REGISTRY 1줄** — 플러그인 구조가 실제로 동작함 (UI 전략 목록·백테스트도 자동 인식)
- 핵심 불변식(단방향 스트림, Account=SOT, executor 무상태)이 모듈 경계와 일치 — 분리에 이유가 있음
- sim/live가 executor/account 페어 교체만으로 갈림 — live 코드가 sim 경로를 오염 안 함
- ETH/SOL/XRP 확장은 config의 slug prefix 변경만으로 가능한 구조 (SPEC ver4 대비 완료)

#### 개선안 (우선순위순)

| # | 항목 | 내용 | 노력 | 시점 |
|---|---|---|---|---|
| 1 | **backtest 전략 로직 이중화 제거** ✅ 완료 (2026-07-12) | `backtest.py`(무비용 구버전)와 `run_grid.py`가 MA 로직을 재구현 — 파일 주석 스스로 "전략 바뀌면 sync 필요" 인정. engine.py 방식(실전략 리플레이)으로 통일: engine의 리플레이 코어를 함수로 추출 → run_grid는 그걸 프로세스풀로 fan-out, backtest.py는 폐기 | 중 | **Phase D 착수 전** |
| 2 | **tests/ 신설** ✅ 완료 (2026-07-12) | 리팩토링 때의 7개 파이프라인 테스트가 커밋 안 된 일회성이었음. tests/로 영구화: 거부매수 재시도·exit 래치·logger append·PerfReport 집계·configstore 검증 | 중 | Phase D 착수 전 |
| 3 | config 검증 위치 이동 | 검증 규칙이 ui/configstore.py에만 있음 → core/config_schema.py로 옮겨 **runner 시작 시에도 검증** (지금은 잘못된 config로도 봇이 뜸). UI는 그걸 import | 소 | 아무 때나 |
| 4 | 런타임 상태 파일 정리 | sim_account_*.json이 루트에 산재 → `state/` 디렉토리로. backtest 결과 CSV(grid_results*.csv 등)도 `backtest/results/`로 | 소 | Phase D에서 자연 해결 |
| 5 | 로그 스키마 상수화 | CSV 컬럼명이 core/logger·ui/metrics·backtest에 문자열로 중복 — logger가 스키마 상수를 노출하고 나머지가 import | 소 | 아무 때나 |
| 6 | executor/account 계약 명시화 | 현재 duck-typing — strategies/base.py처럼 Protocol/ABC로 인터페이스 문서화 (신규 구현·모킹 시 실수 방지) | 소 | 아무 때나 |
| 7 | 레거시 3폴더 정리 | P0 재검증으로 새 구조 신뢰 확보 후 archive/ 하위 이동 또는 삭제 (git 스냅샷 존재: MA d0129ca, pre 3c2186c) | 소 | P0 완료 후 |
| 8 | 패키징 | pyproject.toml (+콘솔 스크립트) — 현재 `-m` 실행으로 충분, 서버 배포(P3) 시점에 | 소 | P3 |

**하지 않기로 한 것**: core를 더 잘게 쪼개기(이벤트버스, DI 프레임워크 등) — 현재 규모(~4k LOC)에서 추상화 비용 > 이득. 전략이 5개+ 되고 자산이 늘면 재검토.

---

### 2026-07-12 — 구조 개선 #1 완료: backtest 엔진 통일 (Phase D 선행 작업)

**변경**:

| 파일 | 내용 |
|---|---|
| `backtest/engine.py` | 리플레이 코어에서 `prepare_slugs()` 추출 (그리드가 groupby를 콤보마다 반복하지 않게) · `replay()`가 DataFrame 또는 prepared 리스트 둘 다 수용 · `--json <path>` 출력 추가 (Phase D의 "stdout 정규식 파싱 금지" 대비) |
| `backtest/run_grid.py` | **전면 재작성** — 벡터화 MA 재구현 삭제, `engine.replay`를 프로세스풀로 fan-out. 그리드 축을 실전략 config 키로 교체 (**구 그리드의 상대 tp/sl 축은 실전략이 지원하지 않는 파라미터였음** → `tp_abs` [None, 0.95, 0.98, 0.99]로 대체). train/val 분리·구 최적점 비교·헤어컷 민감도 유지. `--quick`(16콤보 스모크)/`--workers`/`--json` 추가 |
| `backtest/sweep_threshold.py` | `prepare_slugs` 사용 + argparse(`--haircut/--pfail/--seed/--data/--out/--json`) |
| `backtest/backtest.py` | **폐기(git rm)** — 무비용 + MA 로직 이중화. git 이력으로만 참조 |
| `backtest/README.md` | 파이프라인/파일 표 갱신, dust_frac 행 제거(엔진 모델로 통일) |

**검증 (전부 통과)**:
- 회귀: 수정 후 `engine.py`가 수정 전과 완전 동일 수치 — MA −5.18 / 1138 fills / MDD −52.80, threshold +28.50 / 340 fills
- `run_grid --quick`(4워커, Windows spawn) 정상 — 교차검증: 그리드의 tp_abs=0.98/cd0/ban-none 행(train 24.74, val −29.92)이 단독 엔진 실행 per_source와 정확히 일치
- `sweep_threshold` 72콤보 — 기존 판정 재현 (tp 0.99가 1위 score 22.65, 현 config 2위)
- 3파일 py_compile + JSON 출력 4종 파싱 확인
- 성능: exact-replay ~1.1s/콤보 → 풀 그리드 3600콤보 ≈ 10워커 13분 (구 벡터화 15분과 대등)

**의미**: 이제 백테스트 경로가 `engine.replay` 하나 — 전략 코드가 바뀌면 그리드/스윕이 자동 추종. 단, 구 `grid_results_realistic.csv`(상대 tp/sl 축)와 새 그리드 결과는 축이 달라 직접 비교 불가 — 다음 풀 그리드 실행 시 새 기준으로 갱신할 것.

### 2026-07-12 (같은 세션) — 구조 개선 #2 완료: tests/ 신설

**구성** (49 tests, ~4초, `python -m pytest tests/ -q`):

| 파일 | 커버 |
|---|---|
| `test_threshold_strategy.py` | 진입 윈도/favorite 선택 · **거부매수 재시도(슬롯 미소모)** · submitted 보수적 슬롯 소모 · SL 후 재진입 · TP 슬럭 잠금 · 레벨트리거 exit 재발화 · 거부 exit 무변이 · max_entries · slug 리셋 |
| `test_ma_breakout_strategy.py` | cap 하 cross-up 진입 · **exit_armed 래치(체결까지 재발사, 체결 시 해제)** · tp_abs 우선순위 · buy_inflight 스태킹 차단+거부 후 재시도 · slug 변경 시 상태 폐기 |
| `test_account_sim.py` | SOT 불변식 — filled만 변이 · 부분 청산 잔량 · dust 청산 · 반대편 exit 무시 · 디스크 왕복 |
| `test_logger.py` | **append 모드(헤더 1회, run_id로 run 구분)** · intent+trade 1행 페어링 · 비활성 sink 무출력 |
| `test_perf_report.py` | run_id 파싱(전략명 '_' 포함) · **(전략,모드) 분리(D9)** · 실현 PnL=청산 slug만(D10) · dust=청산 취급 · equity 누적 현금흐름(D11) · mtime/size 캐시 무효화 |
| `test_configstore.py` | 저장+백업+diff · no-op 무기록 · 같은 초 백업 충돌 회피 · **거부 12종 파라미터라이즈**(잠금/미존재/타입/enum/범위/양수/null/정수) |
| `test_engine.py` | 비용 모델(매수 intent가, 매도 bid−haircut 전량 스윕, p_fail 거부) · ReplayAccount dust · 리플레이 결정성(seed 고정, parquet 없으면 skip) |

- `requirements.txt`에 pytest 추가, CLAUDE.md에 구조/테스트 규칙 반영

### 2026-07-12 (같은 세션) — Phase D 완료: Backtest 탭

**구현** ("수집 → 재평가 → config 반영" 사이클이 UI 안에서 완결):

| 파일 | 내용 |
|---|---|
| `ui/jobs.py` (신규) | `JobManager` — job 1개 = backtest 스크립트 subprocess 1개 (data_prep/engine/sweep_threshold/run_grid). **동시 실행 1개**(워커 스레드 + FIFO 큐, 대기 5개 제한). stdout → `logs/ctl/bt_<job_id>.log`. 결과는 스크립트 `--json`이 **직접** `backtest/results/<ts>_<seq>_<kind>_<strategy>.json`에 기록 (stdout 파싱 없음 — 설계 노트 준수). 선행조건: engine/sweep/grid는 parquet 필수 + 이벤트 로그가 더 최신이면 stale 플래그. queued 취소/running terminate 지원 |
| `ui/server.py` | `GET /api/backtest/data`(parquet 존재/최신성) · `POST /api/backtest/run` · `GET /api/backtest/jobs[/{id}]`(+로그 tail 16KB) · `POST /api/backtest/jobs/{id}/cancel` · `GET /api/backtest/results` |
| `index.html` Backtest 탭 | 실행 폼(종류별 폼 요소 전환, 풀 그리드는 confirm, stale 배너) → job 테이블(상태 chip, 경과, 취소) + 로그 tail 뷰(2초 폴링, 스크롤 고정) → 결과 아카이브 테이블(종류별 핵심 지표 헤드라인) → **체크로 나란히 비교** → **"1위 → config" 버튼**(Phase C PUT 재사용, confirm에 diff 요약) |
| `.gitignore` | `backtest/results/` 추가 (logs/·configs/backups/와 동일한 런타임 산출물 방침) |

**결정 추가**:

| # | 결정 | 이유 |
|---|---|---|
| D17 | 결과 아카이브 = 스크립트 `--json`을 아카이브 경로에 직접 쓰게 함 (래핑 없음). 파일명 `<ts>_<seq>_<kind>_<strategy>.json` | JSON이 이미 self-describing(cost_model/overrides/top 포함). seq는 같은 초 충돌 방지 |
| D18 | grid/sweep의 "1위 반영"에서 tp_abs 등 null 반영이 현 config가 non-null이면 400 — configstore D16 규칙 유지, UI는 에러 그대로 표시 | nullable 규칙을 UI 편의로 우회하지 않음 (사용자가 Config 탭에서 직접 판단) |

**검증 (전부 통과)**: py_compile 2파일 + JS node --check + 기존 49 tests 통과 유지 / E2E(테스트 포트 8788): engine job 등록→queued→running→done(rc 0), 로그 tail 스트리밍, 아카이브 생성(threshold +28.50 재현), stale=true 정확(수집분이 parquet보다 최신), 400 거부 2종(kind/strategy), **큐 직렬화 확인**(2번째 job이 queued로 대기 후 순차 실행), 페이지 200

**미결**: 사용자 브라우저에서 탭 실제 조작 확인(서버 `python -m ui.server` 후 Backtest 탭) — API/JS는 검증됐으나 렌더링은 육안 확인 권장

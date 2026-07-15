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

## 로드맵 (정본 — 구 STATUS.md P0~P4 흡수, 2026-07-12)

- **P0 — sim 수집** ✅ (2026-07-13): threshold 33 slugs 수집 완료 (집 12 + 회사 21, 목표 30 초과). 단 재평가에서 신규 구간 음수 → 수집 연장. **2026-07-14 완전성 기준(D22) 재집계: 완전 slug 23 — 연장 목표 완전 60개** 후 D23 절차로 재판정
- **P1 — 백테스트 현실화** ✅ (2026-07-07): 비용 캘리브레이션(haircut 0.01 / p_fail 0.2) — 엔진이 3/3 실거래를 ±$2.6로 재현. 판정: MA 라이브 부적합, threshold 주력 후보(tp 0.99)
- **P2 — 실행 품질** (live 손실 요인 제거, live 재개 전 필수 — core 작업):
  - [ ] `sell_dust:below_step` 대응 — 리팩토링 반영분(청산 실패 시 다음 tick 재발행) 라이브 검증
  - [x] exit_tp도 스윕 경로로 ✅ 2026-07-15 확인: 리팩토링에서 이미 **모든 SELL이 IOC 스윕 경로** (executor_live.fill → _sell_sweep_ioc). exit_tp는 트리거 시점 bid를 limit가로 IOC 스윕 + 레벨트리거 재발화라 3/3의 "FAK 한 방 no-match" 구조 해소됨. `tests/test_executor_live.py`(6개)로 라우팅·가격 규칙 고정. 라이브 실측 확인만 1번 항목과 함께 남음
  - [ ] live SELL 스윕(≤10초)의 메인 루프 블로킹 → 스레드 분리 — 최악 사례: exit_tp no-match 시 스윕이 고정가로 창 전체(10s)를 소진하며 블로킹 (2026-07-15 분석)
  - [ ] 주문 전 USDC 실잔고 가드 (현재 cash는 명목 흐름)
  - [ ] maker 진입 검토 — `execution.buy: "limit"` 경로로 스프레드 회수 (왕복비용 ~$0.02가 유일한 확정 마이너스: 2026-07-14 캘리브레이션 스터디). adverse selection은 live 소액 실측으로
  - [x] **sim 이월 포지션 정산 처리** ✅ 2026-07-14 저녁 — 마지막 bid 강제 장부 마감(exit_expiry) + 교차 slug exit 차단 + stale write-off (SPEC §4.5). 과거 실측 3건(MA +5.3 과대 / threshold −3.5~−8.8 과소)의 장부는 소급 수정 안 함
- **P3 — 인프라**: tick당 HTTP 4회 순차 → 병렬화 or CLOB WebSocket · slug 경계 404 폴백(로컬 시계 레이스) · GTC 잔류 주문 추적/취소(현재 buy_inflight 래치로 중복만 방지) · 서버 상시 가동, 패키징(구조 감사 #8) · **events.csv 일자 로테이션 + data_prep 증분화** (수개월치 누적 대비 — 2026-07-12 심층 리뷰) · **quote 수집을 봇에서 분리한 recorder** (봇 2개 동시 실행 시 시세 중복 기록 제거) · ~~data_prep의 live_mar03 소스를 backtest/data/로 승격~~ ✅ 2026-07-13 집: `backtest/data/mar03_live.csv`로 승격(git 추적), archive/ 의존 제거
- **P4 — 확장**: ETH/SOL/XRP·5분/1시간 마켓 (config slug prefix/interval 교체) — **선행: 봇 정체성을 "전략"→"전략@마켓"으로** (config 파일명·sim 계좌 파일·procman 키·run_id·metrics 집계 5곳이 전략 단위라 같은 전략 2마켓 동시 실행 시 충돌, 2026-07-12 심층 리뷰) · train/val 소스명 하드코딩 정리 · Binance ATR(`core/adapters_binance.py` + 전략 플러그인) · 아카이브 최종 처분(구조 감사 #7)
- **live 재개 기준 (불변)**: sim slug 30+ 무결 + 현실화 백테스트 기대값 플러스 + P2 완료 → 소액부터. UI로는 Phase E의 3단계 가드 경유

### 참고 — 2026-03-03 라이브 세션 (P2의 근거, 구 STATUS §1 요약)

- MA breakout 4시간, 15 slugs: 137주문(체결 122/거부 15), **실현 −$27.30**, slug 3승 12패
- 거부 15건 = `sell_dust:below_step` ×14 (잔고 반영 지연 → **미청산 36.5tk 만기 노출**의 직접 원인) + FAK no-match ×1 (exit_tp 실패)
- 무비용 백테스트 +$81.66 vs 라이브 −$27.30 갭 → P1 현실화의 동기. 주요인: market 매도 = bid−slippage(0.05)의 이중 부담, 평균 매수 0.290 vs 매도 0.272
- polybots_pre 라이브는 1왕복(−$0.74)뿐 — 표본 부족으로 평가 불가

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
| 3 | config 검증 위치 이동 ✅ 완료 (2026-07-12) | 검증 규칙이 ui/configstore.py에만 있음 → core/config_schema.py로 옮겨 **runner 시작 시에도 검증** (지금은 잘못된 config로도 봇이 뜸). UI는 그걸 import | 소 | 아무 때나 |
| 4 | 런타임 상태 파일 정리 ✅ 완료 (2026-07-12) | sim_account_*.json이 루트에 산재 → `state/` 디렉토리로. backtest 결과 CSV(grid_results*.csv 등)도 `backtest/results/`로 | 소 | Phase D에서 자연 해결 |
| 5 | 로그 스키마 상수화 ✅ 완료 (2026-07-12) | CSV 컬럼명이 core/logger·ui/metrics·backtest에 문자열로 중복 — logger가 스키마 상수를 노출하고 나머지가 import | 소 | 아무 때나 |
| 6 | executor/account 계약 명시화 ✅ 완료 (2026-07-12) | 현재 duck-typing — strategies/base.py처럼 Protocol/ABC로 인터페이스 문서화 (신규 구현·모킹 시 실수 방지) | 소 | 아무 때나 |
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

### 2026-07-12 (같은 세션) — 문서 체제 정리: 5문서로 통합, 숨은 .md 전부 처분

**결정 D19**: 문서는 **CLAUDE / SPEC / WORKLOG / backtest README / DOCS(문서 맵, 신규)** 5개가 전부. 새 .md를 만들기 전에 DOCS.md의 표에 자리가 있는지 확인. 로드맵 정본은 WORKLOG 한 곳 (STATUS·SPEC §10·ANALYSIS §6에 3중 분산돼 있던 것 해소).

- 삭제: `ANALYSIS.md`(히스토리→git), `STATUS.md`(로드맵·3/3 세션 요약을 위 "로드맵" 섹션으로 흡수 후), `REPORT.html`(낡은 프레젠테이션판), `AGENTS.md`(IDE 미러 — gitignore 등록으로 재발 차단)
- 숨은 문서 발굴: `polybots_pre/backup/`의 19개(SPEC v0.1~v2.0 초안 등, 레거시 git에도 없던 untracked) → **pre git 스냅샷 `5a84048`로 보존 후 디스크 삭제**
- `SPEC.md` v3.1로 현행화: §9 엔진 통일 반영, §10을 Control UI·tests로 교체, 로드맵은 WORKLOG 포인터화, §5에 core/control.py 추가
- `.pytest_cache/` gitignore. 레거시 `SPECv2.1.md` 2부는 폴더째 정리(#7) 때 함께 처분
- 후속: SPEC §2를 "구조도" 챕터로 확장 — 2.1 폴더 지도(주석 트리) · 2.2 실행 단위 3종(봇/UI/backtest)과 파일 결합 관계도 · 2.3 기존 이벤트 스트림

### 2026-07-12 (같은 세션) — 멀티 머신 작업 준비: 데이터의 git 편입 (결정 D20)

**D20 — git 데이터 정책**: 수집 자산은 track, 휘발성·재생성물·비밀은 ignore.
- **track**: `logs/*.csv`(P0 수집분 — 세션 종료마다 스냅샷 커밋), `state/`(sim 계좌), `backtest/data/*_events.csv`(대체 불가 원본, 82MB→git 압축 3.3MB), `backtest/results/`(결과 아카이브)
- **ignore**: `logs/ctl/`(heartbeat·stop·stdout — 머신 로컬), `quotes_all.parquet`(data_prep으로 재생성), 루트 `sim_account*.json` 잔재, `.env`(불변 — 절대 커밋 금지), `configs/backups/`, `archive/`
- **멀티 머신 규칙: 수집(sim)은 한 번에 한 머신에서만.** 떠나기 전 `봇 정지 → 스냅샷 커밋 → push`, 도착해서 `pull → 봇 시작`. logs는 append 파일이라 양쪽 동시 수집 시 git 병합 불가.
- 회사 PC 최초 셋업: `git clone` → `pip install -r requirements.txt` → `python -m pytest tests/ -q`(53개) → `python -m ui.server`. live 자격증명(.env)은 git 밖 — sim/백테스트/UI에는 불필요.
- **원격 연결 완료**: https://github.com/juneon/polybots (private). 이 repo는 1~2월 구버전이 들어있던 기존 repo였음 — 구 히스토리는 **`legacy-v2` 브랜치로 보존**(+로컬 archive/에 이중 보존) 후 main을 현 모노레포로 교체. 수집 8/30 시점 스냅샷까지 push됨 — 회사 PC는 clone 후 9번째 slug부터 이어서 수집.

### 2026-07-12 (같은 세션) — 구조 개선 #3~#6 완료 (감사 항목 전부 소진, #7·#8만 잔류)

| # | 구현 |
|---|---|
| #3 | `core/config_schema.py` 신설 — 값 규칙(이름 기반 range/enum/양수/비음수)의 단일 원본. **runner가 시작 시 `validate_config`로 fail-fast** (잘못된 config로 봇이 뜨지 않음 — cap=1.5로 exit 1 검증). ui/configstore는 `validate_change` import (잠금/백업/diff 정책만 UI에 잔류) |
| #4 | sim 계좌 → `state/sim_account_<전략>.json`. **시작 시 구 루트 파일 자동 이관**(runner), UI metrics는 state/→루트 폴백(구코드로 도는 봇 호환). 죽은 `sim_account.json`(D7 이전) 삭제. 구 축(상대 tp/sl) 결과 CSV 2개 git rm, backtest 스크립트 기본 출력도 `results/`로 |
| #5 | `core/logger.py`가 EVENTS/TRADES/SNAPSHOTS_FIELDS 상수 노출 — ui/metrics(매직 인덱스 제거)·tests가 import |
| #6 | `core/contracts.py` — Executor/Account `@runtime_checkable` Protocol. Sim/Replay 페어 conformance 테스트 포함 |

**검증**: 테스트 53개(신규 4: 계약 준수 2 + 배포 config 유효성 + 잘못된 값 검출) 전부 통과 / bad-config runner exit 1 / ma_breakout sim 스모크 — stop-file graceful 종료(rc 0), state/ 이관 확인. **주의: 실행 중이던 threshold sim(사용자 터미널)은 구코드라 루트 파일에 계속 씀 — 다음 재시작 때 자동 이관되고 그동안 UI 폴백이 커버**

### 2026-07-13 — 회사 PC 온보딩 + P0 수집 완료(33 slugs) + 재평가 (멀티 머신 첫 사이클)

**회사 PC 셋업** (D20 절차 실행):
- clone 정리: 실수로 옛 로컬 폴더 안에 중첩 clone됐던 것을 `Desktop\polybots`로 정착. 옛 폴더는 `Desktop\polybots_old` 백업, 레거시 3폴더는 백업에서 `archive/`로 복원 (집과 동일 레이아웃)
- `pip install -r requirements.txt` → tests **52 passed / 1 skipped** (skip = parquet 부재 리플레이 테스트, data_prep 후 실행 가능 — D20 예상대로)
- `.env`는 이 머신에 새 clone 기준 없음 → sim/백테스트/UI에 불필요 (live 전 별도 이관 필요)

**P0 수집 완료**:
- threshold sim 12 → **33 slugs** (목표 30 초과). UI Control 탭으로 시작/정지 — Phase A 원격 머신 실사용 검증 겸. 정지는 stop_all API, 두 봇 모두 forced=false·rc 0 그레이스풀, 미청산 포지션 없음
- ma_breakout sim이 병행 수집됨(동일 33 slugs) — 시세 이중 기록(P3 recorder 이슈)이 실제 발생, 수집 데이터는 (slug,tick) dedup으로 무해하나 events.csv 크기만 증가

**발견 — data_prep 머신 이식성 (P3에 항목 추가)**:
- 첫 재평가에서 `live_mar03` per_source가 통째로 소실 — 원인: 소스 경로가 gitignored `archive/polybots_MA/logs/events.csv` 의존이라 신규 머신에서 **val 데이터가 조용히 누락**됨. 백업에서 archive/ 복원으로 해결 후 전체 재실행 (mar03 누락 상태의 결과 아카이브 3건은 오판 방지 위해 삭제)

**재평가** (sim_new 34 slugs 반영, 비용 모델 기본 haircut 0.01/p_fail 0.2 — UI Backtest 탭 job 경유):
| 지표 | 어제 (07-12, sim 4 slugs) | 오늘 (07-13, sim 34 slugs) |
|---|---|---|
| engine 현 config 전체 PnL / score | +28.50 / 22.65 | **+15.60 / 5.78** |
| per_source | janfeb +24.15 · mar03 +4.35 · sim 0.0 | janfeb +24.15 · mar03 +4.35 · **sim_new −12.9** |
| sweep 1위 | tp 0.99 (score 22.65) | **tp 0.99 유지** (score 5.78, val mar03 +4.35 통과). 현 config(tp 0.98)는 2위(3.36, val +2.74) |

**판정**: live 재개 기준의 "기대값 플러스"는 **전체 기준으로는 충족**(+15.60, val 플러스, 1위 파라미터 기존 판정 유지). 그러나 **신규 수집 구간(7/12~13)에서 −12.9로 음수** — 최근 시장에서 엣지 약화 신호. 표본이 작아(34 vs janfeb 189) 확정은 이르다. 다음 세션 선택지:
- (a) 수집 연장(60+ slugs)으로 sim_new 표본 확충 후 재판정 ← 보수적 기본안
- (b) sweep 1위(tp 0.99)만 config 반영하고 sim 관찰 지속
- (c) 병행: P2 실행 품질 착수 (수집과 독립적인 live 코드 작업)

**git**: 수집 스냅샷(logs/state) + 결과 아카이브(backtest/results) + 본 로그 커밋/push — 집에서 pull로 이어받기.

### 2026-07-13 (집) — 시간축 버그 수정 + 손실 원인 규명(휩쏘 71%) + 수집 재개

**회사 결과 재현**: pull 후 data_prep→engine→sweep 전부 재실행 — 소수점까지 일치 (+15.60 / 5.78 / sim −12.9). 테스트 53개 통과.

**버그 발견/수정 — (slug,tick) dedup은 무해하지 않았다**:
- tick은 run 전역 카운터라, 봇 2개 동시 기록 or 재시작 시 같은 slug 안에서 tick 범위가 어긋남. (slug,tick) dedup+정렬 결과 **sim 34개 중 31개 slug의 시계열이 비단조**(4개는 심각 — 예: 1783863900은 후반부(tick 1-465)가 전반부(tick 744-897)보다 앞에 정렬됨)
- 수정: data_prep dedup/정렬을 **time_left_sec 기준**으로, engine prepare_slugs 정렬을 ts 기준으로. 수정 후 비단조 slug 0
- 영향: sim −12.9 → **−13.2** (오염이 손실을 부풀린 게 아니었음 — 손실은 실제)

**손실 원인 규명 (숫자가 아니라 "왜")**:
- 가설 "수집 중단 시 강제청산이 극단 손실을 만든다" → **기각**: truncated slug 6개 중 포지션 보유 중 끊긴 건 1건뿐, 영향 +0.3
- 실제 원인: sim 손실 전부 **정상 stop-loss** (21건 −22.0). 그중 **15건(71%)이 휩쏘** — 손절 후 해당 사이드가 0.99로 정산 (홀드했으면 +23.7). 나머지 6건은 진짜 세이브 (홀드 시 −48.9 → −6.1로 방어). 순효과: 손절(−22.0)이 무손절 홀드(−25.2)보다 근소 우위
- 해석: 최근 시장은 slug 중반 변동성이 커서 favorite가 0.06 이상 출렁였다 회복하는 패턴 빈발

**데이터 셋팅 (일자별)**:
- data_prep이 sim 수집분을 UTC 일자별 소스로 분리 (`sim_260712`, `sim_260713`, ...) → engine per_source·sweep에 일자별 PnL 자동 표시 (sweep에 `sim` 합계 컬럼 추가)
- live_mar03을 `backtest/data/mar03_live.csv`로 승격 (P3 항목 완료, archive/ 의존 제거)
- sweep의 "current config" 하드코딩(0.98) 제거 — configs/threshold.json에서 읽음. **주의: config tp는 P1 때 이미 0.99로 반영돼 있었음** (14ba4a7) — 어제 "현 config 2위(0.98)"는 이 낡은 라벨이 만든 오해

**클린 데이터 재스윕 (72조합)**:
| 조합 | pnl | score | janfeb | mar03 | sim |
|---|---|---|---|---|---|
| **0.80/0.06/0.99/0.90 (현 config)** | 15.30 | **5.33 (1위)** | 24.15 | +4.35 | −13.20 |
| 0.85/0.10/0.99/0.95 | 9.24 | 2.89 | 16.04 | −1.79 | **−5.01** |
- 현 config가 종합 1위 유지. 단 sim 구간은 0.85/0.10 계열(넓은 손절+높은 진입)이 손실 60% 축소 — 휩쏘 분석과 일치. **어느 조합도 sim 양수는 없음** → 파라미터 교체보다 표본 확충이 우선 (선택지 (a) 채택)
- 수집 재개: threshold sim 단독 가동 (ma_breakout 병행 없이 — 시세 이중 기록 회피)

### 2026-07-13 (집, 이어서) — 백테스트 환경 정비 + t_enter 축 확장 스윕 + config 교체(0.85/0.12/0.98)

**백테스트 환경 정비 (결과가 어디에 저장되는가)**:
- 기존: UI job만 `backtest/results/`에 타임스탬프 아카이브, CLI는 engine=화면 출력뿐 / sweep=고정 파일명 덮어쓰기
- 수정: **CLI도 기본 자동 아카이브** — engine은 `results/<ts>_engine_<전략>.json` (`--no-save`로 끔), sweep은 `results/<ts>_sweep_threshold.{csv,json}`. `--json`/`--out` 명시 시 그대로(UI 경로 호환)
- sweep에 `val`(mar03+sim) 컬럼과 "TOP 5 by val" 출력 추가 — train(janfeb)만 좋은 과최적 조합 식별용

**확장 스윕 (144조합)**: 기존 4축에 **t_enter(enter_time_left_sec: 450/300/180) 추가** — 휩쏘 후속(늦은 진입 = 출렁임 노출 시간 축소 가설). 결과:
| 조합 | pnl | mdd | score | janfeb | mar03 | sim | val | W/L |
|---|---|---|---|---|---|---|---|---|
| **0.85/0.12/0.98/0.90/t450 (신규 1위)** | 11.79 | **−10.30** | **6.64** | 14.44 | −0.95 | **−1.70** | −2.65 | 109/65 |
| 0.80/0.06/0.99/0.90/t450 (구 config, 2위) | 15.30 | −19.94 | 5.33 | 24.15 | +4.35 | −13.20 | −8.85 | 85/99 |
- t_enter 늦추기(300/180)는 val은 좋아지나 janfeb 음수로 붕괴 → 과최적 판정, 탈락. t450 유지
- 신규 1위는 총 pnl은 낮지만 MDD 절반·승률 46→63%·sim 손실 87% 축소. 새 파라미터 기준 sim_260713은 **+1.7 양전** (구 config −7.2)

**config 교체**: configs/threshold.json → enter 0.85(re 동일)/stop_drop 0.12/tp 0.98 (cap 0.9·t450·나머지 불변). 엔진 재검증 = 스윕 row와 일치. 유의: mar03 −0.95로 근소 음수 — "val 음수 탈락" 규칙의 경계선. sim 표본(34)이 쌓이면 재판정
- 실행 취약점 메모: tp 0.98은 FAK no-match 이력(P2 exit_tp 스윕 항목)과 접점 — live 전 P2 필수 재확인

**수집 재시작**: 구 run(20260713_233324) stop-file 그레이스풀 종료(rc 0) → 새 config로 `20260713_235323_threshold_sim` 가동. 테스트 53개 통과. UI sweep 설명 문구의 "72콤보" 하드코딩도 정리

### 2026-07-14 — 실매매 리뷰(trades.csv) + sim 이월 버그 발견 + 수집분 전용 최적화 → REPORT.html

**실제 sim 매매 리뷰** (trades.csv 202건, 계좌 타임라인 기준 라운드트립 재구성):
- MA: 70rt +30.36 (승률 15.7% 복권형 — TP 8건 +50.3이 전부, MA크로스 62건 −19.9) / threshold: 31rt −16.30 (손절 25건 중 휩쏘 16건)
- **버그 발견 — sim 이월 포지션**: 런/slug 종료 시 포지션이 정산 없이 이월 → 다음 slug의 다른 토큰 가격으로 청산. 3건 실측, 보정 시 MA ≈+25.1 / threshold ≈−12.8 (P2에 항목 추가)
- 카운터팩추얼: 청산 규칙 제거는 양쪽 다 손해 (MA 시간청산이 +18.0 방어, threshold 손절 순효과 +3.4)

**수집분(34 slugs) 전용 최적화** (threshold 144 + MA 120조합, 비용 반영):
- 현 config 기준선: **MA +19.06 (score 15.73) vs threshold −5.10** — 최근 레짐에서 MA 우세, threshold는 최적 조합(0.85/0.10/0.99/t180)조차 +1.0
- 단 MA sim 1위(cap0.7/ma600/c3/tp0.99)는 janfeb −28.9로 붕괴 = **레짐 뒤집힘**. 전 구간 생존형은 cap0.7/ma600/c0/tp없음(전체 +27.7) — MA 재검토 시 1순위
- 판단: MA config 즉시 교체는 보류(34 slugs 표본). MA sim 재가동은 recorder 분리(P3)와 엮어 결정

**REPORT.html** (루트, gitignore/D19): 위 전부 + 차트(누적 PnL·slug별·카운터팩추얼)로 재생성 가능한 상세 보고서. 생성 스크립트는 세션 스크래치(analyze_actual/optimize_sim/build_report.py)

### 2026-07-14 (회사) — 백테스트 정리: 이름 통일 + slug 완전성 + robust config 판정 (변경 없음 결론)

**결정 4건**:

| # | 결정 | 내용 |
|---|---|---|
| D21 | **전략 정식명 `threshold` / `ma`** (ma_breakout 개명) | 코드·config·문서 전부 rename. **과거 로그 CSV는 불변** — 옛 run_id의 `ma_breakout`은 읽기 시점 정규화(`ui.metrics.LEGACY_STRATEGY_NAMES`), sim 계좌 파일은 runner가 시작 시 자동 이관 (집 PC도 pull 후 첫 실행에서 자동) |
| D22 | **slug 완전성 기준 + complete-only 기본** | complete = 시작 tleft≥870 ∧ 종료 tleft≤15 ∧ 내부 갭≤60s (임계 흔들어도 200±1 견고). 엔진의 만기 강제청산(마지막 bid≈정산가)은 완전 slug에서만 참 → 백테스트 기본 complete-only, `--include-partial`은 비교용 |
| D23 | **robust 3중 기준 = config 반영 조건** | ① train 점수 상위 ② val(=out-of-sample) ≥ 0 ③ 이웃 plateau(인접 조합 비붕괴). 셋 다 만족해야 configs/ 반영, 미달이면 현행 유지 + 사유 기록 |
| D24 | **reports/ 폴더 (git track)** | 큰 작업의 착수 전 plan / 완료 후 result HTML 쌍 (`<YYYYMMDD>_<주제>_{plan|result}.html`). 문서 5개 체계(D19)는 불변 — 정본은 여전히 WORKLOG |

**데이터 인벤토리 (완전성 기준 첫 집계)**: 총 243 slugs = janfeb 189(완전 161) + mar03 18(완전 16) + sim 36(완전 23). 미완성 43개 사유: 늦은 시작 21 / 이른 종료 20 / 중간 갭 5(중복 포함)

**브리지 (현 config, 전체→완전만)**: threshold +10.99 → **+16.36** (미완성이 −5.4 왜곡) / ma +11.38 → **+3.76** (미완성이 +7.6 부풀림) — 완전성 분리의 실효 확인

**robust 판정 (완전 200 slugs, 비용 반영)**:
- **threshold 144조합 재스윕**: 어제 config(0.85/0.12/0.98/cap0.9/t450)가 score 2위 + 상위 15개 중 유일 val 양수(+1.05)로 생존. **단 이웃 6개 전부 val 음수 = 스파이크** (enter_1 ±0.05 → score −20.66/−6.20). val 견고 영역(0.9/t180 계열)은 train 음수 = 레짐 특화 → D23 완전 충족 조합 **없음**
- **ma 3,600조합 그리드**: 현 config(cap0.5/ma300/tc0/tp0.98)는 train 1위(7.78)지만 **oos(mar03+sim) −15.11 탈락** (mar03 −23.97, P1의 "MA 라이브 부적합"과 일치). train·oos 동시 양수 34/3,600뿐. 최선 영역 **cap0.45/ma200/tc0/tp0.99/cd30~90/ban80~100** (oos +3.1, tp/cd/ban 3축 plateau) — 단 ma_len 240 절벽(−14.9)·cap 스파이크, train score 1.84로 약함. 어제 후보 cap0.7/ma600은 그리드 축 밖(다음 그리드에서 축 확장 검토)
- **결론: 양 전략 config 변경 없음** (D23 미달). threshold 현행 유지(가용 최선, 신뢰도 낮음 표기), ma는 후보 영역만 기록(sim 재가동은 여전히 recorder 분리 P3와 연계)

**방향 (우선순위)**: ① sim 수집 계속 — **완전 slug 기준 목표 60** (현재 23, 게이지 30의 재해석) 후 재판정 ② P2 sim 이월 포지션 정산 수정 (✅ 저녁 완료) ③ 다음 ma 그리드에 cap 0.6~0.7 / ma_len 600 / `entry_slope_max` 축 추가 (심야 스크리닝 참조) ④ 재평가는 D23 절차로

**산출물**: `reports/20260714_backtest_cleanup_{plan,result}.html` (result에 파라미터 민감도 차트 — plateau/스파이크 시각화), `backtest/results/20260714_165927_sweep_threshold.*` · `20260714_grid_ma.*`. 테스트 57개(+4: 완전성) 통과

### 2026-07-14 (회사, 이어서) — 휩쏘 가드 `stop_confirm_sec` 구현 + 검증 (신규 유망 영역 발견, config는 유지)

**변수 기여도 프로브** (완전 200, 현 config 기준 한 축씩): dd 재진입 필터 제거 시 +16.36→**−1.29** (이 전략의 최대 기여 변수 — 재진입은 dd 필터와 세트일 때만 플러스) · 재진입 제거(max_entries=1)는 train↑ oos↓ · force_exit 50→30 소폭 개선(+17.44, 단 P2 SELL 스윕 창과 상충으로 보류)

**신규 파라미터**: `strategies/threshold.py`에 `stop_confirm_sec` — 손절 레벨 이탈이 N초(tleft 기준) **연속 유지**될 때만 exit_sl 발동, 회복 시 리셋. 기본 0(기존 동작, config 반영). 근거: 손실의 71%가 휩쏘(2026-07-13). 테스트 2개 추가(59 passed)

**스윕 (576조합 = 기존 5축 × confirm 0/5/10/20)**:
- 현 config(confirm0) 여전히 score 1위권(2/576) — 넓은 손절(0.12)에는 dwell이 **해로움** (진짜 붕괴 때 더 낮게 팔게 됨: confirm10에서 janfeb −2.86, MDD −24)
- **핵심 발견: train·val 동시 양수 18개 중 15개가 confirm>0.** dwell은 "늦은 진입(t180)"과 조합될 때 작동 — 어제 t180이 janfeb 음수로 탈락했던 약점을 dwell이 고침
- **신규 후보 영역: enter0.85 / stop 0.06~0.10 / tp0.98 / t180 / confirm 20~30** — 대표 (0.85/0.10/0.98/0.9/t180/c30): pnl +8.36, **MDD −6.8**(현행의 60%), W/L 62/19(승률 77%), janfeb +5.6 / mar03 +2.71 / sim +0.1 **전 소스 양수**. plateau: confirm축 20~30 평탄(c10 −4.4/c40 +3.5로 양끝 확인), stop_drop축 0.06~0.10 전부 양수, 이웃 both>0 = 4/8 (현 config 0/7 대비 최초의 "영역")
- 한계: 거래 수가 적어(t180 창) 총이익은 현행의 절반, oos 표본 39 slugs는 여전히 소표본 → **D23 ③ 부분 통과로 config 교체는 보류**

**결정**: config 유지(수집 표본 일관성). 후보 영역을 **차기 재판정(완전 sim 60개)의 1순위 비교 대상**으로 등록 — 재판정 시 현행 vs t180/c20~30 영역을 나란히 평가. `backtest/results/20260714_174129_sweep_threshold.*`

### 2026-07-14 (집, 저녁) — P2 sim 이월 포지션 정산 수정 + 수집 게이지를 완전 slug 기준으로 재작성

**P2 이월 버그 수정** (로드맵 P2 5번 항목 완료 — SPEC §4.5 신설):
- `core/account_sim.py`: 포지션에 매수 slug 기록 + **교차 slug exit 무시 가드** (이월 포지션이 다른 slug 가격으로 팔리는 경로 차단) + `drop_position()`(무현금 write-off)
- `core/runner.py` `settle_open_position`: slug 교체·런 종료 시 미청산 포지션을 **마지막 bid로 `exit_expiry` 강제 장부 마감** (만기 bid≈정산가, 엔진 강제청산과 동일 모델. intent+trade 정상 로깅 → 실현 PnL에 포함). 시작 시 stale 이월(slug 불일치/미기록)은 write-off — 정산가 추정 금지, 해당 slug는 D10에 의해 실현 PnL 제외. 크래시 후 같은 slug 재시작은 포지션 유지
- 유의: 과거 3건(MA +5.3 과대 / threshold −3.5~−8.8 과소)의 **장부는 소급 수정하지 않음** — trades.csv 불변 원칙, 재판정 때 보정치로만 참고

**수집 게이지 재작성** (UI가 34/39처럼 전략별 관측 누계를 30 기준으로 보여주던 문제):
- 원인: 게이지가 "전략별 slug_init 누계"였음 — ma 34는 7/12~13 병행 수집 흔적, 완전성·전략간 중복 미반영, 목표 30은 D22 이전 기준
- `ui/metrics.SlugCollection`: quote 행의 time_left로 **D22 완전성**(≥870/≤15/갭≤60s)을 증분 판정, **전략간 slug 중복 제거**. 판정 로직은 data_prep.flag_complete와 동일(상수 동기화는 테스트로 강제). 31MB events.csv 초기 스캔 0.38s
- 서버 target 60(D22 재판정 기준), API `collection = {target, complete, total, by_strategy}`. Control 탭: 완전 slug 단일 게이지 + 전략별 관측 수는 설명 줄로
- **실측 25/60 완전 (관측 41)** — 회사 집계 23 + 어젯밤 심야 수집 2로 정합

테스트 59 → **69** (account 가드 3 · settle 3 · 게이지 4). ⚠ 실행 중인 봇/UI 서버는 수정 전 코드 — **다음 재시작부터 적용** (봇 재시작 전 정지 시 이월이 남을 수 있으나 시작 시 stale-drop이 커버)

**후속 조치 (같은 저녁)**: ma 봇 정지(rc 0 — 시세는 threshold 봇 하나로 충분, 중복 기록 원위치), threshold는 새 코드로 재시작(run 20260714_231552). UI 서버 재시작은 사용자 몫으로 남김

### 2026-07-14 (집, 심야) — 신규 변수 후보 스크리닝 분석 (완전 203 slugs, 비용 haircut 0.01)

> 질문: "지금까지의 데이터로 어떤 변수를 추가하면 좋을까". 간이 리플레이 스크리닝이므로 채택 전 엔진 스윕(D23) 필수.
> 한계: threshold는 단일 진입(재진입/dd 필터 제외), ma는 양 사이드 독립 포지션 허용 — 실전략과 절대값은 다름, 변수 간 상대 비교용.

**MA — `entry_slope_max` (MA 기울기 필터) 최유망**:
- 크로스업 진입 669건 분해: MA크로스 청산 615건이 −247.6 (승률 5.9%), TP 41건이 +255.2 — 손익 구조가 "복권 + churn" (실매매 리뷰와 일치)
- **60초 MA 기울기 ≤ −0.005에서만 진입** (하락 중인 MA를 뚫는 반등 = 딥 바운스): +2.96 → **+43.40, 세 소스 전부 개선** (janfeb +23.8→+51.0 / mar03 −21.8→−12.3 / sim +1.0→+4.7), 거래 407건 유지. slope ≤ 0도 +33.7. 상승 MA 추격 진입(slope>0, 120건 −34.8)이 주된 독소였음
- 기각: dwell 확인(크로스 후 N초 유지 뒤 진입) — 사후 분석으론 "20초 유지" 여부가 승률 0.9% vs 34%로 갈리지만, **구현 가능형(확인 시점 가격 진입)은 5~30s 전부 악화** (늦은 진입가가 엣지를 잠식). 45s만 +25로 반전하나 n=80 소표본 · 비단조 → 노이즈 의심. exit band(MA−0.01/0.02 이탈 시만 청산)도 개선 없음
- 다음 ma 그리드에 축 추가: `entry_slope_max` {none, 0, −0.005, −0.01} (기존 예약분 cap 0.6~0.7 / ma_len 600과 함께)

**threshold — 브리치 순간엔 휩쏘/붕괴 구분 불가 (중요한 부정적 결과)**:
- SL 브리치 60건(휩쏘 41/붕괴 19)의 브리치 시점 특징 중앙값이 **완전 동일**: opp_bid 0.26/0.26, 스프레드 0.01/0.01, 직전 30s 낙폭 0.13/0.14, tleft 264/262 — 반대편도 같이 오르는 진짜 리프라이싱이라 "반대편 확인(flip) 가드"·"낙폭 속도" 계열은 전부 헛수고 (flip 가드 실측도 전 임계에서 악화)
- 함의: 휩쏘 대응은 브리치 판별이 아니라 **노출 시간 축소**(t180+confirm, 회사 발견)가 맞는 방향 — 그 후보 영역 우선순위 재확인
- 소소한 후보 `stop_max_spread`: 스프레드 > 0.05일 때 SL 발화 보류(호가 얇을 때 bid에 던지지 않기) — +20.4→+24.9, 단 janfeb만 개선(sim/mar03 중립)이라 2순위 스윕 축으로만 등록
- 기각: 진입 전 변동성 필터 — 중간 변동성이 최고, 저/고 양쪽 부진한 비단조(n=56/버킷)라 과적합 위험

스크립트: 세션 스크래치 analyze_vars.py / analyze_ma2.py (parquet 재생성 포함, 완전 203 = janfeb 161 + mar03 16 + sim 26)

### 2026-07-14 (집, 심야 2) — 프레임 전환 + 캘리브레이션 스터디 → `enter_stable_sec` 구현

**프레임 전환 (사용자 지적으로 확정)**: "휩쏘 71%"는 이상 현상이 아니라 **시장이 캘리브레이션돼 있다는 증거** — 손절 시점 bid(≈0.73~0.75) = 회복 확률이고 실현 회복률 68%가 일치. threshold는 상단 0.98/하단 entry−0.12 박스에서 **~52/48 확률게임을 왕복비용 ~0.02 내며 반복**하는 구조. exit 미세조정으로 EV 안 바뀜 → 레버는 ① 진입 알파 ② 왕복비용 ③ 레짐 게이트 순. 보고서 쌍: `reports/20260714_threshold_calibration_{plan,result}.html` (D24, 이후 보고서는 일자 접두 + 본문에 작성 시점 명기)

**캘리브레이션 스터디 결과 (완전 203, slug당 밴드당 1관측)**:
- **Q1 엣지의 존재**: janfeb은 0.85+ 전 밴드 완만한 저평가(+1.3~1.7%p, 방향 일관), **sim(7월)은 전 밴드 과대평가(−3.3~−6.9%p)** — 7월엔 favorite 매수 자체가 −EV. 어떤 밴드도 2se 유의는 아님(강한 엣지는 애초에 없음)
- **Q2 도달 경로 (핵심 발견)**: 실전 규칙 진입 168건 중 **78%가 0.85 돌파 <15초 스파이크 매수 = edge 0/음수**. 15~180초 유지 후 진입은 양수 edge, **janfeb·sim 방향 일치** (janfeb +0.007→+0.114, sim −0.098→+0.133). tleft 50~180 진입 edge +0.099로 t180 영역 독립 재확인. 안정 진입에선 홀드>브래킷(손절 churn이 순손실) — 필터+넓은 손절 조합 여지
- **Q3 롤링 레짐 게이트 기각**: 민감(10/0)은 janfeb 40% 훼손+sim 악화, 느슨(20/−5)은 무효과. 사전 기준 미달
- **구현**: `strategies/threshold.py`에 `enter_stable_sec` — ask ≥ enter_price_1이 N초(tleft) 연속 유지 후에만 진입, 이탈 시 리셋. **기본 0 = 현행 불변** (config 키 추가). 같은 세션 ma `entry_slope_max`와 함께 신규 변수 2개 대기 상태. 테스트 72 → **74**

**다음 스텝 (구체화 — 우선순위)**:
1. **수집 계속** → 완전 sim 60 도달 시 **D23 재판정**: sweep 축 = 기존 5축 + `stop_confirm_sec` {0,20,30} + **`enter_stable_sec` {0,15,30,60}** — 비교 대상: 현행 vs t180/c20~30 vs stable 계열 vs 조합
2. **다음 ma 그리드**: `entry_slope_max` {none, 0, −0.005, −0.01} + cap 0.6~0.7 + ma_len 600 축 (기존 예약분)
3. **P2에 추가**: maker 진입 검토(`execution.buy: "limit"` 경로 활용) — 왕복 ~$0.02가 유일한 확정 마이너스, 스프레드 절반 회수 가능. adverse selection 리스크는 live 소액에서 실측
4. 레짐 게이트: 기각. 재진입 포함 실전략 기준으로 재판정 때 1회만 재확인
5. sim이 전 밴드 −EV인 현 레짐에서는 **파라미터 교체보다 표본 확충이 계속 우선** (수집 중단 금지)

### 2026-07-15 (회사) — 수집 이어받기 + ma 그리드 slope 축 확장(풀 그리드 진행 중) + P2 exit_tp 확인

**수집**: pull(집 4커밋) 재현 확인 후 threshold sim 재개(run 20260715_154502, 15:45~17:57 그레이스풀 정지, 이월 포지션 없음). 정지 시점 **완전 35/60** (관측 threshold 52 / ma 36). 집에서 pull 후 이어받기.

**ma 그리드 확장** (심야 스크리닝 후속 — 예약분 실행. plan: `reports/20260715_ma_grid_slope_plan.html`, 가설 H1~H3 사전 등록):
- `run_grid.py` 7축으로: **`entry_slope_max` {none, 0, −0.005, −0.01}** + cap {0.7, 0.6 추가} + ma_len {600 추가} = **24,192조합**
- val 집계 정정: 기존 val_pnl=mar03만 → `mar03_pnl`/`sim_pnl` 분리 컬럼 + **val_pnl=mar03+sim** (D23 ②를 표에서 직접 읽음. 07-14 그리드의 "oos −15.11"은 수동 계산이었음 — 정식화)
- quick 32조합 스모크: **상위 8개 전부 slope −0.005** (동일 조합 train 16.4→51.2, sim +1.7→+5.8) — H1 방향이 실엔진에서 재현. 단 mar03은 여전히 음수 → 풀 그리드로 판정
- **풀 그리드 진행 중** (18시 현재 ~50%, cap 0.7/0.6 신규 구간이 리플레이 무거워 완주는 저녁 예상) → 결과: `backtest/results/20260715_155700_grid_ma.{csv,json}` (gitignore — 내일 회사에서 판정). **내일 할 일: D23 3중 기준 판정 + result 리포트**(`reports/20260715_ma_grid_slope_result.html`, 민감도 차트 포함) + WORKLOG 갱신
- 교훈: 24k 일괄 확장은 과했음 — 다음엔 신규 축만 좁게 스크리닝 후 유망 영역만 풀 그리드

**P2 "exit_tp 스윕 경로" 확인 완료** (로드맵 체크 처리): 리팩토링에서 이미 전 SELL이 IOC 스윕 경로였음 — exit_tp는 트리거 시점 bid를 limit가로 스윕 + 레벨트리거 재발화라 3/3 "FAK 한 방 no-match" 구조 해소 상태. `tests/test_executor_live.py` 6개로 라우팅·가격·부분체결 합산·dust/타임아웃/allowance 규칙 고정 (CLOB 클라이언트 모킹, .env 불필요). **부산물**: no-match 시 스윕이 고정가로 창 전체(10s)를 소진하며 메인 루프 블로킹 — P2 스레드 분리 항목에 최악 사례로 메모.

테스트 74 → **80**. 다음 세션(집): pull → 수집 재개. 그리드 판정은 회사 PC 결과 파일 기준(내일).

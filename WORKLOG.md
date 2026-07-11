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
- **Phase C — Config 탭**: 스키마 기반 폼 + 검증 + `configs/backups/` 자동 백업 + diff. `account.*` 잠금
- **Phase D — Backtest 탭**: `ui/jobs.py` — data_prep/engine/sweep/grid 백그라운드 실행 + 진행률 + 결과 아카이브(`backtest/results/`) 비교
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

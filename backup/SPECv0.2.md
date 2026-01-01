# polybots — SPEC v0.2

## 0. 목표
Polymarket(UpDown 15m) 자동매매 프로그램을 **ver1(모의계좌, read-only + 시뮬 매매 로그)** 형태로 단순 구현한다.  
구조는 10개 이하 파일 유지, VSCode + Python만으로 혼자 유지 가능한 수준을 최우선으로 한다.

---

## 1. 범위 (v0.x)
### 포함 (ver1 / TEST 단계)
- Polymarket:
  - event_url 또는 slug로부터 “현재 거래 가능한” market context를 resolve
  - YES/NO token_id를 얻고 CLOB `/book`으로 top-of-book(best bid/ask)을 1초 간격으로 수집
- 시뮬 계좌:
  - 주문을 실제로 제출하지 않음 (read-only)
  - (추후 TEST에서) 전략 조건 만족 시 가상 매수/매도 실행 및 trades.csv 기록
- 로깅:
  - snapshots.csv: 1초 단위(or 설정값) top-of-book 스냅샷 기록
  - trades.csv: 시뮬 매매 이벤트 발생 시만 기록 (진입/청산/손절/재진입 등)
- config.json으로 실행 파라미터를 모두 제어

### 제외 (ver2+)
- 실계좌 주문/서명/키 관리
- 서버 상주/자동 재시작
- WebSocket 고속 수집

---

## 2. 디렉토리 구조 (현재)
polybots/
- config.json
- requirements.txt
- state.json
- SPECv0.2.md
- REVIEW.md
- logs/
  - snapshots.csv
  - trades.csv
- src/
  - main.py
  - app.py
  - logger.py
  - sim_account.py
  - strategy.py
  - utils_time.py
  - adapters_polymarket.py
  - adapters_binance.py

---

## 3. 실행 방식
- 권장 실행: 프로젝트 루트에서
  - `py -m src.main`

(Windows에서 `py src/main.py`는 import 경로 이슈가 생길 수 있어 `-m` 권장)

---

## 4. Config 스키마 (요약)
- app.loop_interval_sec: 메인 루프 sleep 간격 (초)
- app.max_loops: 테스트 시 루프 횟수 제한 (None이면 무한)
- markets[0].event_url: polymarket event url (또는 slug 지원)
- polymarket_dynamic: slug prefix 기반으로 “현재 시간 슬롯 slug”를 동적으로 resolve (15m 등)
- logging: logs 디렉토리 및 csv 파일명

(상세 스키마는 config.json 및 REVIEW.md 참고)

---

## 5. 로그 설계
### logs/snapshots.csv
목적: “1초 단위로 top-of-book을 제대로 읽는지” 검증

기록 기준:
- 매 tick마다 기록 가능(옵션)
- 혹은 snapshot_interval_sec마다 기록 가능(옵션)

필수 컬럼(권장):
- ts_iso, slug, event_id, market_id, yes_token_id, no_token_id
- yes_bid, yes_ask, no_bid, no_ask
- loop_idx, note

### logs/trades.csv
목적: “시뮬 계좌에서 주문/체결/손익 계산이 일관되는지” 검증  
(거래 이벤트가 발생하는 시점만 기록)

필수 컬럼(권장):
- ts_iso, market_slug, side(YES/NO), action(BUY/SELL), price, size, notional_usd
- cash_before, cash_after, position_before, position_after
- reason(strategy rule), pnl_realized, fee, slippage

---

## 6. 테스트 계획 (Step-by-step)

### TEST 0 — 부트/설정/저장/종료
목표:
- config.json 로드
- state.json 로드/저장 (빈 파일/없는 파일 처리)
- 루프 max_loops 동작
- 종료 시 state 저장, 로그 디렉토리 생성

성공 기준:
- `app started` → tick 출력 → `max_loops reached -> exiting` → state 저장 로그

### TEST 1 — Polymarket top-of-book 수집 (현재 단계)
목표:
- event_url/slug → Gamma로 event/market context resolve
- YES/NO token_id 확보
- CLOB `/book`으로 best bid/ask 추출
- 1초 간격 루프에서 YES/NO top-of-book 출력 및 snapshots.csv 기록

성공 기준:
- YES/NO bid/ask가 0.01/0.99에 고정되지 않고 시장 상황에 맞게 변화
- YES/NO의 가격 레벨이 UI와 “대략” 같은 범위로 이동 (정확 일치까지는 TEST 1.1에서)

### TEST 1.1 — UI token_id 매칭 정확화 (다음 단계)
목표:
- Gamma로 받은 token_id가 UI token_id와 다를 수 있음
- “현재 화면과 동일 토큰”을 자동 선택하거나 config로 pinning

성공 기준:
- UI Order Book과 상위 N개 호가/최우선호가가 동일/근접

### TEST 1.2 — Snapshot 로깅 품질 확인
목표:
- snapshots.csv가 누락 없이 기록
- timestamp, token_id, best bid/ask가 일관적으로 채워짐

성공 기준:
- CSV가 엑셀로 열었을 때 시계열이 자연스럽고 결측치가 거의 없음(네트워크 실패 시 note에 기록)

### TEST 2 — SimAccount 기본 매수/매도
목표:
- 고정 규칙(예: 매 tick마다 소액 매수 후 즉시 매도)로 체결/잔고/손익 계산 검증

성공 기준:
- trades.csv 손익/잔고가 재현 가능하고 논리적으로 맞음

### TEST 3 — Strategy v1 (시간/확률 조건 기반) 시뮬
목표:
- “5분 남았을 때 80% 이상이면 진입” 등 규칙을 코드화
- 손절(-10%), 0.99 청산, 재진입 허용 등 확인

성공 기준:
- 전략 이벤트 발생 시 trades.csv가 의도대로 기록

### TEST 4 — Binance 연결 + ATR(d) 계산 (ver1.5)
목표:
- Binance 15m/5m klines(200개) 수집
- ATR 계산, d=abs((S0-K)/ATR) 기록
- d 조건 + 남은 시간 조건 + 가격 조건 결합

성공 기준:
- 계산값이 snapshots.csv 또는 별도 컬럼에 기록되고 재현 가능

---

## 7. 다음 세션 시작 체크리스트
- (필수) `py -m src.main`로 정상 실행되는지
- config.json의 max_loops가 반영되는지
- adapters_polymarket.py에서 best bid/ask가 max/min으로 뽑히는지
- snapshots.csv가 정상적으로 늘어나는지
- UI와의 token_id/가격대가 어긋나면 TEST 1.1로 진행


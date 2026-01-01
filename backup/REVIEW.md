# polybots — REVIEW / Logbook

## 목적
- 어디까지 진행됐는지 “되돌아보기”
- 다음 세션에서 막힘 없이 이어가기
- 에러/삽질 포인트를 기록해 재발 방지

---

## 진행 현황 요약 (현재)
- TEST 0: 완료 (부트/루프/max_loops/state 저장)
- TEST 1: 부분 성공(성공권)
  - Gamma로 slug/event → market context resolve
  - YES/NO token_id로 CLOB `/book` 호출 성공
  - best bid/ask 산출 로직 수정 후, 가격이 시장 수준으로 움직이기 시작
  - max_loops 제한 동작 확인

다음 목표:
- TEST 1.1: UI에서 보고 있는 오더북과 token_id 매칭 정밀화 (필요 시)
- 이후 SimAccount/trades.csv로 확장

---

## 지금까지 겪은 문제 / 해결 기록

### 1) Python import / 모듈 경로 이슈
증상:
- `py src/main.py` 실행 시 `No module named 'src'` 또는 `No module named 'app'` 등 발생

원인:
- 패키지 경로가 루트 기준으로 잡히지 않는 상태에서 상대 import가 깨짐

해결:
- 루트에서 `py -m src.main`로 실행을 표준으로 고정

---

### 2) state.json JSONDecodeError
증상:
- `JSONDecodeError: Expecting value: line 1 column 1` (state.json이 빈 파일)

원인:
- 빈 파일을 json.load로 읽음

해결:
- load_state에서 파일 없거나 빈 경우 default state 반환하도록 처리
- (운영) state.json은 빈 파일로 두지 말고 `{}` 또는 프로그램이 자동 생성하게 둠

---

### 3) requests 미설치 및 VSCode import 경고
증상:
- runtime: `No module named 'requests'`
- VSCode: import requests 노란 밑줄

원인:
- venv 인터프리터 불일치 or 패키지 미설치

해결:
- `pip install -r requirements.txt` 또는 `pip install requests`
- VSCode에서 Python Interpreter를 venv로 지정

---

### 4) CLOB API 404 / 잘못된 endpoint
증상:
- `/orderbook?market_id=...` 같은 경로로 404

원인:
- Gamma API와 CLOB API endpoint 혼동

해결:
- CLOB는 `https://clob.polymarket.com/book?token_id=...`
- Gamma는 `https://gamma-api.polymarket.com/...`

---

### 5) Gamma 응답 키 mismatch (clobTokenIds)
증상:
- `Market missing clobTokenIds` 예외

원인:
- 시장 데이터에서 clobTokenIds 필드가 항상 같은 키로 오지 않거나, markets 목록을 event에서 직접 받지 못하는 케이스

해결:
- adapters_polymarket.py에서
  - events/slug 응답의 `markets`가 없으면 `/markets?event_id=`로 fallback
  - `clobTokenIds` 및 변형 키들을 탐색하여 token_ids 추출

---

### 6) “호가를 가져오는데 0.01/0.99만 찍힘” 문제 (핵심)
증상:
- top-of-book이 항상 YES 0.01/0.99 같은 식으로 고정되는 것처럼 보임
- DEBUG book dump에서는 asks에 0.99,0.98,0.97... 같이 “큰 값부터” 내려옴

원인 후보 2개:
A) 오더북 레벨 배열이 정렬돼 있다는 가정이 틀렸음  
   - asks/bids가 오름차순/내림차순 보장이 없는데 첫 원소를 “최우선”으로 사용
B) UI가 보고 있는 token_id와 Gamma에서 뽑은 token_id가 다를 수 있음

해결 (A는 완료):
- best bid/ask 계산을 “정렬 가정 없이” 변경
  - best bid = max(bids.price)
  - best ask = min(asks.price)

결과:
- tick 출력이 시장 레벨로 움직이기 시작 (YES 0.58/0.59 등)

남은 가능성 (B):
- UI와 “완전 동일”한 오더북을 보려면 token_id 매칭(또는 pinning)이 필요할 수 있음
- TEST 1.1에서 처리 예정

---

## 현재 실행 로그(성공 케이스)
- `py -m src.main`
- 출력에서:
  - resolved slug
  - event_id / market_id
  - yes_token_id / no_token_id
  - DEBUG book dump (top N)
  - tick #1..#N YES bid/ask NO bid/ask
  - max_loops reached → exiting

---

## 다음에 할 테스트 (우선순위)
### (1) TEST 1.1 — UI token_id 매칭(선택)
목표:
- UI에서 보이는 오더북(상위 레벨)과 봇의 `/book`이 일치하는지 확인
방법:
- F12 Network에서 `/book?token_id=` 또는 bids/asks 응답을 찾기
- 또는 코드로 후보 token_id 쌍들을 midpoint/book로 스코어링하여 “가장 유동성/합리 가격” market 선택

성공 기준:
- UI의 top-of-book과 봇 출력이 근접/일치

### (2) TEST 1.2 — snapshots.csv 검증
목표:
- 1초 단위 기록이 누락 없이 쌓이는지
- 파일 포맷/컬럼이 안정적인지

### (3) TEST 2 — SimAccount 단순 매매 + trades.csv
목표:
- strategy 없이도 “가상 매수/매도 → 잔고/포지션/손익” 계산이 정합인지 확인

---

## 다음 세션 시작 방법 (체크리스트)
1) VSCode에서 venv 인터프리터 확인
2) `pip install -r requirements.txt`
3) `py -m src.main`
4) config.json의 `app.max_loops`가 출력에 반영되는지 확인
5) snapshots.csv 증가 확인
6) (필요 시) TEST 1.1로 token_id 매칭 정밀화 진행

---

## 파일 업데이트 정책
- 다음 세션에서 수정하는 파일:
  - src/* (필요한 곳만)
  - config.json
  - SPECv0.2.md
  - REVIEW.md
- 목표:
  - “작업 진행 로그는 REVIEW.md”
  - “현재 스펙/테스트 정의는 SPEC.md”

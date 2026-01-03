SPEC v1.6

1. Goal (목적)

(ver1) : 시뮬레이터
1.1 adapters_polymarket.py : polymarket에서 데이터를 가져옴
1.2 slug_loop.py : 1초 단위로 slug를 추적하며 quote 이벤트 스트림 생성
1.3 printer.py : 화면 출력을 이벤트 기반으로 수행
1.4 strategy.py : 전략 수행 intents 를 out
1.5 logger.py : 손익/체결/포지션 로그를 CSV로 남김 

1.6 config.json : 동작에 대한 정의
1.7 state.json : 단기 기억 저장 장치 vs 장기기억은 logger을 통해 csv화

1.8 Binance에서 데이터를 가져와서 >> adapters_binance.py
1.9 ADR계산 및 전략 구현 >> strategy.py
1.10 코드 최적화 >> legacy vs docs에서 in/out 값 다 확인하면서 코드 하나하나 최적화. 지금 가정이 너무 많음

(ver2) 부터는 동일한 전략 엔진을 사용하되, **실제 주문(거래)**까지 수행한다.
(ver3) 서버에 업로드 해서 24시간 구동

* todo
- strategy 구현
- log 수정 : event에 모든걸 구현할 필요는 없음.
>> debug 모드(config에서 설정)에서'만' events.csv 작동
>> 기본적으로는 특정 evnet(buy 등)에 대한 log들만


2. Architecture (핵심 구조)

2.1 단방향 이벤트 스트림 유지 (핵심 불변)
- 원할한 이해를 위함

config.json, state.json
   ↓ (load)
main.py
   ↓ (create)
adapters_polymarket.py
   ↓ (passed into)
slug_loop.py  ── yield event(dict) ──→ main.py (for-loop)
                                  ↓
                               strategy.py (decide)
                                  ↓
                           sim_account.py (execute)
                                  ↓
                 logger.py (append CSV) + printer.py (stdout)

* 정리
- slug_loop는 시장 관측(source): tick/quote/slug_change/exit/warn 이벤트 생성만
- strategy는 판단(decision): 이벤트를 보고 intent(주문 의도)만 생성
- main은 조립/라우팅/실행(execute)/state 업데이트
- logger/printer는 싱크(sink): 출력/기록만


3. Directory Layout(디렉토리 구조)

polybots/
- SPECv1.6.md
- CONTRACT.md
- REVIEW.md
- AGENTS.md
- requirements.txt

- config.json
- state.json

- logs/
  - snapshots.csv
  - trades.csv

- src/
  - main.py
  - adapters_polymarket.py
  - adapters_binance.py
  - slug_loop.py
  - printer.py
  - strategy.py

  - logger.py
  - sim_account.py


4. Execution (실행방식)
  : py -m src.main


5. config.json 설명

5.1 for slug
loop_mode (문자열, 필수)
 - "one": 현재 slug만 계속 폴링. 15분이 지나 slug가 바뀌면 종료
 - "rolling": slug가 바뀌면 자동으로 새 slug로 토큰을 다시 찾고 연속 폴링. (네 핵심 목적)
 - "duration": slug 여부는 rolling처럼 처리하되, run_seconds 초가 지나면 종료.
run_seconds (숫자, 기본 0)
 - loop_mode="duration"일 때만 사용.
 - 0이면 시간 종료 조건을 사용하지 않음.
max_slugs (정수, 기본 0)
 - 관측할 slug 개수 제한.
 - 0이면 무제한.
 - 예: 2면 “지금 slug + 다음 slug”까지만 확인하고 종료 → 롤오버 테스트에 최적.
print_every (정수, 기본 1)
 - 출력 빈도 제어. 1이면 매 초 출력, 5면 5초마다 한 번 출력.

5.2 그 외.
- gamma_base, clob_base, event_slug_prefix, interval_sec, timeout_sec는 adapter/slug 생성
<< 최적화를 위한 config.json의 {} 구분 고민 : 함수들이 호출할때의 구문 변경 필요


6. state.json 설명


7. Event Model

7.1 시장 이벤트 (slug_loop가 생성)

- slug_init
- slug_change
- tick
- quote (quote_updown 결과 포함)
- warn (quote fetch 실패 등)
- exit

7.2 거래/상태 이벤트

* 추가 예정


8. Strategy Rules v1(기초)

8.1 대상
- Polymarket Up/Down (15m) 게임 (slug 기준 1게임)

8.2 진입/청산 규칙 (slug당 최대 2회 진입)
- 남은 시간 7분 30초 이하에서, price ≥ 0.8이면 진입
- 진입 후 0.1 이상 하락하면 손절. 익절은 0.99
- 한 번 손절한 경우, 0.9 이상에서 재진입 가능. 익절후 재진입은 없음
- 재진입 후에도 동일하게 0.1 하락 손절, 0.99 익절
- 매수는 ask, 매도는 bid 기준으로 체결가를 

9. Logging Architecture (로그 구성)

9.1 events.csv : 디버깅/재현용 “원문 스트림”

- 목적: “그때 무슨 이벤트가 어떤 순서로 왔는지”를 100% 보존
- 내용: tick/quote/warn/slug_change/exit + (나중에) intent/fill/snapshot 이벤트도 그대로 들어갈 수 있음
- 특징: 구조가 바뀌어도 깨지지 않게 data JSON으로 통으로 박아둠

9.2 trades.csv : 분석/정산용 “체결 테이블”
- 목적: 수익률, 체결가, 횟수, 승률, 슬리피지 등 계산
- 특징: 컬럼이 고정된 정규화 테이블

9.3 snapshots.csv : 모니터링/리스크용 “계좌 시계열”
- 목적: 시간에 따른 cash/position/pnl/m2m 추이, MDD, 노출 추적
- 특징: 역시 정규화 테이블 (시계열 분석에 최적)

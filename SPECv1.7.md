SPEC v1.7

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
1) 에러 수정
2) logger 완성 >> 관리모드까지
3) 한시간 돌려보기


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
- SPECv1.7.md
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

* 네트워크설정
{
  "gamma_base": "https://gamma-api.polymarket.com",
  "clob_base": "https://clob.polymarket.com",
  "timeout_sec": 5
}
| 키             | 타입     | 설명                               |
| ------------- | ------ | -------------------------------- |
| `gamma_base`  | string | Polymarket Gamma API base URL    |
| `clob_base`   | string | Polymarket CLOB API base URL     |
| `timeout_sec` | number | HTTP 요청 timeout (초). 네트워크 지연 방지용 |

* Slug/ Loop 제어 설정
{
  "event_slug_prefix": "btc-updown-15m",
  "interval_sec": 900,
  "loop_mode": "one",
  "run_seconds": 0,
  "max_slugs": 0,
  "print_every": 1
}
| 키                   | 타입     | 설명                                      |
| ------------------- | ------ | --------------------------------------- |
| `event_slug_prefix` | string | Polymarket 이벤트 slug prefix              |
| `interval_sec`      | number | slug 단위 게임 길이 (초). 15분 = 900            |
| `loop_mode`         | string | `"one"`, `"rolling"`, `"duration"` 중 하나 |
| `run_seconds`       | number | `duration` 모드에서만 사용. 전체 실행 시간           |
| `max_slugs`         | number | 관측할 slug 개수 제한 (0 = 무제한)                |
| `print_every`       | number | printer 출력 주기 (tick 기준)                 |

loop_mode 설명
"one"
 - 현재 slug만 관측
 - slug 종료 시 프로그램 종료
"rolling"
 - slug_change 발생 시 자동으로 다음 slug로 이동
 - 연속 실행 (핵심 운영 모드)
"duration"
 - rolling처럼 동작하되
 - run_seconds 초가 지나면 종료


* Strategy 설정
{
  "strategy": {
    "enter_time_left_sec": 450,
    "enter_price_1": 0.8,
    "enter_price_re": 0.9,
    "stop_drop": 0.1,
    "take_profit": 0.99,
    "max_entries_per_slug": 2,
    "qty": 1
  }
}
| 키                      | 타입     | 설명                            |
| ---------------------- | ------ | ----------------------------- |
| `enter_time_left_sec`  | number | 만기까지 남은 시간이 이 값 이하일 때만 진입     |
| `enter_price_1`        | number | 첫 진입 시 ask 기준 최소 가격           |
| `enter_price_re`       | number | 재진입 시 ask 기준 최소 가격            |
| `stop_drop`            | number | 손절폭 (entry_price - stop_drop) |
| `take_profit`          | number | 익절 기준 (bid ≥ take_profit)     |
| `max_entries_per_slug` | number | slug당 최대 진입 횟수                |
| `qty`                  | number | 주문 수량 (시뮬레이션 단위)              |


전략 핵심 규칙 요약
- slug당 최대 max_entries_per_slug회 진입
- 손절 후 재진입 가능
- 익절 발생 시 해당 slug는 즉시 종료(tp hard-lock)

* Logging 설정 
| 키                       | 타입      | 설명                          |
| ----------------------- | ------- | --------------------------- |
| `debug_events`          | boolean | `true`일 때만 events.csv 기록    |
| `reset_events_each_run` | boolean | 실행 시작 시 events.csv를 `w`로 리셋 |

Logging 정책 : 장기 기억 저장을 위한 기능
events.csv
- 디버깅 / 재현용. 기본 OFF
- 구조 변경에 안전하도록 data(JSON) 통째로 기록

trades.csv
- 항상 기록
- intent / fill 이벤트를 정규화된 테이블로 저장

snapshots.csv
- snapshot 이벤트가 발생할 때만 기록
- 계좌 시계열 추적용


6. state.json 설명
* 설명 : 현재 실행 slug에 대한 단기 기억 저장소
- 실행 중 지속적으로 업데이트
- 프로그램 재시작 시 초기화 가능
- 항상 현재 slug 하나만 유지 (누적 금지)

* 구조 예시
{
  "schema_version": 1,
  "updated_ts": 1767455001,
  "slugs": {
    "btc-updown-15m-1767454200": {
      "entries": {
        "up": 0,
        "down": 1
      },
      "position": null,
      "last_intent": { ... },
      "tp_done": true
    }
  }
}
| 키                | 타입     | 설명                      |
| ---------------- | ------ | ----------------------- |
| `schema_version` | number | state 구조 버전             |
| `updated_ts`     | number | 마지막 업데이트 시각 (epoch sec) |
| `slugs`          | object | **현재 slug 하나만**을 키로 가짐  |


* slug 상태
{
  "entries": { "up": 0, "down": 1 },
  "position": null,
  "last_intent": { ... },
  "tp_done": true
}
| 키             | 타입          | 설명                      |
| ------------- | ----------- | ----------------------- |
| `entries`     | object      | 방향별 진입 횟수               |
| `position`    | object/null | 현재 보유 포지션               |
| `last_intent` | object/null | 마지막 전략 의사결정             |
| `tp_done`     | boolean     | 익절 발생 여부 (true면 재진입 금지) |

* position 구조
{
  "side": "up",
  "qty": 1,
  "entry": 0.82,
  "entry_tick": 123,
  "entry_time": 1767454000
}


7. Strategy Rules v1(기초)

7.1 대상
- Polymarket Up/Down (15m) 게임 (slug 기준 1게임)

7.2 진입/청산 규칙 (slug당 최대 2회 진입)
- 남은 시간 7분 30초 이하에서, price ≥ 0.8이면 진입
- 진입 후 0.1 이상 하락하면 손절. 익절은 0.99
- 한 번 손절한 경우, 0.9 이상에서 재진입 가능. 익절후 재진입은 없음
- 재진입 후에도 동일하게 0.1 하락 손절, 0.99 익절
- 매수는 ask, 매도는 bid 기준으로 체결가를 


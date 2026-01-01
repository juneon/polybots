SPEC v1.2

1. Goal (목적)

(ver1) 
1.1 Polymarket에서 데이터를 가져와서 >> adapters_polymarket.py
1.2 가상 매매 시뮬레이션을 수행 >> strategy.py
1.3 손익/체결/포지션 로그를 CSV로 남김 >> logger.py
1.4 Binance에서 데이터를 가져와서 >> adapters_binance.py
1.5 ADR계산 및 전략 구현 >> strategy.py
1.6 코드 최적화 >> legacy vs docs에서 in/out 값 다 확인하면서 코드 하나하나 최적화. 지금 가정이 너무 많음


(ver2) 부터는 동일한 전략 엔진을 사용하되, **실제 주문(거래)**까지 수행한다.
(ver3) 서버에 업로드 해서 24시간 구동


2. 디렉토리 구조

polybots/
- SPECv0.2.md
- REVIEW.md

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
  - strategy.py
  - logger.py
  - sim_account.py

3. 실행방식
  - py -m src.main

4. config.json 설명
loop_mode (문자열, 필수)
 - "one": 현재 slug만 계속 폴링. 15분이 지나 slug가 바뀌어도 무시하고 기존 토큰으로만 조회.
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

5. stats.json 설명

6. 테스트 계획

6.1 루프 구성
- 특정 시간 or 몇 초. 동안 best bid/ask price를 갖고 올지

6.2.1 전략 구성
- 7분 30초 이하로 남았을 때 0.8 이상이면 진입. 0.1 이상 빠지면 손절 0.99에 익절
- 한 번 손절한 경우 0.9 이상에 재진입. 0.1 이상 빠지면 손절 0.99에 익절
>> 따라서 slug 당 최대 2번 진입
* 매수할때는 ask 매도할때는 bid

6.2.2 로그 남기기
- 한 게임에 대해서
- 반복되는 게임에 대해서

7. 파일별 역할분리 : 가정. 수정가능
7.1 sim_account.py
- cash
- positions
- place_market_buy()
- place_market_sell()
- mark_to_market()

* 가상 계좌/ 포지션/ 체결관리

7.2 logger.py
logger.log_trade(...)
logger.log_snapshot(...)
등..

* /log 관리

7.3 main.py
- config/state load
- adapter 호출
- strategy.동작()
- logger 호출
- state save
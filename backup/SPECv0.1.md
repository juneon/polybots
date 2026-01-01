# Polymarket Auto Trading (Sim) - SPEC v0.1

## 0. 목적
- Polymarket 이벤트(Up/Down 등)에서 **모의 계좌(sim account)** 기반 자동매매 시스템을 구축한다.
- ver1 목표:
  1) Polymarket top-of-book(최우선 호가) 데이터를 안정적으로 수집
  2) Binance 5m/15m 캔들 기반 ATR 및 d 계산(ver1.5)
  3) 단순 전략 조건에 따라 모의 매수/매도 수행
  4) 실제 투입 전 검증 가능한 최소 로그(trades/snapshots)를 남긴다

## 1. 범위 / 버전 정의
### ver1: 모의 자동매매 + Polymarket 데이터
- Polymarket: market 정보 및 bid/ask(top-of-book) 수집
- 모의 계좌: 포지션/현금/손익 업데이트
- 전략(ver1 기본):
  - 남은 시간 <= 5분 AND 확률(가격) >= 0.80 → 진입
  - 진입 대비 -10% 손절(재진입 가능)
  - 0.99에 매도(익절)

### ver1.5: ATR/d 조건 추가 + Binance 데이터
- Binance: 15m/5m 캔들(기본 200개) 수집
- ATR(15m/5m) 계산
- d = abs(S0 - K) / ATR_15m 기록
- 진입 조건 추가:
  - d >= 0.8 AND 남은 시간 <= 7분 30초 AND (ver1 진입조건 유지)

### ver2: 실계좌 연결(소액 테스트)
- Polymarket 주문(실거래) 연결
- 슬리피지/체결/부분체결 등 현실 요소 반영

### ver3: 서버 상시 구동
- 재부팅/재실행 자동화, 장애 복구, 24/7 운영

## 2. 운영 원칙(단순성)
- 파일 수 10개 이하 유지(초기 8~9개)
- main은 최대한 얇게 유지
- adapters는 Polymarket / Binance로 분리
- 전략 로직은 strategy.py로 고립(다른 곳에 흩뿌리지 않기)
- DB 금지, CSV 로그 + state.json만 사용

## 3. 디렉토리 구조(초기)
polybots/
  SPECv0.1.md
  REVIEW.md
  requirements.txt
  config.json
  state.json                 # 런타임 자동 생성/갱신
  /src
    main.py
    app.py
    adapters_polymarket.py
    adapters_binance.py
    strategy.py
    sim_account.py
    logger.py
    utils_time.py            # optional
  /logs
    trades.csv
    snapshots.csv

## 4. 데이터 소스
### 4.1 Polymarket
- 입력: event URL 또는 slug
- 출력:
  - market_id
  - K(기준 가격, strike 성격)
  - 만료 시간(expiry)
  - top-of-book: YES bid/ask, NO bid/ask

**주의**
- ver1에서는 orderbook 전체 depth 필요 없음(최우선 호가만).
- fetch 주기 1초(기본), 저장(스냅샷) 주기 10초(기본).

### 4.2 Binance
- 입력: symbol (예: BTCUSDT)
- 출력:
  - 현재가 S0
  - klines 15m/5m 각 200개(기본)
  - ATR_15m, ATR_5m

## 5. 핵심 지표
- S0: Binance 현재가
- K: Polymarket 이벤트 기준가격(Up/Down의 기준)
- ATR_15m, ATR_5m: strategy.py에서 계산
- d: abs(S0 - K) / ATR_15m

## 6. 모의 계좌(sim account) 규칙
- 단일 포지션(0 또는 1)만 허용(ver1 단순화)
- 체결가 규칙(기본):
  - BUY(진입): 해당 side의 ask 가격으로 체결
  - SELL(청산): 해당 side의 bid 가격으로 체결
- 수수료/슬리피지:
  - ver1 기본 0으로 두고 config로 켜기(옵션)
- state.json에 최소 상태 저장:
  - cash, position, pnl_realized, last_action_time

## 7. 전략 규칙
### 7.1 ver1 (기본)
- Enter:
  - time_to_expiry_sec <= 300
  - price >= 0.80
- Stop:
  - price <= entry_price * 0.90
- Take:
  - price >= 0.99
- Re-enter:
  - 손절 후 조건 재충족 시 재진입 가능
  - (옵션) 재진입 쿨다운 seconds 적용 가능(config)

### 7.2 ver1.5 (추가 필터)
- Enter 조건에 추가:
  - d >= 0.8
  - time_to_expiry_sec <= 450
  - AND ver1 Enter 조건도 만족

## 8. 로깅 설계(CSV)
### 8.1 trades.csv (이벤트 로그)
- 거래 발생 시점만 기록
- 목적: 전략 의사결정/체결 규칙/손익 검증

권장 컬럼:
- ts, market_id, action(BUY/SELL), side(YES/NO)
- size_usd, fill_price
- best_bid, best_ask
- fee_usd, slippage_bps
- equity_before, equity_after
- reason(enter_80, stop_-10, take_99, manual_test 등)

### 8.2 snapshots.csv (관측 로그)
- 시장 상태를 샘플링 기록(기본 10초)
- 목적: 데이터 수집 안정성 + 조건 충족 타이밍 확인

권장 컬럼:
- ts, market_id, time_to_expiry_sec
- yes_bid, yes_ask, no_bid, no_ask
- S0, K, atr_15m, atr_5m, d
- strategy_signal(0/1), position(0/1)

**중요**
- 모든 호가(depth)를 저장하지 않는다.
- “1초 단위 확인”은 fetch는 1초로 하되, 저장은 10초(기본) + 디버그 모드에서만 1초 저장.

## 9. 테스트 단계(정의)
- Test 0: 환경/실행
- Test 1: Polymarket top-of-book 수집 안정성(거래 없음)
- Test 2: Binance klines/ATR 수집 및 계산(거래 없음)
- Test 3: 결합 스냅샷(d/신호 기록) 검증(거래 없음)
- Test 4: 강제 주문(모의 BUY/SELL) 체결 규칙 검증
- Test 5: ver1 전략 자동 실행 검증
- Test 6: ver1.5(ATR/d) 조건 추가 후 진입 변화 검증

각 테스트의 통과 기준/체크리스트는 REVIEW.md에서 관리한다.

## 10. 예외/실패 처리(초기 정책)
- API 실패 시:
  - n회 재시도 후 스킵(다음 루프)
- 데이터 None / 시간 역행 / 음수 스프레드:
  - snapshots에 error flag 기록
  - trade는 금지(보수적으로)

## 11. 다음 확장 포인트(ver2/ver3)
- 실주문 실행 레이어 추가(Polymarket auth)
- 체결/부분체결/취소 처리
- 서버 프로세스 관리, 재시작 복구, 알림

## 12. config.json 스키마 정의

## config.json 스키마(설명)
- `app`
    - `loop_interval_sec` (number): fetch 주기(기본 1)
    - `snapshot_interval_sec` (number): snapshots 저장 주기(기본 10)
    - `debug_snapshot_every_tick` (bool): true면 1초마다 snapshot 저장(디버그 모드)
    - `timezone` (string): 기본 "Asia/Seoul"
- `markets` (array)
    - `name` (string): 사용자 친화 이름
    - `event_url` (string): polymarket event url (또는 slug를 별도 필드로 둘 수도 있음)
    - `binance_symbol` (string): 예 "BTCUSDT"
    - `side_preference` (string): "YES" 또는 "NO" (ver1 단순화를 위한 기본 거래 방향)
- `sim_account`
    - `initial_cash_usd` (number)
    - `bet_fraction` (number): 0~1 (총자산 대비 1회 베팅 비중)
    - `max_position_usd` (number): 1회 최대 베팅액 상한
    - `fee_bps` (number): 수수료 bps(0이면 비활성)
    - `slippage_bps` (number): 슬리피지 bps(0이면 비활성)
    - `allow_reentry` (bool)
    - `reentry_cooldown_sec` (number)
- `strategy`
    - `version` (string): "v1" 또는 "v1.5"
    - `enter_time_left_sec` (number): 300
    - `enter_min_price` (number): 0.80
    - `stop_loss_pct` (number): 0.10 (진입 대비 -10%)
    - `take_profit_price` (number): 0.99
    - `d_threshold` (number): 0.8 (v1.5에서 사용)
    - `d_time_left_sec` (number): 450 (v1.5에서 사용)
    - `atr_period` (number): ATR 기간(기본 14)
    - `klines_limit` (number): 캔들 개수(기본 200)
- `logging`
    - `logs_dir` (string): "logs"
    - `trades_file` (string): "trades.csv"
    - `snapshots_file` (string): "snapshots.csv"
    - `write_headers_if_missing` (bool)



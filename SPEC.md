# SPEC v3.1 — polybots 통합 명세

> v2.1까지의 단일-프로젝트 구조(polybots_pre/polybots_MA)를 공유 코어 + 전략 플러그인 모노레포로 통합.
> v3.1 (2026-07-12): backtest 엔진 통일(§9) · Control UI/tests 추가(§10) · 로드맵을 WORKLOG로 이관(§11).
> 이 문서는 **시스템의 현재 모습**만 기술한다. 결정/진행/로드맵은 WORKLOG.md, 문서 맵은 DOCS.md.

## 1. Goal

- Polymarket BTC Up/Down 15분 마켓(slug 단위 1게임)을 1초 tick으로 관측·매매.
- 하나의 코어 엔진 위에서 여러 전략을 플러그인으로 운용 (1 전략 = 1 모듈 + 1 config).
- sim(모의)과 live(실거래)는 Account/Executor 교체로만 전환. 전략 코드는 동일.

## 2. Architecture — 단방향 이벤트 스트림 (핵심 불변)

```
configs/<strategy>.json
        ↓
core/runner.py  (--strategy --mode)
        ↓
core/adapters_polymarket.py     (HTTP: Gamma 1회/slug, CLOB 4회/tick, 재시도+백오프)
        ↓
core/slug_loop.py               → event(dict): slug_init | slug_change | quote | warn | exit
        ↓
strategies/<name>.py            → intents (list[dict])     ← account.position 읽기 전용(SOT)
        ↓
core/executor_{sim|live}.py     → trade(dict): filled | submitted | rejected
        ↓
core/account_{sim|live}.py      ← trade 적용 (filled만 상태 변경, SOT)
        ↓                        ↘ strategy.on_trade(trade)  (체결 피드백)
core/logger.py + core/printer.py  (sink)
```

원칙:
- **Strategy는 체결에 관여하지 않는다.** intent 발행 시점에 내부 포지션/카운터를 미리 바꾸지 않는다(낙관적 설정 금지). 체결 피드백은 `on_trade`로만 수신.
- **Executor는 상태를 가지지 않는다.**
- **Account는 단일 진실(SOT).** 포지션 존재/side/entry의 진실은 account.position.
- 시간 판단은 `time_left_sec`(tleft)로 통일. `ts`는 로그 전용.

## 3. 실행

```
python -m core.runner --strategy <name> --mode <sim|live> [--config path]
```
- `--mode` 기본 sim. live는 CLI로만 활성화 (config가 아님).
- config 기본 경로: `configs/<strategy>.json`
- 매 실행마다 `run_id`(`YYYYMMDD_HHMMSS_<strategy>_<mode>`)가 모든 CSV 행에 기록됨.

## 4. 이벤트/데이터 스키마

### 4.1 quote 이벤트 (slug_loop → strategy)
```json
{
  "type": "quote", "slug": "btc-updown-15m-<epoch>",
  "slug_start_ts": 0, "time_left_sec": 0, "tick": 0,
  "quote": {
    "up":   {"outcome": "Up",   "token_id": "...", "bid": "0.57", "ask": "0.58"},
    "down": {"outcome": "Down", "token_id": "...", "bid": "0.42", "ask": "0.43"}
  }
}
```
- bid/ask 컨벤션(2026-07-06 오더북 대조 검증 완료): `bid = /price?side=buy`(최고 매수호가), `ask = /price?side=sell`(최저 매도호가).

### 4.2 intent (strategy → executor)
```json
{
  "type": "intent", "kind": "buy | exit_tp | exit_sl | exit_time",
  "slug": "...", "tick": 0, "side": "up | down",
  "price": 0.58, "qty_tokens": 10.0, "time_left_sec": 0, "ts": 0
}
```
- quote 1개당 intent 0~1개. 우선순위: 청산 → 진입.
- price: buy는 대상 side의 ask, exit는 보유 side의 bid.

### 4.3 trade (executor → account/strategy/logger)
```json
{
  "type": "trade", "kind": "...", "slug": "...", "tick": 0, "side": "...",
  "ts": 0, "status": "filled | submitted | rejected", "reason": "",
  "token_id": "...", "qty_tokens": 0.0, "fill_price": 0.0,
  "data": {}, "debug": {}
}
```
- `filled`만 account 상태를 바꾼다. `submitted`(체결 미확인 잔류 주문)는 전략이 보수적으로 처리(중복 주문 방지 래치).

### 4.4 account (SOT, 읽기 전용 조회)
- `cash: float` — 명목 현금 흐름(수수료 미포함, 잔고 검증 아님)
- `position: dict | None` — `{"side", "entry", "qty_tokens", "notional_usd", ("token_id")}`
- `state: dict` — `{"slug_idx", "entries": {"up","down"}, "tp_done"}`
- live: `sync_position()`(매도 직전 잔고 정정, 0-래깅 가드), `reconcile_from_clob()`(slug 경계 정합화)

## 5. 컴포넌트 명세 (IN/OUT)

| 모듈 | 목적 | IN | OUT |
|---|---|---|---|
| `core/adapters_polymarket.py` | Gamma(slug→token_id, slug당 1회 캐시) + CLOB(/price, tick당 4회). HTTP 재시도 2회+백오프 | slug, config | quote dict |
| `core/slug_loop.py` | 1초 tick으로 slug 추적, 이벤트 스트림 생성. loop_mode: one/rolling/duration | adapter, config | event(dict) 스트림 |
| `strategies/*.py` | quote 해석 → intent 생성. account 읽기 전용 | event, account, config | intents |
| `core/executor_sim.py` | 100% 체결 가정, intent 가격으로 fill | intent, quote_ev | trade |
| `core/executor_live.py` | 실주문. BUY=GTC 1샷, SELL=IOC 스윕(잔고 폴링, 최대 sell_sweep_window_sec) | intent, quote_ev, account | trade |
| `core/account_sim.py` | 모의 계좌. sim_account.json 영속화 | trade(filled) | 상태 |
| `core/account_live.py` | 실계좌 상태. dust 임계, 래깅 가드, slug 경계 reconcile | trade(filled), CLOB 잔고 | 상태 |
| `core/logger.py` | CSV 기록. **append 모드 + run_id** | event/intent/trade, account | logs/*.csv |
| `core/printer.py` | 사람이 읽는 tick 출력 (MA 등 전략 debug 포함) | quote_ev, account, strategy | stdout |
| `core/runner.py` | 조립 + 라우팅 + CLI(`--run-id` 포함). KeyboardInterrupt 시 로그 정상 close | argv, config | — |
| `core/control.py` | stop-file 감지 + heartbeat 원자적 기록 (UI 연동, CLI 단독 실행에도 무해) | run_id | `logs/ctl/<run_id>.status.json` |

## 6. 전략 명세

### 6.1 공통 인터페이스 (`strategies/base.py`)
- `on_event(ev, account) -> list[intent]` — quote 소비, 의사결정. account 변경 금지.
- `on_trade(trade) -> None` — 체결 피드백. **filled 확인 후에만** 내부 카운터/락/쿨다운 갱신.
- `debug_state(slug) -> dict` — printer용 읽기 전용 상태 (선택).

### 6.2 ma_breakout (구 polybots_MA) — `configs/ma_breakout.json`

백테스트 근거: 2026-01~02 7일치 그리드 서치 최적값 (cap=0.5, ma=300, tc=0, cd=0 → PnL $81.7, score 73.7).

진입 (무포지션일 때만):
- side의 **ask ≤ cap**(0.5)이고 ask가 ask-SMA(ma_len=300틱)를 **상향돌파**하는 tick에 매수.
- 후보가 둘이면 더 싼 ask 선택. `tick_confirm > 0`이면 N틱 연속 유지 확인 후 진입.
- `no_entry_last_sec` 마감 구간, `cooldown_sec`(체결 후), `buy_inflight`(미확인 잔류 주문) 동안 진입 금지.

청산 (보유 중):
- **TP**: 보유 side의 bid ≥ `tp_abs`(0.98) → `exit_tp` (레벨 조건 — 자연 재시도)
- **MA 이탈**: 보유 side의 bid가 bid-SMA를 하향돌파 → `exit_time` (엣지 조건 — **exit_armed 래치**로 체결 확인까지 매 tick 재발행)

| 파라미터 | 의미 | 현재값 |
|---|---|---|
| `qty_tokens` | 주문 수량(토큰) | 10 |
| `cap` | 진입 상한 (ask ≤ cap) | 0.5 |
| `ma_len` | SMA 윈도우(tick). 워밍업 동안(≈ma_len초) 진입 불가 | 300 |
| `tick_confirm` | 0=돌파 tick 진입, N=연속 N틱 확인 | 0 |
| `cooldown_sec` | 매수 체결 후 재진입 금지 시간 | 0 |
| `no_entry_last_sec` | 마감 N초 전 진입 금지 (null=비활성) | null |
| `tp_abs` | 익절 bid 임계 (null=비활성) | 0.98 |

### 6.3 threshold (구 polybots_pre) — `configs/threshold.json`

진입 (무포지션 + `t_deadline < tleft ≤ t_enter` 윈도우):
- side = Up/Down 중 **ask가 더 높은 쪽**(우세측).
- `ask > entry_cap`(0.9)이면 거부.
- 첫 진입(n=0): `ask ≥ enter_price_1`(0.8).
- 재진입(n≥1): **손절 체결 확정 후에만**, `ask ≥ enter_price_re`(0.8), (선택) dd 필터 —
  최근 `dd_window_sec`(120초, tleft 기준) 내 peak bid 대비 `dd = cur_bid − peak ≤ reentry_dd_min`(−0.15)일 때만.
- slug당 최대 `max_entries_per_slug`(2)회 — **체결(filled) 기준 카운트**.

청산 (보유 중, 우선순위순 — 모두 레벨 조건, 체결까지 자연 재시도):
1. `tleft ≤ force_exit_left_sec`(50) → `exit_time`
2. `bid ≥ take_profit`(0.98) → `exit_tp` — 체결 확정 시 slug hard-lock(재진입 금지)
3. `bid ≤ entry − stop_drop`(0.06) → `exit_sl` — 체결 확정 시 재진입 허용 플래그

## 7. config 공통 키

| 키 | 의미 |
|---|---|
| `gamma_base` / `clob_base` | Polymarket API base URL |
| `event_slug_prefix` | 이벤트 slug prefix (`btc-updown-15m`) |
| `interval_sec` | slug 게임 길이(900 = 15분) |
| `timeout_sec` | HTTP 타임아웃 |
| `loop_mode` | `one` / `rolling`(운영) / `duration` |
| `run_seconds` / `max_slugs` | duration 시간 / slug 수 제한 (0=무제한) |
| `print_every` | printer 출력 주기(tick) |
| `execution.buy/tp/sl/time` | kind별 주문 모드 (market=슬리피지 가산, limit=intent 가격) |
| `execution.slippage/buy_cap/sell_floor` | market 모드 가격 보정 한계 |
| `execution.sell_sweep_window_sec/poll_sec` | live SELL IOC 스윕 창/폴링 주기 |
| `logging.events/trades/snapshots` | CSV별 기록 on/off |
| `account.user/chain_id/signature_type/buy_size_tokens/post_only` | live 계정/주문 파라미터 |

시크릿(.env, gitignore됨): `PM_PRIVATE_KEY`, `PM_USER` — live 모드에서만 필요.

## 8. Logging 정책

- 모든 CSV는 **append 모드** — 실행해도 과거 기록이 지워지지 않는다. `run_id` 컬럼으로 실행 구분.
- `events.csv`: 원본 이벤트(JSON 통째). 백테스트 데이터 수집원. slug 경계에서만 flush.
- `trades.csv`: intent+trade 결합 1행. 즉시 flush.
- `snapshots.csv`: filled 발생 tick의 계좌 스냅샷. 즉시 기록.

## 9. Backtest (2026-07-12 엔진 통일)

- `backtest/engine.py`가 **유일한 엔진** — 실제 `strategies/` 코드를 on_event/on_trade 파이프라인 그대로 리플레이 + 비용 모델(BUY=intent가, SELL=bid−haircut, p_fail 확률 거부). `from engine import replay, prepare_slugs`.
- `run_grid.py`(ma_breakout 그리드)와 `sweep_threshold.py`(threshold 스윕)는 engine.replay의 fan-out — **전략 로직 재구현 없음** (구 backtest.py는 폐기, git 이력 참조).
- 모든 스크립트가 `--json <path>` 요약 출력 → UI Backtest 탭이 `backtest/results/`에 아카이브.
- 파이프라인 절차 / 비용 캘리브레이션 / train-val 검증 규칙: `backtest/README.md`.

## 10. Control UI · tests (2026-07 추가)

- `ui/` — 로컬 웹 대시보드 (FastAPI, **127.0.0.1:8787 전용**, `python -m ui.server`): 봇 프로세스 제어(stop-file/heartbeat = core/control.py 경유, 크래시 격리), 성과 집계(trades.csv), config 편집(검증+자동 백업), 백테스트 job 실행/아카이브/비교. **live 시작은 Phase E까지 서버가 403 거부. 서버는 .env를 절대 읽지 않음.**
- `tests/` — pytest 단위 테스트 (전략 체결 피드백 불변식, account SOT, logger append, 성과 집계, config 검증, 엔진 비용 모델). `python -m pytest tests/ -q`.

## 11. 알려진 한계 / 로드맵

정본은 `WORKLOG.md`의 "로드맵" 섹션 (P0 수집 → P2 실행품질 → P3 인프라 → P4 확장, live 재개 기준 포함).

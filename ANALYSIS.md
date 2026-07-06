# polybots 분석 및 리팩토링 리포트

> 작성일: 2026-07-06 | 분석 대상: polybots_pre, polybots_MA, polybots_backtest
> 이 문서는 리팩토링 전 전체 분석 결과와, Phase 0~2에서 실제 적용한 수정사항의 기록이다.

---

## 1. 세 프로젝트의 관계 (분석 결과)

```
polybots_backtest ──(그리드 서치로 최적 파라미터 발견)──▶ polybots_MA
polybots_pre ──────(폴더 통째로 복사 후 전략 교체)──────▶ polybots_MA
```

- **polybots_pre와 polybots_MA는 같은 git 저장소의 사본.** 커밋 3개(`178b161`→`7936e95`→`774a47b`)가 완전히 동일하고, 모든 차이는 커밋되지 않은 로컬 수정에만 존재했다.
- **polybots_backtest**의 그리드 서치 최적값(cap=0.5, ma=300, tick_confirm=0, cooldown=0, ban=none → PnL $81.7, score 73.7, 3,600조합 중 1위)이 polybots_MA의 config와 정확히 일치 — 백테스트 결과를 그대로 MA 봇에 반영한 흐름.
- src 10개 파일 중 **6개는 두 프로젝트가 바이트 단위로 동일** (adapter, slug_loop, executor_sim, account_sim, account_live, logger). 4개만 상이 (strategy, executor_live, main, printer).

## 2. 작동 방식 요약

### 공통 아키텍처 (단방향 이벤트 스트림)
```
config.json → main.py
  slug_loop(1초 tick, 15분 slug 추적) → quote 이벤트
    → strategy.on_event() → intent
      → executor.fill() → trade (py_clob_client → Polymarket CLOB)
        → account.apply() → 포지션/현금 갱신 (SOT)
          → logger(CSV) + printer(콘솔)
```
BTC 15분 Up/Down 마켓(`btc-updown-15m`)을 1초마다 관측. Gamma API로 slug→token_id(slug당 1회 캐시), CLOB `/price`로 bid/ask(tick당 4회).

### 전략 비교
| | polybots_pre (threshold) | polybots_MA (ma_breakout) |
|---|---|---|
| 철학 | 강한 쪽 추종: ask ≥ 0.8인 우세 side 매수 | 저가 돌파: ask ≤ 0.5에서 SMA(300틱) 상향돌파 매수 |
| 손절 | entry − 0.06, 손절 후 dd 필터로 1회 재진입 | 고정 손절 없음, bid의 SMA 하향돌파 시 청산 |
| 익절 | bid ≥ 0.98 | bid ≥ 0.98 |
| 매도 실행 | 잔고 80% 게이트 + FAK 루프(≤2.5초, 가격 점증 하향) | IOC 스윕(≤10초, 0.5초 잔고 폴링) — 잔고 반영 지연 대응 개선판 |
| 진입 시간창 | 450초~80초 전 | 제한 없음(옵션) |

### polybots_backtest
7일치 events.csv를 로드해 6개 파라미터축 3,600조합을 완전탐색하는 단일 스크립트. MA 전략의 파라미터 근거.

## 3. 발견된 문제점

### 🔴 위험 (실거래 계좌 관련)
1. **`.env`(지갑 개인키)가 .gitignore에 없음** — 우연히 untracked였을 뿐, `git add .` 한 번이면 개인키 커밋. 양쪽 모두 해당.
2. **전략-계좌 포지션 분열**: MA 전략이 intent 생성 시점에 `self.position`을 낙관적으로 설정. 실주문 거부/미체결 시 전략은 "보유 중"으로 착각(재진입 안 함, 없는 포지션 청산 시도). slug 경계 reconcile은 계좌만 고침 → 최대 15분 불일치. pre도 동일 패턴(n/stopped/lock을 intent 시점에 변경 — 거부된 매수가 진입 슬롯을 소모).
3. **bid/ask 라벨 의심** → **검증 결과 문제 없음** (§5.2 참조).
4. **`except Exception: pass` 남발** — 인증 실패·reconcile 실패·저장 실패가 전부 무음. 실거래 봇에서 최악의 패턴.

### 🟡 구조/신뢰성
5. 라이브 코드 전체가 미커밋 상태 (커밋 3개는 sim 시절 코드).
6. 데드 코드: pre 루트의 `account.py`/`executor.py`(구버전 모놀리스, 동일 클래스명 — footgun), MA의 sim 경로 전체(main이 LIVE 하드코딩), `sl_abs`·`SELL_MIN_TOKENS` 등 반쯤 연결된 기능.
7. **로그 덮어쓰기**: logger가 `"w"` 모드 → 실행할 때마다 과거 기록 전멸.
8. 완전 동기/블로킹: tick당 순차 HTTP 4회(타임아웃 5초), 매도 스윕 10초간 루프 정지.
9. 네트워크 재시도/백오프 없음 — 일시 오류 = tick 유실.
10. MA 전략의 slug별 상태 dict가 rolling 모드에서 무한 증가(메모리 누수).

### 🟢 가독성/문서
11. **MA의 SPECv2.1.md가 완전히 낡음** — pre의 threshold 전략을 설명(두 SPEC이 동일 파일). MA 전략 규칙은 어디에도 미문서화.
12. 6개 동일 파일의 복제 관리, `_f`/`st`/`px` 축약명, `sum` 내장 섀도잉, 레거시 키 fallback, 한/영 혼용 주석, 빈 `.claude` 설정.

## 4. 적용한 수정사항

### Phase 0 — 안전 조치 ✅
- 양쪽 레거시 저장소 `.gitignore`에 `.env`, `logs/`, `sim_account.json` 추가.
- 현재 워킹트리를 스냅샷 커밋 (MA: `d0129ca`, pre: `3c2186c`) — 리팩토링 전 복구 지점 확보.
- 추적 중이던 `logs/*.csv`를 인덱스에서 제거.

### Phase 1 — 모노레포 재구성 ✅
루트에 **공유 코어 + 전략 플러그인** 구조 신설:
```
polybots/
├── CLAUDE.md            # Claude Code용 프로젝트 가이드 + 안전 규칙
├── SPEC.md              # 현행화된 통합 명세 v3.0 (MA 전략 규칙 최초 문서화)
├── ANALYSIS.md          # 본 문서
├── .claude/settings.json# sim 실행/git 허용, .env 읽기 차단
├── .gitignore           # .env, logs/, 레거시 폴더 제외
├── requirements.txt
├── configs/             # 전략별 설정 (threshold.json, ma_breakout.json)
├── core/                # 공유 엔진 (단일 소스)
│   ├── adapters_polymarket.py, slug_loop.py
│   ├── executor_sim.py, executor_live.py     # live: MA의 IOC 스윕판으로 통일
│   ├── account_sim.py, account_live.py
│   ├── logger.py, printer.py
│   └── runner.py        # 통합 CLI: python -m core.runner --strategy X --mode sim|live
├── strategies/
│   ├── base.py          # BaseStrategy 인터페이스 (on_event / on_trade / debug_state)
│   ├── threshold.py     # 구 polybots_pre 전략
│   └── ma_breakout.py   # 구 polybots_MA 전략
└── backtest/            # backtest.py + data/*.csv (이동)
```
- **sim이 기본 모드.** live는 CLI `--mode live`로만 활성화 (config로 켜지지 않음).
- 데드 코드 미이관: pre 루트 모놀리스, sl_abs, SELL_MIN_TOKENS, observe_* 스텁 제거.
- 레거시 3개 폴더는 읽기 전용 아카이브로 보존 (루트 git에서 제외).

### Phase 2 — 정확성 버그 수정 ✅ (신규 코드에 반영)
| # | 수정 | 위치 |
|---|---|---|
| 1 | **낙관적 포지션 설정 제거** — 포지션 진실은 account(SOT), 전략은 읽기만. 내부 카운터/락/쿨다운은 `on_trade(trade)`에서 filled 확인 후에만 갱신 | `strategies/base.py`, `ma_breakout.py`, `threshold.py`, `core/runner.py` |
| 2 | 거부된 매수가 진입 슬롯을 소모하지 않음 (자연 재시도). `submitted`(미확인 잔류 주문)는 중복 주문 방지 래치로 보수 처리 | `threshold.py:on_trade`, `ma_breakout.py:buy_inflight` |
| 3 | MA 하향돌파 청산(엣지 신호)에 **exit_armed 래치** — 매도 실패 시 체결까지 매 tick 재발행 (구 코드는 실패 시 만기까지 방치) | `ma_breakout.py` |
| 4 | bid/ask 매핑 라이브 검증 → **올바름 확정** (§5.2) | `core/adapters_polymarket.py` 주석 |
| 5 | `except: pass` 제거 → `logging` 경고/에러로 표면화 (인증 실패는 ERROR) | `core/executor_live.py`, `account_sim.py`, `logger.py`, `runner.py` |
| 6 | HTTP 재시도 2회 + 백오프 추가 | `core/adapters_polymarket.py:get` |
| 7 | **로그 append 모드 + run_id 컬럼** — 실행해도 과거 기록 보존, run별 구분 가능 | `core/logger.py` |
| 8 | KeyboardInterrupt/예외 시에도 로그 정상 close (try/finally) | `core/runner.py` |
| 9 | MA slug 상태 dict를 slug 전환 시 정리 (메모리 누수 제거) | `ma_breakout.py:_on_slug_change` |
| 10 | sim/live 포지션 dust 임계 통일 (0.01) | `core/account_sim.py` |

### 검증 ✅
- **오프라인 파이프라인 테스트 7건 통과**: threshold 진입→TP→락 / SL→재진입 / 거부매수 재시도, ma_breakout 돌파진입→TP / exit_armed 래치 재시도 (구 코드에서 버그였던 시나리오 포함).
- **실데이터 sim 스모크**: ma_breakout 35초(시세 수신·MA 계산·진입 체결·로그 기록 확인), threshold 12초(slug 전환 처리 확인). 로그 CSV에 run_id 정상 기록.
- **bid/ask 검증**: CLOB `/price` vs `/book` 대조 2회 — 기존 컨벤션 올바름 확정.

## 5. 참고 데이터

### 5.1 그리드 서치 상위 결과 (polybots_backtest, 3,600조합)
| cap | ma | tc | tp/sl | cd | ban | trades | PnL($) | score |
|---|---|---|---|---|---|---|---|---|
| 0.5 | 300 | 0 | none | 0 | none | 505 | 81.66 | 73.75 |
| 0.5 | 200 | 0 | none | 60 | none | 401 | 81.11 | 72.56 |
| 0.5 | 240 | 0 | none | 0 | none | 694 | 78.89 | 67.96 |

### 5.2 bid/ask 검증 (2026-07-06, btc-updown-15m-1783349100)
```
/price?side=buy  = 0.59  == book best_bid (최고 매수호가)
/price?side=sell = 0.60  == book best_ask (최저 매도호가)
→ 프로젝트 컨벤션 (bid=side:buy, ask=side:sell) 올바름. 반전 버그 없음.
```

## 6. 남은 작업 (Phase 3+, 미적용)

- [ ] tick당 HTTP 4회 순차 호출 병렬화 또는 WebSocket 전환
- [ ] live SELL 스윕(≤10초)의 메인 루프 블로킹 → 스레드 분리
- [ ] backtest의 전략 재구현 → 코어 전략 클래스 직접 리플레이로 통합
- [ ] 주문 전 실제 USDC 잔고 가드 (현재 cash는 명목 흐름)
- [ ] slug 경계 404 폴백 (로컬 시계 기반 slug 계산의 레이스)
- [ ] GTC 잔류 주문 추적/취소 (현재는 buy_inflight 래치로 중복만 방지)
- [ ] 레거시 폴더 3개: 새 구조 안정화 확인 후 삭제 또는 압축 보관
- [ ] ver4(ETH/SOL/XRP), ver5(Binance ATR): strategies/ + configs/ 추가로 대응

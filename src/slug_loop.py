# src/slug_loop.py
import time
from typing import Dict, Iterator, Optional, Any


Event = Dict[str, Any]


def run_slug_loop(pm, cfg: dict) -> Iterator[Event]:
    """
    출력/프린터를 전혀 모르는 '정석' 구현.
    - 이벤트(dict)를 yield하는 generator
    - main(혹은 상위)이 이 이벤트를 printer/strategy/logger로 분배

    생성 이벤트 타입:
      - {"type": "slug_init", "slug": str, "observed_slugs": int}
      - {"type": "slug_change", "from": str, "to": str, "observed_slugs": int, "loop_mode": str}
      - {"type": "tick", "tick": int, "slug": str}
      - {"type": "quote", "tick": int, "slug": str, "quote": dict}
      - {"type": "warn", "tick": int, "slug": str, "message": str}
      - {"type": "exit", "reason": str, "meta": {...}}
    """

    loop_mode = str(cfg.get("loop_mode", "rolling")).lower()
    if loop_mode not in ("one", "rolling", "duration"):
        raise ValueError(f"invalid loop_mode: {loop_mode}")

    run_seconds = int(cfg.get("run_seconds", 0))
    max_slugs = int(cfg.get("max_slugs", 0))
    print_every = int(cfg.get("print_every", 1))

    poll_interval = 1  # 합의: 항상 1초

    start_time = time.time()
    deadline: Optional[float] = None
    if loop_mode == "duration" and run_seconds > 0:
        deadline = start_time + run_seconds

    last_slug: Optional[str] = None
    observed_slugs = 0  # 최초 slug 포함
    tick = 0

    while True:
        now = time.time()

        # duration 종료
        if deadline is not None and now >= deadline:
            yield {
                "type": "exit",
                "reason": "duration reached",
                "meta": {"run_seconds": run_seconds, "observed_slugs": observed_slugs, "tick": tick},
            }
            return

        # 현재 slug 계산
        slug, _ = pm.slug_now()

        # slug 초기화 / 변화 감지
        if last_slug is None:
            last_slug = slug
            observed_slugs = 1

            yield {"type": "slug_init", "slug": last_slug, "observed_slugs": observed_slugs}

            # max_slugs 체크 (예: 1이면 첫 slug만 보고 종료)
            if max_slugs > 0 and observed_slugs >= max_slugs:
                yield {
                    "type": "exit",
                    "reason": "max_slugs reached",
                    "meta": {"max_slugs": max_slugs, "observed_slugs": observed_slugs, "tick": tick},
                }
                return

        elif slug != last_slug:
            # one: slug 바뀌는 순간 종료
            if loop_mode == "one":
                yield {
                    "type": "slug_change",
                    "from": last_slug,
                    "to": slug,
                    "observed_slugs": observed_slugs + 1,
                    "loop_mode": loop_mode,
                }
                yield {
                    "type": "exit",
                    "reason": "loop_mode=one (slug changed)",
                    "meta": {"from": last_slug, "to": slug, "tick": tick},
                }
                return

            # rolling / duration: slug 갱신하고 계속
            prev = last_slug
            last_slug = slug
            observed_slugs += 1

            yield {
                "type": "slug_change",
                "from": prev,
                "to": last_slug,
                "observed_slugs": observed_slugs,
                "loop_mode": loop_mode,
            }

            if max_slugs > 0 and observed_slugs >= max_slugs:
                yield {
                    "type": "exit",
                    "reason": "max_slugs reached",
                    "meta": {"max_slugs": max_slugs, "observed_slugs": observed_slugs, "tick": tick},
                }
                return

        # 항상 tick 이벤트는 발생 (상위에서 상태/로그에 활용 가능)
        assert last_slug is not None
        yield {"type": "tick", "tick": tick, "slug": last_slug}

        # quote 이벤트는 print_every에 맞춰서만 발생
        if print_every > 0 and tick % print_every == 0:
            try:
                q = pm.quote_updown(last_slug)
                yield {"type": "quote", "tick": tick, "slug": last_slug, "quote": q}
            except Exception as e:
                yield {
                    "type": "warn",
                    "tick": tick,
                    "slug": last_slug,
                    "message": f"data not ready yet: {e}",
                }

        tick += 1
        time.sleep(poll_interval)

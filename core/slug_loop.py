# core/slug_loop.py
"""Market observation loop (the single event Source).

Yields event dicts:
  slug_init / slug_change / quote / warn / exit

loop_mode:
  - "one":      observe current slug; exit when the slug ends
  - "rolling":  keep running across slug changes (main operating mode)
  - "duration": like rolling, but stop after run_seconds
"""
import time
from typing import Any, Dict, Iterator


def slug_loop(pm, cfg: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    interval_sec = int(cfg.get("interval_sec", 900))
    loop_mode = str(cfg.get("loop_mode", "one"))
    run_seconds = int(cfg.get("run_seconds", 0))
    max_slugs = int(cfg.get("max_slugs", 0))

    start_wall = time.time()

    last_slug = None
    slug_count = 0
    tick = 0

    def _time_left(slug_start_ts: int, now_ts: int) -> int:
        return (slug_start_ts + interval_sec) - now_ts

    while True:
        loop_t0 = time.perf_counter()
        tick += 1

        now_ts = int(time.time())
        slug, slug_start_ts = pm.slug_now()
        time_left_sec = _time_left(slug_start_ts, now_ts)

        # ---- duration stop condition ----
        if loop_mode == "duration" and run_seconds > 0:
            elapsed = time.time() - start_wall
            if elapsed >= run_seconds:
                yield {
                    "type": "exit",
                    "reason": "duration_elapsed",
                    "elapsed_sec": int(elapsed),
                    "tick": tick,
                    "slug": slug,
                    "slug_start_ts": slug_start_ts,
                    "time_left_sec": time_left_sec,
                }
                return

        # ---- one-mode: slug rolled over -> first slug is done, exit ----
        if loop_mode == "one" and last_slug is not None and slug != last_slug:
            yield {
                "type": "exit",
                "reason": "slug_changed",
                "tick": tick,
                "slug": last_slug,
                "slug_start_ts": slug_start_ts,
                "time_left_sec": 0,
            }
            return

        # ---- slug init / change ----
        if slug != last_slug:
            slug_count += 1
            yield {
                "type": "slug_change" if last_slug is not None else "slug_init",
                "slug": slug,
                "slug_start_ts": slug_start_ts,
                "time_left_sec": time_left_sec,
                "slug_count": slug_count,
                "tick": tick,
            }
            last_slug = slug

            if max_slugs > 0 and slug_count >= max_slugs:
                yield {
                    "type": "exit",
                    "reason": "max_slugs_reached",
                    "max_slugs": max_slugs,
                    "slug_count": slug_count,
                    "tick": tick,
                    "slug": slug,
                    "slug_start_ts": slug_start_ts,
                    "time_left_sec": time_left_sec,
                }
                return

        # ---- quote per tick ----
        try:
            quote = pm.quote_updown(slug)
            yield {
                "type": "quote",
                "slug": slug,
                "slug_start_ts": slug_start_ts,
                "time_left_sec": time_left_sec,
                "tick": tick,
                "quote": quote,
            }
        except Exception as e:
            yield {
                "type": "warn",
                "slug": slug,
                "slug_start_ts": slug_start_ts,
                "time_left_sec": time_left_sec,
                "tick": tick,
                "error": repr(e),
            }

        # ---- one-mode safety net ----
        if loop_mode == "one" and time_left_sec <= 0:
            yield {
                "type": "exit",
                "reason": "slug_ended",
                "tick": tick,
                "slug": slug,
                "slug_start_ts": slug_start_ts,
                "time_left_sec": time_left_sec,
            }
            return

        elapsed = time.perf_counter() - loop_t0
        sleep_sec = 1.0 - elapsed
        if sleep_sec > 0:
            time.sleep(sleep_sec)

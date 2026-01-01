# src/printer.py
from typing import Dict, Any


class Printer:
    """
    slug_loop가 만들어낸 이벤트를 받아 '출력'만 담당.
    - slug_loop에 대한 의존성 없음
    - tick 카운트는 이벤트에 포함된 값을 사용 (printer가 tick을 소유하지 않음)
    """

    def __init__(self):
        pass

    def handle(self, event: Dict[str, Any]) -> None:
        t = event.get("type")

        if t == "slug_init":
            slug = event["slug"]
            print("\n=== SLUG INIT ===")
            print(f"slug : {slug}")
            return

        if t == "slug_change":
            frm = event["from"]
            to = event["to"]
            loop_mode = event.get("loop_mode", "")
            observed = event.get("observed_slugs", "?")

            if loop_mode == "one":
                print("\n=== SLUG CHANGE (one) ===")
                print(f"from : {frm}")
                print(f"to   : {to}")
            else:
                print("\n=== SLUG CHANGE ===")
                print(f"from : {frm}")
                print(f"to   : {to}")
                print(f"observed_slugs : {observed}")
            return

        if t == "quote":
            tick = int(event["tick"])
            slug = event["slug"]
            q = event["quote"]

            up = q["up"]
            down = q["down"]

            # 요구사항: [000xxx] slug 전체 출력
            print(f"\n[{tick:06d}] {slug}")
            print(
                f"{'Up':<5}: best_ask(market buy) / best_bid(market sell) : "
                f"{up['ask']} / {up['bid']}"
            )
            print(
                f"{'Down':<5}: best_ask(market buy) / best_bid(market sell) : "
                f"{down['ask']} / {down['bid']}"
            )
            return

        if t == "warn":
            msg = event.get("message", "")
            print(f"[warn] {msg}")
            return

        if t == "exit":
            reason = event.get("reason", "unknown")
            print(f"exit: {reason}")
            return

        # tick 등 출력 필요 없는 이벤트는 무시
        return

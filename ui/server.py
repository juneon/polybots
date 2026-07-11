# ui/server.py
"""Local control dashboard server.

    python -m ui.server          ->  http://127.0.0.1:8787

Binds to 127.0.0.1 ONLY — never expose this on a network interface.
This process never reads .env; live credentials stay with the bot process
(and live mode itself is refused server-side until Phase E).
"""
from __future__ import annotations

import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from strategies import REGISTRY
from .procman import ProcManager
from .metrics import SlugCollection

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"

HOST = "127.0.0.1"
PORT = 8787
COLLECTION_TARGET = 30  # P0 goal: slugs to collect before re-running the backtest (STATUS.md)

app = FastAPI(title="polybots control", docs_url=None, redoc_url=None)
procman = ProcManager()
collection = SlugCollection()


class BotReq(BaseModel):
    strategy: str
    mode: str = "sim"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/strategies")
def strategies():
    out = []
    for name in sorted(REGISTRY):
        cfg = ROOT / "configs" / f"{name}.json"
        out.append({"name": name, "config_exists": cfg.exists()})
    return out


@app.get("/api/status")
def status():
    return {
        "server_ts": int(time.time()),
        "bots": procman.status(),
        "collection": {
            "target": COLLECTION_TARGET,
            "slugs": collection.counts(),
        },
    }


@app.post("/api/bot/start")
def bot_start(req: BotReq):
    if req.strategy not in REGISTRY:
        raise HTTPException(404, f"unknown strategy: {req.strategy}")
    if req.mode != "sim":
        raise HTTPException(403, "live mode is disabled in the UI until Phase E")
    try:
        return procman.start(req.strategy, req.mode)
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@app.post("/api/bot/stop")
def bot_stop(req: BotReq):
    try:
        return procman.stop(req.strategy)
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@app.post("/api/bot/stop_all")
def bot_stop_all():
    return procman.stop_all()


def main():
    print(f"[ui] polybots control -> http://{HOST}:{PORT}   (Ctrl-C to quit)")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()

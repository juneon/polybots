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

from typing import Any, Dict, Optional

from strategies import REGISTRY
from .procman import ProcManager
from .metrics import SlugCollection, PerfReport
from . import configstore
from .configstore import ConfigError
from . import jobs as btjobs
from .jobs import JobError, JobManager

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"

HOST = "127.0.0.1"
PORT = 8787
COLLECTION_TARGET = 30  # P0 goal: slugs to collect before re-running the backtest (STATUS.md)

app = FastAPI(title="polybots control", docs_url=None, redoc_url=None)
procman = ProcManager()
collection = SlugCollection()
perf = PerfReport()
jobman = JobManager()


class BotReq(BaseModel):
    strategy: str
    mode: str = "sim"


class ConfigChanges(BaseModel):
    changes: Dict[str, Any]


class BacktestReq(BaseModel):
    kind: str
    strategy: Optional[str] = None
    params: Dict[str, Any] = {}


def _is_running(strategy: str) -> bool:
    return any(b["strategy"] == strategy for b in procman.status())


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


@app.get("/api/perf")
def perf_report():
    return perf.report()


@app.get("/api/config/{strategy}")
def config_get(strategy: str):
    if strategy not in REGISTRY:
        raise HTTPException(404, f"unknown strategy: {strategy}")
    try:
        d = configstore.describe(strategy)
    except FileNotFoundError:
        raise HTTPException(404, f"config not found: configs/{strategy}.json")
    d["running"] = _is_running(strategy)
    return d


@app.put("/api/config/{strategy}")
def config_put(strategy: str, req: ConfigChanges):
    if strategy not in REGISTRY:
        raise HTTPException(404, f"unknown strategy: {strategy}")
    try:
        res = configstore.apply_changes(strategy, req.changes)
    except FileNotFoundError:
        raise HTTPException(404, f"config not found: configs/{strategy}.json")
    except ConfigError as e:
        raise HTTPException(400, str(e))
    res["running"] = _is_running(strategy)
    return res


@app.get("/api/backtest/data")
def backtest_data():
    return btjobs.data_status()


@app.post("/api/backtest/run")
def backtest_run(req: BacktestReq):
    try:
        return jobman.submit(req.kind, req.strategy, req.params, list(REGISTRY))
    except JobError as e:
        raise HTTPException(400, str(e))


@app.get("/api/backtest/jobs")
def backtest_jobs():
    return {"jobs": jobman.status(), "data": btjobs.data_status()}


@app.get("/api/backtest/jobs/{job_id}")
def backtest_job(job_id: str):
    try:
        return jobman.get(job_id)
    except JobError as e:
        raise HTTPException(404, str(e))


@app.post("/api/backtest/jobs/{job_id}/cancel")
def backtest_cancel(job_id: str):
    try:
        return jobman.cancel(job_id)
    except JobError as e:
        raise HTTPException(404, str(e))


@app.get("/api/backtest/results")
def backtest_results():
    return btjobs.results_list()


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

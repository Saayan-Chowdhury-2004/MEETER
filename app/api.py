"""FastAPI local control API (spec §43).

Binds to 127.0.0.1 only. No internet-facing API.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.agent import Agent
from app.config import AppConfig
from app.storage.repository import Repository
from app.storage.sqlite import Database

app = FastAPI(title="Meeting Agent", version="0.1.0", docs_url="/docs")

_agent: Optional[Agent] = None
_repo: Optional[Repository] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


def init(agent: Agent, repo: Repository) -> None:
    global _agent, _repo, _loop
    _agent = agent
    _repo = repo
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        _loop = None


def _require_agent() -> Agent:
    if _agent is None:
        raise HTTPException(status_code=503, detail="agent not initialized")
    return _agent


# -- schemas -----------------------------------------------------------
class ModeIn(BaseModel):
    mode: str


class CommandIn(BaseModel):
    text: str


class RuleIn(BaseModel):
    instruction: str


class ConfirmIn(BaseModel):
    event_id: str


# -- endpoints -----------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status():
    a = _require_agent()
    data = a.state.model_dump()
    data["uptime_seconds"] = _uptime(a)
    data["pending_confirmations"] = len(a._pending_confirmations)
    return data


def _uptime(agent) -> Optional[float]:
    if not agent.state.started_at:
        return None
    try:
        from datetime import datetime

        started = datetime.fromisoformat(agent.state.started_at)
        return max(0.0, (datetime.now(started.tzinfo) - started).total_seconds())
    except Exception:  # noqa: BLE001
        return None


@app.get("/mode")
def get_mode():
    a = _require_agent()
    return {"mode": a.mode}


@app.post("/mode")
def set_mode(body: ModeIn):
    a = _require_agent()
    if not a.set_mode(body.mode):
        raise HTTPException(status_code=400, detail="invalid mode")
    return {"mode": a.mode}


@app.get("/events")
def events(limit: int = 50):
    _require_agent()
    assert _repo is not None
    return _repo.recent_events(limit)


@app.get("/rules")
def rules():
    a = _require_agent()
    return {"rules": a.rules.describe()}


@app.post("/rules")
def add_rule(body: RuleIn):
    a = _require_agent()
    return {"result": a.compile_rule(body.instruction)}


@app.delete("/rules/{rule_id}")
def delete_rule(rule_id: str):
    a = _require_agent()
    ok = a.rules.remove_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="rule not found")
    return {"deleted": rule_id}


class RuleToggleIn(BaseModel):
    enabled: bool


@app.post("/rules/{rule_id}/toggle")
def toggle_rule(rule_id: str, body: RuleToggleIn):
    a = _require_agent()
    ok = a.rules.set_enabled(rule_id, body.enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="rule not found")
    return {"id": rule_id, "enabled": body.enabled}


@app.post("/commands")
def commands(body: CommandIn):
    a = _require_agent()
    return {"result": a.handle_command(body.text)}


@app.post("/action/confirm")
def action_confirm(body: ConfirmIn):
    a = _require_agent()
    d = a.confirm_action(body.event_id)
    if d is None:
        raise HTTPException(status_code=404, detail="no pending action for this event")
    return {"approved": True}


@app.post("/action/reject")
def action_reject(body: ConfirmIn):
    a = _require_agent()
    d = a.reject_action(body.event_id)
    if d is None:
        raise HTTPException(status_code=404, detail="no pending action for this event")
    return {"approved": False}


@app.post("/pause")
def pause():
    _require_agent().pause()
    return {"status": "paused"}


@app.post("/resume")
def resume():
    a = _require_agent()
    if a.state.emergency_stop:
        a.clear_emergency()
        return {"status": "running", "emergency_cleared": True}
    a.resume()
    return {"status": "running"}


@app.post("/emergency-stop")
def emergency_stop():
    _require_agent().emergency_stop()
    return {"status": "emergency-stopped"}


@app.get("/")
def dashboard():
    index = Path("frontend/dashboard/index.html")
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"error": "dashboard not built"}, status_code=404)

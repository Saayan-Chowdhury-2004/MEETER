"""API tests (spec §43) using httpx against the FastAPI app with a test agent."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(test_agent):
    from app import api
    from app.storage.repository import Repository

    # reuse the test agent's repo
    api.init(test_agent, test_agent.repo)
    from fastapi import FastAPI  # noqa: F401  (ensure module loaded)

    return TestClient(api.app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_mode_roundtrip(client, test_agent):
    r = client.get("/mode").json()
    assert r["mode"] == "observe"
    assert client.post("/mode", json={"mode": "assist"}).json()["mode"] == "assist"
    assert client.post("/mode", json={"mode": "bogus"}).status_code == 400


def test_emergency_stop_endpoint(client, test_agent):
    client.post("/emergency-stop")
    assert test_agent.state.emergency_stop is True
    client.post("/resume")
    assert test_agent.state.emergency_stop is False


def test_events_and_rules(client):
    assert client.get("/events").status_code == 200
    r = client.get("/rules").json()
    assert "rules" in r


def test_command_endpoint(client):
    r = client.post("/commands", json={"text": "what did you detect?"}).json()
    assert "0 events" in r["result"]

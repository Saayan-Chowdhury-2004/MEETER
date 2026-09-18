"""Shared test fixtures.

Everything runs with mock capture/OCR so tests never touch the real screen.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("MEETING_AGENT_ENABLE_AUTOMATION", "0")


@pytest.fixture()
def blank_frame():
    def _make(color=(40, 40, 44)):
        return np.full((360, 640, 3), color, dtype=np.uint8)

    return _make


@pytest.fixture()
def tmp_db():
    with tempfile.TemporaryDirectory() as d:
        from app.storage.repository import Repository
        from app.storage.sqlite import Database

        db = Database(os.path.join(d, "test.db"))
        yield Repository(db)
        db.close()


@pytest.fixture()
def test_agent(tmp_db):
    """Agent wired to mock providers, automation disabled, OBSERVE mode."""
    from unittest.mock import patch

    from app.agent import Agent
    from app.config import AppConfig, PolicyConfig
    from app.intelligence.vlm import MockVLMProvider
    from app.perception.ocr import MockOCRProvider
    from app.perception.url_detector import URLDetector
    from app.grounding.omniparser import MockGroundingProvider, UIElement

    cfg = AppConfig()
    cfg.automation.enabled = False
    cfg.automation.dry_run = True
    cfg.policy.confidence_threshold = 0.95
    cfg.policy.allowed_domains = ["github.com", "forms.google.com"]
    cfg.policy.mode_capabilities = {
        "observe": [],
        "suggest": [],
        "assist": ["open_url", "switch_window", "open_application", "scroll"],
        "autonomous": ["open_url", "click", "type_text", "key_press", "scroll", "open_application", "switch_window", "copy_text"],
    }

    with patch("app.agent.get_ocr_provider", return_value=MockOCRProvider()), patch(
        "app.agent.get_grounding_provider", return_value=MockGroundingProvider()
    ), patch("app.agent.get_vlm_provider", return_value=MockVLMProvider()):
        agent = Agent(cfg, tmp_db)
    # no capture in most tests; tick() not exercised here
    return agent

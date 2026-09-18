"""Action schema validation (spec §15/§52).

Validates that a proposed action carries the right payload for its type.
Purely deterministic — no model output is trusted without this.
"""
from __future__ import annotations

from typing import Optional

from app.events.models import Action

_REQUIRED = {
    "open_url": ["url"],
    "click": ["target"],
    "type_text": ["text"],
    "key_press": ["key"],
    "scroll": [],  # amount optional
    "open_application": ["application"],
    "switch_window": ["window_title"],
    "copy_text": [],  # copies current selection
}


def validate_action(action: Action) -> tuple[bool, str]:
    required = _REQUIRED.get(action.type.value)
    if required is None:
        return False, f"unknown action type: {action.type}"
    for field in required:
        value = getattr(action, field, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            return False, f"action type {action.type.value} missing required field '{field}'"
    if action.type.value == "open_url":
        from urllib.parse import urlparse

        p = urlparse(action.url or "")
        if p.scheme not in ("http", "https") or not p.hostname:
            return False, f"invalid URL: {action.url!r}"
    return True, "ok"

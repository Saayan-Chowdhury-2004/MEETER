"""Action risk classes (spec §17)."""
from __future__ import annotations

from app.events.models import Action, Risk

_LOW_RISK = {
    "open_url",  # further gated by domain allowlist
    "scroll",
    "switch_window",
    "open_application",
    "copy_text",
}

_MEDIUM_RISK = {
    "click",  # unknown button — medium by default
    "type_text",
    "key_press",
}

# Anything not in low/medium is treated as HIGH and blocked by default.
# submit_form / delete_file / execute_shell / send_email / purchase /
# account_setting_change are intentionally absent from the action schema.


def classify(action: Action) -> Risk:
    t = action.type.value
    if t in _LOW_RISK:
        return Risk.LOW
    if t in _MEDIUM_RISK:
        return Risk.MEDIUM
    return Risk.HIGH

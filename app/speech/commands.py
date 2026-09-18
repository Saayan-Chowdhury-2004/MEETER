"""Voice/text command parsing (spec §28).

Commands are matched deterministically — the emergency stop must never depend
on a model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class Command:
    name: str
    argument: Optional[str] = None


_PATTERNS = [
    ("emergency_stop", re.compile(r"\b(stop|stop agent|emergency stop)\b", re.IGNORECASE)),
    ("pause", re.compile(r"\b(pause|pause agent)\b", re.IGNORECASE)),
    ("resume", re.compile(r"\b(resume|resume agent)\b", re.IGNORECASE)),
    ("take_over", re.compile(r"\btake over\b", re.IGNORECASE)),
    ("manual_mode", re.compile(r"\bmanual mode\b", re.IGNORECASE)),
    ("what_detected", re.compile(r"\bwhat did you detect\b", re.IGNORECASE)),
    ("what_did", re.compile(r"\bwhat did you do\b", re.IGNORECASE)),
    ("show_rules", re.compile(r"\bshow (active )?rules\b", re.IGNORECASE)),
    ("disable_rule", re.compile(r"\bdisable (?:the )?rule (.+)$", re.IGNORECASE)),
    ("enable_rule", re.compile(r"\benable (?:the )?rule (.+)$", re.IGNORECASE)),
    ("mode", re.compile(r"\b(mode|switch to) (observe|suggest|assist|autonomous)\b", re.IGNORECASE)),
]


def parse_command(text: str) -> Optional[Command]:
    t = (text or "").strip()
    if not t:
        return None
    for name, pattern in _PATTERNS:
        m = pattern.search(t)
        if m:
            arg = m.group(2) if m.lastindex and m.lastindex >= 2 and name in ("disable_rule", "enable_rule", "mode") else (m.group(1) if m.lastindex else None)
            if name == "mode":
                arg = m.group(2)
            elif name in ("disable_rule", "enable_rule"):
                arg = m.group(1)
            else:
                arg = None
            return Command(name=name, argument=arg)
    return None

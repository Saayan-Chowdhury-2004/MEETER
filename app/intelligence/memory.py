"""Short-term memory for reasoning context (spec §14/§55).

Bounded deque of recent event summaries only — no image data. Kept in RAM.
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Deque, List

from app.events.models import Event


class EventMemory:
    def __init__(self, max_items: int = 100) -> None:
        self._dq: Deque[str] = deque(maxlen=max_items)
        self._lock = threading.Lock()

    def remember(self, event: Event) -> None:
        summary = f"{event.timestamp} {event.type.value} {event.url or event.text[:60]}"
        with self._lock:
            self._dq.append(summary)

    def recent(self, n: int = 5) -> List[str]:
        with self._lock:
            items = list(self._dq)
        return items[-n:]

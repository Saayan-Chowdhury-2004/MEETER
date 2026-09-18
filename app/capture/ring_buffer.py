"""RAM ring buffer for short-term visual context (spec §24/§25).

Frames live in RAM only. Old frames expire automatically after
`ring_buffer_seconds`. No disk persistence unless `persist_frames` is enabled
(explicitly off by default).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Deque, List, Optional

from app.types import Frame

log = logging.getLogger(__name__)


class RingBuffer:
    """Adaptive one-minute RAM ring buffer."""

    def __init__(self, max_seconds: float = 60.0, max_frames: int = 600) -> None:
        self.max_seconds = max_seconds
        self.max_frames = max_frames
        self._dq: Deque[Frame] = deque(maxlen=max_frames)

    def push(self, frame: Frame) -> None:
        self._dq.append(frame)
        self._expire()

    def _expire(self) -> None:
        cutoff = time.time() - self.max_seconds
        while self._dq and self._dq[0].timestamp < cutoff:
            f = self._dq.popleft()
            f.image = None  # type: ignore[assignment] — free pixels promptly

    def snapshot(self) -> List[Frame]:
        self._expire()
        return list(self._dq)

    def latest(self) -> Optional[Frame]:
        self._expire()
        return self._dq[-1] if self._dq else None

    def burst(self, seconds: float = 5.0) -> List[Frame]:
        """Recent frames around an event, for VLM context."""
        self._expire()
        cutoff = time.time() - seconds
        return [f for f in self._dq if f.timestamp >= cutoff]

    def __len__(self) -> int:
        self._expire()
        return len(self._dq)

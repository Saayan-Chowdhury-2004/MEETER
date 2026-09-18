"""Asynchronous in-process event bus (spec §44).

Deliberately simple: asyncio queues, no broker. Topic-based fan-out so the
pipeline stages can subscribe independently.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Dict, List

from app.events.models import Event

log = logging.getLogger(__name__)

Handler = Callable[[Event], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._queues: Dict[str, List[asyncio.Queue]] = {}
        self._tasks: List[asyncio.Task] = []

    def subscribe(self, topic: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._queues.setdefault(topic, []).append(q)
        return q

    def unsubscribe(self, topic: str, q: asyncio.Queue) -> None:
        if topic in self._queues and q in self._queues[topic]:
            self._queues[topic].remove(q)

    async def publish(self, topic: str, event: Event) -> None:
        for q in list(self._queues.get(topic, [])):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("Event bus queue full on topic %s; dropping event", topic)

    def publish_sync(self, topic: str, event: Event) -> None:
        """Publish from non-async code by scheduling on the running loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.warning("publish_sync called without running loop; dropping event")
            return
        loop.create_task(self.publish(topic, event))


bus = EventBus()

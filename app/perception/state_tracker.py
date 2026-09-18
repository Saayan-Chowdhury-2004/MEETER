"""State tracking and deduplication (spec §12).

Keeps hashes of seen messages/URLs/buttons/notifications so identical content
does not re-trigger actions. Bounded LRU-style sets keep memory flat over an
8-hour meeting.
"""
from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Any, Dict, Optional, Set


def _hash(obj: Any) -> str:
    if isinstance(obj, str):
        data = obj.encode("utf-8", "ignore")
    else:
        data = repr(obj).encode("utf-8", "ignore")
    return hashlib.sha1(data).hexdigest()[:16]


class BoundedSeenSet:
    """LRU-bounded set of content hashes with TTL."""

    def __init__(self, max_entries: int = 2000, ttl_seconds: int = 8 * 3600) -> None:
        self.max_entries = max_entries
        self.ttl = ttl_seconds
        self._items: "OrderedDict[str, float]" = OrderedDict()

    def seen(self, key: str) -> bool:
        h = _hash(key)
        ts = self._items.get(h)
        if ts is None:
            return False
        if time.time() - ts > self.ttl:
            del self._items[h]
            return False
        self._items.move_to_end(h)
        return True

    def mark(self, key: str) -> None:
        h = _hash(key)
        self._items[h] = time.time()
        self._items.move_to_end(h)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)


class StateTracker:
    """Tracks what the agent has already seen to produce deduplicated events."""

    def __init__(self, max_entries: int = 2000) -> None:
        self.seen_messages = BoundedSeenSet(max_entries)
        self.seen_urls = BoundedSeenSet(max_entries)
        self.seen_buttons = BoundedSeenSet(max_entries)
        self.seen_notifications = BoundedSeenSet(max_entries)
        self.last_active_window: Optional[str] = None

    def is_new_url(self, url: str) -> bool:
        return not self.seen_urls.seen(url)

    def remember_url(self, url: str) -> None:
        self.seen_urls.mark(url)

    def is_new_message(self, text: str) -> bool:
        return not self.seen_messages.seen(text)

    def remember_message(self, text: str) -> None:
        self.seen_messages.mark(text)

    def is_new_button(self, label: str, bbox) -> bool:
        key = f"{label}@{tuple(bbox)}"
        return not self.seen_buttons.seen(key)

    def remember_button(self, label: str, bbox) -> None:
        self.seen_buttons.mark(f"{label}@{tuple(bbox)}")

    def is_new_notification(self, text: str) -> bool:
        return not self.seen_notifications.seen(text)

    def remember_notification(self, text: str) -> None:
        self.seen_notifications.mark(text)

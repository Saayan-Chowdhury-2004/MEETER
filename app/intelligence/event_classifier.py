"""Deterministic event classification (spec §10/§11).

Turns raw perception output (OCR text of a changed region) into structured
events. URL detection stays deterministic; VLM is never used for URL
extraction.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from app.events.models import Event, EventType
from app.perception.url_detector import URLDetector

log = logging.getLogger(__name__)

_FORM_HINTS = re.compile(r"\b(form|questionnaire|survey)\b", re.IGNORECASE)
_BUTTON_HINTS = re.compile(r"^\s*(submit|ok|cancel|join|download|accept|allow|confirm)\b[!.]?\s*$", re.IGNORECASE)


class EventClassifier:
    def __init__(self, url_detector: Optional[URLDetector] = None) -> None:
        self.urls = url_detector or URLDetector()

    def classify_region_text(
        self,
        text: str,
        source: str = "meeting_chat",
        region: Optional[str] = None,
        state=None,
    ) -> List[Event]:
        """Produce deduplicated events from OCR text of one region."""
        events: List[Event] = []
        if not text or not text.strip():
            return events

        # URL events (deterministic)
        found = self.urls.extract(text)
        for url in found:
            if state is not None and not state.is_new_url(url):
                continue
            if state is not None:
                state.remember_url(url)
            events.append(
                Event(
                    type=EventType.NEW_URL,
                    source=source,
                    text=text.strip()[:500],
                    url=url,
                    confidence=0.98,
                    region=region,
                )
            )

        # form hint
        if _FORM_HINTS.search(text) and state is not None and state.is_new_message(f"FORM::{text[:200]}"):
            state.remember_message(f"FORM::{text[:200]}")
            events.append(
                Event(
                    type=EventType.NEW_DOCUMENT,
                    source=source,
                    text=text.strip()[:500],
                    confidence=0.7,
                    region=region,
                )
            )

        # button-like line
        if _BUTTON_HINTS.match(text.strip()) and state is not None and state.is_new_button(text.strip(), [0, 0, 0, 0]):
            state.remember_button(text.strip(), [0, 0, 0, 0])
            events.append(
                Event(
                    type=EventType.BUTTON_APPEARED,
                    source=source,
                    text=text.strip()[:120],
                    confidence=0.75,
                    region=region,
                )
            )

        # generic new message
        if state is None or state.is_new_message(text):
            if state is not None:
                state.remember_message(text)
            events.append(
                Event(
                    type=EventType.NEW_MESSAGE,
                    source=source,
                    text=text.strip()[:500],
                    confidence=0.6,
                    region=region,
                )
            )
        return events

    def classify_notification(self, text: str, region: Optional[str] = None) -> Optional[Event]:
        if not text.strip():
            return None
        return Event(
            type=EventType.NOTIFICATION_APPEARED,
            source="notifications",
            text=text.strip()[:500],
            confidence=0.7,
            region=region,
        )

"""Common runtime types: Frame and VisionContext.

Frame carries pixels plus metadata; pixels never leave the RAM ring buffer
unless explicitly cropped for a provider call.
"""
from __future__ import annotations

import time
import uuid
from typing import List, Optional

import numpy as np
from pydantic import BaseModel

from app.events.models import Event, OCRResult, UIElement


class Frame:
    __slots__ = ("id", "timestamp", "image", "monitor")

    def __init__(self, image: "np.ndarray", monitor: int = 1, timestamp: Optional[float] = None) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.image = image  # BGR numpy array
        self.monitor = monitor

    @property
    def age_seconds(self) -> float:
        return time.time() - self.timestamp

    def crop(self, x: int, y: int, w: int, h: int) -> "Frame":
        img = self.image[y : y + h, x : x + w]
        f = Frame(img, monitor=self.monitor, timestamp=self.timestamp)
        f.id = self.id  # keep provenance
        return f


class VisionContext(BaseModel):
    """Input handed to the VLM provider — small, structured, and bounded."""

    event: Event
    ocr_text: str
    elements: List[UIElement] = []
    recent_events: List[str] = []
    user_rule: str = ""
    allowed_actions: List[str] = []

"""GUI grounding (spec §13).

Turns a screenshot into semantic UI elements with bboxes. Providers:
- OCRGroundingProvider: derives clickable/link-like elements from OCR lines
  (deterministic; works well for chat links and buttons).
- OmniParserProvider: Microsoft OmniParser (open-source); requires model
  weights download. V1 ships the adapter hook; it activates when the package
  and weights are present.
- MockGroundingProvider: scripted elements for tests.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Protocol

import numpy as np

from app.events.models import GroundingResult, UIElement

log = logging.getLogger(__name__)

_URL_IN_TEXT = re.compile(r"(?:https?://|www\.)[^\s\"')\]]+", re.IGNORECASE)


class GroundingProvider(Protocol):
    def parse(self, image: "np.ndarray") -> GroundingResult: ...


class OCRGroundingProvider:
    """Derive UI elements from OCR output (deterministic default)."""

    _BUTTON_WORDS = re.compile(
        r"\b(submit|ok|cancel|open|join|download|accept|allow|confirm|send|save|next|done)\b",
        re.IGNORECASE,
    )

    def __init__(self, ocr_provider=None) -> None:
        from app.perception.ocr import get_ocr_provider

        self.ocr = ocr_provider or get_ocr_provider("auto")

    def parse(self, image: np.ndarray) -> GroundingResult:
        ocr = self.ocr.extract(image)
        elements: List[UIElement] = []
        for item in ocr.items:
            text = item.text.strip()
            if not text:
                continue
            role = "text"
            if _URL_IN_TEXT.search(text):
                role = "link"
            elif self._BUTTON_WORDS.search(text) and len(text) < 40:
                role = "button"
            elements.append(
                UIElement(semantic_role=role, text=text, bbox=item.bbox, confidence=item.confidence)
            )
        return GroundingResult(elements=elements, provider=f"ocr:{ocr.provider}")

    def find(self, image: np.ndarray, semantic_target: str) -> Optional[UIElement]:
        """Resolve a semantic target (e.g. 'submission_link') to a live element."""
        result = self.parse(image)
        target = semantic_target.lower()
        # direct text/role preference order: link > button > any
        for role_pref in ("link", "button", "element", "text"):
            for el in result.elements:
                if el.semantic_role == role_pref and target.split("_")[0] in el.text.lower():
                    return el
        # fallback: any element mentioning the target token
        for el in result.elements:
            if target.split("_")[0] in el.text.lower():
                return el
        return None


class OmniParserProvider:
    """Adapter hook for Microsoft OmniParser (MIT-licensed components).

    Requires the omni-parser package + model weights; when absent, parse()
    raises and callers fall back to OCR grounding.
    """

    def __init__(self) -> None:
        self._model = None
        try:
            from omniparser import OmniParser  # type: ignore

            self._model = OmniParser()
        except ImportError:
            log.info("OmniParser not installed; OmniParserProvider disabled")

    def parse(self, image: np.ndarray) -> GroundingResult:
        if self._model is None:
            raise RuntimeError("OmniParser unavailable")
        out = self._model.parse(image)  # expected: list of dicts with box/content/type
        elements = [
            UIElement(
                semantic_role=item.get("type", "element"),
                text=str(item.get("content", "")),
                bbox=[int(v) for v in item.get("box", [0, 0, 0, 0])],
                confidence=float(item.get("confidence", 0.9)),
            )
            for item in out
        ]
        return GroundingResult(elements=elements, provider="omniparser")


class MockGroundingProvider:
    def __init__(self, scripted: Optional[dict] = None) -> None:
        self.scripted = scripted or {}

    def parse(self, image: np.ndarray) -> GroundingResult:
        tag = getattr(image, "tag", None) or "default"
        res = self.scripted.get(tag)
        if res is None:
            return GroundingResult(elements=[], provider="mock")
        return GroundingResult(elements=res, provider="mock")

    def find(self, image: np.ndarray, semantic_target: str) -> Optional[UIElement]:
        result = self.parse(image)
        token = semantic_target.split("_")[0].lower()
        for el in result.elements:
            if token in el.text.lower() or token in el.semantic_role.lower():
                return el
        return None


def get_grounding_provider(name: str = "ocr", ocr_provider=None):
    if name == "mock":
        return MockGroundingProvider()
    if name == "omniparser":
        p = OmniParserProvider()
        if p._model is None:
            log.info("Falling back to OCR grounding")
            return OCRGroundingProvider(ocr_provider)
        return p
    return OCRGroundingProvider(ocr_provider)

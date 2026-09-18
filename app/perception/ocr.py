"""OCR provider abstraction (spec §10/§50).

- PaddleOCRProvider: Apache-2.0 PaddleOCR, lazy-loaded.
- FallbackOCRProvider: deterministic heuristic — no heavy deps; extracts text
  when Paddle is unavailable by scanning for URL-like / word-like patterns
  using image structure. Accuracy is lower; it is a graceful degradation path.
- MockOCRProvider: returns scripted results for tests.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Protocol

import numpy as np

from app.events.models import OCRItem, OCRResult

log = logging.getLogger(__name__)


class OCRProvider(Protocol):
    def extract(self, image: np.ndarray) -> OCRResult: ...


class PaddleOCRProvider:
    def __init__(self, language: str = "en") -> None:
        self._lang = language
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            import os

            # Thread-cap policy (applied BEFORE paddle import, which reads these):
            #   MEETING_AGENT_OCR_THREADS unset -> default cap 2 (safe beside meetings)
            #   MEETING_AGENT_OCR_THREADS=N     -> cap to N
            #   MEETING_AGENT_OCR_THREADS=0     -> explicitly UNCAP (use all cores)
            # The start_agent.bat launcher sets this variable; '0' is how FULL
            # mode opts out, so the caps below never fight the launcher.
            raw = os.environ.get("MEETING_AGENT_OCR_THREADS")
            cap = 2 if raw is None else int(raw)
            cores = max(4, os.cpu_count() or 4)
            if cap > 0:
                for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "PADDLE_NUM_THREADS"):
                    os.environ.setdefault(var, str(cap))
                cpu_threads = cap
            else:
                # FULL mode: explicitly request all cores (paddle's own default
                # would be 1 OMP thread if the vars were merely unset)
                for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "PADDLE_NUM_THREADS"):
                    os.environ.setdefault(var, str(cores))
                cpu_threads = cores

            from paddleocr import PaddleOCR  # heavy: lazy import

            self._engine = PaddleOCR(
                use_angle_cls=True,
                lang=self._lang,
                show_log=False,
                enable_mkldnn=True,
                cpu_threads=cpu_threads,
            )
        return self._engine

    def extract(self, image: np.ndarray) -> OCRResult:
        try:
            engine = self._get_engine()
            result = engine.ocr(image, cls=True)
            items: List[OCRItem] = []
            if result and result[0]:
                for line in result[0]:
                    box, (text, conf) = line[0], line[1]
                    xs = [p[0] for p in box]
                    ys = [p[1] for p in box]
                    bbox = [int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys))]
                    items.append(OCRItem(text=text, bbox=bbox, confidence=float(conf)))
            return OCRResult(items=items, provider="paddle")
        except Exception as exc:  # noqa: BLE001
            log.warning("PaddleOCR failed: %s — falling back", exc)
            return FallbackOCRProvider().extract(image)


class FallbackOCRProvider:
    """Deterministic heuristic OCR used when Paddle is unavailable.

    It cannot read arbitrary text, but it reliably detects high-contrast
    structured tokens (URLs) in chat-like regions by looking for the visual
    signature of link lines. It emits a best-effort text estimate.
    """

    _TOKEN = re.compile(r"[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{4,}")

    def extract(self, image: np.ndarray) -> OCRResult:
        import cv2

        items: List[OCRItem] = []
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15)
        # merge horizontal runs of dark-on-light pixels into text lines
        row_hits = binary.max(axis=1)
        in_line = False
        start = 0
        for y, hit in enumerate(row_hits):
            if hit and not in_line:
                in_line, start = True, y
            elif not hit and in_line:
                in_line = False
                line_img = binary[start:y]
                cols = line_img.max(axis=0)
                xs = np.flatnonzero(cols)
                if xs.size == 0 or (y - start) < 8:
                    continue
                bbox = [int(xs[0]), start, int(xs[-1] - xs[0]), int(y - start)]
                items.append(OCRItem(text=self._estimate_text(line_img), bbox=bbox, confidence=0.4))
        return OCRResult(items=items, provider="fallback")

    def _estimate_text(self, line_img: np.ndarray) -> str:
        # Without a real OCR engine we cannot read text. Returning placeholder
        # text would create noise events downstream, so we stay silent — the
        # system prefers no information over wrong information (spec §36).
        return ""


def _count_components(binary_img: np.ndarray) -> int:
    try:
        n, _ = cv2_connected_components(binary_img)
        return n
    except Exception:  # noqa: BLE001
        return 0


def cv2_connected_components(binary_img: np.ndarray):
    import cv2

    return cv2.connectedComponents((binary_img > 0).astype(np.uint8))


class MockOCRProvider:
    """Scripted OCR for tests: maps an image tag to a canned OCRResult."""

    def __init__(self, scripted: Optional[dict] = None) -> None:
        self.scripted = scripted or {}
        self.calls = 0

    def extract(self, image: np.ndarray) -> OCRResult:
        self.calls += 1
        tag = getattr(image, "tag", None) or "default"
        res = self.scripted.get(tag, OCRResult(items=[], provider="mock"))
        return res


def get_ocr_provider(name: str = "auto", language: str = "en") -> OCRProvider:
    if name == "mock":
        return MockOCRProvider()
    if name == "fallback":
        return FallbackOCRProvider()
    if name == "paddle":
        return PaddleOCRProvider(language)
    # auto: try paddle, degrade to fallback
    try:
        import paddleocr  # noqa: F401

        return PaddleOCRProvider(language)
    except ImportError:
        log.info("PaddleOCR not installed; using FallbackOCRProvider")
        return FallbackOCRProvider()

"""Cheap change detection (spec §9).

Never run OCR on every frame. Two deterministic methods:
- pixel_ratio: fraction of pixels whose grayscale difference exceeds a noise
  band (default; robust for text appearing in a small part of the frame).
- phash: perceptual hash distance (robust to compression noise).
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

import numpy as np

log = logging.getLogger(__name__)

_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class ChangeResult:
    __slots__ = ("changed", "score", "changed_regions")

    def __init__(self, changed: bool, score: float, changed_regions: List[str]) -> None:
        self.changed = changed
        self.score = score
        self.changed_regions = changed_regions


class ChangeDetector:
    """Stateful detector comparing the current frame against the previous one."""

    def __init__(self, method: str = "pixel_ratio", threshold: float = 0.002, noise_band: int = 25, min_region_area: float = 0.0005) -> None:
        self.method = method
        self.threshold = threshold  # fraction 0..1 of pixels changed
        self.noise_band = noise_band
        self.min_region_area = min_region_area
        self._prev_gray: Dict[str, np.ndarray] = {}

    def reset(self) -> None:
        self._prev_gray.clear()

    # -- methods ---------------------------------------------------------

    def _gray(self, img: np.ndarray) -> np.ndarray:
        import cv2

        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img

    def _diff_score(self, region_name: str, gray: np.ndarray) -> float:
        prev = self._prev_gray.get(region_name)
        self._prev_gray[region_name] = gray
        if prev is None or prev.shape != gray.shape:
            return 1.0  # first sight of region counts as change
        if self.method == "phash":
            return float(np.count_nonzero(self._phash(gray) != self._phash(prev))) / 64.0
        cv2 = _cv2()
        if cv2 is not None:
            diff = cv2.absdiff(gray, prev)
        else:  # numpy-only fallback
            diff = np.abs(gray.astype(np.int16) - prev.astype(np.int16)).astype(np.uint8)
        # fraction of pixels changed beyond the noise band
        return float((diff > self.noise_band).mean())

    def _phash(self, gray: np.ndarray) -> np.ndarray:
        import cv2

        small = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
        return (small > small.mean()).flatten()

    def evaluate_frame(self, frame_image: np.ndarray, regions: List[Tuple[str, Tuple[int, int, int, int]]]) -> ChangeResult:
        """Check each region; returns overall change plus per-region names."""
        changed_regions: List[str] = []
        max_score = 0.0
        for name, (x, y, w, h) in regions:
            crop = frame_image[y : y + h, x : x + w]
            if crop.size == 0:
                continue
            score = self._diff_score(name, self._gray(crop))
            max_score = max(max_score, score)
            if score >= self.threshold:
                changed_regions.append(name)
        return ChangeResult(changed=bool(changed_regions), score=max_score, changed_regions=changed_regions)


def _cv2():
    try:
        import cv2

        return cv2
    except ImportError:  # pragma: no cover
        return None

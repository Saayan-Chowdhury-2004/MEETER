"""Optional USB camera observation (spec §4.2/§12 — Phase 12, secondary sensor).

V1 keeps this minimal: frames can be pulled and pushed into the same event
pipeline. Sensor fusion lands in a later phase.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from app.types import Frame

log = logging.getLogger(__name__)


class CameraProvider:
    def __init__(self, index: int = 0) -> None:
        self.index = index
        self._cap: Optional[object] = None

    def start(self) -> bool:
        try:
            import cv2

            self._cap = cv2.VideoCapture(self.index)
            if not self._cap.isOpened():  # type: ignore[union-attr]
                self._cap = None
                return False
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("camera start failed: %s", exc)
            return False

    def read(self) -> Optional[Frame]:
        if self._cap is None:
            return None
        try:
            import cv2

            ok, frame = self._cap.read()  # type: ignore[union-attr]
            if not ok:
                return None
            return Frame(image=frame, monitor=0)
        except Exception as exc:  # noqa: BLE001
            log.debug("camera read failed: %s", exc)
            return None

    def stop(self) -> None:
        if self._cap is not None:
            try:
                import cv2

                self._cap.release()  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass
            self._cap = None

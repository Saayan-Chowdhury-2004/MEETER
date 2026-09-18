"""Screen capture providers (spec §4.1/§50).

- MSSCaptureProvider: fast prototype path using python-mss.
- WindowsGraphicsCaptureProvider: production path; requires the
  `windows-graphics-capture` wheel; falls back to MSS when unavailable.
- MockCaptureProvider: deterministic frames for tests.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional, Protocol

import numpy as np

from app.types import Frame

log = logging.getLogger(__name__)


class CaptureError(RuntimeError):
    pass


class ScreenCapture(Protocol):
    def capture(self) -> Frame: ...


class MSSCaptureProvider:
    """Grabs the whole virtual screen or a specific monitor via MSS."""

    def __init__(self, monitor: int = 1, width: int = 0, height: int = 0) -> None:
        import mss  # local import so the package stays optional

        self._mss = mss
        self._sct = mss.mss()
        self.monitor_idx = monitor
        self.target_size: Optional[tuple] = (width, height) if width and height else None

    def capture(self) -> Frame:
        try:
            monitors = self._sct.monitors
            if self.monitor_idx <= 0 or self.monitor_idx >= len(monitors):
                idx = 0 if self.monitor_idx >= len(monitors) else self.monitor_idx
                # index 0 is the virtual screen; keep 1-based semantics
                mon = monitors[min(self.monitor_idx, len(monitors) - 1)]
            else:
                mon = monitors[self.monitor_idx]
            raw = self._sct.grab(mon)
            img = np.array(raw)[:, :, :3][:, :, ::-1]  # BGRA -> BGR
            if self.target_size:
                import cv2

                img = cv2.resize(img, self.target_size)
            return Frame(image=img, monitor=self.monitor_idx)
        except Exception as exc:  # noqa: BLE001
            raise CaptureError(f"MSS capture failed: {exc}") from exc


class WindowsGraphicsCaptureProvider:
    """Windows Graphics Capture path (production).

    The WGC Python ecosystem is still young; V1 ships with MSS as the working
    implementation and this provider documents the upgrade path. It raises
    CaptureError so the orchestrator can fall back safely.
    """

    def __init__(self, monitor: int = 1) -> None:
        self.monitor = monitor
        self._impl = None
        try:
            from windows_graphics_capture import WindowsGraphicsCapture  # type: ignore
        except ImportError:
            log.info("windows-graphics-capture not installed; WGC provider disabled")
            return
        self._impl = WindowsGraphicsCapture(monitor_index=monitor)

    def capture(self) -> Frame:
        if self._impl is None:
            raise CaptureError("Windows Graphics Capture provider not available")
        data = self._impl.grab()  # expected: BGR ndarray
        return Frame(image=np.asarray(data), monitor=self.monitor)


class MockCaptureProvider:
    """Serves synthetic frames; used by tests and demos without a display."""

    def __init__(self, generator: Optional[Callable[[], np.ndarray]] = None) -> None:
        self._gen = generator or self._default_frame
        self._counter = 0

    @staticmethod
    def _default_frame() -> np.ndarray:
        import cv2

        img = np.full((720, 1280, 3), 40, dtype=np.uint8)
        cv2.putText(img, "MEETING (mock)", (430, 340), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (200, 200, 200), 2)
        return img

    def capture(self) -> Frame:
        self._counter += 1
        return Frame(image=self._gen().copy(), monitor=1)


def get_capture_provider(source: str, monitor: int = 1, width: int = 0, height: int = 0):
    if source == "mock":
        return MockCaptureProvider()
    if source == "window":
        log.info("window capture falls back to monitor capture in V1")
        return MSSCaptureProvider(monitor=monitor, width=width, height=height)
    if source == "monitor":
        try:
            wgc = WindowsGraphicsCaptureProvider(monitor=monitor)
            if wgc._impl is not None:
                return wgc
        except Exception:  # noqa: BLE001
            pass
        return MSSCaptureProvider(monitor=monitor, width=width, height=height)
    raise CaptureError(f"Unknown capture source: {source}")

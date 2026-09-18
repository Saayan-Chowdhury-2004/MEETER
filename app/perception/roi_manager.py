"""Region-of-interest management (spec §8).

Regions are defined as fractions of the frame so they survive resolution
changes. Polling rates are advisory; the orchestrator uses priority to decide
which regions are checked first when a frame shows change.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Tuple

from app.events.models import Region

log = logging.getLogger(__name__)


class ROI:
    _counter = 0

    def __init__(self, name: str, box: Tuple[float, float, float, float], priority: str = "medium", polling_hz: float = 2.0) -> None:
        ROI._counter += 1
        self.id = f"roi-{ROI._counter}"
        self.name = name
        self.fx, self.fy, self.fw, self.fh = box
        self.priority = priority
        self.polling_hz = polling_hz
        self.last_processed: float = 0.0

    def to_pixels(self, width: int, height: int) -> Region:
        x = int(self.fx * width)
        y = int(self.fy * height)
        w = int(self.fw * width)
        h = int(self.fh * height)
        # clamp to frame
        x = max(0, min(x, width - 1))
        y = max(0, min(y, height - 1))
        w = max(1, min(w, width - x))
        h = max(1, min(h, height - y))
        return Region(name=self.name, x=x, y=y, w=w, h=h)

    def due(self, now: Optional[float] = None) -> bool:
        now = now or time.time()
        return (now - self.last_processed) >= (1.0 / max(self.polling_hz, 0.01))

    def mark_processed(self, now: Optional[float] = None) -> None:
        self.last_processed = now or time.time()


class ROIManager:
    def __init__(self, regions: Optional[List[Dict]] = None) -> None:
        self.rois: List[ROI] = []
        for r in regions or []:
            self.rois.append(
                ROI(
                    name=r["name"],
                    box=tuple(r["box"]),  # type: ignore[arg-type]
                    priority=r.get("priority", "medium"),
                    polling_hz=float(r.get("polling_hz", 2.0)),
                )
            )
        if not self.rois:
            # fallback: full-frame region
            self.rois.append(ROI(name="full_screen", box=(0.0, 0.0, 1.0, 1.0)))

    def due_rois(self) -> List[ROI]:
        now = time.time()
        rois = [r for r in self.rois if r.due(now)]
        rois.sort(key=lambda r: ({"high": 0, "medium": 1, "low": 2}.get(r.priority, 1), -r.polling_hz))
        return rois

    def pixel_regions(self, width: int, height: int) -> List[Tuple[ROI, Region]]:
        return [(r, r.to_pixels(width, height)) for r in self.rois]

"""Mouse automation (spec §5.4/§23).

Thin wrapper over PyAutoGUI with:
- dry-run mode for tests/CI;
- bbox-center clicking;
- optional PyAutoGUI failsafe (corner-kill) kept enabled.
"""
from __future__ import annotations

import logging
from typing import List, Optional

log = logging.getLogger(__name__)


class MouseController:
    def __init__(self, dry_run: bool = False, enabled: bool = True) -> None:
        self.dry_run = dry_run
        self.enabled = enabled
        if enabled and not dry_run:
            import pyautogui

            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.1

    def click_bbox_center(self, bbox: Optional[List[int]]) -> bool:
        if not bbox or len(bbox) != 4:
            log.warning("click refused: invalid bbox %s", bbox)
            return False
        x, y, w, h = bbox
        cx, cy = int(x + w / 2), int(y + h / 2)
        return self.click_at(cx, cy)

    def click_at(self, x: int, y: int) -> bool:
        if self.dry_run or not self.enabled:
            log.info("[dry-run] click at (%d, %d)", x, y)
            return True
        try:
            import pyautogui

            pyautogui.click(x=x, y=y)
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("click failed: %s", exc)
            return False

    def scroll(self, amount: int) -> bool:
        if self.dry_run or not self.enabled:
            log.info("[dry-run] scroll %d", amount)
            return True
        try:
            import pyautogui

            pyautogui.scroll(amount)
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("scroll failed: %s", exc)
            return False

    def position(self) -> Optional[tuple]:
        if self.dry_run or not self.enabled:
            return (0, 0)
        try:
            import pyautogui

            return pyautogui.position()
        except Exception:  # noqa: BLE001
            return None

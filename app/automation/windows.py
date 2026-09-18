"""Window management (spec §5.4) using pygetwindow with graceful degradation."""
from __future__ import annotations

import logging
from typing import List, Optional

log = logging.getLogger(__name__)


class WindowController:
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    def list_titles(self) -> List[str]:
        try:
            import pygetwindow as gw

            return [t for t in gw.getAllTitles() if t.strip()]
        except Exception as exc:  # noqa: BLE001
            log.debug("window listing failed: %s", exc)
            return []

    def active_title(self) -> Optional[str]:
        try:
            import pygetwindow as gw

            w = gw.getActiveWindow()
            return w.title if w else None
        except Exception:  # noqa: BLE001
            return None

    def switch_to(self, title_substring: str) -> bool:
        if self.dry_run:
            log.info("[dry-run] switch to window %r", title_substring)
            return True
        try:
            import pygetwindow as gw

            matches = gw.getWindowsWithTitle(title_substring)
            if not matches:
                return False
            w = matches[0]
            if w.isMinimized:
                w.restore()
            w.activate()
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("window switch failed: %s", exc)
            return False

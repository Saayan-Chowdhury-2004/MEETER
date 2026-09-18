"""Keyboard automation (spec §5.4)."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Keys allowed by schema (no arbitrary combos beyond modifiers in pyautogui names)
_MODIFIERS = {"ctrl", "alt", "shift", "win", "command", "option"}


class KeyboardController:
    def __init__(self, dry_run: bool = False, enabled: bool = True) -> None:
        self.dry_run = dry_run
        self.enabled = enabled

    def type_text(self, text: str) -> bool:
        if self.dry_run or not self.enabled:
            log.info("[dry-run] type %d chars", len(text))
            return True
        try:
            import pyautogui

            pyautogui.typewrite(text, interval=0.02)
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("type failed: %s", exc)
            return False

    def key_press(self, key: str) -> bool:
        key = (key or "").strip().lower()
        if not key or len(key) > 20:
            log.warning("key_press refused: suspicious key %r", key)
            return False
        if self.dry_run or not self.enabled:
            log.info("[dry-run] key %s", key)
            return True
        try:
            import pyautogui

            pyautogui.press(key)
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("key press failed: %s", exc)
            return False

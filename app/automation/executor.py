"""Action executor (spec §52/§53).

Dispatches validated, firewall-approved actions to the appropriate
controller. The executor never decides — it only does what it is told after
policy approval.
"""
from __future__ import annotations

import logging

from app.automation.applications import ApplicationController
from app.automation.browser import BrowserController
from app.automation.keyboard import KeyboardController
from app.automation.mouse import MouseController
from app.automation.windows import WindowController
from app.events.models import Action, ExecutionResult

log = logging.getLogger(__name__)


class ActionExecutor:
    def __init__(
        self,
        mouse: MouseController,
        keyboard: KeyboardController,
        browser: BrowserController,
        apps: ApplicationController,
        windows: WindowController,
    ) -> None:
        self.mouse = mouse
        self.keyboard = keyboard
        self.browser = browser
        self.apps = apps
        self.windows = windows

    def execute(self, action: Action) -> ExecutionResult:
        t = action.type
        try:
            if t == t.OPEN_URL and action.url:
                ok = self.browser.open_url(action.url)
                return ExecutionResult(success=ok, action_type=t.value, detail=f"open {action.url}")
            if t == t.CLICK and action.bbox:
                ok = self.mouse.click_bbox_center(action.bbox)
                return ExecutionResult(success=ok, action_type=t.value, detail=f"click {action.target} bbox={action.bbox}")
            if t == t.TYPE_TEXT and action.text is not None:
                ok = self.keyboard.type_text(action.text)
                return ExecutionResult(success=ok, action_type=t.value, detail="typed text")
            if t == t.KEY_PRESS and action.key:
                ok = self.keyboard.key_press(action.key)
                return ExecutionResult(success=ok, action_type=t.value, detail=f"key {action.key}")
            if t == t.SCROLL:
                ok = self.mouse.scroll(action.amount or 3)
                return ExecutionResult(success=ok, action_type=t.value, detail=f"scroll {action.amount}")
            if t == t.OPEN_APPLICATION and action.application:
                ok = self.apps.open(action.application)
                return ExecutionResult(success=ok, action_type=t.value, detail=f"open app {action.application}")
            if t == t.SWITCH_WINDOW and action.window_title:
                ok = self.windows.switch_to(action.window_title)
                return ExecutionResult(success=ok, action_type=t.value, detail=f"switch to {action.window_title}")
            if t == t.COPY_TEXT:
                # copy current selection: benign, implemented via ctrl+c
                ok = self.keyboard.key_press("ctrl+c") if self.keyboard.enabled else True
                return ExecutionResult(success=ok, action_type=t.value, detail="copy selection")
            return ExecutionResult(success=False, action_type=t.value, error="action type/payload not executable")
        except Exception as exc:  # noqa: BLE001
            log.exception("execution error")
            return ExecutionResult(success=False, action_type=t.value, error=str(exc))

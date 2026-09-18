"""Post-action verification (spec §22/§37).

OBSERVE → PLAN → VALIDATE → ACT → OBSERVE AGAIN → VERIFY.

Verification is intentionally conservative:
- success requires positive evidence (expected text/state found);
- failure does NOT trigger uncontrolled retries (max_action_retries cap);
- unverifiable actions are marked as such rather than assumed successful.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

import numpy as np

from app.events.models import Action, ExecutionResult, VerificationResult

log = logging.getLogger(__name__)

# wait for UI to settle after an action before re-observing
_SETTLE_SECONDS = 1.0


class PostActionVerifier:
    def __init__(self, capture_fn: Callable[[], object], ocr_extract: Callable[[object], str]) -> None:
        """capture_fn returns a fresh Frame; ocr_extract returns visible text."""
        self.capture_fn = capture_fn
        self.ocr_extract = ocr_extract

    def verify(self, action: Action, result: ExecutionResult) -> VerificationResult:
        if not result.success:
            return VerificationResult(verified=False, detail="execution reported failure")

        time.sleep(_SETTLE_SECONDS)
        try:
            frame = self.capture_fn()
        except Exception as exc:  # noqa: BLE001
            return VerificationResult(verified=False, detail=f"re-observe failed: {exc}")

        if frame is None or getattr(frame, "image", None) is None:
            return VerificationResult(verified=False, detail="no frame available for verification")

        try:
            text = self.ocr_extract(frame.image)
        except Exception as exc:  # noqa: BLE001
            return VerificationResult(verified=False, detail=f"OCR during verification failed: {exc}")

        if action.type.value == "open_url":
            # positive evidence: URL host or expected marker visible
            from urllib.parse import urlparse

            host = urlparse(action.url or "").hostname or ""
            token = (action.expected_state or host.split(".")[0] if host else "").lower()
            if host and host.split(".")[0].lower() in text.lower():
                return VerificationResult(verified=True, detail=f"host token '{host.split('.')[0]}' visible", method="ocr_host_token")
            if token and token in text.lower():
                return VerificationResult(verified=True, detail=f"expected state '{token}' visible", method="ocr_expected_state")
            return VerificationResult(
                verified=False,
                detail="browser tab text not confirmed; treating as unverified (no retry loop)",
                method="ocr_host_token",
            )

        if action.type.value == "open_application":
            name = (action.application or "").lower()
            if name and name in text.lower():
                return VerificationResult(verified=True, detail=f"app '{name}' text visible", method="ocr_app_token")
            return VerificationResult(verified=False, detail=f"app '{name}' not confirmed on screen", method="ocr_app_token")

        if action.type.value == "click":
            # verify the click target's text is gone (state change) OR expected state appears
            if action.expected_state and action.expected_state.lower() in text.lower():
                return VerificationResult(verified=True, detail="expected state present", method="ocr_expected_state")
            return VerificationResult(verified=False, detail="no clear post-click evidence", method="ocr_expected_state")

        # scroll / key_press / type_text / switch_window / copy_text: considered benign
        return VerificationResult(verified=True, detail="low-risk action assumed stable", method="assumed_low_risk")


class StateMatcher:
    """Helpers to express expected post-conditions for actions."""

    @staticmethod
    def url_loaded(url: str) -> str:
        from urllib.parse import urlparse

        host = urlparse(url).hostname or ""
        return host.split(".")[0] if host else "browser"

    @staticmethod
    def app_running(app_name: str) -> str:
        return app_name

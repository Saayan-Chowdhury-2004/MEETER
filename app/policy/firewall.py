"""Action Firewall (spec §16/§36/§37).

Mandatory gate between any action proposal and the executor. Implements the
10 checks from the spec, the four-mode capability model (§29), emergency stop
(§40), and bounded retries (§37).
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional

import numpy as np

from app.events.models import (
    Action,
    ActionProposal,
    PolicyDecision,
    Risk,
)
from app.grounding.omniparser import GroundingProvider
from app.policy.allowlists import ApplicationAllowlist, DomainAllowlist
from app.policy.risk import classify
from app.policy.validation import validate_action

log = logging.getLogger(__name__)


class ActionFirewall:
    def __init__(
        self,
        policy,
        domain_allowlist: DomainAllowlist,
        app_allowlist: ApplicationAllowlist,
        grounding: GroundingProvider,
    ) -> None:
        self.policy = policy
        self.domains = domain_allowlist
        self.apps = app_allowlist
        self.grounding = grounding
        self._executed: Dict[str, float] = {}  # action fingerprint -> ts
        self._retries: Dict[str, int] = {}
        self.emergency_stop: bool = False

    # ------------------------------------------------------------------
    def reset(self) -> None:
        self._executed.clear()
        self._retries.clear()
        self.emergency_stop = False

    def trigger_emergency_stop(self) -> None:
        self.emergency_stop = True
        log.warning("EMERGENCY STOP engaged — all autonomous actions blocked")

    @staticmethod
    def _fingerprint(action: Action) -> str:
        return f"{action.type.value}:{action.url or action.target or action.application or action.key or action.window_title or ''}"

    # ------------------------------------------------------------------
    def evaluate(
        self,
        proposal: ActionProposal,
        mode: str,
        frame_image: Optional[np.ndarray] = None,
    ) -> PolicyDecision:
        """Run all firewall checks. Returns a PolicyDecision, never executes."""

        # 10. emergency stop / kill switch (highest priority, outside VLM loop)
        if self.emergency_stop:
            return PolicyDecision(approved=False, reason="emergency stop engaged", risk=Risk.HIGH)

        # mode capability gate; non-ACT proposals (ASK_USER) park for confirmation
        if proposal.decision != "ACT" or proposal.action is None:
            return PolicyDecision(
                approved=False,
                reason=f"proposal decision={proposal.decision}",
                requires_confirmation=(proposal.decision == "ASK_USER"),
            )

        allowed_types = self.policy.mode_capabilities.get(mode, [])
        if proposal.action.type.value not in allowed_types:
            return PolicyDecision(
                approved=False,
                reason=f"mode '{mode}' does not allow action '{proposal.action.type.value}'",
                risk=classify(proposal.action),
            )

        # 1. action type allowed (schema + global blocklist)
        if proposal.action.type.value in self.policy.blocked_actions:
            return PolicyDecision(
                approved=False,
                reason=f"action type '{proposal.action.type.value}' is blocked by policy",
                risk=Risk.HIGH,
            )

        ok, detail = validate_action(proposal.action)
        if not ok:
            return PolicyDecision(approved=False, reason=f"schema validation failed: {detail}", risk=classify(proposal.action))

        risk = classify(proposal.action)

        # 4. confidence threshold
        if proposal.confidence < self.policy.confidence_threshold:
            return PolicyDecision(
                approved=False,
                reason=f"confidence {proposal.confidence:.2f} below threshold {self.policy.confidence_threshold:.2f}",
                risk=risk,
                requires_confirmation=True,
            )

        # 3. domain allowlist
        if proposal.action.type.value == "open_url":
            status, detail = self.domains.check(proposal.action.url or "")
            if status == "blocked":
                return PolicyDecision(approved=False, reason=detail, risk=risk)
            if status == "unknown" and self.policy.require_confirmation_for_unknown_domains:
                return PolicyDecision(
                    approved=False,
                    reason=detail,
                    risk=risk,
                    requires_confirmation=True,
                )

        # 2. target application expected
        if proposal.action.type.value == "open_application":
            if not self.apps.is_allowed(proposal.action.application or ""):
                return PolicyDecision(
                    approved=False,
                    reason=f"application '{proposal.action.application}' is not allowlisted",
                    risk=risk,
                )

        # 5/6. target still exists + UI unchanged since planning
        if proposal.action.type.value in ("click", "switch_window") and proposal.action.target:
            el = None
            if frame_image is not None:
                try:
                    el = self.grounding.find(frame_image, proposal.action.target)
                except Exception as exc:  # noqa: BLE001
                    return PolicyDecision(approved=False, reason=f"grounding failed: {exc}", risk=risk)
                if el is None:
                    return PolicyDecision(
                        approved=False,
                        reason=f"target '{proposal.action.target}' no longer exists — refusing stale click",
                        risk=risk,
                    )
                # refresh bbox for executor
                proposal.action.bbox = list(el.bbox)
            else:
                return PolicyDecision(approved=False, reason="no current frame for target revalidation", risk=risk)

        # 7. high-risk default BLOCK
        if risk == Risk.HIGH:
            return PolicyDecision(approved=False, reason="high-risk action blocked by default", risk=risk)

        # 9. duplicate execution guard
        fp = self._fingerprint(proposal.action)
        if fp in self._executed:
            return PolicyDecision(
                approved=False,
                reason="identical action already executed (duplicate guard)",
                risk=risk,
            )

        # 8. confirmation requirement
        requires_confirmation = proposal.requires_confirmation or risk != Risk.LOW

        return PolicyDecision(
            approved=True,
            reason=detail if proposal.action.type.value == "open_url" else proposal.reason or "approved",
            risk=risk,
            requires_confirmation=requires_confirmation,
        )

    # ------------------------------------------------------------------
    def record_execution(self, action: Action) -> None:
        self._executed[self._fingerprint(action)] = time.time()

    def register_failure(self, action: Action) -> int:
        """Increment retry counter; returns count. > max_action_retries → stop."""
        fp = self._fingerprint(action)
        self._retries[fp] = self._retries.get(fp, 0) + 1
        return self._retries[fp]

    def retries_exhausted(self, action: Action) -> bool:
        fp = self._fingerprint(action)
        return self._retries.get(fp, 0) >= max(1, getattr(self.policy, "max_action_retries", 1))

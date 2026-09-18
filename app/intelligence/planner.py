"""Planner (spec §14/§15).

Decides what to do with an event:
1. Deterministic rules first — high confidence, cheap.
2. VLM only if enabled and the rules did not resolve the event (§48 step 13+).

The planner NEVER executes; it only emits ActionProposals.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.events.models import ActionProposal, Event
from app.intelligence.vlm import VLMProvider
from app.rules.engine import RuleEngine
from app.types import VisionContext

log = logging.getLogger(__name__)


class Planner:
    def __init__(
        self,
        rules: RuleEngine,
        vlm: VLMProvider,
        memory=None,
        use_vlm_threshold: float = 0.0,
    ) -> None:
        self.rules = rules
        self.vlm = vlm
        self.memory = memory
        self.use_vlm_threshold = use_vlm_threshold

    def propose(self, event: Event, user_rule_hint: str = "") -> ActionProposal:
        # 1) deterministic rules
        rule_proposal = self.rules.match(event)
        if rule_proposal is not None:
            return rule_proposal

        # 2) VLM reasoning for ambiguous/semantic events
        if self.vlm is not None:
            ctx = VisionContext(
                event=event,
                ocr_text=event.text,
                recent_events=self.memory.recent() if self.memory else [],
                user_rule=user_rule_hint,
            )
            return self.vlm.analyze(ctx)
        return ActionProposal.ignore("no rule matched and VLM disabled")

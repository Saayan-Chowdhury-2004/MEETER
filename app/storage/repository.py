"""Repository facade — the rest of the app talks to this, not to sqlite3."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.events.models import Event, PolicyDecision, VerificationResult
from app.storage.sqlite import Database


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record_event(self, event: Event) -> None:
        self.db.insert_event(event)

    def recent_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.db.list_events(limit)

    def record_decision(
        self,
        event: Optional[Event],
        action_type: str,
        detail: str,
        decision: PolicyDecision,
    ) -> int:
        return self.db.insert_action(
            event_id=event.id if event else None,
            timestamp=event.timestamp if event else "",
            action_type=action_type,
            detail=detail,
            approved=decision.approved,
            reason=decision.reason,
        )

    def record_verification(self, action_row_id: int, verification: VerificationResult) -> None:
        from app.events.models import now_iso

        self.db.insert_verification(
            action_row_id, now_iso(), verification.verified, verification.detail, verification.method
        )

    def record_rule(self, rule) -> None:
        import json

        from app.rules.engine import json_rule

        self.db.upsert_rule(rule.id or rule.name, rule.name, rule.enabled, json.dumps(json_rule(rule)))

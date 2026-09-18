"""Rule schema (spec §20/§21).

Rules are strictly validated. The NL rule compiler may only ever produce
objects conforming to this schema — never code.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator


class RuleAction(BaseModel):
    type: str

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        from app.events.models import ActionType

        valid = {t.value for t in ActionType}
        if v not in valid:
            raise ValueError(f"action type '{v}' is not in the allowed action schema")
        return v


class Rule(BaseModel):
    id: Optional[str] = None
    name: str
    enabled: bool = True
    trigger: str  # EventType value, e.g. NEW_URL
    conditions: Dict[str, Any] = Field(default_factory=dict)
    action: RuleAction
    risk: str = "low"
    requires_confirmation: bool = True
    priority: int = 100

    @field_validator("trigger")
    @classmethod
    def _known_trigger(cls, v: str) -> str:
        from app.events.models import EventType

        valid = {t.value for t in EventType}
        if v not in valid:
            raise ValueError(f"trigger '{v}' is not a valid event type")
        return v

    @field_validator("conditions")
    @classmethod
    def _known_conditions(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {"source", "domain", "url_contains", "text_contains", "region", "button_label"}
        unknown = set(v.keys()) - allowed
        if unknown:
            raise ValueError(f"unknown condition keys: {sorted(unknown)}")
        return v


def validate_rule_dict(data: Dict[str, Any]) -> tuple[bool, str, Optional[Rule]]:
    try:
        rule = Rule(**data)
        if not rule.id:
            rule = rule.model_copy(update={"id": rule.name.lower().replace(" ", "_")})
        return True, "ok", rule
    except ValidationError as e:
        return False, str(e), None

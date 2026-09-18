"""Rules engine (spec §20).

Matches structured events against validated rules and produces action
proposals. Deterministic — the VLM never invents rules here.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from app.events.models import Action, ActionType, ActionProposal, Event, Risk
from app.rules.schema import Rule, validate_rule_dict

log = logging.getLogger(__name__)


class RuleEngine:
    def __init__(self, rules: Optional[List[Rule]] = None) -> None:
        self.rules: List[Rule] = list(rules or [])

    # -- persistence -----------------------------------------------------
    def load_from_file(self, path: str) -> int:
        import yaml

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            return 0
        count = 0
        for item in data.get("rules", []):
            ok, err, rule = validate_rule_dict(item)
            if ok and rule:
                self.rules.append(rule)
                count += 1
            else:
                log.warning("skipping invalid rule %s: %s", item.get("name"), err)
        return count

    def save_to_file(self, path: str) -> None:
        import yaml

        payload = {"rules": [json_rule(r) for r in self.rules]}
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, sort_keys=False)

    # -- matching --------------------------------------------------------
    def match(self, event: Event) -> Optional[ActionProposal]:
        """Return the highest-priority matching rule's proposal, else None."""
        best: Optional[ActionProposal] = None
        best_rule: Optional[Rule] = None
        for rule in sorted(self.rules, key=lambda r: r.priority):
            if not rule.enabled or rule.trigger != event.type.value:
                continue
            if not _conditions_match(rule.conditions, event):
                continue
            action = _rule_action(rule, event)
            if action is None:
                continue
            proposal = ActionProposal(
                decision="ACT",
                action=action,
                confidence=0.99,  # deterministic rule match — high confidence
                reason=f"rule '{rule.id}' matched event {event.type.value}",
                risk=Risk(rule.risk) if rule.risk in ("low", "medium", "high") else Risk.MEDIUM,
                requires_confirmation=rule.requires_confirmation,
            )
            if best is None or rule.priority < best_rule.priority:  # type: ignore[operator]
                best, best_rule = proposal, rule
        return best

    def add_rule(self, rule: Rule) -> None:
        self.rules = [r for r in self.rules if r.id != rule.id] + [rule]

    def remove_rule(self, rule_id: str) -> bool:
        before = len(self.rules)
        self.rules = [r for r in self.rules if r.id != rule_id]
        return len(self.rules) < before

    def set_enabled(self, rule_id: str, enabled: bool) -> bool:
        for r in self.rules:
            if r.id == rule_id:
                r.enabled = enabled
                return True
        return False

    def describe(self) -> List[str]:
        return [
            f"{r.id} [{'enabled' if r.enabled else 'disabled'}] trigger={r.trigger} conditions={r.conditions} action={r.action.type}"
            for r in self.rules
        ]


def _conditions_match(conditions: dict, event: Event) -> bool:
    for key, expected in conditions.items():
        if key == "source" and event.source != expected:
            return False
        if key == "region" and event.region != expected:
            return False
        if key == "domain":
            from urllib.parse import urlparse

            host = (urlparse(event.url or "").hostname or "").lower()
            if host != expected.lower() and not host.endswith("." + str(expected).lower()):
                return False
        if key == "url_contains" and expected.lower() not in (event.url or "").lower():
            return False
        if key == "text_contains" and expected.lower() not in event.text.lower():
            return False
        if key == "button_label" and expected.lower() not in event.text.lower():
            return False
    return True


def _rule_action(rule: Rule, event: Event) -> Optional[Action]:
    t = rule.action.type
    try:
        at = ActionType(t)
    except ValueError:
        return None
    if at == ActionType.OPEN_URL:
        if not event.url:
            return None
        return Action(type=at, url=event.url, rule_id=rule.id, expected_state="page loaded")
    if at == ActionType.OPEN_APPLICATION:
        return Action(type=at, application=rule.conditions.get("app"), rule_id=rule.id)
    if at == ActionType.CLICK:
        return Action(type=at, target=rule.conditions.get("button_label", ""), rule_id=rule.id)
    # generic: carry text payload if useful
    return Action(type=at, text=event.text or None, rule_id=rule.id)


def json_rule(r: Rule) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "enabled": r.enabled,
        "trigger": r.trigger,
        "conditions": r.conditions,
        "action": {"type": r.action.type},
        "risk": r.risk,
        "requires_confirmation": r.requires_confirmation,
        "priority": r.priority,
    }

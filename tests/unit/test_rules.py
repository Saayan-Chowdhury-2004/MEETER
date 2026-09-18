import pytest

from app.events.models import Event, EventType
from app.rules.engine import RuleEngine
from app.rules.schema import validate_rule_dict


def _rule(**overrides):
    data = {
        "name": "open_github_links",
        "trigger": "NEW_URL",
        "conditions": {"domain": "github.com", "source": "meeting_chat"},
        "action": {"type": "open_url"},
        "risk": "low",
        "requires_confirmation": False,
    }
    data.update(overrides)
    ok, err, rule = validate_rule_dict(data)
    assert ok, err
    return rule


def test_valid_rule_roundtrip():
    rule = _rule()
    assert rule.id == "open_github_links"


def test_rejects_unknown_trigger():
    ok, err, _ = validate_rule_dict({"name": "x", "trigger": "NOT_A_THING", "action": {"type": "open_url"}})
    assert not ok
    assert "trigger" in err


def test_rejects_unknown_action_type():
    ok, _, _ = validate_rule_dict({"name": "x", "trigger": "NEW_URL", "action": {"type": "execute_shell"}})
    assert not ok


def test_rejects_unknown_condition_keys():
    ok, _, _ = validate_rule_dict(
        {"name": "x", "trigger": "NEW_URL", "conditions": {"arbitrary_code": "rm -rf"}, "action": {"type": "open_url"}}
    )
    assert not ok


def test_engine_matches_domain_and_source():
    eng = RuleEngine([_rule()])
    ev = Event(type=EventType.NEW_URL, source="meeting_chat", url="https://github.com/a/b", text="repo link")
    p = eng.match(ev)
    assert p is not None and p.decision == "ACT"
    assert p.action.url == "https://github.com/a/b"


def test_engine_does_not_match_other_domain():
    eng = RuleEngine([_rule()])
    ev = Event(type=EventType.NEW_URL, source="meeting_chat", url="https://evil.example.com/x", text="link")
    assert eng.match(ev) is None


def test_engine_does_not_match_other_source():
    eng = RuleEngine([_rule()])
    ev = Event(type=EventType.NEW_URL, source="notifications", url="https://github.com/a/b", text="link")
    assert eng.match(ev) is None


def test_enable_disable():
    eng = RuleEngine([_rule()])
    assert eng.set_enabled("open_github_links", False) is True
    ev = Event(type=EventType.NEW_URL, source="meeting_chat", url="https://github.com/a/b")
    assert eng.match(ev) is None

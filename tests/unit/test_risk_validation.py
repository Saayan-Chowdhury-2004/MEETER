import pytest

from app.events.models import Action, ActionType, Risk
from app.policy.risk import classify
from app.policy.validation import validate_action


def test_risk_classes():
    assert classify(Action(type=ActionType.OPEN_URL, url="https://x.com")) == Risk.LOW
    assert classify(Action(type=ActionType.SCROLL)) == Risk.LOW
    assert classify(Action(type=ActionType.OPEN_APPLICATION, application="vscode")) == Risk.LOW
    assert classify(Action(type=ActionType.CLICK, target="btn")) == Risk.MEDIUM
    assert classify(Action(type=ActionType.TYPE_TEXT, text="hi")) == Risk.MEDIUM


def test_validation_requires_fields():
    ok, err = validate_action(Action(type=ActionType.OPEN_URL))
    assert not ok and "url" in err
    ok, err = validate_action(Action(type=ActionType.CLICK))
    assert not ok and "target" in err


def test_validation_rejects_bad_url():
    ok, err = validate_action(Action(type=ActionType.OPEN_URL, url="javascript:alert(1)"))
    assert not ok


def test_validation_accepts_valid():
    ok, err = validate_action(Action(type=ActionType.OPEN_URL, url="https://github.com/a"))
    assert ok

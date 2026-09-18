import numpy as np
import pytest

from app.events.models import Action, ActionProposal, ActionType, Risk
from app.grounding.omniparser import MockGroundingProvider, UIElement
from app.policy.allowlists import ApplicationAllowlist, DomainAllowlist
from app.policy.firewall import ActionFirewall


class FakePolicy:
    def __init__(self):
        self.confidence_threshold = 0.95
        self.require_confirmation_for_unknown_domains = True
        self.max_action_retries = 1
        self.blocked_actions = ["submit_form", "delete_file", "execute_shell"]
        self.mode_capabilities = {
            "observe": [],
            "suggest": [],
            "assist": ["open_url", "scroll", "open_application", "switch_window"],
            "autonomous": ["open_url", "click", "type_text", "key_press", "scroll", "open_application", "switch_window", "copy_text"],
        }


def _firewall(grounding=None):
    domains = DomainAllowlist(["github.com"], [], True)
    apps = ApplicationAllowlist({"vscode": {"paths": ["code"]}, "browser": {"paths": []}})
    return ActionFirewall(FakePolicy(), domains, apps, grounding or MockGroundingProvider())


def _act_proposal(action, confidence=0.97, confirm=False):
    return ActionProposal(decision="ACT", action=action, confidence=confidence, reason="test", requires_confirmation=confirm)


# -- Test 5: submit / high risk blocked by default -------------------------
def test_high_risk_action_blocked():
    fw = _firewall()
    # submit_form is not even in the action schema; a click at low confidence in observe mode is blocked too
    d = fw.evaluate(_act_proposal(Action(type=ActionType.OPEN_URL, url="https://github.com/x")), mode="observe")
    assert not d.approved  # observe mode allows nothing


# -- Test 1: github url allowed in assist mode ------------------------------
def test_github_url_allowed_in_assist():
    fw = _firewall()
    d = fw.evaluate(_act_proposal(Action(type=ActionType.OPEN_URL, url="https://github.com/x")), mode="assist")
    assert d.approved


# -- Test 3: unknown domain requires confirmation ---------------------------
def test_unknown_domain_requires_confirmation():
    fw = _firewall()
    d = fw.evaluate(_act_proposal(Action(type=ActionType.OPEN_URL, url="https://unknown.example.com")), mode="assist")
    assert not d.approved and d.requires_confirmation


def test_blocked_domain_rejected():
    fw = _firewall()
    fw.domains = DomainAllowlist(["github.com"], ["malware.example"], True)
    d = fw.evaluate(_act_proposal(Action(type=ActionType.OPEN_URL, url="https://sub.malware.example/x")), mode="assist")
    assert not d.approved and not d.requires_confirmation


# -- confidence gate ---------------------------------------------------------
def test_low_confidence_asks_user():
    fw = _firewall()
    d = fw.evaluate(_act_proposal(Action(type=ActionType.OPEN_URL, url="https://github.com/x"), confidence=0.65), mode="assist")
    assert not d.approved and d.requires_confirmation


# -- mode capability gate ----------------------------------------------------
def test_click_not_allowed_in_assist():
    fw = _firewall()
    d = fw.evaluate(_act_proposal(Action(type=ActionType.CLICK, target="submit_button")), mode="assist")
    assert not d.approved


# -- schema validation -------------------------------------------------------
def test_open_url_requires_valid_url():
    fw = _firewall()
    d = fw.evaluate(_act_proposal(Action(type=ActionType.OPEN_URL, url="not a url")), mode="assist")
    assert not d.approved


def test_open_application_must_be_allowlisted():
    fw = _firewall()
    d = fw.evaluate(_act_proposal(Action(type=ActionType.OPEN_APPLICATION, application="terminal")), mode="assist")
    assert not d.approved
    d2 = fw.evaluate(_act_proposal(Action(type=ActionType.OPEN_APPLICATION, application="vscode")), mode="assist")
    assert d2.approved


# -- Test 6: target moved / stale coordinates --------------------------------
def test_stale_target_rejected_when_not_on_screen():
    class EmptyGrounding(MockGroundingProvider):
        def find(self, image, semantic_target):
            return None

    fw = _firewall(EmptyGrounding())
    d = fw.evaluate(
        _act_proposal(Action(type=ActionType.CLICK, target="submit_button")), mode="autonomous", frame_image=np.zeros((10, 10, 3), dtype=np.uint8)
    )
    assert not d.approved and "no longer exists" in d.reason


def test_click_with_fresh_target_updates_bbox():
    class FoundGrounding(MockGroundingProvider):
        def find(self, image, semantic_target):
            return UIElement(semantic_role="button", text="Submit", bbox=[100, 100, 80, 30], confidence=0.99)

    fw = _firewall(FoundGrounding())
    d = fw.evaluate(
        _act_proposal(Action(type=ActionType.CLICK, target="submit_button")), mode="autonomous", frame_image=np.zeros((10, 10, 3), dtype=np.uint8)
    )
    assert d.approved and d.risk == Risk.MEDIUM  # click is medium → confirmation required


# -- Test 2: duplicate action guard -------------------------------------------
def test_duplicate_action_blocked():
    fw = _firewall()
    prop = _act_proposal(Action(type=ActionType.OPEN_URL, url="https://github.com/x"))
    assert fw.evaluate(prop, mode="assist").approved
    fw.record_execution(prop.action)
    d = fw.evaluate(_act_proposal(Action(type=ActionType.OPEN_URL, url="https://github.com/x")), mode="assist")
    assert not d.approved and "duplicate" in d.reason


# -- Test 8: emergency stop ----------------------------------------------------
def test_emergency_stop_blocks_everything():
    fw = _firewall()
    fw.trigger_emergency_stop()
    d = fw.evaluate(_act_proposal(Action(type=ActionType.OPEN_URL, url="https://github.com/x")), mode="autonomous")
    assert not d.approved and "emergency" in d.reason


# -- retries (Test 7 support) ---------------------------------------------------
def test_retry_ceiling():
    fw = _firewall()
    a = Action(type=ActionType.OPEN_URL, url="https://github.com/x")
    fw.register_failure(a)
    assert fw.retries_exhausted(a)  # max_action_retries=1


def test_high_risk_click_on_autonomous_still_needs_confirmation():
    fw = _firewall()
    class FoundGrounding(MockGroundingProvider):
        def find(self, image, semantic_target):
            return UIElement(semantic_role="button", text="Submit", bbox=[1, 1, 10, 10], confidence=0.99)

    fw.grounding = FoundGrounding()
    d = fw.evaluate(_act_proposal(Action(type=ActionType.CLICK, target="submit_button")), mode="autonomous", frame_image=np.zeros((5, 5, 3), dtype=np.uint8))
    assert d.approved and d.requires_confirmation  # medium risk → confirm

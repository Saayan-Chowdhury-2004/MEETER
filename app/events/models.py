"""Structured event models (spec §11/§15/§52).

All cross-layer messages are Pydantic models — no free-form dicts crossing
module boundaries. Meeting content is always carried in fields explicitly
marked untrusted so downstream consumers know its authority level (spec §38).
"""
from __future__ import annotations

import itertools
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

_id_counter = itertools.count(1)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def new_event_id() -> str:
    return f"event-{next(_id_counter):06d}-{uuid.uuid4().hex[:6]}"


class EventType(str, Enum):
    NEW_URL = "NEW_URL"
    NEW_MESSAGE = "NEW_MESSAGE"
    BUTTON_APPEARED = "BUTTON_APPEARED"
    SCREEN_CHANGED = "SCREEN_CHANGED"
    POPUP_APPEARED = "POPUP_APPEARED"
    NOTIFICATION_APPEARED = "NOTIFICATION_APPEARED"
    MEETING_STATE_CHANGED = "MEETING_STATE_CHANGED"
    NEW_DOCUMENT = "NEW_DOCUMENT"
    DOWNLOAD_STARTED = "DOWNLOAD_STARTED"
    VOICE_COMMAND = "VOICE_COMMAND"
    USER_COMMAND = "USER_COMMAND"
    APPLICATION_CHANGED = "APPLICATION_CHANGED"
    WINDOW_CHANGED = "WINDOW_CHANGED"


class Region(BaseModel):
    name: str
    x: int
    y: int
    w: int
    h: int


class OCRItem(BaseModel):
    text: str
    bbox: List[int]  # x, y, w, h in frame pixels
    confidence: float = 1.0


class OCRResult(BaseModel):
    items: List[OCRItem] = Field(default_factory=list)
    provider: str = "unknown"


class UIElement(BaseModel):
    semantic_role: str = "element"  # link | button | input | text | element
    text: str = ""
    bbox: List[int]
    confidence: float = 1.0


class GroundingResult(BaseModel):
    elements: List[UIElement] = Field(default_factory=list)
    provider: str = "unknown"
    frame_ref: Optional[str] = None  # ring-buffer frame id used for grounding


class ActionType(str, Enum):
    OPEN_URL = "open_url"
    CLICK = "click"
    TYPE_TEXT = "type_text"
    KEY_PRESS = "key_press"
    SCROLL = "scroll"
    OPEN_APPLICATION = "open_application"
    SWITCH_WINDOW = "switch_window"
    COPY_TEXT = "copy_text"
    # Explicitly NOT implemented in V1 (spec §52):
    # submit_form, delete_file, execute_shell, send_email, purchase,
    # account_setting_change


class Risk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Action(BaseModel):
    type: ActionType
    # one of the following depending on type
    url: Optional[str] = None
    application: Optional[str] = None  # logical name from app allowlist
    target: Optional[str] = None  # semantic target id resolved via grounding
    bbox: Optional[List[int]] = None  # revalidated immediately before execution
    text: Optional[str] = None
    key: Optional[str] = None
    amount: int = 0
    window_title: Optional[str] = None

    # optional metadata
    expected_state: Optional[str] = None  # for post-action verification
    rule_id: Optional[str] = None


class ActionProposal(BaseModel):
    """Output of VLM/planner — never executed directly (spec §16)."""

    decision: str  # ACT | IGNORE | ASK_USER
    action: Optional[Action] = None
    confidence: float = 0.0
    reason: str = ""
    risk: Risk = Risk.MEDIUM
    requires_confirmation: bool = True

    @classmethod
    def ignore(cls, reason: str) -> "ActionProposal":
        return cls(decision="IGNORE", confidence=1.0, reason=reason)

    @classmethod
    def ask(cls, reason: str) -> "ActionProposal":
        return cls(decision="ASK_USER", confidence=1.0, reason=reason)


class Event(BaseModel):
    id: str = Field(default_factory=new_event_id)
    timestamp: str = Field(default_factory=now_iso)
    type: EventType
    source: str = "screen"
    text: str = ""  # UNTRUSTED meeting content (spec §38)
    url: Optional[str] = None
    confidence: float = 0.0
    region: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    approved: bool
    reason: str
    requires_confirmation: bool = False
    risk: Risk = Risk.MEDIUM
    revalidated: bool = False


class ExecutionResult(BaseModel):
    success: bool
    action_type: str = ""
    detail: str = ""
    error: Optional[str] = None


class VerificationResult(BaseModel):
    verified: bool
    detail: str = ""
    method: str = "ocr_text_present"


class AgentState(BaseModel):
    """Snapshot of agent status for the dashboard/API."""

    mode: str = "observe"
    status: str = "idle"  # idle | running | paused | stopped
    emergency_stop: bool = False
    current_event: Optional[Event] = None
    last_decision: Optional[PolicyDecision] = None
    last_proposal: Optional[ActionProposal] = None
    frames_in_buffer: int = 0
    events_seen: int = 0
    started_at: Optional[str] = None
    vlm_calls: int = 0
    ocr_calls: int = 0
    # meeting gating (tasks 3+4)
    meeting_active: bool = False
    meeting_app: Optional[str] = None
    meeting_title: Optional[str] = None
    # lightweight resource metrics (sampled while a meeting is active)
    cpu_percent: float = 0.0
    ram_mb: float = 0.0

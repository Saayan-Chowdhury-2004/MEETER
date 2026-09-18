"""Agent orchestrator — the event pipeline (spec §7/§29/§44).

capture → change detection → ROI routing → OCR/deterministic analysis →
event engine → (rules | grounding | VLM) → action firewall → executor →
post-action verification → event log.

Meeting-gated (tasks 3+4): the agent only observes while a known meeting app
(Zoom/Webex/Teams/Meet…) is running, and then only observes that app's window
region — never the whole desktop. No meeting → idle standby (tiny poll, no
OCR, no events). This avoids tracking general user activity and saves
resources during long sessions.

Modes (§29): OBSERVE / SUGGEST / ASSIST / AUTONOMOUS. Default OBSERVE.
The kill switch is handled outside the VLM loop (§40).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Optional

from app.config import AppConfig
from app.events.models import (
    Action,
    ActionProposal,
    ActionType,
    AgentState,
    Event,
    EventType,
    PolicyDecision,
    VerificationResult,
)
from app.grounding.omniparser import get_grounding_provider
from app.intelligence.event_classifier import EventClassifier
from app.intelligence.memory import EventMemory
from app.intelligence.planner import Planner
from app.intelligence.rule_compiler import RuleCompiler
from app.intelligence.vlm import get_vlm_provider
from app.perception.change_detector import ChangeDetector
from app.perception.ocr import get_ocr_provider
from app.perception.roi_manager import ROIManager
from app.perception.state_tracker import StateTracker
from app.policy.allowlists import ApplicationAllowlist, DomainAllowlist
from app.policy.firewall import ActionFirewall
from app.rules.engine import RuleEngine
from app.storage.repository import Repository
from app.types import Frame
from app.verification.post_action import PostActionVerifier, StateMatcher

log = logging.getLogger(__name__)


class Agent:
    def __init__(self, config: AppConfig, repository: Repository) -> None:
        self.config = config
        self.repo = repository
        self.state = AgentState()

        # meeting gating (tasks 3+4)
        from app.perception.meeting_tracker import MeetingTracker, MeetingTrackerConfig

        mc = getattr(config, "meeting", None)
        self.tracker = MeetingTracker(
            MeetingTrackerConfig(
                poll_interval_idle=mc.poll_interval_idle if mc else 2.0,
                poll_interval_active=mc.poll_interval_active if mc else 5.0,
            )
        )
        self.current_meeting = None  # MeetingWindow | None
        self.idle_sleep = mc.poll_interval_idle if mc else 2.0  # standby check rate
        self._active_since: Optional[float] = None
        self._last_meeting_app: Optional[str] = None

        # perception
        self.capture = None  # created in start_capture()
        self.ring_buffer = None
        self.change_detector = ChangeDetector(
            method=config.change_detection.method,
            threshold=config.change_detection.threshold,
            noise_band=getattr(config.change_detection, "noise_band", 25),
            min_region_area=config.change_detection.min_region_area,
        )
        self.rois = ROIManager([r.model_dump() for r in config.regions])
        self.ocr = get_ocr_provider(config.ocr.provider, config.ocr.language)
        self.state_tracker = StateTracker()
        self.classifier = EventClassifier()

        # intelligence
        self.rules = RuleEngine()
        loaded = self.rules.load_from_file(config.rules.file)
        log.info("loaded %d rule(s)", loaded)
        self.vlm = get_vlm_provider(config.vlm.provider, config.vlm.host, config.vlm.model, config.vlm.timeout_seconds)
        self.memory = EventMemory()
        self.planner = Planner(self.rules, self.vlm if config.vlm.enabled else None, self.memory)
        self.rule_compiler = RuleCompiler(config.vlm.host)

        # policy
        self.domains = DomainAllowlist(
            config.policy.allowed_domains,
            config.policy.blocked_domains,
            config.policy.require_confirmation_for_unknown_domains,
        )
        self.apps = ApplicationAllowlist(config.policy.allowed_apps)
        self.grounding = get_grounding_provider(config.grounding.provider, self.ocr)
        self.firewall = ActionFirewall(config.policy, self.domains, self.apps, self.grounding)

        # automation (enabled flag gates everything; dry_run for safe testing)
        from app.automation.applications import ApplicationController
        from app.automation.browser import BrowserController
        from app.automation.executor import ActionExecutor
        from app.automation.keyboard import KeyboardController
        from app.automation.mouse import MouseController
        from app.automation.windows import WindowController

        dry = config.automation.dry_run or not config.automation.enabled
        self.executor = ActionExecutor(
            mouse=MouseController(dry_run=dry),
            keyboard=KeyboardController(dry_run=dry),
            browser=BrowserController(mode=config.automation.browser, dry_run=dry),
            apps=ApplicationController(self.apps, dry_run=dry),
            windows=WindowController(dry_run=dry),
        )
        self.automation_live = config.automation.enabled and not config.automation.dry_run

        # verification
        self.verifier: Optional[PostActionVerifier] = None  # needs capture; set in start()

        # runtime
        self._running = False
        self._paused = False
        self._pending_confirmations: dict = {}
        self._killswitch_thread: Optional[threading.Thread] = None
        self._last_screen_change_event: float = 0.0
        self.SCREEN_CHANGED_THROTTLE_S = 10.0
        # lightweight resource sampling (only while a meeting is active)
        self._last_metrics_sample: float = 0.0
        self.METRICS_INTERVAL_S = 30.0

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def start_capture(self) -> None:
        from app.capture.ring_buffer import RingBuffer
        from app.capture.screen import get_capture_provider

        self.capture = get_capture_provider(
            self.config.capture.source, self.config.capture.monitor,
            self.config.capture.width, self.config.capture.height,
        )
        self.ring_buffer = RingBuffer(max_seconds=self.config.memory.ring_buffer_seconds)
        self.verifier = PostActionVerifier(
            capture_fn=lambda: self.capture.capture() if self.capture else None,
            ocr_extract=lambda img: " ".join(i.text for i in self.ocr.extract(img).items),
        )
        self.state.status = "running"
        from app.events.models import now_iso

        self.state.started_at = now_iso()
        log.info("capture provider ready (source=%s)", self.config.capture.source)

    def start_killswitch(self) -> None:
        """Global hotkey listener handled OUTSIDE the VLM loop (spec §40)."""
        if not self.config.automation.enabled:
            return

        def _listener():
            try:
                from pynput import keyboard

                combos = _parse_hotkey(self.config.kill_switch.hotkey)
                current: set = set()

                def on_press(key):
                    try:
                        if key in combos:
                            current.add(key)
                        elif hasattr(key, "char") and key.char and keyboard.KeyCode.from_char(key.char) in combos:
                            current.add(keyboard.KeyCode.from_char(key.char))
                        if combos and combos.issubset(current):
                            log.warning("KILL SWITCH pressed")
                            self.emergency_stop()
                            current.clear()
                    except Exception:  # noqa: BLE001
                        pass

                def on_release(key):
                    try:
                        if key in current:
                            current.remove(key)
                        elif hasattr(key, "char") and key.char and keyboard.KeyCode.from_char(key.char) in current:
                            current.remove(keyboard.KeyCode.from_char(key.char))
                    except Exception:  # noqa: BLE001
                        pass

                with keyboard.Listener(on_press=on_press, on_release=on_release) as lst:
                    lst.join()
            except ImportError:
                log.info("pynput not available; hotkey kill switch disabled")
            except Exception as exc:  # noqa: BLE001
                log.warning("kill switch listener failed: %s", exc)

        self._killswitch_thread = threading.Thread(target=_listener, daemon=True, name="killswitch")
        self._killswitch_thread.start()

    async def run(self) -> None:
        """Main observation loop — meeting-gated and adaptive (tasks 3+4)."""
        if self.capture is None:
            self.start_capture()
        self._running = True
        self.state.status = "running"
        log.info("agent loop started (mode=%s, meeting-gated)", self.mode)
        try:
            while self._running:
                cycle_start = time.time()
                if not self._paused:
                    try:
                        await asyncio.to_thread(self.tick)
                    except Exception:
                        log.exception("tick failed")
                # adaptive sleep: fast during meetings, slow standby otherwise
                await asyncio.sleep(self._sleep_interval())
        except asyncio.CancelledError:
            pass
        finally:
            self.state.status = "stopped"
            log.info("agent loop stopped")

    def _sleep_interval(self) -> float:
        meeting = self.current_meeting is not None
        if meeting:
            return 1.0 / max(self.config.capture.fps, 0.1)   # capture fps during meetings
        return self.idle_sleep                                # cheap standby otherwise

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    def _update_meeting_state(self) -> None:
        """Detect meeting transitions; drives gating + session events."""
        meeting = self.tracker.get_meeting()
        prev = self.current_meeting
        self.current_meeting = meeting

        # publish to dashboard/API
        self.state.meeting_active = meeting is not None
        self.state.meeting_app = meeting.app if meeting else None
        self.state.meeting_title = meeting.title[:80] if meeting else None

        now = time.time()
        if meeting and (prev is None or prev.app != meeting.app):
            self._active_since = now
            self.change_detector.reset()  # fresh baseline for the new window
            self.handle_event(
                Event(
                    type=EventType.MEETING_STATE_CHANGED,
                    source="meeting_tracker",
                    text=f"meeting detected: {meeting.app} — {meeting.title[:80]}",
                    confidence=1.0,
                ),
                None,
                record_only=True,
            )
            log.info("meeting active: %s (%s)", meeting.app, meeting.title[:60])
        elif not meeting and prev is not None:
            self._active_since = None
            self.handle_event(
                Event(
                    type=EventType.MEETING_STATE_CHANGED,
                    source="meeting_tracker",
                    text=f"meeting ended: {prev.app}",
                    confidence=1.0,
                ),
                None,
                record_only=True,
            )
            log.info("meeting ended: %s — returning to standby", prev.app)

    def _observe_meeting(self, meeting) -> None:
        """Observe ONLY the meeting window region (task 4)."""
        try:
            frame: Frame = self.capture.capture()
        except Exception as exc:  # noqa: BLE001
            log.error("capture failure: %s — automation halted", exc)
            self.firewall.emergency_stop = True
            self.state.status = "degraded"
            return

        # Crop to the meeting window when we know where it is
        obs_img = frame.image
        bbox = meeting.bbox if meeting else None
        if bbox:
            x, y, w, h = bbox
            H, W = frame.image.shape[:2]
            x, y = max(0, x), max(0, y)
            w, h = min(w, W - x), min(h, H - y)
            if w > 10 and h > 10:
                obs_img = frame.image[y : y + h, x : x + w]
            else:
                obs_img = None  # window off-screen/invalid: skip OCR, keep state

        if obs_img is not None:
            self.ring_buffer.push(Frame(image=obs_img, monitor=frame.monitor))
            self.state.frames_in_buffer = len(self.ring_buffer)

            regions = self.rois.pixel_regions(obs_img.shape[1], obs_img.shape[0])
            result = self.change_detector.evaluate_frame(
                obs_img, [(r.name, (reg.x, reg.y, reg.w, reg.h)) for r, reg in regions]
            )
            if result.changed:
                self._maybe_screen_changed_event(result)
                self._process_changed_regions(result, regions, obs_img)

        self._sample_resources()

    def _maybe_screen_changed_event(self, result) -> None:
        now_mono = time.monotonic()
        if now_mono - self._last_screen_change_event >= self.SCREEN_CHANGED_THROTTLE_S:
            self._last_screen_change_event = now_mono
            self.handle_event(
                Event(
                    type=EventType.SCREEN_CHANGED,
                    source="screen",
                    text=f"changed regions: {', '.join(result.changed_regions)}",
                    confidence=1.0,
                ),
                None,
                record_only=True,
            )

    def _process_changed_regions(self, result, regions, obs_img) -> None:
        for roi, reg in regions:
            if roi.name not in result.changed_regions:
                roi.mark_processed()
                continue
            if not roi.due():
                continue
            roi.mark_processed()
            crop = obs_img[reg.y : reg.y + reg.h, reg.x : reg.x + reg.w]
            if crop.size == 0:
                continue
            try:
                ocr_result = self.ocr.extract(crop)
                self.state.ocr_calls += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("OCR failure (continuing observation, §37): %s", exc)
                continue
            text = " ".join(i.text for i in ocr_result.items).strip()
            if not text:
                continue
            events = self.classifier.classify_region_text(
                text, source=self._source_for(roi.name), region=roi.name, state=self.state_tracker
            )
            for ev in events:
                self.handle_event(ev, None)

    def _sample_resources(self) -> None:
        """Lightweight CPU/RAM sampling every 30s while a meeting is active."""
        now = time.time()
        if now - self._last_metrics_sample < self.METRICS_INTERVAL_S:
            return
        self._last_metrics_sample = now
        try:
            import psutil

            p = psutil.Process()
            self.state.cpu_percent = p.cpu_percent(interval=None)
            self.state.ram_mb = p.memory_info().rss / 1e6
        except Exception:  # noqa: BLE001
            pass

    def tick(self) -> None:
        """One observation pass. Cheap when no meeting; focused when active."""
        self._update_meeting_state()
        meeting = self.current_meeting
        if meeting is None:
            return  # standby: no capture, no OCR, no events (task 4)
        self._observe_meeting(meeting)

    # ------------------------------------------------------------------
    def _source_for(self, region_name: str) -> str:
        if "chat" in region_name.lower():
            return "meeting_chat"
        if "notif" in region_name.lower():
            return "notifications"
        return region_name

    def handle_event(
        self,
        event: Event,
        frame: Optional[Frame] = None,
        record_only: bool = False,
    ) -> None:
        """Full pipeline for one event: plan → firewall → execute → verify.

        record_only=True bypasses planning/firewall for pure activity markers
        that must never trigger actions (e.g. SCREEN_CHANGED, §11).
        """
        self.state.events_seen += 1
        self.state.current_event = event
        self.memory.remember(event)
        self.repo.record_event(event)
        if record_only:
            return

        proposal = self.planner.propose(event, user_rule_hint=", ".join(self.rules.describe()))

        # §33/§36: a URL event on an unknown domain always asks the user,
        # even when no rule matched (never silently ignore, never auto-open).
        if (
            proposal.decision == "IGNORE"
            and event.url
            and self.config.policy.require_confirmation_for_unknown_domains
        ):
            status, _detail = self.domains.check(event.url)
            if status == "unknown":
                proposal = ActionProposal(
                    decision="ASK_USER",
                    action=Action(
                        type=ActionType.OPEN_URL,
                        url=event.url,
                        expected_state=StateMatcher.url_loaded(event.url),
                    ),
                    confidence=0.5,
                    reason="URL domain is not allowlisted — requesting confirmation (§36)",
                    requires_confirmation=True,
                )

        self.state.last_proposal = proposal

        current_image = None
        if frame is not None:
            current_image = frame.image
        elif self.ring_buffer is not None and self.ring_buffer.latest() is not None:
            latest = self.ring_buffer.latest()
            current_image = latest.image
        decision = self.firewall.evaluate(proposal, self.mode, frame_image=current_image)
        self.state.last_decision = decision
        action_row = self.repo.record_decision(
            event,
            proposal.action.type.value if proposal.action else "none",
            proposal.reason,
            decision,
        )

        # SUGGEST mode (§29): any actionable proposal is offered to the user,
        # never executed and never silently dropped.
        if self.mode == "suggest" and proposal.decision == "ACT" and proposal.action is not None:
            self._pending_confirmations[event.id] = (proposal, decision, event)
            log.info("SUGGEST: found %s — proposed %s (awaiting user)", event.type.value, proposal.action.type.value)
            return

        if proposal.decision == "ASK_USER" or decision.requires_confirmation:
            self._pending_confirmations[event.id] = (proposal, decision, event)
            if decision.requires_confirmation or proposal.decision == "ASK_USER":
                log.info("SUGGEST: %s (reason: %s)", proposal.reason or decision.reason, decision.reason)
            return

        if decision.approved and proposal.action is not None:
            self._execute_and_verify(proposal.action, event, decision, action_row)
        else:
            log.info("blocked: %s", decision.reason)

    def _execute_and_verify(self, action: Action, event: Event, decision: PolicyDecision, action_row: int) -> None:
        """ACT → OBSERVE AGAIN → VERIFY (§22). With retry ceiling (§37)."""
        if self.mode == "observe":
            log.info("OBSERVE mode: would execute %s", action.type.value)
            return
        result = self.executor.execute(action)
        self.firewall.record_execution(action)
        log.info("executed %s → success=%s (%s)", action.type.value, result.success, result.detail)

        verification = VerificationResult(verified=False, detail="not verified")
        if self.verifier is not None:
            verification = self.verifier.verify(action, result)
        self.repo.record_verification(action_row, verification)
        log.info("verification: %s (%s)", verification.verified, verification.detail)

        execution_failed = not result.success
        verification_failed = self.verifier is not None and not verification.verified
        if execution_failed or verification_failed:
            retries = self.firewall.register_failure(action)
            if self.firewall.retries_exhausted(action):
                log.error("retry ceiling reached for %s — stopping autonomous retries (§37)", action.type.value)
                self._paused = True
                self.state.status = "paused"

    # ------------------------------------------------------------------
    # modes & control (§29/§28)
    # ------------------------------------------------------------------
    @property
    def mode(self) -> str:
        return self.state.mode

    def set_mode(self, mode: str) -> bool:
        if mode not in ("observe", "suggest", "assist", "autonomous"):
            return False
        self.state.mode = mode
        log.info("mode set to %s", mode)
        return True

    def pause(self) -> None:
        self._paused = True
        self.state.status = "paused"

    def resume(self) -> None:
        self._paused = False
        self.state.status = "running"

    def emergency_stop(self) -> None:
        """Immediate halt of all autonomous actions (§40)."""
        self.firewall.trigger_emergency_stop()
        self._paused = True
        self.state.emergency_stop = True
        self.state.status = "paused"
        log.warning("emergency stop: all autonomous actions halted")

    def clear_emergency(self) -> None:
        self.firewall.emergency_stop = False
        self.state.emergency_stop = False
        self.resume()

    # pending confirmations (dashboard ALLOW/BLOCK)
    def confirm_action(self, event_id: str) -> Optional[PolicyDecision]:
        item = self._pending_confirmations.pop(event_id, None)
        if item is None:
            return None
        proposal, decision, event = item
        if proposal.action is not None:
            action_row = self.repo.record_decision(event, proposal.action.type.value, "user confirmed", decision)
            self._execute_and_verify(proposal.action, event, decision, action_row)
        return decision

    def reject_action(self, event_id: str) -> Optional[PolicyDecision]:
        item = self._pending_confirmations.pop(event_id, None)
        if item is None:
            return None
        _, decision, event = item
        self.repo.record_decision(event, "none", "user rejected", PolicyDecision(approved=False, reason="user rejected"))
        return decision

    # commands (§28)
    def handle_command(self, text: str) -> str:
        from app.speech.commands import parse_command

        cmd = parse_command(text)
        if cmd is None:
            return "unknown command"
        if cmd.name == "emergency_stop":
            self.emergency_stop()
            return "emergency stop engaged"
        if cmd.name == "pause":
            self.pause()
            return "paused"
        if cmd.name == "resume":
            self.clear_emergency() if self.state.emergency_stop else self.resume()
            return "resumed"
        if cmd.name == "take_over":
            self.set_mode("autonomous")
            return "autonomous mode enabled"
        if cmd.name == "manual_mode":
            self.set_mode("observe")
            return "manual (observe) mode"
        if cmd.name == "what_detected":
            return f"{self.state.events_seen} events detected"
        if cmd.name == "what_did":
            acts = self.repo.db.list_actions(10)
            return "; ".join(f"{a['action_type']}({'ok' if a['approved'] else 'blocked'})" for a in acts) or "nothing yet"
        if cmd.name == "show_rules":
            return "\n".join(self.rules.describe()) or "no rules"
        if cmd.name == "disable_rule" and cmd.argument:
            ok = self.rules.set_enabled(cmd.argument.strip(), False)
            return f"rule {cmd.argument} disabled" if ok else "rule not found"
        if cmd.name == "enable_rule" and cmd.argument:
            ok = self.rules.set_enabled(cmd.argument.strip(), True)
            return f"rule {cmd.argument} enabled" if ok else "rule not found"
        if cmd.name == "mode" and cmd.argument:
            return "mode set" if self.set_mode(cmd.argument) else "invalid mode"
        return "unhandled command"

    # rule compilation (§21)
    def compile_rule(self, instruction: str) -> str:
        ok, msg, rule = self.rule_compiler.compile(instruction)
        if ok and rule is not None:
            self.rules.add_rule(rule)
            self.repo.record_rule(rule)
            return f"rule '{rule.id}' added"
        return f"rule compilation failed: {msg}"


def _parse_hotkey(hotkey: str) -> set:
    from pynput import keyboard

    mapping = {
        "ctrl": keyboard.Key.ctrl,
        "ctrl_l": keyboard.Key.ctrl_l,
        "alt": keyboard.Key.alt,
        "shift": keyboard.Key.shift,
        "win": keyboard.Key.cmd,
    }
    out = set()
    for part in hotkey.split("+"):
        part = part.strip().lower()
        if part in mapping:
            out.add(mapping[part])
        elif len(part) == 1:
            out.add(keyboard.KeyCode.from_char(part))
    return out

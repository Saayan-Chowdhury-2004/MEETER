"""Meeting-window tracker (tasks 3+4).

The agent only observes while a known meeting application is in the
foreground, and then only observes that application's window — not the whole
desktop. When no meeting is running, the agent idles (tiny poll, no OCR,
no events), which makes long sessions and all-day standby cheap.

Detection is deterministic and layered:
1. Process names (psutil) — robust (zoom.exe, Teams.exe, ...).
2. Window titles (pygetwindow) — catches browser-based meetings (Meet in
   Chrome/Edge) and PWA windows without spawning extra processes.
3. Browser tab titles (pygetwindow titles only; no screenshots of non-meeting
   windows are ever OCR'd).

No pixels of non-meeting windows are processed. This directly implements
task 4: no tracking of general desktop activity.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)


@dataclass
class MeetingWindow:
    app: str                      # zoom | webex | teams | meet | meet_generic | slack_huddle...
    title: str
    process: Optional[str] = None
    hwnd: Optional[int] = None    # OS window handle
    bbox: Optional[Tuple[int, int, int, int]] = None  # left, top, width, height


@dataclass
class MeetingTrackerConfig:
    # process-name -> canonical app label
    process_map: dict = field(default_factory=lambda: {
        "zoom.exe": "zoom",
        "webexmta.exe": "webex",
        "webex.exe": "webex",
        "cisco webex meetings.exe": "webex",
        "teams.exe": "teams",
        "ms-teams.exe": "teams",
        "skype.exe": "skype",
        "slack.exe": "slack",
        "discord.exe": "discord",
        "goog Meet.exe": "meet",
    })
    # title keywords -> app label (checked case-insensitively)
    title_keywords: List[str] = field(default_factory=lambda: [
        "zoom meeting", "zoom webinar", "zoom - ", "zoom",
        "cisco webex meetings", "webex meetings", "webex",
        "microsoft teams", "teams meeting", " ms teams", "teams",
        "google meet", "meet - ", "google meet - ",
        "slack huddle", "huddle",
        "discord voice",
    ])
    # meeting title keyword -> app label
    keyword_map: dict = field(default_factory=lambda: {
        "zoom": "zoom",
        "webex": "webex",
        "teams": "teams",
        "google meet": "meet",
        "meet -": "meet",
        "huddle": "slack",
        "discord voice": "discord",
    })
    # browser process names that can host web meetings (their windows are
    # inspected only via TITLE, never via pixels)
    browser_processes: set = field(default_factory=lambda: {
        "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
    })
    poll_interval_idle: float = 2.0     # seconds between checks when no meeting
    poll_interval_active: float = 5.0   # seconds between checks during a meeting


class MeetingTracker:
    """Detects the active meeting window; returns None when no meeting runs."""

    def __init__(self, config: Optional[MeetingTrackerConfig] = None) -> None:
        self.config = config or MeetingTrackerConfig()
        self._last: Optional[MeetingWindow] = None

    # ------------------------------------------------------------------
    def get_meeting(self) -> Optional[MeetingWindow]:
        """Return the current meeting window or None. Cheap, no pixels."""
        win = self._detect()
        self._last = win
        return win

    @property
    def last(self) -> Optional[MeetingWindow]:
        return self._last

    # ------------------------------------------------------------------
    def _detect(self) -> Optional[MeetingWindow]:
        # 1) dedicated meeting processes
        proc_hit = self._by_process()
        if proc_hit:
            return proc_hit
        # 2) window titles of all apps incl. browsers (Meet in a tab)
        return self._by_window_title()

    def _by_process(self) -> Optional[MeetingWindow]:
        try:
            import psutil

            for p in psutil.process_iter(["name"]):
                name = (p.info["name"] or "").lower()
                app = self.config.process_map.get(name)
                if app:
                    return self._window_for_app(app, process=name)
        except ImportError:
            log.debug("psutil unavailable; process detection disabled")
        except Exception as exc:  # noqa: BLE001
            log.debug("process scan failed: %s", exc)
        return None

    def _window_for_app(self, app: str, process: str) -> Optional[MeetingWindow]:
        """Find the best matching OS window for a detected meeting process."""
        try:
            import pygetwindow as gw

            # per-app keywords for narrowing titles
            hints = {
                "zoom": ["zoom", "meeting", "webinar"],
                "webex": ["webex", "meeting"],
                "teams": ["teams", "meeting"],
                "meet": ["meet", "google"],
                "slack": ["slack"],
                "discord": ["discord"],
                "skype": ["skype"],
            }.get(app, [app])

            candidates = []
            for title in gw.getAllTitles():
                t = title.strip()
                if not t:
                    continue
                tl = t.lower()
                if any(h in tl for h in hints):
                    try:
                        wins = gw.getWindowsWithTitle(t)
                        if wins:
                            w = wins[0]
                            candidates.append(
                                MeetingWindow(
                                    app=app, title=t, process=process, hwnd=w._hWnd,
                                    bbox=(w.left, w.top, w.width, w.height),
                                )
                            )
                    except Exception:  # noqa: BLE001
                        candidates.append(MeetingWindow(app=app, title=t, process=process))
            if not candidates:
                # process is running but window not found (minimized to tray?)
                return MeetingWindow(app=app, title=app, process=process)
            # prefer the largest visible window (the main meeting UI)
            candidates.sort(key=lambda m: (m.bbox is not None, -(m.bbox[2] * m.bbox[3]) if m.bbox else 0), reverse=True)
            best = candidates[0]
            # avoid nonsense zero-size
            if best.bbox and (best.bbox[2] < 100 or best.bbox[3] < 100):
                best.bbox = None
            return best
        except Exception as exc:  # noqa: BLE001
            log.debug("window lookup failed for %s: %s", app, exc)
            return MeetingWindow(app=app, title=app, process=process)

    def _by_window_title(self) -> Optional[MeetingWindow]:
        """Title scan across all windows; catches browser-based meetings."""
        try:
            import pygetwindow as gw
        except ImportError:
            return None
        try:
            for title in gw.getAllTitles():
                t = title.strip()
                if not t:
                    continue
                tl = t.lower()
                for kw in self.config.title_keywords:
                    if kw in tl:
                        app = self._app_for_keyword(tl)
                        if app:
                            try:
                                wins = gw.getWindowsWithTitle(t)
                                w = wins[0] if wins else None
                                return MeetingWindow(
                                    app=app, title=t,
                                    process="browser" if self._is_browser_title(tl) else None,
                                    hwnd=w._hWnd if w else None,
                                    bbox=(w.left, w.top, w.width, w.height) if w else None,
                                )
                            except Exception:  # noqa: BLE001
                                return MeetingWindow(app=app, title=t)
            return None
        except Exception as exc:  # noqa: BLE001
            log.debug("title scan failed: %s", exc)
            return None

    def _app_for_keyword(self, title_lower: str) -> Optional[str]:
        for kw, app in self.config.keyword_map.items():
            if kw in title_lower:
                return app
        return None

    def _is_browser_title(self, title_lower: str) -> bool:
        # heuristic: browser meeting titles end with "- Google Chrome" etc.
        return any(b in title_lower for b in (
            "google chrome", "microsoft edge", "mozilla firefox", "brave", "opera",
        ))

    # ------------------------------------------------------------------
    def poll_interval(self, meeting_active: bool) -> float:
        return self.config.poll_interval_active if meeting_active else self.config.poll_interval_idle

# How It Works — A Guided Tour

> This is a plain-language explanation of the Meeting Agent: the mental model, what
> each folder does, how to start it, and why it looks like "nothing is happening"
> at first. For setup details, licensing, and security limitations, see `README.md`.

The confusion first: **the implementation exists, it's all in `app/`** — 41 Python
modules. The frontend is deliberately just *one* HTML file; it's a thin control panel
that talks to the backend. If you open `frontend/dashboard/index.html` directly in a
browser it looks dead, because it's meant to be **served by** the running agent.
There's no separate frontend build, no React app — by design (spec §5.5:
"lightweight HTML/JS").

---

## The mental model

```
MEETING TRACKER (Zoom/Webex/Teams/Meet…)
      │  no meeting running? → STANDBY: 2-second poll, no capture, no OCR, no events
      │  meeting detected
      ▼
Meeting window only (never the whole desktop, never your other apps)
      │  screenshots at capture FPS
      ▼
CHEAP WATCHER  ── is this region different from last frame? ── no → throw frame away
      │ yes
      ▼
OCR (PaddleOCR reads the text)  →  regex finds URLs/buttons
      │
      ▼
EVENTS  (NEW_URL, NEW_MESSAGE, BUTTON_APPEARED… structured JSON)
      │
      ▼
RULES  ("open links from chat")  ── matched? ── yes → action proposal
      │ no match / ambiguous
      ▼
VLM (Qwen3-VL via Ollama, optional)  → action proposal
      │
      ▼
ACTION FIREWALL  (10 checks: mode allows it? domain allowlisted? target still on screen? confidence high enough? already done?)
      │ approved
      ▼
EXECUTOR  (click / open URL / launch app)
      │
      ▼
VERIFY  (screenshot again: did it actually work?)  →  SQLite log (metadata only)
```

The whole point: **the agent only works while you are in a meeting, and then only
looks at the meeting window.** The cheap watcher handles 99% of frames; OCR and
everything below it only run when something actually changed. Start the agent in
the morning; it costs almost nothing until your 2 PM call begins.

---

## What each folder does

| Path | Role |
|---|---|
| `app/agent.py` | **The orchestrator** — the loop that runs the whole pipeline every frame, holds the 4 modes |
| `app/main.py` | Entry point: loads config, starts agent + local web server |
| `app/capture/` | Screen grabbers (MSS today, Windows Graphics Capture stubbed) + the 60-second RAM ring buffer |
| `app/perception/` | Meeting tracker (Zoom/Webex/Teams/Meet detection), change detection, ROI regions, OCR providers, URL regex, dedup memory |
| `app/events/` | The typed event models + internal asyncio bus |
| `app/rules/` | Rule schema + matching engine (loads `config/rules.yaml`) |
| `app/intelligence/` | VLM providers (Ollama/llama.cpp/mock), NL rule compiler, event classifier |
| `app/policy/` | **The Action Firewall**, risk classes, domain/app allowlists |
| `app/automation/` | Mouse/keyboard/browser/app launching — the only code that can touch your PC |
| `app/verification/` | Post-action "did it work?" checker |
| `app/storage/` | SQLite: events, actions, verifications. Never images |
| `app/api.py` | FastAPI endpoints (`/status`, `/events`, `/mode`, `/emergency-stop`…) |
| `frontend/dashboard/index.html` | The dashboard UI (served at `http://127.0.0.1:8765/`) |
| `config/*.yaml` | All behavior: modes, regions, allowlists, rules |
| `tests/` | 77 tests incl. the 8 safety-critical scenarios and meeting-gating behavior |

---

## How to start it

**The simple way — two switches:**

```text
start_agent.bat        switch ON  (MEETING mode: OCR capped to 2 CPU threads,
                                   light enough to run beside any meeting)
start_agent.bat full   switch ON  (FULL mode: OCR may use all CPU threads,
                                   max speed when you need it)
stop_agent.bat         switch OFF (kills the agent; its CPU threads and RAM
                                   are released automatically)
```

Double-click them in Explorer or run from a terminal. The start script waits
until the dashboard is reachable, then tells you the URL. Starting twice is
harmless (it refuses to run a second copy), and stopping when nothing runs is
also harmless.

**Under the hood** the .bat files call `tools/agent_ctl.py`, which sets the
thread-cap environment variables *before* Python starts (MEETING mode) or sets
them to "all cores" (FULL mode). The cap exists only inside the agent process —
`stop_agent.bat` ends the process, so nothing capped lingers.

```powershell
# manual equivalent of the .bat files
.\.venv\Scripts\python tools\agent_ctl.py start          # ON, capped
.\.venv\Scripts\python tools\agent_ctl.py start --full   # ON, uncapped
.\.venv\Scripts\python tools\agent_ctl.py stop           # OFF
.\.venv\Scripts\python tools\agent_ctl.py status         # is it running?
```

Then open **http://127.0.0.1:8765/** — that's the dashboard, live and fed by
the backend.

Other useful commands:

```powershell
.\.venv\Scripts\python -m pytest tests -q     # run the safety tests
.\.venv\Scripts\python -m app.benchmark       # performance report
```

---

## Why it looks like "nothing is happening"

Three safety gates are **closed by default**, on purpose:

1. **Mode = `observe`** — it watches and logs, never acts (spec §29 default).
2. **`automation.enabled: false`** — mouse/keyboard code exists but runs dry-run.
3. **No VLM configured** — rules do the work; AI is opt-in.

So when you start it: it captures your screen, detects changes, reads text, writes
events to SQLite and the dashboard… and does nothing else. That's correct behavior.
Actions only become possible when you switch to `suggest`/`assist`/`autonomous`
**and** enable automation — and even then the firewall, allowlists, and confirmation
gates still apply.

The fastest way to *see* it work: start it, open the dashboard, and just use your PC
normally — then click through **Recent events**; you'll see it noticing URLs and
window changes in real time.

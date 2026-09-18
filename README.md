# Local Third-Person Meeting Agent

A local-first, open-source **computer-use observer agent** for Windows. It watches your
screen from outside the meeting application (Google Meet / Teams / Zoom / anything),
detects important events as they happen, and can perform **pre-authorized** actions —
like opening GitHub links posted in the meeting chat — without any meeting-platform
integration, cloud AI, subscriptions, or paid APIs.

> Think of it as a cautious third person sitting beside you during an 8-hour meeting:
> mostly silent, occasionally useful, never touching anything you did not allow.

## Design principle

**The agent thinks only when thinking is necessary — and only when a meeting is running.**

```
meeting tracker (Zoom/Webex/Teams/Meet…) ── none running → STANDBY (tiny poll, no OCR, no events)
        │ meeting detected
        ▼
capture (meeting window only) → change detection → ROI routing → OCR / deterministic analysis
        → event engine → (rules | grounding | local VLM)
        → action firewall → executor → post-action verification → event log
```

- **Meeting-gated (default):** the agent idles until it detects a known meeting app,
  then observes **only that app's window** — it does not track general desktop activity.
- The screen is watched **cheaply** (pixel-ratio change detection per ROI).
- Changed regions get **OCR** (CPU-thread-capped) ; OCR text becomes **structured events**
  (URLs, buttons, messages).
- **Rules** (deterministic) resolve most events. The **local VLM** (Qwen3-VL via Ollama/llama.cpp)
  is called only when semantics are ambiguous.
- Every action passes the **Action Firewall** (10 checks, spec §16) before execution,
  and is **verified** afterwards.
- Visual frames live in a **60-second RAM ring buffer** and expire automatically.
  Only event metadata is persisted (SQLite). No meeting recording.

## Quick start (Windows)

```powershell
# 1. Create venv and install
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\pip install -e ".[dev]"

# 2. Run tests
.\.venv\Scripts\python -m pytest tests -q

# 3. Generate synthetic fixtures (optional)
.\.venv\Scripts\python scripts\make_fixtures.py

# 4. Benchmark
.\.venv\Scripts\python -m app.benchmark

# 5. Run (OBSERVE mode by default — the agent watches but never acts)
.\.venv\Scripts\python -m app.main
# Dashboard: http://127.0.0.1:8765/
```

Or use the scripts: `powershell -File scripts\setup.ps1`, then `scripts\start.ps1`.

## Modes

| Mode | Behavior |
|---|---|
| `observe` (default) | Watches and logs events. Never executes. |
| `suggest` | Proposes actions in the dashboard; you click ALLOW/BLOCK. |
| `assist` | Autonomously performs low-risk pre-approved actions (e.g. allowlisted URLs). |
| `autonomous` | Performs all actions your policy allows. Enable explicitly. |

Kill switch: `Ctrl+Alt+Shift+M` (configurable) halts all autonomous actions immediately,
outside the AI loop. The dashboard also has an EMERGENCY STOP button.

## Configuration

- `config/default.yaml` — agent, capture, regions, OCR, VLM, policy, API.
- `config/policies.yaml` — risk classes, mode capabilities, domain/app allowlists.
- `config/rules.yaml` — structured rules; editable, or add via dashboard/API:
  `"Open every GitHub link posted in chat"` is compiled to a validated rule
  (local LLM when available, deterministic pattern compiler otherwise — never arbitrary code).

## Default safety posture

- OBSERVE mode until you change it.
- Automation disabled (`automation.enabled: false`); mouse/keyboard run dry-run until enabled.
- Unknown domains always ask for confirmation.
- High-risk actions (submit, delete, shell, purchase…) are **not in the action schema at all**.
- Duplicate actions are blocked; failed verification stops after `max_action_retries: 1`.
- Meeting content is treated as **untrusted input**; it can never override system policy
  (prompt-injection defense per spec §38/§39).

## Local AI (optional)

The deterministic pipeline works without any model. To enable the VLM:

```powershell
# Install Ollama from https://ollama.com, then:
ollama pull qwen3-vl
# then set in config/default.yaml:  vlm: { enabled: true, provider: ollama }
```

OCR uses PaddleOCR (Apache-2.0) when installed; otherwise the agent runs with the
silent fallback provider (change detection still works; text events are simply absent).

## Security limitations (read before enabling automation)

- **This software controls your mouse and keyboard.** Keep AUTONOMOUS mode off unless you
  understand exactly which rules are active. The `take over` voice/text command enables it.
- OCR and grounding are imperfect: a misread button label can cause a wrong click.
  Mitigations (allowlists, confidence gates, target revalidation) reduce but do not
  eliminate this risk.
- URL detection is regex-based; it can be spoofed by look-alike domains. Only the
  allowlist protects you — keep it short.
- Meeting content is attacker-controlled if a participant is hostile. The agent treats it
  as untrusted, but defense depends on the policy files; review `config/policies.yaml`.
- The local API has **no authentication** — it is bound to 127.0.0.1, but any local process
  can call it. Do not run untrusted software alongside the agent.
- No sandboxing: the automation layer uses real OS input. A bug can click the wrong thing.
- This is V1 quality software: test in OBSERVE/SUGGEST modes across several meetings
  before trusting ASSIST/AUTONOMOUS.

## Decision records (spec §59)

| Decision | Why | Alternatives | Licensing | Performance | Security |
|---|---|---|---|---|---|
| MSS capture (WGC stub) | zero-setup, fast (~19 FPS measured) | Windows Graphics Capture (production path stubbed), dxcam | LGPL-ish (mss is MIT/BSD-style) | excellent | reads screen only |
| Pixel-ratio change detection | robust to text-in-small-region changes (mean-diff failed on chat text: 0.65 vs threshold 12) | mean abs diff, SSIM | n/a | 1.7 ms/frame @ 1280x720 | none |
| Silent fallback OCR | prefers no info over wrong info (§36) | Tesseract (heavy), heuristic OCR (produced noise events) | Apache-2.0 (Paddle) | Paddle ~100-300 ms; fallback ~20 ms | none |
| Regex URL extraction | deterministic, auditable, spec §10 forbids VLM here | VLM extraction | n/a | <1 ms | allowlist-gated downstream |
| Rules before VLM | deterministic-first (§48) | VLM-first | n/a | avoids all VLM latency when rules match | smaller attack surface |
| Ollama VLM provider | local inference, no cloud | llama.cpp server (adapter included) | Apache-2.0 (Qwen3-VL) | ~1-2 s/call (GPU) | screen crops only, structured JSON out |
| Action Firewall as separate module | mandatory gate (§16); testable in isolation | inline checks | n/a | negligible | the core safety mechanism |
| SQLite metadata only | spec §45 forbids media archive | files, Postgres | public domain | negligible | no sensitive frames on disk |
| asyncio in-process bus | spec §44 forbids brokers for V1 | Redis/Kafka | n/a | sub-ms pub/sub | no network exposure |

## Repository layout

See the spec §31; notable additions: `app/agent.py` (orchestrator), `app/api.py`
(control API), `app/benchmark.py` (spec §35 report), `frontend/dashboard/index.html`.

## What is NOT implemented in V1 (per spec)

- Windows Graphics Capture production capture (stub — MSS works today).
- OmniParser model weights wiring (adapter + OCR-grounding fallback included).
- faster-whisper voice loop (command parser + STT interface ready; `sounddevice` loop optional).
- USB-camera secondary sensor (Phase 12).
- `submit_form`, `delete_file`, `execute_shell`, `send_email`, `purchase`,
  `account_setting_change` are intentionally absent from the action schema (spec §52).

## Licenses of pinned dependencies (verify before distribution)

| Package | License |
|---|---|
| pydantic 2.5.3 | MIT |
| PyYAML 6.0.1 | MIT |
| mss 9.0.1 | MIT |
| opencv-python 4.9.0.80 | Apache-2.0 |
| numpy 1.26.4 | BSD-3 |
| paddleocr 2.7.0.3 | Apache-2.0 |
| Pillow 10.2.0 | HPND (MIT-CMU) |
| fastapi 0.104.1 | MIT |
| uvicorn 0.24.0.post1 | BSD-3 |
| pyautogui 0.9.54 | BSD-3 |
| pynput 1.7.6 | LGPL-3.0 |
| playwright 1.40.0 | Apache-2.0 |
| requests 2.31.0 | Apache-2.0 |
| faster-whisper (optional) | MIT |
| Qwen3-VL (model) | Apache-2.0 |
| Ollama | MIT |
| llama.cpp | MIT |
| OmniParser | MIT (components) |

> Re-verify each pinned version's license before packaging/distributing (spec §6).

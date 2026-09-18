# Changelog

All notable changes to the **MEETER — Local Third-Person Meeting Agent** are
documented in this file. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Working rules for this file**
> 1. **Read the latest entries before modifying the project** — they record design
>    decisions, file locations, and constraints that new changes must respect.
> 2. Add a new entry under **[Unreleased]** for every functional change, with the
>    files touched and the reason ("why", not just "what").
> 3. When changes are committed, move them into a version section (or a dated
>    entry for pre-1.0 work) matching the git commit message.

---

## [Unreleased]

_(nothing yet — new changes go here first)_

---

## [0.1.0] — 2026-09-18

### Added — initial build (`ab4ce78`)
- Complete local-first computer-use agent per the build spec
  (`local-third-person-meeting-agent-build-spec.md`):
  `capture → change detection → ROI routing → OCR/deterministic analysis →
  event engine → (rules | grounding | local VLM) → action firewall →
  executor → post-action verification → event log`.
- **Pipeline modules** (`app/`): orchestrator (`agent.py`), control API (`api.py`),
  benchmark, screen capture + 60s RAM ring buffer (`capture/`), meeting tracker /
  change detector / OCR / URL detector / dedup memory (`perception/`), typed events
  + asyncio bus (`events/`), rule schema + engine (`rules/`), VLM providers
  (Ollama / llama.cpp / mock) + NL rule compiler (`intelligence/`), Action Firewall
  with risk classes and allowlists (`policy/`), automation layer (`automation/`),
  post-action verifier (`verification/`), SQLite metadata store (`storage/`).
- **Config** (`config/`): `default.yaml` (behavior), `policies.yaml` (safety:
  risk classes, mode capabilities, domain/app allowlists, blocked actions),
  `rules.yaml` (structured rules), `observe-live.yaml` (throttled live profile).
- **Frontend**: single-file dashboard (`frontend/dashboard/index.html`) served at
  `http://127.0.0.1:8765/` — events, rules, mode switch, proposals, emergency stop.
- **Safety posture**: OBSERVE default, automation dry-run until enabled, 10-check
  firewall, high-risk actions (submit/delete/shell/email/purchase) absent from the
  action schema, prompt-injection-resistant (meeting content is untrusted input),
  frames never persisted to disk.
- **Tests**: 77 tests incl. the 8 safety-critical scenarios and meeting-gating.
- **Tooling**: `start_agent.bat` / `stop_agent.bat` (via `tools/agent_ctl.py`),
  PowerShell setup/start/benchmark scripts, MIT `LICENSE`, `.env.example`,
  tailored `.gitignore` (excludes `data/`, logs, DB, `.venv`, `.env` — all
  runtime data stays local per the project plan).

### Changed — link handling generalized + cross-device scaffold (`21e3b07`)
> **Constraint for future work:** link *detection* is domain-agnostic —
> `app/perception/url_detector.py` captures **every** URL into the JSON event log.
> Nothing in this project may filter detection by domain. Domain scoping belongs
> only in *action* rules and the firewall allowlist.

- `config/rules.yaml`: default rule is now a generic, opt-in
  `open_shared_links` (any domain, `requires_confirmation: true`); the GitHub
  rule is kept only as a commented example.
- `config/policies.yaml`: documented that the domain allowlist gates *actions*,
  never detection or logging.
- `frontend/dashboard/index.html`: instruction-first UI ("Tell the agent what to
  do…"), links filter renamed to "Links (all)", new **Automation brain** card
  (live rules/Ollama/STT status), roadmap note for cross-device awareness.
- `app/config.py` + `config/default.yaml`: new `notify:` scaffold
  (`NotifyConfig`) for future cross-device awareness — `interesting_events`,
  `transport` (future: ntfy | pushover | webhook), `only_when_away`,
  `ollama_relay`. **Not wired to any transport yet.**
- `app/api.py`: `/status` now exposes `vlm` and `speech` state for the dashboard.
- `tests/conftest.py`: test agent injects its own GitHub rule so tests no longer
  depend on the repo's user-editable `rules.yaml`.

### Notes — runtime facts (not in git)
- Local Ollama v0.34.1 at `http://127.0.0.1:11434`; models available:
  `gpt-oss:20b` (text-only), `gemma4:latest` (vision-capable). Config's pinned
  `qwen3-vl` is **not pulled**; `gemma4:latest` has been verified working through
  `OllamaVLMProvider` (valid JSON → `ActionProposal`, decision ACT on a chat URL).
- To enable live inference: set `vlm.enabled: true` and `vlm.model: gemma4:latest`
  in `config/default.yaml`.
- Remote: `https://github.com/Saayan-Chowdhury-2004/MEETER.git` (branch `main`).

[Unreleased]: https://github.com/Saayan-Chowdhury-2004/MEETER/compare/0.1.0...HEAD
[0.1.0]: https://github.com/Saayan-Chowdhury-2004/MEETER/releases/tag/0.1.0

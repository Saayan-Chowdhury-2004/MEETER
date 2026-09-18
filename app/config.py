"""Typed configuration loading with environment-variable overrides.

Decision record (spec §59):
- Why YAML: human-editable, no cloud account, matches spec §42.
- Why Pydantic: schema validation with clear errors, type hints, no global state.
- Alternatives: TOML (fine but spec suggests YAML), JSON (no comments).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

import yaml
from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    mode: str = "observe"
    data_dir: str = "data"
    emergency_stop: bool = False


class CaptureConfig(BaseModel):
    source: str = "monitor"  # monitor | window | mock
    monitor: int = 1
    fps: float = 2.0
    width: int = 0
    height: int = 0


class MeetingConfig(BaseModel):
    """Meeting-gated observation (tasks 3+4)."""

    enabled: bool = True
    poll_interval_idle: float = 2.0
    poll_interval_active: float = 5.0


class MemoryConfig(BaseModel):
    ring_buffer_seconds: int = 60
    persist_frames: bool = False


class RegionConfig(BaseModel):
    name: str
    box: List[float]  # fractions x, y, w, h
    priority: str = "medium"
    polling_hz: float = 2.0


class ChangeDetectionConfig(BaseModel):
    method: str = "pixel_ratio"
    threshold: float = 0.002
    noise_band: int = 25
    min_region_area: float = 0.0005


class OcrConfig(BaseModel):
    enabled: bool = True
    provider: str = "auto"  # paddle | fallback | auto
    language: str = "en"


class UrlDetectionConfig(BaseModel):
    deduplicate: bool = True


class GroundingConfig(BaseModel):
    provider: str = "ocr"  # ocr | omniparser | mock


class VLMConfig(BaseModel):
    enabled: bool = False
    provider: str = "mock"  # mock | ollama | llama_cpp
    model: str = "qwen3-vl"
    host: str = "http://127.0.0.1:11434"
    confidence_threshold: float = 0.95
    timeout_seconds: float = 30.0


class RulesConfig(BaseModel):
    file: str = "config/rules.yaml"


class PolicyConfig(BaseModel):
    require_confirmation_for_unknown_domains: bool = True
    allow_form_submission: bool = False
    allow_file_deletion: bool = False
    allow_shell_commands: bool = False
    confidence_threshold: float = 0.95
    max_action_retries: int = 1
    # extended policy fields (loaded from policies.yaml)
    mode_capabilities: Dict[str, List[str]] = Field(default_factory=dict)
    blocked_actions: List[str] = Field(default_factory=list)
    allowed_domains: List[str] = Field(default_factory=list)
    blocked_domains: List[str] = Field(default_factory=list)
    allowed_apps: Dict[str, Dict[str, List[str]]] = Field(default_factory=dict)
    url_shorteners: List[str] = Field(default_factory=list)


class AutomationConfig(BaseModel):
    enabled: bool = False
    browser: str = "default"
    dry_run: bool = False


class SpeechConfig(BaseModel):
    enabled: bool = False
    model: str = "base.en"
    device: str = "cpu"


class NotifyConfig(BaseModel):
    """Cross-device awareness (roadmap scaffold).

    Not wired to any transport yet. When implemented, `on` events will ping
    the user's other device about interesting meeting moments, and the relay
    will carry follow-up instructions back to the agent.
    """

    enabled: bool = False
    interesting_events: List[str] = Field(
        default_factory=lambda: ["NEW_URL", "NEW_MESSAGE", "BUTTON_APPEARED", "MEETING_STATE_CHANGED"]
    )
    transport: str = "none"  # future: ntfy | pushover | webhook
    topic_url: str = ""      # e.g. https://ntfy.sh/<your-private-topic>
    only_when_away: bool = True
    ollama_relay: bool = False  # future: accept follow-up commands from remote device


class KillSwitchConfig(BaseModel):
    hotkey: str = "ctrl+alt+shift+m"


class ApiConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "data/agent.log"


class AppConfig(BaseModel):
    agent: AgentConfig = Field(default_factory=AgentConfig)
    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    meeting: MeetingConfig = Field(default_factory=MeetingConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    regions: List[RegionConfig] = Field(default_factory=list)
    change_detection: ChangeDetectionConfig = Field(default_factory=ChangeDetectionConfig)
    ocr: OcrConfig = Field(default_factory=OcrConfig)
    url_detection: UrlDetectionConfig = Field(default_factory=UrlDetectionConfig)
    grounding: GroundingConfig = Field(default_factory=GroundingConfig)
    vlm: VLMConfig = Field(default_factory=VLMConfig)
    rules: RulesConfig = Field(default_factory=RulesConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)
    speech: SpeechConfig = Field(default_factory=SpeechConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
    kill_switch: KillSwitchConfig = Field(default_factory=KillSwitchConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_yaml(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(path: str | Path = "config/default.yaml") -> AppConfig:
    """Load default config and merge the policies file over the policy section."""
    data = load_yaml(path)
    policies = load_yaml("config/policies.yaml")
    if policies:
        data["policy"] = _deep_merge(data.get("policy", {}), policies)
    cfg = AppConfig(**data)
    _apply_env_overrides(cfg)
    return cfg


def _env(name: str, current: Any, cast):
    v = os.environ.get(name)
    if v is None:
        return current
    try:
        return cast(v)
    except Exception:  # noqa: BLE001 — defensive: ignore bad env values
        return current


def _bool(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


def _apply_env_overrides(cfg: AppConfig) -> None:
    cfg.agent.mode = _env("MEETING_AGENT_MODE", cfg.agent.mode, str)
    cfg.agent.data_dir = _env("MEETING_AGENT_DATA_DIR", cfg.agent.data_dir, str)
    cfg.capture.source = _env("MEETING_AGENT_CAPTURE_SOURCE", cfg.capture.source, str)
    cfg.capture.fps = _env("MEETING_AGENT_CAPTURE_FPS", cfg.capture.fps, float)
    cfg.automation.enabled = _env(
        "MEETING_AGENT_ENABLE_AUTOMATION", cfg.automation.enabled, _bool
    )
    cfg.vlm.enabled = _env("MEETING_AGENT_ENABLE_VLM", cfg.vlm.enabled, _bool)
    cfg.vlm.host = _env("OLLAMA_HOST", cfg.vlm.host, str)
    cfg.api.host = _env("MEETING_AGENT_API_HOST", cfg.api.host, str)
    cfg.api.port = _env("MEETING_AGENT_API_PORT", cfg.api.port, int)
    cfg.agent.emergency_stop = _env(
        "MEETING_AGENT_EMERGENCY_STOP", cfg.agent.emergency_stop, _bool
    )

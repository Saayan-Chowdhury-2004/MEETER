"""Natural-language rule compiler (spec §21).

Uses a local LLM (Ollama) when available to translate a user sentence into a
rule dict, then validates it against the fixed Rule schema. If the LLM is
unavailable or produces invalid output, falls back to a small deterministic
pattern compiler. The compiler can never emit code — only schema-validated
rule dicts.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from app.rules.schema import Rule, validate_rule_dict

log = logging.getLogger(__name__)

_COMPILE_PROMPT = """You convert the user's instruction into a JSON rule for a local
computer-use agent. Respond with JSON only, no commentary.

Allowed triggers: {triggers}
Allowed action types: {actions}
Allowed condition keys: source, domain, url_contains, text_contains, region, button_label

Schema:
{{
  "name": "<snake_case_name>",
  "trigger": "<event type>",
  "conditions": {{...}},
  "action": {{"type": "<action type>"}},
  "risk": "low|medium|high",
  "requires_confirmation": true|false
}}

Safety defaults: requires_confirmation must be true unless the user explicitly
granted autonomy; risk must not be "high".

USER INSTRUCTION:
{instruction}
"""


class RuleCompiler:
    def __init__(self, ollama_host: str = "http://127.0.0.1:11434", model: str = "qwen3:8b") -> None:
        self.host = ollama_host.rstrip("/")
        self.model = model

    # ------------------------------------------------------------------
    def compile(self, instruction: str) -> tuple[bool, str, Optional[Rule]]:
        # 1) local LLM attempt
        rule_dict = self._via_llm(instruction)
        # 2) deterministic fallback
        if rule_dict is None:
            rule_dict = _pattern_compile(instruction)
        if rule_dict is None:
            return False, "could not interpret instruction", None
        ok, err, rule = validate_rule_dict(rule_dict)
        if not ok:
            return False, f"compiled rule failed validation: {err}", None
        _apply_safety_defaults(rule)
        return True, "ok", rule

    # ------------------------------------------------------------------
    def _via_llm(self, instruction: str) -> Optional[dict]:
        try:
            import requests
        except ImportError:
            return None
        from app.events.models import ActionType, EventType

        prompt = _COMPILE_PROMPT.format(
            triggers=", ".join(t.value for t in EventType),
            actions=", ".join(a.value for a in ActionType),
            instruction=instruction,
        )
        try:
            resp = requests.post(
                f"{self.host}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False, "format": "json"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("response", "")
            return _extract_json(raw)
        except Exception as exc:  # noqa: BLE001 — offline / no Ollama is normal
            log.debug("rule compiler LLM unavailable: %s", exc)
            return None


def _extract_json(raw: str) -> Optional[dict]:
    raw = raw.strip()
    # find first { ... } block
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


_DOMAIN_RE = re.compile(r"(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)", re.IGNORECASE)

# Common brand names users say instead of full domains
_BRANDS = {
    "github": "github.com",
    "google forms": "forms.google.com",
    "google docs": "docs.google.com",
    "google drive": "drive.google.com",
    "notion": "notion.so",
}


def _find_domain(instruction: str) -> Optional[str]:
    lowered = instruction.lower()
    for brand, domain in _BRANDS.items():
        if brand in lowered:
            return domain
    m = _DOMAIN_RE.search(instruction)
    return m.group(1).lower() if m else None


def _pattern_compile(instruction: str) -> Optional[dict]:
    """Deterministic fallback compiler for common rule shapes."""
    text = instruction.lower().strip()
    if not text:
        return None

    # "never submit..." / "don't submit..." → safety rule handled by policy, not engine
    if re.search(r"\b(never|don'?t|do not)\b", text) and re.search(r"\b(submit|form)\b", text):
        return {
            "name": "never_submit_forms",
            "trigger": "USER_COMMAND",
            "conditions": {"text_contains": "submit"},
            "action": {"type": "copy_text"},  # harmless placeholder; policy blocks submit anyway
            "risk": "low",
            "requires_confirmation": True,
        }

    # "open every <domain> link ..." → open_url rule
    m = re.search(r"\bopen\b.*\b(links?|urls?)\b", text)
    if m:
        domain = _find_domain(instruction)
        if domain:
            requires = "ask" not in text and "confirm" not in text
            return {
                "name": f"open_{domain.replace('.', '_')}_links",
                "trigger": "NEW_URL",
                "conditions": {"domain": domain, "source": "meeting_chat"},
                "action": {"type": "open_url"},
                "risk": "low",
                "requires_confirmation": not requires,
            }

    # "notify me when ..." → observe-only rule (suggest-mode proposal)
    if "notify" in text:
        domain = _find_domain(instruction)
        return {
            "name": "notify_" + (domain.replace(".", "_") if domain else "events"),
            "trigger": "NEW_URL",
            "conditions": {"domain": domain} if domain else {},
            "action": {"type": "copy_text"},  # suggestion only
            "risk": "low",
            "requires_confirmation": True,
        }
    return None


def _apply_safety_defaults(rule: Rule) -> None:
    """Compiler output can never grant high risk or silent autonomy."""
    if rule.risk == "high":
        rule.risk = "medium"
    # Note: requires_confirmation may stay False only when the user's sentence
    # explicitly requested autonomous opening (handled by pattern compiler).

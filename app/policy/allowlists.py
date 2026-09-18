"""Domain and application allowlists (spec §18/§19)."""
from __future__ import annotations

import shutil
import subprocess
from typing import Dict, List, Optional
from urllib.parse import urlparse


class DomainAllowlist:
    def __init__(
        self,
        allowed: List[str],
        blocked: Optional[List[str]] = None,
        require_confirmation_unknown: bool = True,
    ) -> None:
        self.allowed = {d.lower().lstrip(".") for d in allowed}
        self.blocked = {d.lower().lstrip(".") for d in (blocked or [])}
        self.require_confirmation_unknown = require_confirmation_unknown

    def check(self, url: str) -> "tuple[str, str]":
        """Return (status, detail): allowed | blocked | unknown."""
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return "unknown", f"no hostname in URL: {url!r}"
        if self._matches(self.blocked, host):
            return "blocked", f"domain {host} is blocklisted"
        if self._matches(self.allowed, host):
            return "allowed", f"domain {host} is allowlisted"
        return "unknown", f"domain {host} is not allowlisted"

    @staticmethod
    def _matches(domains: set, host: str) -> bool:
        return host in domains or any(host.endswith("." + d) for d in domains)


class ApplicationAllowlist:
    """Maps logical app names to known executables (spec §19/§53)."""

    def __init__(self, apps: Dict[str, Dict[str, List[str]]]) -> None:
        self.apps = {k.lower(): v for k, v in (apps or {}).items()}

    def is_allowed(self, logical_name: str) -> bool:
        return logical_name.lower() in self.apps

    def resolve(self, logical_name: str) -> Optional[str]:
        entry = self.apps.get(logical_name.lower())
        if not entry:
            return None
        for path in entry.get("paths", []):
            resolved = shutil.which(path)
            if resolved:
                return resolved
            # windows: try System32 / common locations for bare exe names
            if path.lower().endswith(".exe"):
                candidate = f"C:/Windows/System32/{path}"
                try:
                    if path.lower() in ("calc.exe", "notepad.exe", "explorer.exe"):
                        return path  # launch via shell, resolved by Windows
                except Exception:  # noqa: BLE001
                    pass
        # browser with empty paths = system default
        if entry.get("paths") == []:
            return None  # None means "system default", handled by browser module
        return None

    def launch(self, logical_name: str) -> bool:
        entry = self.apps.get(logical_name.lower())
        if not entry:
            return False
        paths = entry.get("paths", [])
        if not paths:  # system default (e.g., browser)
            return True
        for path in paths:
            resolved = shutil.which(path)
            try:
                if resolved:
                    subprocess.Popen([resolved])
                    return True
                if path.lower().endswith(".exe"):
                    subprocess.Popen([path])
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

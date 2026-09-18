"""Application launching (spec §19/§53).

Only logical names from the application allowlist can be launched. The VLM
can never pass an arbitrary executable path.
"""
from __future__ import annotations

import logging

from app.policy.allowlists import ApplicationAllowlist

log = logging.getLogger(__name__)


class ApplicationController:
    def __init__(self, allowlist: ApplicationAllowlist, dry_run: bool = False) -> None:
        self.allowlist = allowlist
        self.dry_run = dry_run

    def open(self, logical_name: str) -> bool:
        if not self.allowlist.is_allowed(logical_name):
            log.warning("refusing to launch non-allowlisted app %r", logical_name)
            return False
        if self.dry_run:
            log.info("[dry-run] launch app %s", logical_name)
            return True
        return self.allowlist.launch(logical_name)

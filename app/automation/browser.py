"""Browser automation (spec §5.4/§18).

V1: open URLs with the system default browser (deterministic, no browser
driver required). Playwright adapter included for deterministic in-browser
verification later.
"""
from __future__ import annotations

import logging
import webbrowser

log = logging.getLogger(__name__)


class BrowserController:
    def __init__(self, mode: str = "default", dry_run: bool = False) -> None:
        self.mode = mode
        self.dry_run = dry_run

    def open_url(self, url: str) -> bool:
        from urllib.parse import urlparse

        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            log.warning("refusing to open non-http URL %r", url)
            return False
        if self.dry_run:
            log.info("[dry-run] open URL %s", url)
            return True
        try:
            webbrowser.open(url)
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("open_url failed: %s", exc)
            return False

    # -- Playwright path (optional) -------------------------------------
    def open_url_playwright(self, url: str) -> bool:
        if self.dry_run:
            log.info("[dry-run] playwright open %s", url)
            return True
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                page = browser.new_page()
                page.goto(url, timeout=30000)
                # leave browser open for the user; do not close
                return True
        except Exception as exc:  # noqa: BLE001
            log.error("playwright open failed: %s", exc)
            return False

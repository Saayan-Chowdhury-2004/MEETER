"""Logging setup: console + rotating file for event metadata only (spec §41)."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(level: str = "INFO", file: str = "data/agent.log") -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(console)

    if file:
        Path(file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            file, maxBytes=5_000_000, backupCount=2, encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(fh)

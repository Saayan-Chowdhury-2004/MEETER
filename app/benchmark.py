"""Benchmark harness (spec §35): python -m app.benchmark

Measures capture FPS, CPU/RAM, OCR latency, end-to-end event→decision latency,
and pipeline behavior on synthetic frames. Produces a text report.
"""
from __future__ import annotations

import statistics
import time
from typing import Callable, List

import numpy as np


def _cpu_percent() -> float:
    try:
        import psutil

        return psutil.cpu_percent(interval=None)
    except ImportError:
        return 0.0


def _ram_gb() -> float:
    try:
        import psutil

        return psutil.Process().memory_info().rss / 1e9
    except ImportError:
        return 0.0


def bench_capture(provider, seconds: float = 3.0) -> float:
    n = 0
    t0 = time.time()
    while time.time() - t0 < seconds:
        provider.capture()
        n += 1
    return n / (time.time() - t0)


def bench_ocr(ocr, frames: List[np.ndarray]) -> float:
    latencies: List[float] = []
    for img in frames:
        t0 = time.time()
        ocr.extract(img)
        latencies.append(time.time() - t0)
    return statistics.mean(latencies) * 1000 if latencies else 0.0


def bench_change_detection(detector, frames: List[np.ndarray], region) -> float:
    latencies = []
    for img in frames:
        t0 = time.time()
        detector.evaluate_frame(img, [("full", region)])
        latencies.append(time.time() - t0)
    return statistics.mean(latencies) * 1000


def bench_end_to_end(agent, events) -> float:
    latencies = []
    for ev in events:
        t0 = time.time()
        agent.handle_event(ev, None)
        latencies.append((time.time() - t0) * 1000)
    return statistics.mean(latencies) if latencies else 0.0


# note: report text is ASCII-only so Windows cp1252 consoles can print it


def run_report() -> str:
    from app.capture.screen import get_capture_provider
    from app.perception.change_detector import ChangeDetector
    from app.perception.ocr import get_ocr_provider

    lines: List[str] = []
    add = lines.append

    add("Meeting Agent Benchmark")
    add("=" * 40)

    # capture fps (safe: falls back to mock when no display)
    try:
        cap = get_capture_provider("monitor", 1)
        fps = bench_capture(cap, 2.0)
        add(f"Capture FPS:                 {fps:.1f}")
    except Exception as exc:  # noqa: BLE001
        add(f"Capture FPS:                 n/a ({exc})")

    add(f"Average CPU:                 {_cpu_percent():.1f}%")
    add(f"Average RAM:                 {_ram_gb():.2f} GB")

    ocr = get_ocr_provider("auto")
    frame = np.full((720, 1280, 3), 40, dtype=np.uint8)
    frames = [frame.copy() for _ in range(3)]
    try:
        add(f"Average OCR latency:         {bench_ocr(ocr, frames):.1f} ms")
    except Exception as exc:  # noqa: BLE001
        add(f"Average OCR latency:         n/a ({exc})")

    det = ChangeDetector()
    region = (0, 0, 1280, 720)
    add(f"Change detection latency:    {bench_change_detection(det, frames, region):.2f} ms")

    # end-to-end event→decision using mock providers
    try:
        from app.agent import Agent
        from app.config import load_config
        from app.events.models import Event, EventType
        from app.storage.repository import Repository
        from app.storage.sqlite import Database
        import tempfile, os

        cfg = load_config()
        cfg.automation.enabled = False
        cfg.automation.dry_run = True
        tmp = tempfile.mkdtemp()
        db = Database(os.path.join(tmp, "bench.db"))
        agent = Agent(cfg, Repository(db))
        events = [
            Event(type=EventType.NEW_URL, source="meeting_chat", url="https://github.com/example/repo", text="repo: https://github.com/example/repo"),
            Event(type=EventType.NEW_MESSAGE, source="meeting_chat", text="hello"),
        ]
        add(f"Event-decision latency:      {bench_end_to_end(agent, events):.1f} ms")
    except Exception as exc:  # noqa: BLE001
        add(f"Event-decision latency:      n/a ({exc})")

    add("")
    add("Note: values are machine-dependent; benchmark on target hardware.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(run_report())

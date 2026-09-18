import time

from app.capture.ring_buffer import RingBuffer
from app.types import Frame


def _frame(ts):
    import numpy as np

    return Frame(image=np.zeros((4, 4, 3), dtype=np.uint8), timestamp=ts)


def test_frames_expire_after_max_seconds():
    rb = RingBuffer(max_seconds=1.0)
    now = time.time()
    rb.push(_frame(now - 5.0))  # old
    rb.push(_frame(now))       # fresh
    assert len(rb) == 1


def test_burst_window():
    rb = RingBuffer(max_seconds=60)
    now = time.time()
    rb.push(_frame(now - 10))
    rb.push(_frame(now - 1))
    burst = rb.burst(seconds=5)
    assert len(burst) == 1

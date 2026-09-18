"""Local speech-to-text (spec §27/§11 Phase 11).

Optional faster-whisper backend. When unavailable, `listen()` returns None and
the agent continues text-only. All inference is local; no cloud STT.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

log = logging.getLogger(__name__)


class SpeechToText:
    def __init__(self, model_size: str = "base.en", device: str = "cpu") -> None:
        self.model_size = model_size
        self.device = device
        self._model = None

    def _load(self) -> bool:
        if self._model is not None:
            return True
        try:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_size, device=self.device, compute_type="int8")
            return True
        except ImportError:
            log.info("faster-whisper not installed; speech layer disabled")
            return False
        except Exception as exc:  # noqa: BLE001
            log.warning("STT load failed: %s", exc)
            return False

    def transcribe_file(self, path: str) -> Optional[str]:
        if not self._load():
            return None
        try:
            segments, _ = self._model.transcribe(path)
            return " ".join(s.text.strip() for s in segments).strip()
        except Exception as exc:  # noqa: BLE001
            log.warning("transcription failed: %s", exc)
            return None

    def listen_forever(self, on_text: Callable[[str], None], chunk_seconds: float = 4.0) -> None:
        """Blocking mic loop; call from a dedicated thread."""
        if not self._load():
            return
        try:
            import sounddevice as sd  # optional dependency
            import numpy as np

            samplerate = 16000
            log.info("STT listening (chunk=%.1fs)...", chunk_seconds)
            while True:
                audio = sd.rec(
                    int(chunk_seconds * samplerate), samplerate=samplerate, channels=1, dtype="float32"
                )
                sd.wait()
                segments, _ = self._model.transcribe(audio[:, 0], language="en")
                text = " ".join(s.text.strip() for s in segments).strip()
                if text:
                    on_text(text)
        except ImportError:
            log.info("sounddevice not installed; mic capture unavailable")
        except Exception as exc:  # noqa: BLE001
            log.warning("STT loop stopped: %s", exc)

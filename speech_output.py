import subprocess
import threading
import logging

log = logging.getLogger(__name__)


class SpeechOutput:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def is_speaking(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def speak(self, text: str):
        self.stop()
        log.info("speaking: %s", text[:80])
        with self._lock:
            self._proc = subprocess.Popen(["say", text])

    def stop(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
            self._proc = None

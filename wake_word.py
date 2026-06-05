import os
import threading
import logging
import numpy as np
import sounddevice as sd
import speech_recognition as sr
from collections import deque
from pathlib import Path
from dotenv import load_dotenv

log = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent / ".env")

_raw = os.environ.get("WAKE_PHRASES", "computer,hey computer,okay computer")
WAKE_PHRASES = [p.strip().lower() for p in _raw.split(",") if p.strip()]
SAMPLE_RATE = 16000
WINDOW_SECONDS = 3    # how much audio to recognize at once
STEP_SECONDS = 1      # slide forward by this much each time


class WakeWordDetector:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._callback = None

    def start(self, on_wake):
        self._callback = on_wake
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        log.info("wake word detector started")

    def stop(self):
        self._stop_event.set()
        log.info("wake word detector stopped")

    def _listen_loop(self):
        recognizer = sr.Recognizer()
        step_samples = int(STEP_SECONDS * SAMPLE_RATE)
        window_samples = int(WINDOW_SECONDS * SAMPLE_RATE)

        # Circular buffer holds WINDOW_SECONDS of audio
        buffer: deque[np.ndarray] = deque()
        buffer_len = 0

        def audio_callback(indata, frames, time, status):
            buffer.append(indata[:, 0].copy())
            nonlocal buffer_len
            buffer_len += len(indata)

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                            blocksize=step_samples, callback=audio_callback):
            log.info("wake word stream open")
            while not self._stop_event.is_set():
                # Wait until we have a full window
                if buffer_len < window_samples:
                    self._stop_event.wait(timeout=STEP_SECONDS)
                    continue

                # Drain oldest step from buffer, keep rest
                chunk = np.concatenate(list(buffer))
                # Trim to window size
                window = chunk[-window_samples:]

                # Convert to bytes for SpeechRecognition
                raw = (window.astype(np.int16)).tobytes()
                audio_data = sr.AudioData(raw, SAMPLE_RATE, 2)

                try:
                    text = recognizer.recognize_google(audio_data).lower()
                    log.info("heard: %s", text)
                    words = text.split()
                    tail = " ".join(words[-5:])
                    for phrase in WAKE_PHRASES:
                        if phrase in tail:
                            log.info("WAKE triggered: %s", tail)
                            self._stop_event.set()
                            if self._callback:
                                self._callback()
                            return
                except sr.UnknownValueError:
                    pass
                except sr.RequestError as e:
                    log.warning("recognition error: %s", e)

                # Slide: drop oldest step worth of samples
                to_drop = step_samples
                while buffer and to_drop > 0:
                    chunk = buffer[0]
                    if len(chunk) <= to_drop:
                        to_drop -= len(chunk)
                        buffer_len -= len(chunk)
                        buffer.popleft()
                    else:
                        buffer[0] = chunk[to_drop:]
                        buffer_len -= to_drop
                        to_drop = 0

                self._stop_event.wait(timeout=STEP_SECONDS)

import threading
import logging
import numpy as np
import sounddevice as sd
from openwakeword.model import Model

log = logging.getLogger(__name__)

WAKE_MODEL = "hey_jarvis"
WAKE_MODEL_PATH: str | None = None  # set to a local .onnx/.tflite path to override WAKE_MODEL
DETECTION_THRESHOLD = 0.5
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1280  # 80 ms at 16 kHz, as expected by openWakeWord


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
        log.info("wake word detector started (model=%s)", WAKE_MODEL_PATH or WAKE_MODEL)

    def stop(self):
        self._stop_event.set()
        log.info("wake word detector stopped")

    def _listen_loop(self):
        models = [WAKE_MODEL_PATH] if WAKE_MODEL_PATH else [WAKE_MODEL]
        oww = Model(wakeword_models=models, inference_framework="onnx")

        audio_queue: list[np.ndarray] = []

        def audio_callback(indata, frames, time, status):
            audio_queue.append(indata[:, 0].copy())

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=CHUNK_SAMPLES,
            callback=audio_callback,
        ):
            log.info("wake word stream open")
            while not self._stop_event.is_set():
                if not audio_queue:
                    self._stop_event.wait(timeout=0.01)
                    continue

                scores = oww.predict(audio_queue.pop(0))

                for model_name, score in scores.items():
                    if score >= DETECTION_THRESHOLD:
                        log.info("WAKE triggered: model=%s score=%.3f", model_name, score)
                        self._stop_event.set()
                        if self._callback:
                            self._callback()
                        return

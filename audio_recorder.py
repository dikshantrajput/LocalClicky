import sounddevice as sd
import soundfile as sf
import numpy as np
import tempfile
import os
import threading
import logging

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1

VAD_FRAME_MS = 30
VAD_FRAME_SAMPLES = int(SAMPLE_RATE * VAD_FRAME_MS / 1000)  # 480 samples

SILENCE_TIMEOUT_S = 1.5   
MAX_DURATION_S = 30.0     
MIN_SPEECH_S = 0.8        

try:
    import webrtcvad as _webrtcvad
    _vad_available = True
except ImportError:
    try:
        import webrtcvad_wheels as _webrtcvad  # type: ignore[no-redef]
        _vad_available = True
    except ImportError:
        _webrtcvad = None  # type: ignore[assignment]
        _vad_available = False
        log.warning("webrtcvad not installed — run: pip install webrtcvad-wheels")


class AudioRecorder:
    def __init__(self, on_silence=None):
        """
        on_silence: optional callable invoked when silence timeout fires,
                    so the caller can trigger stop_recording().
        """
        self._frames: list[np.ndarray] = []
        self._recording = False
        self._lock = threading.Lock()
        self._path: str | None = None
        self._on_silence = on_silence

        self._vad = _webrtcvad.Vad(3) if _vad_available and _webrtcvad is not None else None  # 3 = most aggressive noise filtering
        self._vad_buffer = np.zeros(0, dtype="int16")
        self._silence_timer: threading.Timer | None = None
        self._max_timer: threading.Timer | None = None
        self._speech_started = False
        self._speech_duration = 0.0

    def start(self):
        self._frames = []
        self._vad_buffer = np.zeros(0, dtype="int16")
        self._recording = True
        self._speech_started = False
        self._speech_duration = 0.0
        self._path = os.path.join(tempfile.gettempdir(), "localclicky_audio.wav")

        # Retry up to 5 times — another app (e.g. OBS) may have briefly locked the mic
        last_err = None
        for attempt in range(5):
            try:
                self._stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    callback=self._callback,
                    blocksize=VAD_FRAME_SAMPLES,
                )
                self._stream.start()
                last_err = None
                break
            except Exception as e:
                last_err = e
                log.warning("mic open failed (attempt %d/5): %s", attempt + 1, e)
                import time as _t
                _t.sleep(1.0)

        if last_err:
            self._recording = False
            raise RuntimeError(
                f"Could not open microphone after 5 attempts: {last_err}\n"
                "Another app (OBS, Zoom, etc.) may be holding exclusive mic access."
            )

        # Hard cap timer
        self._max_timer = threading.Timer(MAX_DURATION_S, self._on_max_duration)
        self._max_timer.daemon = True
        self._max_timer.start()

        log.info("recording started (VAD=%s)", "on" if self._vad else "off")

    def _callback(self, indata, frames, time, status):
        if not self._recording:
            return

        chunk = indata[:, 0].copy()

        with self._lock:
            self._frames.append(indata.copy())

        if self._vad is None:
            return

        self._vad_buffer = np.concatenate([self._vad_buffer, chunk])
        while len(self._vad_buffer) >= VAD_FRAME_SAMPLES:
            frame = self._vad_buffer[:VAD_FRAME_SAMPLES]
            self._vad_buffer = self._vad_buffer[VAD_FRAME_SAMPLES:]
            self._process_vad_frame(frame)

    def _process_vad_frame(self, frame: np.ndarray):
        assert self._vad is not None
        frame_bytes = frame.tobytes()
        try:
            is_speech = self._vad.is_speech(frame_bytes, SAMPLE_RATE)
        except Exception:
            return

        if is_speech:
            self._speech_duration += VAD_FRAME_MS / 1000.0
            if self._speech_duration >= MIN_SPEECH_S:
                self._speech_started = True
            # Cancel pending silence timer
            if self._silence_timer is not None:
                self._silence_timer.cancel()
                self._silence_timer = None
        else:
            if self._speech_started and self._silence_timer is None:
                self._silence_timer = threading.Timer(SILENCE_TIMEOUT_S, self._on_silence_timeout)
                self._silence_timer.daemon = True
                self._silence_timer.start()

    def _on_silence_timeout(self):
        if self._recording:
            log.info("silence detected — stopping recording")
            if self._on_silence:
                self._on_silence()

    def _on_max_duration(self):
        if self._recording:
            log.info("max duration reached — stopping recording")
            if self._on_silence:
                self._on_silence()

    def stop(self) -> str | None:
        self._recording = False

        if self._silence_timer:
            self._silence_timer.cancel()
            self._silence_timer = None
        if self._max_timer:
            self._max_timer.cancel()
            self._max_timer = None

        self._stream.stop()
        self._stream.close()

        with self._lock:
            frames = self._frames[:]

        if not frames:
            log.warning("no audio captured")
            return None

        assert self._path is not None
        audio = np.concatenate(frames, axis=0)
        sf.write(self._path, audio, SAMPLE_RATE)
        size = os.path.getsize(self._path)
        log.info("recording stopped: %d bytes", size)
        return self._path

import threading
import time
import logging
import re

import ollama_client
import screen_capture
import whisper_transcriber
import cursor_control
from audio_recorder import AudioRecorder
from speech_output import SpeechOutput
from wake_word import WakeWordDetector

log = logging.getLogger(__name__)

_DISMISSAL_PATTERNS = re.compile(
    r'\b(bye|goodbye|good bye|see you|stop listening|go to sleep|dismiss|that\'s all|thanks? bye)\b',
    re.IGNORECASE
)

SESSION_IDLE_TIMEOUT = 25.0


class AppState:
    IDLE = "idle"
    LISTENING = "listening"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"


class CompanionManager:
    def __init__(self, on_state_change=None, on_token=None):
        self.state = AppState.IDLE
        self.transcript = ""
        self.response = ""
        self.history: list[dict] = []
        self.conversation: list[tuple[str, str]] = []

        self._on_state_change = on_state_change or (lambda s: None)
        self._on_token = on_token or (lambda t: None)

        self._recorder = AudioRecorder(on_silence=self._on_recording_silence)
        self._speech = SpeechOutput()
        self._wake = WakeWordDetector()

        self._in_session = False
        self._session_timer: threading.Timer | None = None

    def _set_state(self, state: str):
        self.state = state
        self._on_state_change(state)
        log.info("state → %s", state)

    def start_listening(self):
        self._in_session = False
        self._cancel_session_timer()
        self._set_state(AppState.LISTENING)
        self._wake.start(on_wake=self._on_wake)

    def _on_wake(self):
        log.info("wake word triggered — starting session")
        self._wake.stop()
        self._in_session = True
        threading.Thread(target=self._start_recording_after_wake, daemon=True).start()

    def _start_recording_after_wake(self):
        if self._wake._thread and self._wake._thread.is_alive():
            self._wake._thread.join(timeout=2.0)
        self.start_recording()

    def _arm_session_timer(self):
        """If user doesn't speak within SESSION_IDLE_TIMEOUT seconds, end the session."""
        self._cancel_session_timer()
        self._session_timer = threading.Timer(SESSION_IDLE_TIMEOUT, self._session_expired)
        self._session_timer.daemon = True
        self._session_timer.start()

    def _cancel_session_timer(self):
        if self._session_timer:
            self._session_timer.cancel()
            self._session_timer = None

    def _session_expired(self):
        if self._in_session and self.state not in (AppState.RECORDING, AppState.TRANSCRIBING, AppState.THINKING, AppState.SPEAKING):
            log.info("session idle timeout — returning to wake word")
            self._end_session()

    def _end_session(self):
        log.info("session ended")
        self._in_session = False
        self._cancel_session_timer()
        self._recorder.stop() if self.state == AppState.RECORDING else None
        self.start_listening()


    def start_recording(self):
        if self.state == AppState.RECORDING:
            return
        self._cancel_session_timer()
        self._speech.stop()
        self.transcript = ""
        self.response = ""
        self._set_state(AppState.RECORDING)
        try:
            self._recorder.start()
        except RuntimeError as e:
            log.error("microphone unavailable: %s", e)
            self._set_state(AppState.ERROR)
            if self._in_session:
                self._end_session()
            return

    def _on_recording_silence(self):
        if self.state == AppState.RECORDING:
            self.stop_recording()

    def stop_recording(self):
        if self.state != AppState.RECORDING:
            return
        audio_path = self._recorder.stop()
        if not audio_path:
            self._set_state(AppState.ERROR)
            return

        import os
        size = os.path.getsize(audio_path)
        if size < 44 + 25600:
            log.info("audio too short (%d bytes) — skipping", size)
            if self._in_session:
                self._set_state(AppState.IDLE)
                self._arm_session_timer()
                threading.Thread(target=self._wait_then_record, daemon=True).start()
            else:
                self.start_listening()
            return

        threading.Thread(target=self._process, args=(audio_path,), daemon=True).start()

    def _process(self, audio_path: str):
        # Transcribe
        self._set_state(AppState.TRANSCRIBING)
        try:
            text = whisper_transcriber.transcribe(audio_path)
        except Exception as e:
            log.error("transcription failed: %s", e)
            self._set_state(AppState.ERROR)
            return

        if not text:
            log.warning("no speech detected")
            if self._in_session:
                self._set_state(AppState.IDLE)
                self._arm_session_timer()
                threading.Thread(target=self._wait_then_record, daemon=True).start()
            else:
                self.start_listening()
            return

        self.transcript = text
        log.info("transcript: %s", text)

        if _DISMISSAL_PATTERNS.search(text):
            log.info("dismissal detected — ending session")
            self._speech.speak("Goodbye!")
            while self._speech.is_speaking:
                time.sleep(0.1)
            self._end_session()
            return

        # Screenshot
        self._set_state(AppState.THINKING)
        capture_result = screen_capture.capture()
        if capture_result:
            image, image_size, physical_size = capture_result
        else:
            image, image_size, physical_size = None, None, None
            log.warning("screenshot FAILED — vision model will NOT be used")

        # Ollama
        self.response = ""
        try:
            response = ollama_client.chat(
                history=self.history,
                user_text=text,
                base64_image=image,
                on_token=self._handle_token,
                image_size=image_size
            )
        except Exception as e:
            err = str(e)
            log.error("ollama error: %s", err)
            if "400" in err:
                log.error("400 Bad Request — model '%s' may not support vision or is not pulled.", ollama_client.VISION_MODEL)
            self._set_state(AppState.ERROR)
            return

        raw = response if response else "Done."

        # Extract cursor action — check final response first, then look_at_screen's stored tag
        spoken, action_tag = cursor_control.extract_action(raw)
        if not action_tag and ollama_client._last_cursor_action:
            action_tag = ollama_client._last_cursor_action
            spoken = raw
        if action_tag:
            log.info("cursor action: %s", action_tag)
            eff_image_size = image_size or ollama_client._last_image_size
            eff_physical_size = physical_size or ollama_client._last_physical_size
            if eff_image_size and eff_physical_size:
                cursor_control.execute(action_tag, eff_image_size, eff_physical_size)
            else:
                log.warning("cursor action ignored — no screenshot size available")
        spoken = spoken if spoken else "Done."
        self.response = spoken

        # Update history
        self.history.append({"role": "user", "content": text})
        self.history.append({"role": "assistant", "content": spoken})
        if len(self.history) > 20:
            self.history = self.history[-20:]
        self.conversation.append((text, spoken))

        # Speak
        self._set_state(AppState.SPEAKING)
        self._speech.speak(spoken)
        while self._speech.is_speaking:
            time.sleep(0.2)

        self._set_state(AppState.IDLE)

        if self._in_session:
            # Stay in session — wait a beat then start recording for the next command
            threading.Thread(target=self._wait_then_record, daemon=True).start()
        else:
            self.start_listening()

    def _wait_then_record(self):
        """Brief pause after speaking, then start recording for the next command in-session."""
        time.sleep(0.4)
        if self._in_session and self.state == AppState.IDLE:
            log.info("session active — ready for next command")
            self.start_recording()
            # Arm idle timer in case user doesn't say anything
            self._arm_session_timer()

    def _handle_token(self, token: str):
        self.response += token
        self._on_token(token)

    def clear_history(self):
        self.history = []
        self.conversation = []

    def push_to_talk_start(self):
        if self.state in (AppState.IDLE, AppState.LISTENING):
            self._wake.stop()
            self._in_session = True
            self.start_recording()

    def push_to_talk_stop(self):
        if self.state == AppState.RECORDING:
            self.stop_recording()

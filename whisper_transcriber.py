import subprocess
import os
import logging

log = logging.getLogger(__name__)

WHISPER_CANDIDATES = [
    "/opt/homebrew/bin/whisper-cli",
    "/usr/local/bin/whisper-cli",
    "/opt/homebrew/bin/whisper-cpp",
    "/usr/local/bin/whisper-cpp",
]

MODEL_CANDIDATES = [
    "/opt/homebrew/share/whisper-cpp/models/ggml-base.en.bin",
    "/opt/homebrew/share/whisper-cpp/models/ggml-base.bin",
    os.path.expanduser("~/.whisper/models/ggml-base.en.bin"),
    os.path.expanduser("~/.cache/whisper/ggml-base.en.bin"),
]


def _find(candidates: list[str]) -> str:
    return next((p for p in candidates if os.path.exists(p)), candidates[0])


WHISPER_PATH = _find(WHISPER_CANDIDATES)
MODEL_PATH = _find(MODEL_CANDIDATES)


def transcribe(audio_path: str) -> str:
    log.info("whisper binary: %s", WHISPER_PATH)
    log.info("model: %s", MODEL_PATH)
    log.info("audio: %s (%d bytes)", audio_path, os.path.getsize(audio_path))

    result = subprocess.run(
        [WHISPER_PATH, "--model", MODEL_PATH, "--no-timestamps", "--language", "en", audio_path],
        capture_output=True, text=True
    )

    log.info("whisper exit: %d", result.returncode)
    if result.returncode != 0:
        raise RuntimeError(f"Whisper failed (exit {result.returncode}): {result.stderr[-300:]}")

    text = result.stdout.strip()
    # Whisper outputs these tokens when no real speech is detected
    if text in ("[BLANK_AUDIO]", "(inaudible)", "[noise]", "") or text.startswith("["):
        return ""
    return text

# LocalClicky

**Control your Mac with your voice. Completely offline.**

Your voice, your screen, your commands — nothing leaves your machine. No cloud APIs. No API keys. No subscriptions.

![macOS](https://img.shields.io/badge/macOS-12%2B-black?style=flat-square) ![Python](https://img.shields.io/badge/Python-3.11%2B-blue?style=flat-square) ![Ollama](https://img.shields.io/badge/AI-Ollama-orange?style=flat-square) ![License](https://img.shields.io/badge/license-MIT-green?style=flat-square) ![Offline](https://img.shields.io/badge/cloud-none-red?style=flat-square)

---

## Why LocalClicky

Every cloud voice assistant makes the same tradeoff: you get convenience, they get your data. Your audio gets uploaded. Your screen gets sent to a server. Your commands get logged.

LocalClicky breaks that tradeoff. Everything runs on your hardware:

- **[Whisper.cpp](https://github.com/ggerganov/whisper.cpp)** — transcription, runs locally
- **[Ollama](https://ollama.com)** (qwen3, gemma4) — AI reasoning and vision, runs locally
- **macOS say** — text-to-speech, built into your Mac
- **PyAutoGUI** — cursor and click control

No data leaves your machine. Not your voice. Not your screenshots. Not your commands.

---

## What it can do

- Sits in the menubar — no Dock icon, stays out of the way
- Say **"Hey Jarvis"** → starts a session — stays active until you say goodbye
- **Voice Activity Detection** — auto-stops recording when you stop talking (no fixed timeout)
- **Sees your screen on demand** — vision model (gemma4:e4b) takes a screenshot when needed
- **Moves your cursor and clicks** based on what it sees on screen
- **Controls your Mac**: open/quit apps, adjust volume, control Spotify, manage files, run shell commands, inject JS into Chrome
- **Creates reminders** with natural language dates
- Multi-round tool calling — runs commands, checks results, confirms or retries
- Conversation memory across the session (last 10 exchanges)
- **Session mode** — chain commands back-to-back without repeating the wake word

---

## Menubar icons

| Icon | State |
|------|-------|
| 🎙️ | Idle / ready |
| 👂 | Listening for "Computer" |
| 🔴 | Recording your voice |
| 🔄 | Transcribing |
| 🤔 | Thinking (Ollama) |
| 🔊 | Speaking response |
| ⚠️ | Error |

---

## Prerequisites

### 1. Whisper (transcription)

```bash
brew install whisper-cpp

# Download the base English model
mkdir -p /opt/homebrew/share/whisper-cpp/models
curl -L -o /opt/homebrew/share/whisper-cpp/models/ggml-base.en.bin \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
```

### 2. Ollama (local AI)

```bash
brew install ollama

# Start Ollama
ollama serve

# Pull the models
ollama pull qwen3:8b     # command model — tool calling, Mac control
ollama pull gemma4:e4b   # vision model — sees your screen when needed
```

### 3. Python dependencies

```bash
cd PyClicky
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -c "import openwakeword; openwakeword.utils.download_models()"
```

### 4. Silence detection (optional but recommended)

```bash
pip install webrtcvad-wheels
```

Without this, recording falls back to a 30-second hard cap instead of stopping when you stop talking.

---

## Run

```bash
cd PyClicky
source venv/bin/activate
ollama serve &   # if not already running
python main.py
```

The app appears in your menubar. No Dock icon.

---

## Permissions (grant once)

LocalClicky needs three macOS permissions for the `python3` binary inside your venv:
`/path/to/PyClicky/venv/bin/python3`

| Permission | Why | Where to grant |
|---|---|---|
| **Microphone** | Voice recording | Prompted automatically on first run |
| **Screen Recording** | Screenshot for vision | System Settings → Privacy & Security → Screen Recording |
| **Accessibility** | Cursor movement & clicks | System Settings → Privacy & Security → Accessibility |

> **Tip:** If `python3` is not selectable in the file picker, add **Terminal** instead — Python inherits Terminal's permissions when launched from it.

---

## How to use

### Starting a session

Say **"Hey Jarvis"** — the icon turns 🔴 and recording starts. When you stop talking, it automatically processes your command and responds.

After responding, it stays active and listens for your next command immediately — **no need to say "Computer" again**.

### Ending a session

Say **"bye"**, **"goodbye"**, **"stop listening"**, **"go to sleep"**, or **"that's all"** — the assistant says goodbye and returns to wake word mode.

The session also auto-expires after **25 seconds of silence**.

### Example commands

| You say | What happens |
|---|---|
| "Open Spotify and play hip hop" | Opens Spotify, searches and plays |
| "Set Spotify volume to 30 percent" | AppleScript sets Spotify's internal volume |
| "Set volume to 50 percent" | Sets macOS system volume |
| "Click the notification bell" | Takes screenshot, finds the bell, clicks it |
| "What's on my screen?" | Takes screenshot, describes what it sees |
| "Create a reminder to call John tomorrow at 9am" | Creates reminder in macOS Reminders |
| "Open a new tab in Chrome" | AppleScript opens a new Chrome tab |
| "Play next track" | AppleScript skips to next Spotify track |
| "Make a folder called Projects on my Desktop" | `mkdir ~/Desktop/Projects` |
| "What is the capital of France?" | Answers directly, no tools needed |

### How screen interaction works

When you ask to click or find something, the assistant calls `look_at_screen` — it takes a clean screenshot, sends it to the vision model (gemma4:e4b), and gets back a bounding box for the target element. The center of that box is computed and clicked automatically.

The model decides on its own when it needs to see the screen — you don't have to phrase commands any special way.

---

## Architecture

```
Wake word ("Computer")
        ↓
AudioRecorder.start()           ← opens sounddevice InputStream
        ↓  (VAD auto-stop on silence, 30s hard cap)
AudioRecorder.stop()            → WAV file
        ↓
WhisperTranscriber.transcribe() → runs whisper-cli → transcript text
        ↓
Dismissal check ("bye" etc.)   → end session / OllamaClient.chat()
        ↓
OllamaClient.chat() — always qwen3:8b with think mode + tools:
  ├─ run_shell_command  → zsh → output
  ├─ query_system       → read-only zsh → output
  ├─ look_at_screen     → screencapture → gemma4:e4b → [CLICK:x1,y1,x2,y2]
  └─ create_reminder    → Python builds correct AppleScript → osascript
  (up to 5 tool rounds, streaming)
        ↓
CursorControl.extract_action()  → parse [CLICK/POINT/RCLICK:x1,y1,x2,y2]
CursorControl.execute()         → compute center → pyautogui moves/clicks
        ↓
SpeechOutput.speak()            → macOS `say` speaks the response
        ↓
Session active: wait 0.4s → start recording again
Session idle 25s: return to WakeWordDetector
```

---

## File structure

```
PyClicky/
├── main.py                # rumps menubar app — icons, menu, state display
├── companion.py           # state machine — session management, full pipeline
├── ollama_client.py       # qwen3 with tools, gemma4 vision via look_at_screen
├── wake_word.py           # offline wake word via openWakeWord (hey_jarvis pretrained model)
├── audio_recorder.py      # sounddevice mic capture + VAD silence detection → WAV
├── whisper_transcriber.py # calls whisper-cli subprocess, returns transcript
├── screen_capture.py      # screencapture → resize to 1280px → base64 JPEG
├── cursor_control.py      # parses [CLICK/POINT/RCLICK:x1,y1,x2,y2], clicks center
├── speech_output.py       # macOS `say` command wrapper
├── shell_executor.py      # zsh subprocess runner, cwd=~
└── requirements.txt
```

---

## Configuration

### Change models

Edit `ollama_client.py`:

```python
VISION_MODEL = "gemma4:e4b"   # called by look_at_screen tool for visual tasks
COMMAND_MODEL = "qwen3:8b"    # main model — tool calling, reasoning, Mac control
```

The command model must support reliable tool calling. The vision model must be multimodal.

| Vision | Command | Notes |
|---|---|---|
| `gemma4:e4b` | `qwen3:8b` | Default — good balance of speed and capability |
| `gemma4:e4b` | `qwen3:14b` | Better reasoning, needs ~16GB RAM |
| `gemma4:27b` | `qwen3:8b` | Better vision accuracy, needs ~32GB RAM |
| `qwen2.5vl:7b` | `qwen3:8b` | Alternative vision model |

### Change wake word / detection threshold

Edit `wake_word.py`:

```python
# Use a different pretrained model (e.g. "alexa", "hey_mycroft"):
WAKE_MODEL = "hey_jarvis"

# Point to a custom trained .onnx or .tflite file instead:
WAKE_MODEL_PATH = "/path/to/your/computer.onnx"  # overrides WAKE_MODEL when set

# Lower = more sensitive (more false positives), higher = stricter:
DETECTION_THRESHOLD = 0.5
```

To train a custom "computer" model, follow the
[openWakeWord training guide](https://github.com/dscripka/openWakeWord/blob/main/docs/training.md),
then set `WAKE_MODEL_PATH` to the output `.onnx` file.

### Change session idle timeout

Edit `companion.py`:

```python
SESSION_IDLE_TIMEOUT = 25.0   # seconds of silence before returning to wake word mode
```

### Change screenshot resolution

Edit `screen_capture.py`:

```python
MAX_WIDTH = 1280    # resize screenshot to this width before sending to vision model
JPEG_QUALITY = 75   # compression quality
```

Lower `MAX_WIDTH` = faster responses, slightly less visual detail. Higher = more detail, larger payload.

### Change Ollama server URL

Edit `ollama_client.py`:

```python
OLLAMA_URL = "http://localhost:11434/api/chat"
```

---

## Troubleshooting

**"No speech detected" every time**
- Check microphone permission
- Speak louder or closer to the mic
- Whisper model path may be wrong — check logs for the `model:` line

**Recording never stops / runs too long**
- Install webrtcvad: `pip install webrtcvad-wheels` for VAD silence detection
- Without it, recording stops after 30 seconds

**Screenshot always fails**
- Grant Screen Recording to Terminal in System Settings → Privacy & Security
- Test: `screencapture -x -t jpg /tmp/test.jpg && echo OK`

**Cursor doesn't move**
- Grant Accessibility to Terminal in System Settings → Privacy & Security → Accessibility

**Wake word never triggers**
- Wake word detection runs fully offline via openWakeWord — no internet needed
- Default keyword is **"hey Jarvis"** (not "Computer") — say that phrase to trigger
- To use a different keyword, change `WAKE_MODEL` in `wake_word.py` (see Configuration)
- Check logs for `WAKE triggered:` lines; lower `DETECTION_THRESHOLD` if it's not firing
- Speak clearly and at normal pace — very fast or whispered speech may score below threshold

**Mic error when OBS or Zoom is running**
- The app will retry 5 times automatically
- If it still fails, close the other app briefly then restart the session

**Model says "I can't see your screen"**
- Ensure Screen Recording permission is granted
- Try rephrasing: "look at my screen and click..."

**Ollama 400 error**
- Check `ollama list` — ensure both models are pulled
- Restart Ollama: `ollama serve`

**"Too many steps" response**
- The model hit the 5-round tool call limit
- Check shell_executor logs for the underlying command error

---

## Requirements

- macOS 12+
- Python 3.11+
- Homebrew
- ~8GB RAM free (for both models)
- Ollama running locally

---

## Dependency reference

| Package | Purpose |
|---|---|
| `rumps` | macOS menubar app framework |
| `sounddevice` | Mic input stream |
| `soundfile` | Write WAV files |
| `numpy` | Audio buffer manipulation |
| `httpx` | Streaming HTTP to Ollama |
| `openwakeword` | Offline wake word detection |
| `pyautogui` | Cursor movement and clicks |
| `Pillow` | Screenshot resize |
| `webrtcvad-wheels` | Voice activity detection (optional) |

---

## Contributing

LocalClicky is early. Meaningful areas to improve:

- **Custom "computer" wake word** — train a personal openWakeWord model using the [training guide](https://github.com/dscripka/openWakeWord/blob/main/docs/training.md) and swap `WAKE_MODEL_PATH` in `wake_word.py`
- **App-specific skills** — context-aware commands for Terminal, Xcode, Figma, VS Code
- **Packaging** — proper `.app` bundle so users don't need to run from terminal
- **Windows / Linux ports** — the core pipeline is cross-platform; the menubar layer isn't
- **Better click accuracy** — the vision model (gemma4) has limited spatial precision; a GUI-specific model would help significantly

If you want to work on any of these, open an issue first. PRs welcome.

---

## License

MIT

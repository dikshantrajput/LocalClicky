# Contributing to PyClicky

Thanks for your interest. PyClicky is in active early development — all contributions welcome.

## Ways to contribute

- **Bug reports** — open an issue with your terminal log output
- **Feature requests** — open an issue describing the use case
- **Code** — pick something from the list below or scratch your own itch
- **Testing** — try it on different Mac hardware / macOS versions and report results

## What needs help

- [ ] **Offline wake word** — replace Google Speech Recognition with Porcupine or a local Whisper-based detector so it works with no internet
- [ ] **Silence detection** — auto-stop recording when the user stops talking instead of fixed 8s timer
- [ ] **Safari support** — browser control currently Chrome-only (JS injection via osascript)
- [ ] **Floating conversation panel** — a proper window showing chat history (currently just a menu dropdown)
- [ ] **Settings UI** — let users change models, wake word, voice, timeout without editing code
- [ ] **Login item setup** — script or GUI to add PyClicky to Login Items
- [ ] **Better vision+tool model** — gemma4 tool calling is unreliable; need a multimodal model that also does reliable JSON tool use

## Getting started

```bash
git clone https://github.com/yourusername/pyclicky
cd pyclicky
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# install system deps
brew install whisper-cpp ollama
ollama pull gemma4:e4b
ollama pull qwen3:8b
ollama serve &

python main.py
```

## Pull request guidelines

- One feature or fix per PR — keep it focused
- Test on macOS before submitting
- Paste relevant log output in the PR description if fixing a bug
- Discuss new dependencies in an issue first — keep the install simple

## Bug reports

Include:
1. macOS version (`sw_vers`)
2. Python version (`python3 --version`)
3. Ollama version (`ollama --version`) and models pulled (`ollama list`)
4. Full terminal output from when the bug occurred
5. What you said / what you expected / what happened

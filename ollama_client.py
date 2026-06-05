import httpx
import json
import logging
import os
import re
from pathlib import Path
from dotenv import load_dotenv

log = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent / ".env")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
VISION_MODEL = os.environ.get("VISION_MODEL", "gemma4:e4b")
COMMAND_MODEL = os.environ.get("COMMAND_MODEL", "qwen3:8b")
MAX_TOOL_ROUNDS = 5

_SYSTEM_PROMPT = """You are a voice-controlled Mac assistant. The user speaks to you — your responses are read aloud, so be brief and natural.

TOOLS:
- run_shell_command — execute zsh to control the Mac (apps, files, settings, osascript)
- query_system — read-only shell to check state (use before acting if uncertain, or to confirm a result)
- look_at_screen — your eyes: takes a screenshot and sees/clicks what's on screen

WHEN TO USE EACH:
- App control, files, settings, Spotify, volume → run_shell_command
- Need to know current state before acting → query_system first
- User asks to click, point, find, or describe something on screen → look_at_screen (once — do not call it repeatedly)
- "How do I…" / "Can you help me…" / advice questions → answer from knowledge directly, no tools
- Pure conversation → reply directly, no tools

HARD RULES:
- You CAN click and move the mouse via look_at_screen — NEVER say you cannot
- NEVER pass cursor/click instructions to run_shell_command
- Always use absolute paths: ~/Desktop/file not ./file
- run_shell_command exit 0 with no output = SUCCESS — do NOT say it failed or call query_system just to confirm an obvious action (quit, open, move)
- Only call query_system when you genuinely need to verify a non-obvious result or check state
- If the user says "yes", "go ahead", "do it" — look at the conversation history to know what to do
- Response length: 1 sentence max. No preamble, no filler, no "I'll now...", just do it and confirm in one line."""


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_shell_command",
            "description": (
                "Execute a zsh command on the Mac. Use absolute paths always.\n"
                "Examples:\n"
                "- Open app: open -a 'Spotify'\n"
                "- Quit app: osascript -e 'tell application \"Spotify\" to quit'\n"
                "- Spotify volume (0-100): osascript -e 'tell application \"Spotify\" to set sound volume to 20'\n"
                "- System/Mac volume (0-100): osascript -e 'set volume output volume 50'\n"
                "- Spotify play/pause: osascript -e 'tell application \"Spotify\" to playpause'\n"
                "- Spotify next track: osascript -e 'tell application \"Spotify\" to next track'\n"
                "- Spotify play genre: osascript -e 'tell application \"Spotify\" to play track \"spotify:playlist:...\"'\n"
                "- New Chrome tab: osascript -e 'tell application \"Google Chrome\" to make new tab at end of tabs of window 1'\n"
                "- Chrome navigate: osascript -e 'tell application \"Google Chrome\" to set URL of active tab of window 1 to \"https://...\"'\n"
                "- Run JS in Chrome: osascript -e 'tell app \"Google Chrome\" to execute front window\\'s active tab javascript \"document.querySelector(\\\"button\\\").click()\"'\n"
                "- Create folder: mkdir -p ~/Desktop/foldername\n"
                "- Move files: mv ~/Desktop/file ~/Documents/\n"
                "- Exit 0 = success even with no output"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The zsh command to run"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_system",
            "description": (
                "Read-only shell command to check state. Use when you need to know something before acting, "
                "or when the result of an action is genuinely unclear. Do NOT use just to confirm obvious successes.\n"
                "Examples:\n"
                "- Current volume: osascript -e 'get volume settings'\n"
                "- Spotify track: osascript -e 'tell application \"Spotify\" to get name of current track'\n"
                "- Spotify playing?: osascript -e 'tell application \"Spotify\" to get player state'\n"
                "- App running?: osascript -e 'tell application \"System Events\" to (name of every process) contains \"Spotify\"'\n"
                "- File exists?: test -f ~/Desktop/file.txt && echo yes || echo no\n"
                "- List folder: ls ~/Desktop/"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "A read-only shell command"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Create a reminder in the macOS Reminders app. Use this instead of run_shell_command for any reminder creation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The reminder title"},
                    "due_date": {"type": "string", "description": "Due date/time in ISO format: YYYY-MM-DDTHH:MM, e.g. '2026-06-06T09:00'. Omit for no due date."}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "look_at_screen",
            "description": (
                "Your eyes. Takes a screenshot and either describes what's visible or clicks an element. "
                "Call this whenever the user asks to click/tap/select something, asks what's on screen, "
                "or when you need to see the screen to answer. "
                "Do NOT say you cannot see the screen — just call this."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "What to do — be specific: 'click the bell notification icon in the top-right of Chrome' or 'describe what app is in the foreground'"
                    }
                },
                "required": ["instruction"]
            }
        }
    }
]


def _run_tool(name: str, args: dict) -> str:
    from shell_executor import run
    if name in ("run_shell_command", "query_system"):
        cmd = args.get("command", "")
        log.info("tool call %s: %s", name, cmd)
        output, exit_code = run(cmd)
        if exit_code == 0:
            return output if output else "Success (command completed with no output)"
        return f"Error (exit {exit_code}): {output}"
    if name == "create_reminder":
        return _create_reminder(args.get("name", "Reminder"), args.get("due_date"))
    if name == "look_at_screen":
        instruction = args.get("instruction", "")
        log.info("tool call look_at_screen: %s", instruction)
        return _look_at_screen(instruction)
    return f"Unknown tool: {name}"


_last_image_size: tuple[int, int] | None = None
_last_physical_size: tuple[int, int] | None = None
_last_cursor_action: str | None = None
_turn_screenshot: tuple | None = None

def _create_reminder(name: str, due_date: str | None) -> str:
    from shell_executor import run
    if due_date:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(due_date)
            script = (
                f'tell application "Reminders"\n'
                f'set d to current date\n'
                f'set year of d to {dt.year}\n'
                f'set month of d to {dt.month}\n'
                f'set day of d to {dt.day}\n'
                f'set hours of d to {dt.hour}\n'
                f'set minutes of d to {dt.minute}\n'
                f'set seconds of d to 0\n'
                f'make new reminder with properties {{name:"{name}", due date:d}}\n'
                f'end tell'
            )
        except ValueError:
            return f"Error: invalid due_date format '{due_date}', use YYYY-MM-DDTHH:MM"
    else:
        script = f'tell application "Reminders" to make new reminder with properties {{name:"{name}"}}'

    output, exit_code = run(f"osascript << 'EOF'\n{script}\nEOF")
    if exit_code == 0:
        return f"Reminder '{name}' created" + (f" due {due_date}" if due_date else "")
    return f"Error creating reminder: {output}"


def _look_at_screen(instruction: str) -> str:
    """Take a screenshot (or reuse cached one) and ask the vision model."""
    global _last_image_size, _last_physical_size, _last_cursor_action, _turn_screenshot
    import screen_capture
    if _turn_screenshot is None:
        result = screen_capture.capture()
        if not result:
            return "ERROR: Could not take screenshot. Check Screen Recording permission."
        _turn_screenshot = result
        log.info("look_at_screen: fresh screenshot")
    else:
        result = _turn_screenshot
        log.info("look_at_screen: reusing cached screenshot")

    b64, image_size, physical_size = result
    _last_image_size = image_size
    _last_physical_size = physical_size
    img_w, img_h = image_size

    vision_prompt = (
        f"Mac screenshot ({img_w}x{img_h}px). Red grid labels show x,y coordinates at intersections.\n"
        f"Task: {instruction}\n\n"
        f"RESPOND WITH ONE OF:\n"
        f"A) If clicking/pointing is needed — output ONLY the tag, nothing else, no explanation:\n"
        f"   [CLICK:x1,y1,x2,y2]   (left-click — x1,y1=top-left of element, x2,y2=bottom-right)\n"
        f"   [RCLICK:x1,y1,x2,y2]  (right-click)\n"
        f"   [POINT:x1,y1,x2,y2]   (move cursor only)\n"
        f"   Read the nearest red grid label to each corner of the element to get coordinates.\n"
        f"   Example: if element spans from label '800,200' to label '1000,300' → [CLICK:800,200,1000,300]\n\n"
        f"B) If describing the screen — answer in 1-2 sentences, no tag needed."
    )

    messages = [{"role": "user", "content": vision_prompt, "images": [b64]}]
    payload = {"model": VISION_MODEL, "messages": messages, "stream": False}

    try:
        with httpx.Client(timeout=60) as client:
            resp = client.post(OLLAMA_URL, json=payload)
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "")
            log.info("vision model response: %s", content)
            tag_match = re.search(
                r'\[(?:CLICK|POINT|RCLICK):\d+\s*,\s*\d+(?:\s*,\s*\d+\s*,\s*\d+)?\]',
                content, re.IGNORECASE
            )
            if tag_match:
                tag = tag_match.group(0)
                _last_cursor_action = tag
                return f"Element located at {tag}. The click will be executed automatically."
            return f"Could not locate element on screen. Vision model said: {content[:100]}"
    except Exception as e:
        log.error("look_at_screen vision call failed: %s", e)
        return f"ERROR: vision model failed: {e}"


def _extract_run_commands(text: str) -> tuple[str, list[str]]:
    pattern = r"\[RUN:\s*(.*?)\]"
    commands = re.findall(pattern, text, re.DOTALL)
    clean = re.sub(pattern, "", text).strip()
    return clean, [c.strip() for c in commands]


def chat(history: list[dict], user_text: str, base64_image: str | None, on_token,
    image_size: tuple[int, int] | None = None) -> str:
    global _last_image_size, _last_physical_size, _last_cursor_action, _turn_screenshot
    _last_cursor_action = None
    _turn_screenshot = None

    model = COMMAND_MODEL
    log.info("using model: %s", model)

    user_msg: dict = {"role": "user", "content": user_text}
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}] + history + [user_msg]

    with httpx.Client(timeout=120) as client:
        for round_num in range(MAX_TOOL_ROUNDS):
            payload: dict = {"model": model, "messages": messages, "stream": True, "tools": TOOLS, "think": True}

            full_text = ""
            pending_tool_calls: list = []
            buffered_tokens: list = []

            with client.stream("POST", OLLAMA_URL, json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg = chunk.get("message", {})
                    content = msg.get("content") or ""
                    if content:
                        full_text += content
                        buffered_tokens.append(content)

                    tool_calls = msg.get("tool_calls") or []
                    pending_tool_calls.extend(tool_calls)

                    if chunk.get("done"):
                        break

            log.info("round %d done — text: %d chars, tool_calls: %d", round_num + 1, len(full_text), len(pending_tool_calls))

            if not pending_tool_calls:
                for token in buffered_tokens:
                    on_token(token)

                clean, cmds = _extract_run_commands(full_text)
                if cmds:
                    log.info("fallback [RUN:] commands: %s", cmds)
                    for cmd in cmds:
                        from shell_executor import run
                        run(cmd)
                    return clean

                return full_text

            log.info("tool round %d: %d call(s)", round_num + 1, len(pending_tool_calls))
            assistant_msg: dict = {
                "role": "assistant",
                "content": full_text or "",
                "tool_calls": pending_tool_calls,
            }
            messages.append(assistant_msg)
            for call in pending_tool_calls:
                fn = call.get("function", {})
                result = _run_tool(fn.get("name", ""), fn.get("arguments", {}))
                messages.append({"role": "tool", "content": result})

    return "I ran into too many steps and couldn't complete the action."



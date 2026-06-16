import rumps
import threading
import logging
import sys

from companion import CompanionManager, AppState

logging.basicConfig(
    level=logging.INFO,
    format="[LocalClicky] %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout
)
log = logging.getLogger(__name__)

STATE_ICONS = {
    AppState.IDLE:        "🎙️",
    AppState.LISTENING:   "👂",
    AppState.RECORDING:   "🔴",
    AppState.TRANSCRIBING:"🔄",
    AppState.THINKING:    "🤔",
    AppState.SPEAKING:    "🔊",
    AppState.ERROR:       "⚠️",
}


class LocalClickyApp(rumps.App):
    def __init__(self):
        super().__init__(STATE_ICONS[AppState.IDLE], quit_button=None)

        self._history_window: rumps.Window | None = None
        self._response_buffer = ""

        self.manager = CompanionManager(
            on_state_change=self._on_state_change,
            on_token=self._on_token,
        )

        self.menu = [
            rumps.MenuItem("Show Conversation", callback=self._show_conversation),
            rumps.MenuItem("Clear History", callback=self._clear_history),
            None,  # separator
            rumps.MenuItem("Quit", callback=self._quit),
        ]

        # Start wake word on launch
        threading.Thread(target=self.manager.start_listening, daemon=True).start()

    # MARK: - State

    def _on_state_change(self, state: str):
        icon = STATE_ICONS.get(state, "🎙️")
        rumps.notification(
            title="LocalClicky",
            subtitle="",
            message=self._state_label(state),
            sound=False
        ) if state in (AppState.RECORDING, AppState.SPEAKING) else None
        # Update menubar icon on main thread
        self.title = icon

    def _state_label(self, state: str) -> str:
        return {
            AppState.IDLE:         "Ready",
            AppState.LISTENING:    "Listening for 'Hey Jarvis'…",
            AppState.RECORDING:    "Recording…",
            AppState.TRANSCRIBING: "Transcribing…",
            AppState.THINKING:     "Thinking…",
            AppState.SPEAKING:     "Speaking…",
            AppState.ERROR:        "Error",
        }.get(state, state)

    def _on_token(self, token: str):
        self._response_buffer += token

    # MARK: - Menu actions

    @rumps.clicked("Show Conversation")
    def _show_conversation(self, _):
        if not self.manager.conversation:
            rumps.alert("No conversation yet. Say 'Computer' to start.")
            return

        lines = []
        for user, assistant in self.manager.conversation[-10:]:
            lines.append(f"You: {user}")
            lines.append(f"Assistant: {assistant}")
            lines.append("")
        rumps.alert(title="Conversation", message="\n".join(lines))

    @rumps.clicked("Clear History")
    def _clear_history(self, _):
        self.manager.clear_history()
        rumps.notification("LocalClicky", "", "Conversation cleared.", sound=False)

    def _quit(self, _):
        rumps.quit_application()


if __name__ == "__main__":
    LocalClickyApp().run()

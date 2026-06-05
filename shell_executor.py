import subprocess
import re
import logging

log = logging.getLogger(__name__)


def run(command: str) -> tuple[str, int]:
    import os
    log.info("executing: %s", command)
    result = subprocess.run(
        ["/bin/zsh", "-c", command],
        capture_output=True, text=True,
        cwd=os.path.expanduser("~"),  # default to home dir, same as a fresh terminal
    )
    output = "\n".join(filter(None, [result.stdout.strip(), result.stderr.strip()]))
    log.info("exit %d, output: %s", result.returncode, output[:200])
    return output, result.returncode


def extract_commands(text: str) -> tuple[str, list[str]]:
    pattern = r"\[RUN:\s*(.*?)\]"
    commands = re.findall(pattern, text, re.DOTALL)
    clean = re.sub(pattern, "", text).strip()
    return clean, [c.strip() for c in commands]

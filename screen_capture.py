import subprocess
import base64
import os
import io
import tempfile
import logging
from PIL import Image

log = logging.getLogger(__name__)

MAX_WIDTH = 1280
JPEG_QUALITY = 75

DEBUG_SAVE_PATH = os.path.expanduser("~/Desktop/localclicky_debug.jpg")


def capture() -> tuple[str, tuple[int, int], tuple[int, int]] | None:
    try:
        path = os.path.join(tempfile.gettempdir(), "localclicky_screen.jpg")
        result = subprocess.run(
            ["screencapture", "-x", "-t", "jpg", path],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            log.warning("screencapture failed (exit %d): %s", result.returncode, result.stderr)
            log.warning("Grant Screen Recording in System Settings → Privacy & Security → Screen Recording")
            return None
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            log.warning("screencapture produced no file — Screen Recording permission likely denied")
            return None

        with Image.open(path) as img:
            original_size = os.path.getsize(path)
            physical_w, physical_h = img.width, img.height

            if img.width > MAX_WIDTH:
                ratio = MAX_WIDTH / img.width
                img = img.resize((MAX_WIDTH, int(img.height * ratio)), Image.Resampling.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=JPEG_QUALITY)
            data = buf.getvalue()

            if DEBUG_SAVE_PATH:
                img.save(DEBUG_SAVE_PATH, format="JPEG", quality=JPEG_QUALITY)

        os.unlink(path)
        log.info(
            "screenshot: %d KB → %d KB (%dx%d), physical (%dx%d)",
            original_size // 1024, len(data) // 1024, img.width, img.height, physical_w, physical_h,
        )
        return base64.b64encode(data).decode(), (img.width, img.height), (physical_w, physical_h)
    except Exception as e:
        log.warning("screen capture error: %s", e)
        return None

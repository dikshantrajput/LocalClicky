import re
import logging
import pyautogui

log = logging.getLogger(__name__)

pyautogui.FAILSAFE = True  # move mouse to top-left corner to abort

_TAG_PATTERN = re.compile(
    r'`?\[(POINT|CLICK|RCLICK):(\d+)\s*,\s*(\d+)(?:\s*,\s*(\d+)\s*,\s*(\d+))?\]`?',
    re.IGNORECASE
)


def extract_action(text: str) -> tuple[str, str | None]:
    """
    Returns (clean_text, action_tag) where action_tag is the raw matched tag or None.
    Strips the tag from the spoken text.
    """
    match = _TAG_PATTERN.search(text)
    if not match:
        return text, None
    clean = _TAG_PATTERN.sub("", text).strip()
    return clean, match.group(0)


def execute(tag: str, image_size: tuple[int, int], physical_size: tuple[int, int]):
    """Execute a [POINT:x,y], [CLICK:x,y], or [RCLICK:x,y] tag.

    image_size: dimensions of the resized image sent to the model
    physical_size: original physical pixel dimensions from screencapture
    Logical screen size comes from pyautogui.size().
    """
    match = _TAG_PATTERN.match(tag)
    if not match:
        log.warning("invalid action tag: %s", tag)
        return

    action = match.group(1).upper()
    x1, y1 = int(match.group(2)), int(match.group(3))

    if match.group(4) is not None:
        # Bounding box — click the center
        x2, y2 = int(match.group(4)), int(match.group(5))
        px = (x1 + x2) // 2
        py = (y1 + y2) // 2
        log.info("bounding box (%d,%d)-(%d,%d) → center (%d,%d)", x1, y1, x2, y2, px, py)
    else:
        px, py = x1, y1

    # image coords → physical coords → logical coords
    img_w, img_h = image_size
    phys_w, phys_h = physical_size
    logical_w, logical_h = pyautogui.size()

    lx = int(px * (phys_w / img_w) * (logical_w / phys_w))
    ly = int(py * (phys_h / img_h) * (logical_h / phys_h))

    # macOS menu bar is ~25px tall. If model places a click in that zone it's almost
    # always aiming at browser tabs/toolbar just below it — nudge down to y=30 minimum.
    if ly < 30:
        log.info("y=%d is inside menu bar zone — clamping to 30", ly)
        ly = 30

    log.info(
        "cursor action: %s image(%d,%d) → logical(%d,%d) "
        "[img %dx%d, phys %dx%d, logical %dx%d]",
        action, px, py, lx, ly, img_w, img_h, phys_w, phys_h, logical_w, logical_h,
    )

    try:
        if action == "POINT":
            pyautogui.moveTo(lx, ly, duration=0.3)
        elif action == "CLICK":
            pyautogui.moveTo(lx, ly, duration=0.3)
            pyautogui.click(lx, ly)
        elif action == "RCLICK":
            pyautogui.moveTo(lx, ly, duration=0.3)
            pyautogui.rightClick(lx, ly)

        actual_x, actual_y = pyautogui.position()
        log.info(
            "cursor landed at actual(%d,%d) — expected logical(%d,%d) — drift(%+d,%+d)",
            actual_x, actual_y, lx, ly, actual_x - lx, actual_y - ly,
        )
    except pyautogui.FailSafeException:
        log.warning("pyautogui failsafe triggered — mouse moved to top-left corner")
    except Exception as e:
        log.error("cursor action failed: %s", e)
        if "not allowed assistive" in str(e).lower() or "accessibility" in str(e).lower() or "1002" in str(e):
            log.error("FIX: Grant Accessibility permission to Terminal/Python in System Settings → Privacy & Security → Accessibility")

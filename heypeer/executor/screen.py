"""Screen capture for "read_screen" - taken only when explicitly asked
for, never as part of every turn (that is exactly the design this project
moved away from - see `nemotron/client.py`'s module docstring for why
`interpret_text` no longer sends a screenshot on every request).
"""

import io

# Resized to at most this wide before sending. A 4K screenshot is several MB
# and does not obviously help Nemotron read on-screen text any better than a
# more reasonably sized one - this keeps the request fast without losing
# legibility for the kind of thing "qu'est-ce qu'il y a sur mon ecran ?" is
# actually asking about (an error dialog, a window title, a message).
MAX_WIDTH = 1280


def capture() -> "bytes | None":
    """A PNG screenshot of the whole screen, or None if screen capture
    isn't available here at all - `PIL.ImageGrab` needs a real display
    (Windows, macOS, or an X server with the right extensions; this
    project's own Linux dev sandbox has neither), and any failure must
    degrade to an honest spoken message, never a crash mid-turn.
    """
    try:
        from PIL import ImageGrab

        image = ImageGrab.grab()
    except Exception:
        return None

    if image.width > MAX_WIDTH:
        ratio = MAX_WIDTH / image.width
        image = image.resize((MAX_WIDTH, round(image.height * ratio)))

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()

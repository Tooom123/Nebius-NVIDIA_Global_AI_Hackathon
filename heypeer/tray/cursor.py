"""Best-effort colored-cursor indicator for when Hey Peer's auto mode is on.

Full support is Windows-only today, via the classic Win32 `SetSystemCursor`
API fed a generated tinted `.cur` file. macOS and Linux (X11/Wayland) don't
expose an equally simple, stable API for recoloring the *system* cursor —
`set_active()` there logs and no-ops instead of pretending to work. This
hasn't been exercised on a real Windows machine (this dev sandbox is
Linux/headless); the win32 call sequence is unit-tested with a mocked
`ctypes.windll`, but the actual on-screen result needs verifying for real.
"""

import io
import platform
import struct
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

# Distinct from typical system cursor colors, so it reads clearly as "Hey
# Peer is armed" rather than blending into a normal white/black arrow.
ACTIVE_TINT = (46, 204, 113, 255)

OCR_NORMAL = 32512  # win32 system cursor id for the default arrow
SPI_SETCURSORS = 0x0057  # reloads all system cursors from the active scheme


def _make_tinted_cursor_image(color: tuple[int, int, int, int], size: int = 32) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # A simple arrow silhouette — visibly cursor-shaped, not a pixel clone of
    # any particular OS's default arrow.
    draw.polygon(
        [
            (0, 0),
            (0, size - 1),
            (size // 3, size * 2 // 3),
            (size // 2, size - 1),
            (size * 2 // 3, size * 2 // 3),
            (size - 1, size // 2),
        ],
        fill=color,
        outline=(0, 0, 0, 255),
    )
    return image


def _write_cur_file(image: Image.Image, hotspot: tuple[int, int], out_path: Path) -> None:
    """Writes a minimal valid .cur file with a PNG-encoded frame.

    PNG-compressed icon/cursor frames are supported by the Win32 icon loader
    since Windows Vista, regardless of pixel size — this avoids having to
    hand-encode a legacy BMP DIB frame.
    """
    png_buffer = io.BytesIO()
    image.save(png_buffer, format="PNG")
    png_bytes = png_buffer.getvalue()

    width, height = image.size
    width_byte = width if width < 256 else 0
    height_byte = height if height < 256 else 0

    header = struct.pack("<HHH", 0, 2, 1)  # reserved=0, type=2 (cursor), count=1
    entry = struct.pack(
        "<BBBBHHII",
        width_byte,
        height_byte,
        0,  # color count (0 = no palette, i.e. >=8bpp)
        0,  # reserved
        hotspot[0],
        hotspot[1],
        len(png_bytes),
        6 + 16,  # offset of image data: header (6) + this entry (16)
    )
    out_path.write_bytes(header + entry + png_bytes)


class CursorIndicator:
    """Toggles a colored mouse cursor to show that auto mode is armed."""

    def __init__(self) -> None:
        self._supported = platform.system() == "Windows"
        self._active = False

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        if not self._supported:
            print(
                "[heypeer] Indicateur de curseur coloré non supporté sur "
                f"{platform.system()} — ignoré (Windows uniquement pour l'instant)."
            )
            return
        self._apply_windows(active)

    def _apply_windows(self, active: bool) -> None:
        import ctypes

        user32 = ctypes.windll.user32
        if active:
            image = _make_tinted_cursor_image(ACTIVE_TINT)
            cursor_path = Path(tempfile.gettempdir()) / "heypeer_cursor_active.cur"
            _write_cur_file(image, hotspot=(0, 0), out_path=cursor_path)
            handle = user32.LoadCursorFromFileW(str(cursor_path))
            if handle:
                user32.SetSystemCursor(handle, OCR_NORMAL)
        else:
            user32.SystemParametersInfoW(SPI_SETCURSORS, 0, None, 0)

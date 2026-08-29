"""Best-effort colored-cursor indicator for when Hey Peer's auto mode is on.

Full support is Windows-only today, via the classic Win32 `SetSystemCursor`
API fed a tinted `.cur` file. macOS and Linux (X11/Wayland) don't expose an
equally simple, stable API for recoloring the *system* cursor — `set_active()`
there logs and no-ops instead of pretending to work.

The tinted cursor is built by extracting Windows' own default arrow cursor
bitmap (via `GetIconInfo`/`GetDIBits` on the monochrome AND/XOR mask) and
recoloring only its white fill pixels — the black outline, transparency, and
exact silhouette are all preserved as-is, so this only changes color, never
shape.

Every win32 function used here gets explicit `argtypes`/`restype` — ctypes
defaults undeclared arguments/return values to 32-bit `c_int`, which silently
truncates real 64-bit handles/pointers on 64-bit Windows and raises
`OverflowError: int too long to convert` the moment a handle happens to sit
above 2**31 (which real HBITMAP/HCURSOR values from the heap routinely do).
"""

import io
import platform
import struct
import tempfile
from pathlib import Path

from PIL import Image

# Distinct from typical system cursor colors, so it reads clearly as "Hey
# Peer is armed" rather than blending into a normal white/black arrow.
ACTIVE_TINT = (46, 204, 113, 255)

IDC_ARROW = 32512
OCR_NORMAL = 32512  # win32 system cursor id for the default arrow
SPI_SETCURSORS = 0x0057  # reloads all system cursors from the active scheme
DIB_RGB_COLORS = 0
BI_RGB = 0


def _win32_structures(ctypes_mod, wintypes):
    """Defines the ctypes Structures shared by extraction and DIB reading.
    Kept in one place so both users stay in sync."""

    class ICONINFO(ctypes_mod.Structure):
        _fields_ = [
            ("fIcon", wintypes.BOOL),
            ("xHotspot", wintypes.DWORD),
            ("yHotspot", wintypes.DWORD),
            ("hbmMask", wintypes.HBITMAP),
            ("hbmColor", wintypes.HBITMAP),
        ]

    class BITMAP(ctypes_mod.Structure):
        _fields_ = [
            ("bmType", ctypes_mod.c_long),
            ("bmWidth", ctypes_mod.c_long),
            ("bmHeight", ctypes_mod.c_long),
            ("bmWidthBytes", ctypes_mod.c_long),
            ("bmPlanes", wintypes.WORD),
            ("bmBitsPixel", wintypes.WORD),
            ("bmBits", ctypes_mod.c_void_p),
        ]

    class BITMAPINFOHEADER(ctypes_mod.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes_mod.c_long),
            ("biHeight", ctypes_mod.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes_mod.c_long),
            ("biYPelsPerMeter", ctypes_mod.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes_mod.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    return ICONINFO, BITMAP, BITMAPINFOHEADER, BITMAPINFO


def _prepare_win32_functions(ctypes_mod, wintypes, ICONINFO):
    """Declares argtypes/restype on every win32 entry point used in this
    module. Must be called (idempotent, cheap) before any of them are
    invoked — see module docstring for why this matters."""
    user32 = ctypes_mod.windll.user32
    gdi32 = ctypes_mod.windll.gdi32

    user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    user32.LoadCursorW.restype = wintypes.HICON

    user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes_mod.POINTER(ICONINFO)]
    user32.GetIconInfo.restype = wintypes.BOOL

    gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes_mod.c_int, ctypes_mod.c_void_p]
    gdi32.GetObjectW.restype = ctypes_mod.c_int

    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC

    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes_mod.c_int

    gdi32.GetDIBits.argtypes = [
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes_mod.c_void_p,
        ctypes_mod.c_void_p,
        wintypes.UINT,
    ]
    gdi32.GetDIBits.restype = ctypes_mod.c_int

    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteObject.restype = wintypes.BOOL

    user32.LoadCursorFromFileW.argtypes = [wintypes.LPCWSTR]
    user32.LoadCursorFromFileW.restype = wintypes.HICON

    user32.SetSystemCursor.argtypes = [wintypes.HICON, wintypes.DWORD]
    user32.SetSystemCursor.restype = wintypes.BOOL

    user32.SystemParametersInfoW.argtypes = [
        wintypes.UINT,
        wintypes.UINT,
        wintypes.LPVOID,
        wintypes.UINT,
    ]
    user32.SystemParametersInfoW.restype = wintypes.BOOL

    return user32, gdi32


def _read_dib_bits(ctypes_mod, wintypes, user32, gdi32, BITMAPINFOHEADER, BITMAPINFO, hbitmap, width, height, bit_count):
    """Reads a bitmap's raw pixel bytes top-down via GetDIBits. Shared by the
    monochrome (1bpp AND/XOR mask) and color (32bpp BGRA) extraction paths."""
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes_mod.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height  # negative = top-down rows
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = bit_count
    bmi.bmiHeader.biCompression = BI_RGB

    row_bytes = ((width * bit_count + 31) // 32) * 4
    buffer = (ctypes_mod.c_ubyte * (row_bytes * height))()
    hdc = user32.GetDC(None)
    gdi32.GetDIBits(hdc, hbitmap, 0, height, buffer, ctypes_mod.byref(bmi), DIB_RGB_COLORS)
    user32.ReleaseDC(None, hdc)
    return buffer, row_bytes


def _extract_mono_arrow(ctypes_mod, wintypes, user32, gdi32, structs, icon_info, tint):
    """Classic monochrome cursor: hbmColor is NULL, hbmMask stacks a 1bpp AND
    mask over a 1bpp XOR mask, each full-height."""
    _ICONINFO, BITMAP, BITMAPINFOHEADER, BITMAPINFO = structs

    bmp = BITMAP()
    gdi32.GetObjectW(icon_info.hbmMask, ctypes_mod.sizeof(BITMAP), ctypes_mod.byref(bmp))
    width = bmp.bmWidth
    total_height = bmp.bmHeight
    height = total_height // 2

    buffer, row_bytes = _read_dib_bits(
        ctypes_mod, wintypes, user32, gdi32, BITMAPINFOHEADER, BITMAPINFO,
        icon_info.hbmMask, width, total_height, bit_count=1,
    )

    def get_bit(row_offset: int, x: int, y: int) -> int:
        row = row_offset + y
        byte_index = row * row_bytes + x // 8
        bit_index = 7 - (x % 8)
        return (buffer[byte_index] >> bit_index) & 1

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            and_bit = get_bit(0, x, y)
            xor_bit = get_bit(height, x, y)
            if and_bit == 1 and xor_bit == 0:
                pixels[x, y] = (0, 0, 0, 0)  # transparent
            elif and_bit == 0 and xor_bit == 1:
                pixels[x, y] = tint  # the arrow's white fill -> recolored
            else:
                pixels[x, y] = (0, 0, 0, 255)  # outline (and the rare invert case)
    return image


def _extract_color_arrow(ctypes_mod, wintypes, user32, gdi32, structs, icon_info, tint):
    """Modern color cursor: hbmColor holds a real 32bpp BGRA bitmap with its
    own alpha channel — common on current Windows cursor schemes/themes.
    Recolors by brightness: bright (white-ish) pixels become `tint` at their
    original alpha, dark (outline) pixels stay black — same idea as the
    monochrome path's AND/XOR split, just reading real color+alpha instead."""
    _ICONINFO, BITMAP, BITMAPINFOHEADER, BITMAPINFO = structs

    bmp = BITMAP()
    gdi32.GetObjectW(icon_info.hbmColor, ctypes_mod.sizeof(BITMAP), ctypes_mod.byref(bmp))
    width, height = bmp.bmWidth, bmp.bmHeight

    buffer, row_bytes = _read_dib_bits(
        ctypes_mod, wintypes, user32, gdi32, BITMAPINFOHEADER, BITMAPINFO,
        icon_info.hbmColor, width, height, bit_count=32,
    )

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            i = y * row_bytes + x * 4
            b, g, r, a = buffer[i], buffer[i + 1], buffer[i + 2], buffer[i + 3]
            if a == 0:
                pixels[x, y] = (0, 0, 0, 0)
            elif (r + g + b) / 3 > 128:
                pixels[x, y] = (tint[0], tint[1], tint[2], a)
            else:
                pixels[x, y] = (0, 0, 0, a)
    return image


def _extract_recolored_arrow(tint: tuple[int, int, int, int]) -> tuple[Image.Image, tuple[int, int]]:
    """Reads Windows' own default arrow cursor bitmap and returns a copy with
    its white fill pixels replaced by `tint` — same shape, same outline, same
    hotspot, only the color changes. Windows-only; must not be called
    elsewhere."""
    import ctypes
    from ctypes import wintypes

    structs = _win32_structures(ctypes, wintypes)
    ICONINFO = structs[0]
    user32, gdi32 = _prepare_win32_functions(ctypes, wintypes, ICONINFO)

    hcursor = user32.LoadCursorW(None, ctypes.cast(IDC_ARROW, wintypes.LPCWSTR))
    if not hcursor:
        raise OSError("LoadCursorW(IDC_ARROW) failed")

    icon_info = ICONINFO()
    if not user32.GetIconInfo(hcursor, ctypes.byref(icon_info)):
        raise OSError("GetIconInfo failed")

    try:
        if icon_info.hbmColor:
            image = _extract_color_arrow(ctypes, wintypes, user32, gdi32, structs, icon_info, tint)
        else:
            image = _extract_mono_arrow(ctypes, wintypes, user32, gdi32, structs, icon_info, tint)
        hotspot = (icon_info.xHotspot, icon_info.yHotspot)
        return image, hotspot
    finally:
        gdi32.DeleteObject(icon_info.hbmMask)
        if icon_info.hbmColor:
            gdi32.DeleteObject(icon_info.hbmColor)


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
                "[heypeer] Indicateur de curseur colore non supporte sur "
                f"{platform.system()} - ignore (Windows uniquement pour l'instant)."
            )
            return
        self._apply_windows(active)

    def reset(self) -> None:
        """Unconditionally restores the default system cursor scheme,
        bypassing the active-state dedup in `set_active`. Called defensively
        at startup (in case a previous crashed run left the cursor stuck) and
        at shutdown, since a normal `set_active(False)` would silently no-op
        if this instance never saw `active` flip to True — e.g. right after
        a crash, a fresh `CursorIndicator` starts at `_active=False` already."""
        self._active = False
        if not self._supported:
            return
        import ctypes
        from ctypes import wintypes

        ICONINFO, *_ = _win32_structures(ctypes, wintypes)
        user32, _gdi32 = _prepare_win32_functions(ctypes, wintypes, ICONINFO)
        user32.SystemParametersInfoW(SPI_SETCURSORS, 0, None, 0)

    def _apply_windows(self, active: bool) -> None:
        import ctypes
        from ctypes import wintypes

        ICONINFO, *_ = _win32_structures(ctypes, wintypes)
        user32, _gdi32 = _prepare_win32_functions(ctypes, wintypes, ICONINFO)

        if active:
            image, hotspot = _extract_recolored_arrow(ACTIVE_TINT)
            cursor_path = Path(tempfile.gettempdir()) / "heypeer_cursor_active.cur"
            _write_cur_file(image, hotspot=hotspot, out_path=cursor_path)
            handle = user32.LoadCursorFromFileW(str(cursor_path))
            if handle:
                user32.SetSystemCursor(handle, OCR_NORMAL)
        else:
            user32.SystemParametersInfoW(SPI_SETCURSORS, 0, None, 0)

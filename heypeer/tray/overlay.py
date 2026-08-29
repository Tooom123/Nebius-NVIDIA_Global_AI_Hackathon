"""A click-through, per-pixel-alpha overlay window on Windows.

`UpdateLayeredWindow` composites a 32-bit BGRA bitmap straight into the
desktop, so the window has genuine per-pixel transparency: antialiased
edges, soft glows, and no background of any kind. That is the capability
every earlier approach lacked —

* a web view's own `transparent=True` still left the WinForms form's grey
  behind it, and
* `SetWindowRgn` clips with a 1-bit mask, so edges come out hard and jagged
  and a glow is impossible.

Both were attempts to talk a browser engine into something Win32 exposes
directly. Rendering the frame ourselves (see `blob_render.py`) and pushing
it through here is the standard way polished Windows overlays are built, and
it takes the browser engine — and its failure modes — out of the picture.

Windows-only by design, like `cursor.py`. `is_supported()` reports that
honestly rather than the caller having to guess.

Every win32 function gets explicit `argtypes`/`restype`: ctypes otherwise
defaults them to 32-bit `c_int` and silently truncates 64-bit handles, which
already caused a real `OverflowError` crash in this project (see
`cursor.py`'s module docstring).
"""

import platform

WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080  # keeps it out of the taskbar and Alt-Tab
WS_EX_TRANSPARENT = 0x00000020  # clicks pass straight through to what's underneath
WS_EX_NOACTIVATE = 0x08000000  # never steals focus from what the user is doing
WS_POPUP = 0x80000000

SW_HIDE = 0
SW_SHOWNOACTIVATE = 4

ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01

BI_RGB = 0
DIB_RGB_COLORS = 0


def is_supported() -> bool:
    return platform.system() == "Windows"


def _premultiplied_bgra(image) -> bytes:
    """Converts an RGBA PIL image to the premultiplied BGRA bytes
    `UpdateLayeredWindow` expects with `AC_SRC_ALPHA`.

    Premultiplication is required, not cosmetic: without it Windows renders
    a bright halo around every partially transparent pixel — which is most of
    the glow.
    """
    import numpy as np

    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint16)
    alpha = rgba[..., 3:4]
    rgb = (rgba[..., :3] * alpha // 255).astype(np.uint8)
    bgra = np.dstack([rgb[..., ::-1], alpha.astype(np.uint8)])
    return bgra.tobytes()


class Overlay:
    """A borderless, click-through window whose contents are a PIL image."""

    def __init__(self, width: int, height: int, title: str = "Hey Peer Overlay") -> None:
        self.width = width
        self.height = height
        self.title = title
        self._hwnd = None
        self._visible = False
        self._wndclass = None  # kept referenced so its WNDPROC isn't collected

    def create(self) -> bool:
        """Creates the window (hidden). Returns whether it succeeded — a
        failure here is cosmetic, so callers degrade rather than crash."""
        if not is_supported():
            return False
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_long, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM
        )

        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("style", ctypes.c_uint),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
                ("hIconSm", wintypes.HICON),
            ]

        user32.DefWindowProcW.argtypes = [
            wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM
        ]
        user32.DefWindowProcW.restype = ctypes.c_long
        user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
        user32.RegisterClassExW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND

        try:
            wndclass = WNDCLASSEXW()
            wndclass.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wndclass.lpfnWndProc = WNDPROC(user32.DefWindowProcW)
            wndclass.lpszClassName = "HeyPeerOverlay"
            wndclass.hInstance = None
            # Re-registering the same class fails harmlessly if the process
            # already did it; CreateWindowExW below still works.
            user32.RegisterClassExW(ctypes.byref(wndclass))
            self._wndclass = wndclass  # keep the WNDPROC alive

            self._hwnd = user32.CreateWindowExW(
                WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
                | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE,
                "HeyPeerOverlay",
                self.title,
                WS_POPUP,
                0, 0, self.width, self.height,
                None, None, None, None,
            )
            return bool(self._hwnd)
        except Exception:
            self._hwnd = None
            return False

    def update(self, image, x: int, y: int) -> bool:
        """Pushes `image` (RGBA PIL, window-sized) to the screen at (x, y)."""
        if not self._hwnd:
            return False
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class SIZE(ctypes.Structure):
            _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [
                ("BlendOp", ctypes.c_ubyte),
                ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte),
            ]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        user32.GetDC.argtypes = [wintypes.HWND]
        user32.GetDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        user32.ReleaseDC.restype = ctypes.c_int
        gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateDIBSection.argtypes = [
            wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
        ]
        gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
        gdi32.SelectObject.restype = wintypes.HANDLE
        gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        gdi32.DeleteObject.restype = wintypes.BOOL
        gdi32.DeleteDC.argtypes = [wintypes.HDC]
        gdi32.DeleteDC.restype = wintypes.BOOL
        user32.UpdateLayeredWindow.argtypes = [
            wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
            wintypes.HDC, ctypes.POINTER(POINT), wintypes.COLORREF,
            ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD,
        ]
        user32.UpdateLayeredWindow.restype = wintypes.BOOL

        width, height = image.size
        screen_dc = memory_dc = bitmap = None
        try:
            screen_dc = user32.GetDC(None)
            memory_dc = gdi32.CreateCompatibleDC(screen_dc)

            header = BITMAPINFOHEADER()
            header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            header.biWidth = width
            header.biHeight = -height  # negative: top-down rows, matching PIL
            header.biPlanes = 1
            header.biBitCount = 32
            header.biCompression = BI_RGB

            bits = ctypes.c_void_p()
            bitmap = gdi32.CreateDIBSection(
                memory_dc, ctypes.byref(header), DIB_RGB_COLORS, ctypes.byref(bits), None, 0
            )
            if not bitmap:
                return False
            gdi32.SelectObject(memory_dc, bitmap)

            payload = _premultiplied_bgra(image)
            ctypes.memmove(bits, payload, len(payload))

            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            position = POINT(int(x), int(y))
            size = SIZE(width, height)
            source = POINT(0, 0)
            return bool(
                user32.UpdateLayeredWindow(
                    self._hwnd, screen_dc, ctypes.byref(position), ctypes.byref(size),
                    memory_dc, ctypes.byref(source), 0, ctypes.byref(blend), ULW_ALPHA,
                )
            )
        except Exception:
            return False
        finally:
            # GDI objects are a finite process-wide resource; leaking one per
            # frame at 30fps would exhaust them within minutes.
            if bitmap:
                gdi32.DeleteObject(bitmap)
            if memory_dc:
                gdi32.DeleteDC(memory_dc)
            if screen_dc:
                user32.ReleaseDC(None, screen_dc)

    def set_visible(self, visible: bool) -> None:
        if not self._hwnd or visible == self._visible:
            return
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        try:
            # SHOWNOACTIVATE, so bringing the indicator up never pulls focus
            # away from whatever the user is typing in.
            user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE if visible else SW_HIDE)
            self._visible = visible
        except Exception:
            pass

    def pump_messages(self) -> None:
        """Drains pending window messages. Cheap, and required — a window
        that never processes its queue is considered hung by Windows."""
        if not self._hwnd:
            return
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND), ("message", ctypes.c_uint),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long),
            ]

        user32.PeekMessageW.argtypes = [
            ctypes.POINTER(MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint
        ]
        user32.PeekMessageW.restype = wintypes.BOOL

        try:
            message = MSG()
            while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):  # 1 = PM_REMOVE
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except Exception:
            pass

    def destroy(self) -> None:
        if not self._hwnd:
            return
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        try:
            user32.DestroyWindow(self._hwnd)
        except Exception:
            pass
        self._hwnd = None

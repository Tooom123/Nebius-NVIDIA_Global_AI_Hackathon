"""Drawing "I <3 NVIDIA & NEBIUS" in Paint, with the mouse.

## Why stroke it rather than type it

Paint has a text tool, and typing would be legible in one action. The user
chose the drawing: the point of this part of the demo is to *watch* Hey
Peer draw, and a typed caption appears all at once with nothing to see.

So the letters are strokes - the same continuous drags a person makes -
and they look hand-drawn because they are. That is the effect, not a
shortcoming.

## The alphabet

Only the letters this one phrase needs, as polylines in a 0..1 box per
glyph. A general vector font would be a font renderer, and this is a demo
line that never changes; five letters and a heart is the honest scope.

Coordinates are fractions so the whole phrase scales to whatever canvas
area it is given, and each glyph is a *list of strokes* rather than one
path - a letter like I is three separate pen-downs, and joining them would
draw the pen travelling between them.

## What is not handled

Paint's own state. If the brush is tiny, the colour is white, or a
selection is active, this draws faithfully and invisibly. Those are one
click each to set up and the demo machine is prepared in advance, so the
alternative - clicking through Paint's ribbon by coordinate - would add
several fragile steps to guard against something a person fixes once.
"""

# Each glyph: a list of strokes, each stroke a list of (x, y) in 0..1,
# origin top-left. Widths are per-glyph so I is narrow and M-width letters
# are not squeezed into the same box.
GLYPHS = {
    "I": {
        "width": 0.30,
        "strokes": [
            [(0.05, 0.0), (0.25, 0.0)],
            [(0.15, 0.0), (0.15, 1.0)],
            [(0.05, 1.0), (0.25, 1.0)],
        ],
    },
    # A heart, as two lobes into a point. Drawn as one continuous stroke so
    # the pen never lifts, which is what makes it read as drawn rather than
    # assembled.
    "<3": {
        "width": 0.70,
        "strokes": [[
            (0.35, 1.00), (0.10, 0.62), (0.03, 0.40), (0.08, 0.20),
            (0.20, 0.12), (0.30, 0.18), (0.35, 0.30),
            (0.40, 0.18), (0.50, 0.12), (0.62, 0.20),
            (0.67, 0.40), (0.60, 0.62), (0.35, 1.00),
        ]],
    },
    "N": {
        "width": 0.55,
        "strokes": [[(0.05, 1.0), (0.05, 0.0), (0.45, 1.0), (0.45, 0.0)]],
    },
    "V": {
        "width": 0.55,
        "strokes": [[(0.05, 0.0), (0.25, 1.0), (0.45, 0.0)]],
    },
    "D": {
        "width": 0.55,
        "strokes": [[
            (0.05, 1.0), (0.05, 0.0), (0.30, 0.05), (0.45, 0.30),
            (0.45, 0.70), (0.30, 0.95), (0.05, 1.0),
        ]],
    },
    "A": {
        "width": 0.55,
        "strokes": [
            [(0.05, 1.0), (0.25, 0.0), (0.45, 1.0)],
            [(0.12, 0.65), (0.38, 0.65)],
        ],
    },
    "&": {
        "width": 0.55,
        "strokes": [[
            (0.42, 1.00), (0.12, 0.55), (0.10, 0.25), (0.22, 0.10),
            (0.34, 0.20), (0.30, 0.42), (0.08, 0.72),
            (0.12, 0.92), (0.30, 0.98), (0.45, 0.80),
        ]],
    },
    "E": {
        "width": 0.50,
        "strokes": [
            [(0.40, 0.0), (0.08, 0.0), (0.08, 1.0), (0.40, 1.0)],
            [(0.08, 0.5), (0.32, 0.5)],
        ],
    },
    "B": {
        "width": 0.55,
        "strokes": [
            [(0.08, 1.0), (0.08, 0.0), (0.34, 0.06), (0.40, 0.25),
             (0.30, 0.48), (0.08, 0.50)],
            [(0.08, 0.50), (0.36, 0.56), (0.44, 0.76), (0.34, 0.95), (0.08, 1.0)],
        ],
    },
    "U": {
        "width": 0.55,
        "strokes": [[(0.05, 0.0), (0.05, 0.75), (0.25, 1.0), (0.45, 0.75), (0.45, 0.0)]],
    },
    "S": {
        "width": 0.50,
        "strokes": [[
            (0.40, 0.10), (0.20, 0.00), (0.08, 0.15), (0.14, 0.38),
            (0.36, 0.55), (0.42, 0.78), (0.28, 0.98), (0.08, 0.88),
        ]],
    },
    " ": {"width": 0.35, "strokes": []},
}

PHRASE = ("I", " ", "<3", " ", "N", "V", "I", "D", "I", "A", " ",
          "&", " ", "N", "E", "B", "I", "U", "S")

# Gap between glyphs, as a fraction of glyph height - so spacing scales
# with the text rather than staying fixed while letters grow.
TRACKING = 0.10

# Seconds between the points of one stroke. This is what makes it look
# drawn rather than stamped: fast enough not to be tedious across nineteen
# glyphs, slow enough that the line is visibly being laid down.
POINT_INTERVAL = 0.006
# Between strokes, while the pen is up and travelling.
STROKE_PAUSE = 0.05


def phrase_width(height: float) -> float:
    """How wide the whole phrase will be, for a given glyph height."""
    total = sum(GLYPHS[ch]["width"] for ch in PHRASE)
    return (total + TRACKING * (len(PHRASE) - 1)) * height


def layout(
    canvas: "tuple[int, int, int, int]", phrase=PHRASE
) -> "list[list[tuple[int, int]]]":
    """Every stroke of the phrase, in screen pixels, laid out to fit inside
    `canvas` as `(left, top, width, height)`.

    Returns strokes rather than glyphs: by this point the letters do not
    matter, only the pen movements, and the caller draws whatever it is
    handed.
    """
    left, top, width, height = canvas

    # Sized to whichever bound binds first - a long phrase on a wide canvas
    # is limited by height, a short one on a narrow canvas by width.
    glyph_height = min(height * 0.55, width * 0.9 / max(phrase_width(1.0), 1e-6))
    total_width = phrase_width(glyph_height)
    x = left + (width - total_width) / 2
    y = top + (height - glyph_height) / 2

    strokes = []
    for char in phrase:
        glyph = GLYPHS.get(char)
        if glyph is None:
            continue
        for stroke in glyph["strokes"]:
            strokes.append([
                (round(x + px * glyph_height), round(y + py * glyph_height))
                for px, py in stroke
            ])
        x += (glyph["width"] + TRACKING) * glyph_height
    return strokes


def canvas_area(window: "tuple[int, int, int, int]") -> "tuple[int, int, int, int]":
    """The drawable part of a Paint window, as `(left, top, width, height)`.

    Inset from the window rather than measured: Paint's ribbon is at the
    top and its status bar at the bottom, and both are a fixed share of the
    window at any size. Drawing inside a generous inset is safer than
    finding the canvas exactly - a stroke that starts on the ribbon clicks
    a tool instead of drawing.
    """
    left, top, width, height = window
    return (
        left + int(width * 0.10),
        top + int(height * 0.32),
        int(width * 0.80),
        int(height * 0.50),
    )


def find_window() -> "tuple[int, int, int, int] | None":
    """Paint's window rectangle, or None if it is not open."""
    try:
        import uiautomation as auto

        for name in ("Paint", "Untitled - Paint", "Sans titre - Paint"):
            window = auto.WindowControl(searchDepth=1, SubName=name)
            if window.Exists(maxSearchSeconds=1):
                rect = window.BoundingRectangle
                return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
        return None
    except Exception:
        return None


def focus_window() -> bool:
    """Brings Paint to the front. Same reasoning as FL Studio's: an
    unfocused window eats the first press activating itself, which on a
    drag means the stroke starts late and in the wrong place."""
    import time

    try:
        import uiautomation as auto

        for name in ("Paint", "Untitled - Paint", "Sans titre - Paint"):
            window = auto.WindowControl(searchDepth=1, SubName=name)
            if window.Exists(maxSearchSeconds=1):
                window.SetActive()
                time.sleep(0.35)
                return True
        return False
    except Exception:
        return False

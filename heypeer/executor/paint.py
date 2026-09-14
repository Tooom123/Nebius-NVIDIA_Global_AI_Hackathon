"""Drawing "I <3 NVIDIA & NEBIUS" in Paint, with the mouse.

## Why stroke it rather than type it

Paint has a text tool, and typing would be legible in one action. The user
chose the drawing: the point of this part of the demo is to *watch* Hey
Peer draw, and a typed caption appears all at once with nothing to see.

So the letters are strokes - the same continuous drags a person makes -
and they look hand-drawn because they are. That is the effect, not a
shortcoming.

## The alphabet

Polylines in a 0..1 box per glyph, hand-placed. It started as only the
letters one fixed phrase needed; it now covers the Latin alphabet this
project can draw, because the phrase is no longer fixed - Nemotron chooses
it (see `NemotronClient.compose_tribute`), and a model choosing words that
cannot be drawn is worse than no choice at all.

Still not a font renderer: no lowercase, no accents, no kerning pairs. What
it is is enough letters that a short chosen phrase draws rather than
silently losing characters, and `drawable` says what is in range so the
caller can fall back rather than draw a phrase with holes in it.

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
    "C": {
        "width": 0.52,
        "strokes": [[(0.42, 0.12), (0.22, 0.00), (0.06, 0.30), (0.06, 0.70),
                     (0.22, 1.00), (0.42, 0.88)]],
    },
    "G": {
        "width": 0.56,
        "strokes": [[(0.44, 0.12), (0.24, 0.00), (0.06, 0.30), (0.06, 0.70),
                     (0.24, 1.00), (0.44, 0.86), (0.44, 0.58), (0.28, 0.58)]],
    },
    "H": {
        "width": 0.55,
        "strokes": [[(0.05, 0.0), (0.05, 1.0)], [(0.45, 0.0), (0.45, 1.0)],
                    [(0.05, 0.52), (0.45, 0.52)]],
    },
    "K": {
        "width": 0.52,
        "strokes": [[(0.06, 0.0), (0.06, 1.0)], [(0.42, 0.0), (0.06, 0.54)],
                    [(0.16, 0.44), (0.44, 1.0)]],
    },
    "L": {"width": 0.46, "strokes": [[(0.08, 0.0), (0.08, 1.0), (0.40, 1.0)]]},
    "M": {
        "width": 0.66,
        "strokes": [[(0.05, 1.0), (0.05, 0.0), (0.28, 0.55), (0.51, 0.0), (0.51, 1.0)]],
    },
    "O": {
        "width": 0.56,
        "strokes": [[(0.25, 0.00), (0.06, 0.28), (0.06, 0.72), (0.25, 1.00),
                     (0.44, 0.72), (0.44, 0.28), (0.25, 0.00)]],
    },
    "P": {
        "width": 0.52,
        "strokes": [[(0.08, 1.0), (0.08, 0.0), (0.34, 0.06), (0.42, 0.26),
                     (0.32, 0.48), (0.08, 0.52)]],
    },
    "R": {
        "width": 0.54,
        "strokes": [[(0.08, 1.0), (0.08, 0.0), (0.34, 0.06), (0.42, 0.26),
                     (0.32, 0.48), (0.08, 0.52)],
                    [(0.22, 0.52), (0.44, 1.0)]],
    },
    "T": {"width": 0.50, "strokes": [[(0.04, 0.0), (0.44, 0.0)], [(0.24, 0.0), (0.24, 1.0)]]},
    "W": {
        "width": 0.70,
        "strokes": [[(0.04, 0.0), (0.18, 1.0), (0.32, 0.36), (0.46, 1.0), (0.60, 0.0)]],
    },
    "Y": {
        "width": 0.52,
        "strokes": [[(0.06, 0.0), (0.24, 0.50), (0.42, 0.0)], [(0.24, 0.50), (0.24, 1.0)]],
    },
    # The letters the first pass missed. Found by asking Nemotron for three
    # phrases and watching one fail on the J of JURY - a reminder that "the
    # alphabet this project can draw" is only true if it is actually
    # complete, and that a half-alphabet fails silently at the worst moment.
    "F": {"width": 0.48, "strokes": [[(0.40, 0.0), (0.08, 0.0), (0.08, 1.0)],
                                     [(0.08, 0.5), (0.32, 0.5)]]},
    "J": {"width": 0.46, "strokes": [[(0.36, 0.0), (0.36, 0.78), (0.22, 0.98),
                                      (0.06, 0.84)]]},
    "Q": {
        "width": 0.56,
        "strokes": [[(0.25, 0.00), (0.06, 0.28), (0.06, 0.72), (0.25, 1.00),
                     (0.44, 0.72), (0.44, 0.28), (0.25, 0.00)],
                    [(0.32, 0.74), (0.48, 1.04)]],
    },
    "X": {"width": 0.52, "strokes": [[(0.06, 0.0), (0.44, 1.0)],
                                     [(0.44, 0.0), (0.06, 1.0)]]},
    "Z": {"width": 0.50, "strokes": [[(0.06, 0.0), (0.44, 0.0), (0.06, 1.0), (0.44, 1.0)]]},
    "!": {"width": 0.26, "strokes": [[(0.12, 0.0), (0.12, 0.70)], [(0.12, 0.92), (0.12, 1.0)]]},
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


def drawable(phrase: "str | list[str]") -> bool:
    """Whether every character of `phrase` has a glyph.

    Checked before drawing rather than skipping the unknown ones mid-stroke:
    a phrase missing two letters is not a shorter phrase, it is a mistake
    nobody watching can read, and the caller has a fixed fallback to use
    instead.
    """
    return all(ch in GLYPHS for ch in phrase)


def parse_phrase(text: str) -> "list[str]":
    """A phrase as drawable tokens, uppercased, with "<3" kept whole.

    The heart is two characters in text and one glyph on the canvas, so it
    has to survive tokenising - splitting it would try to draw "<" and "3",
    neither of which exists.
    """
    tokens: "list[str]" = []
    i = 0
    upper = text.upper()
    while i < len(upper):
        if upper[i : i + 2] == "<3":
            tokens.append("<3")
            i += 2
        else:
            tokens.append(upper[i])
            i += 1
    return tokens


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

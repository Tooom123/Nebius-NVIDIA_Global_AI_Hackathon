"""A tiny native text-input dialog, used by the "Demander à Hey Peer..." tray
menu item so instructions can be typed directly without a mic/wake-word or a
console — useful for debugging and for the demo.
"""


def ask_instruction() -> str | None:
    """Blocks with a native dialog; returns the typed text, or None if the
    user cancelled or left it empty."""
    import tkinter as tk
    from tkinter import simpledialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        text = simpledialog.askstring("Hey Peer", "Que veux-tu faire ?", parent=root)
    finally:
        root.destroy()
    return text if text else None

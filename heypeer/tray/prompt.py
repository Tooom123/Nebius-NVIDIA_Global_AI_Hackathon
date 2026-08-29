"""A tiny native text-input dialog, used by the "Demander à Hey Peer..." tray
menu item so instructions can be typed directly without a mic/wake-word or a
console — useful for debugging and for the demo.

Must be called from its own dedicated thread, never from inside a tray
callback: on Windows, tray menu callbacks run inside the native
message-dispatch callback, and creating/running a Tk modal from there was
observed to come up broken (`grab failed`, unable to type, wouldn't close).
`TrayApp._prompt` already takes care of this — don't call `ask_instruction`
directly from a menu handler.
"""


def ask_instruction() -> str | None:
    """Blocks with a native dialog; returns the typed text, or None if the
    user cancelled or left it empty."""
    import tkinter as tk
    from tkinter import simpledialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.lift()
    root.after(0, lambda: (root.focus_force(), root.attributes("-topmost", False)))
    try:
        text = simpledialog.askstring("Hey Peer", "Que veux-tu faire ?", parent=root)
    finally:
        root.destroy()
    return text if text else None

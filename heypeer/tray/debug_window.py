"""A small always-on-top window logging Hey Peer's interactions live (wake
word detected, instruction heard, intent resolved, confirmation, result) --
built so debugging doesn't require squinting at console output interleaved
with the wake-word debug dB meter's carriage-return-redrawn line.

Runs its own dedicated Tk mainloop in a background thread; other threads
push lines through a thread-safe queue and the Tk loop polls it periodically
via `root.after(...)` -- Tkinter widgets must only ever be touched from the
thread running their mainloop.
"""

import queue
import threading


class DebugWindow:
    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def log(self, message: str) -> None:
        self._queue.put(message)

    def _run(self) -> None:
        import tkinter as tk

        root = tk.Tk()
        root.title("Hey Peer - debug")
        root.attributes("-topmost", True)
        root.geometry("460x320+40+40")
        root.configure(bg="white")

        text = tk.Text(root, wrap="word", state="disabled", bg="white", fg="black", bd=0)
        text.pack(fill="both", expand=True, padx=8, pady=8)

        def poll() -> None:
            try:
                while True:
                    line = self._queue.get_nowait()
                    text.configure(state="normal")
                    text.insert("end", line + "\n")
                    text.see("end")
                    text.configure(state="disabled")
            except queue.Empty:
                pass
            root.after(150, poll)

        self._ready.set()
        root.after(150, poll)
        root.mainloop()

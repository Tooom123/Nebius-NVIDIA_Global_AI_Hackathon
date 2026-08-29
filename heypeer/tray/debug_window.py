"""A small always-on-top window showing Hey Peer's conversation live:
a circle that pulses with mic input while recording (a simplified take on
"voice mode" style UIs — no shader/glow effects, just a Tk Canvas oval whose
radius and color react to state and audio level) above a scrolling
transcript of the interaction (wake word detected, instruction heard,
resolved intent, confirmation, result).

Runs its own dedicated Tk mainloop in a background thread; other threads
push updates through thread-safe queues that the Tk loop polls periodically
via `root.after(...)` — Tkinter widgets must only ever be touched from the
thread running their mainloop.
"""

import math
import queue
import threading
import time

# (fill color, base radius, "breathes" on its own without live audio level)
STATE_STYLE = {
    "idle": ("#bdbdbd", 20, False),
    "listening": ("#4a90d9", 24, True),
    "recording": ("#2ecc71", 24, False),  # radius driven by live level instead
    "thinking": ("#f39c12", 26, True),
    "speaking": ("#9b59b6", 28, True),
}
MAX_LEVEL_RADIUS_BOOST = 34
POLL_MS = 50


class DebugWindow:
    def __init__(self) -> None:
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._level = 0.0
        self._state = "idle"
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def log(self, message: str) -> None:
        self._log_queue.put(message)

    def set_level(self, level: float) -> None:
        with self._lock:
            self._level = max(0.0, min(1.0, level))

    def set_state(self, state: str) -> None:
        with self._lock:
            self._state = state if state in STATE_STYLE else "idle"

    def _run(self) -> None:
        import tkinter as tk

        root = tk.Tk()
        root.title("Hey Peer")
        root.attributes("-topmost", True)
        root.geometry("420x420+40+40")
        root.configure(bg="white")

        canvas_size = 160
        canvas = tk.Canvas(root, width=canvas_size, height=canvas_size, bg="white", highlightthickness=0)
        canvas.pack(pady=(12, 4))
        cx = cy = canvas_size / 2
        circle = canvas.create_oval(cx - 20, cy - 20, cx + 20, cy + 20, fill="#bdbdbd", outline="")

        text = tk.Text(root, wrap="word", state="disabled", bg="white", fg="black", bd=0)
        text.pack(fill="both", expand=True, padx=8, pady=8)

        current_radius = 20.0

        def poll() -> None:
            nonlocal current_radius
            try:
                while True:
                    line = self._log_queue.get_nowait()
                    text.configure(state="normal")
                    text.insert("end", line + "\n")
                    text.see("end")
                    text.configure(state="disabled")
            except queue.Empty:
                pass

            with self._lock:
                state, level = self._state, self._level
            color, base_radius, breathes = STATE_STYLE[state]
            if state == "recording":
                target_radius = base_radius + level * MAX_LEVEL_RADIUS_BOOST
            elif breathes:
                # A gentle idle pulse so "listening"/"thinking"/"speaking"
                # read as alive even without a live audio level to react to.
                target_radius = base_radius + 4 * math.sin(time.time() * 3)
            else:
                target_radius = base_radius
            # Smooth toward the target instead of jumping, so it reads as a
            # pulse rather than a flicker.
            current_radius += (target_radius - current_radius) * 0.3
            canvas.coords(
                circle,
                cx - current_radius,
                cy - current_radius,
                cx + current_radius,
                cy + current_radius,
            )
            canvas.itemconfigure(circle, fill=color)

            root.after(POLL_MS, poll)

        self._ready.set()
        root.after(POLL_MS, poll)
        root.mainloop()

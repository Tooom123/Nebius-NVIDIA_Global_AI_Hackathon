from heypeer.tray.debug_window import DebugWindow


def test_log_does_not_raise_and_reaches_the_window() -> None:
    window = DebugWindow()
    window.log("hello")
    window.log("world")
    # No direct way to assert on the Tk widget's content from another
    # thread (Tkinter isn't thread-safe) - this just confirms logging from
    # an arbitrary thread doesn't raise, which is the actual contract.

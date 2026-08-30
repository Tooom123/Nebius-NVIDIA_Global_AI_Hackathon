"""Guards what `heypeer.main` drags in when it is merely imported.

This exists because a single innocuous-looking top-level import - one
constant from `heypeer.wakeword.listener` - segfaulted the app. That module
pulls onnxruntime and openwakeword, and `heypeer.main` is re-imported inside
the overlay's child process by multiprocessing's spawn, so the native
runtimes were being loaded twice in two processes alongside PortAudio and
GDI. It also added 0.6s to every startup.

Import weight is invisible in review and only shows up as a crash or a slow
launch on someone else's machine, so it is asserted rather than remembered.
"""

import subprocess
import sys

# Heavy native runtimes that must stay out of the startup path. Each is
# loaded on demand: the wake-word models when voice actually starts, the
# rest inside the code paths that need them.
FORBIDDEN_AT_IMPORT = ("onnxruntime", "openwakeword", "faster_whisper", "piper")


def _modules_after_importing(module: str) -> set:
    """Imports `module` in a clean interpreter and reports what got loaded.

    A subprocess, not an import here: pytest has already imported most of
    the project by the time this runs, so checking `sys.modules` in-process
    would prove nothing.
    """
    code = f"import sys, {module}; print('\\n'.join(sorted(sys.modules)))"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return set(result.stdout.split())


def test_importing_main_does_not_load_native_runtimes() -> None:
    loaded = _modules_after_importing("heypeer.main")

    offenders = [name for name in FORBIDDEN_AT_IMPORT if name in loaded]
    assert offenders == [], (
        f"{offenders} loaded just by importing heypeer.main. Import them inside "
        "the functions that use them - see this module's docstring."
    )


def test_importing_the_overlay_does_not_load_native_runtimes() -> None:
    """The overlay runs in a spawned child, which re-imports this module.
    Anything heavy here is paid for a second time, in a second process."""
    loaded = _modules_after_importing("heypeer.tray.debug_window")

    offenders = [name for name in (*FORBIDDEN_AT_IMPORT, "numpy") if name in loaded]
    assert offenders == [], f"{offenders} loaded just by importing the overlay module"

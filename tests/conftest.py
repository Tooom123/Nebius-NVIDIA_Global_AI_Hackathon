"""Shared test fixtures.

The overlay windows (`caption_window`, `countdown_window`) each start a real
`multiprocessing.Process` on construction. In a test run that is pure cost
and a source of flakiness: dozens of forked processes doing nothing, plus a
DeprecationWarning per fork about forking a multi-threaded parent. Nothing
in the suite asserts on a real window - there is no display here - so they
are stubbed out globally rather than patched test by test, where the next
test to speak would silently start forking again.
"""

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _no_real_overlay_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replaces the overlay window classes with mocks for every test."""
    import heypeer.tray.caption_window as caption_window
    import heypeer.tray.countdown_window as countdown_window

    monkeypatch.setattr(caption_window, "CaptionWindow", MagicMock())
    monkeypatch.setattr(countdown_window, "CountdownWindow", MagicMock())


def _fake_piper(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stubs everything `tts.speak()` touches below the routing logic:
    voice loading, synthesis and playback.

    Lives here rather than in one test module because two of them need it -
    `test_tts.py` for the Piper path and `test_kokoro_tts.py` for asserting
    which engine a language actually reaches. `tests` is not an importable
    package, so sharing it any other way does not work.
    """
    import importlib
    import sys
    import types

    from heypeer.tray import tts

    monkeypatch.setattr(tts, "_ensure_voice_downloaded", lambda name: f"/fake/{name}.onnx")
    fake_voice = MagicMock()

    def fake_synthesize_wav(text, wav_file, syn_config):
        # A minimal, valid wav so the rest of speak() (which reads it back
        # to trim silence) has something real to work with.
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes((0).to_bytes(2, "little") * 100)

    fake_voice.synthesize_wav.side_effect = fake_synthesize_wav
    fake_piper_voice_cls = MagicMock(load=MagicMock(return_value=fake_voice))
    fake_module = types.ModuleType("piper")
    fake_module.PiperVoice = fake_piper_voice_cls
    # Carry the real submodules across. Replacing `piper` wholesale used to
    # be harmless because speak() imported piper.config before the stub was
    # installed; now that English can return early through Kokoro, the
    # French path imports it afterwards and got "piper is not a package".
    for name in ("config", "download_voices"):
        real = sys.modules.get(f"piper.{name}")
        if real is None:
            try:
                real = importlib.import_module(f"piper.{name}")
            except ImportError:
                continue
        setattr(fake_module, name, real)
        monkeypatch.setitem(sys.modules, f"piper.{name}", real)
    monkeypatch.setitem(sys.modules, "piper", fake_module)
    monkeypatch.setattr("heypeer.tray.audio_out.play", MagicMock())
    return fake_voice


@pytest.fixture
def fake_piper(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """`_fake_piper` as a fixture, for tests that just want it applied."""
    return _fake_piper(monkeypatch)

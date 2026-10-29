# PyInstaller build spec - `pyinstaller heypeer.spec` on Windows.
#
# Produces dist/HeyPeer.exe, so a demo machine needs neither a git clone nor
# pip install. Written as a .spec rather than a long command line because
# the hidden imports and data files below are the whole difficulty, and a
# command nobody can read is a command nobody can fix.
#
# ## What has to be told to PyInstaller, and why
#
# Its static analysis follows `import` statements. Three things here are
# invisible to that:
#
# * onnxruntime, openwakeword and faster-whisper load native libraries and
#   model files at runtime by path, not by import.
# * piper's voice loading and pystray's Windows backend are selected
#   dynamically, so the modules that actually get used are never named in
#   any import statement.
# * This project imports several executor modules *inside* functions (a
#   deliberate startup-time optimisation - see main.py), which PyInstaller
#   does still find, but the optional pyaudiowpatch is genuinely absent on
#   the build machine unless installed, and must not be a hard failure.
#
# ## What is bundled and what is not
#
# Bundled: the activation chime, and the app's own code. That is all the
# read-only data this app ships with.
#
# Bundled too: the generic wake-word model, trained on synthetic speech, so
# that "Hey Peer" works on a fresh machine before anyone records a voice.
#
# NOT bundled, on purpose: a personalised wake-word model and the Piper
# voices. A personalised model is trained *on the user's own voice* (see
# `wakeword/train.py`) - shipping one trained on someone else's voice would
# be worse than shipping the generic one. The Piper voices are large and
# downloaded on first use. Both live under `heypeer.paths.data_root()`, which
# in a frozen build resolves to %LOCALAPPDATA%\HeyPeer rather than the
# temporary unpack directory - see that module for why the distinction
# matters.

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

hidden = [
    "onnxruntime",
    "onnxruntime.capi._pybind_state",
    "openwakeword",
    "openwakeword.utils",
    "faster_whisper",
    "piper",
    "piper.config",
    "pystray._win32",
    "PIL._tkinter_finder",
]

datas = [
    ("heypeer/assets/activation_chime.wav", "heypeer/assets"),
    ("data/wakeword/hey_peer.onnx", "data/wakeword"),
]
# openWakeWord ships melspectrogram/embedding ONNX models inside the
# package; without these the listener cannot featurise audio at all.
datas += collect_data_files("openwakeword")

binaries = collect_dynamic_libs("onnxruntime")

a = Analysis(
    ["heypeer/main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # Excluded to keep the build from ballooning: these are development and
    # training-time dependencies that the shipped app never touches. Not
    # tkinter: the tray's "Demander a Hey Peer..." dialog and the first-run
    # colour picker are both tkinter.
    excludes=["matplotlib", "pytest", "sklearn", "skl2onnx", "scipy"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="HeyPeer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-compressed onnxruntime DLLs have been known to fail to load
    runtime_tmpdir=None,
    # The tray app has no console. Pass --cli at runtime for the console
    # loop; on a windowed build that opens its own console window.
    console=False,
    disable_windowed_traceback=False,
    icon=None,
)

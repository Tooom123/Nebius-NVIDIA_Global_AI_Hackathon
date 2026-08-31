"""Tests for launching applications by name.

The interesting property here is not that the right app starts - it is that a
name Hey Peer does not recognise never reaches the OS. Everything on this path
originates in a speech transcript that then passed through a language model,
so "run whatever it said" would be handing a model's output to the shell.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from heypeer.executor.apps import KNOWN_APPS, App, LaunchFailed, is_running, launch, resolve_app


def test_an_exact_name_resolves() -> None:
    assert resolve_app("Spotify").name == "Spotify"


def test_an_alias_resolves() -> None:
    assert resolve_app("le navigateur").name == "Chrome"
    assert resolve_app("calculette").name == "Calculatrice"


def test_resolution_ignores_case_and_accents() -> None:
    """The name arrives from a transcript and then from a model; neither
    guarantees the case or the accents of anything. "spotifaï" in particular
    is what the pronunciation layer calls it."""
    assert resolve_app("SPOTIFY").name == "Spotify"
    assert resolve_app("spotifaï").name == "Spotify"


def test_a_near_miss_still_resolves() -> None:
    assert resolve_app("spotifi").name == "Spotify"


def test_an_unknown_name_is_refused_rather_than_guessed_at() -> None:
    """The whole point of the registry. Declining costs one turn; the
    alternative is starting a process named by a language model."""
    assert resolve_app("Machin") is None
    assert resolve_app("rm -rf /") is None
    assert resolve_app("") is None
    assert resolve_app("   ") is None


def test_no_alias_is_claimed_by_two_apps() -> None:
    """An alias that resolves to the wrong app is silent - it launches
    something plausible - so it has to be caught here rather than in use."""
    seen: dict = {}
    for app in KNOWN_APPS:
        for key in (app.name, *app.aliases):
            assert key.lower() not in seen, f"{key!r} claimed by {seen.get(key.lower())} and {app.name}"
            seen[key.lower()] = app.name


def test_a_uri_scheme_is_preferred_over_the_executable() -> None:
    """A URI lets the OS resolve whichever build the user installed - Store
    app or desktop - where an executable name only finds one of them."""
    with patch("heypeer.executor.apps._open_target") as open_target:
        launch(App(name="X", uri_scheme="x:", executable="x.exe"))

    open_target.assert_called_once_with("x:")


def test_the_executable_is_tried_when_the_uri_fails() -> None:
    """An app that registered no handler still has an executable; failing at
    the first attempt must not end the launch.

    `shutil.which` is mocked to resolve "x.exe" to a real-looking path,
    matching how `launch` actually finds an executable now (a resolved
    path via `_executable_candidates`, not the bare name handed straight to
    `_open_target` - see round 33: that bare-name form is not reliable
    through `os.startfile`, which is not documented to search PATH for an
    extensionless name the way `subprocess` is)."""
    with (
        patch("heypeer.executor.apps._open_target", side_effect=[OSError("no handler"), None]) as o,
        patch("shutil.which", return_value=r"C:\Program Files\X\x.exe"),
    ):
        launch(App(name="X", uri_scheme="x:", executable="x.exe"))

    assert [c.args[0] for c in o.call_args_list] == ["x:", r"C:\Program Files\X\x.exe"]


def test_an_app_that_will_not_start_raises_rather_than_pretending() -> None:
    """The caller turns this into a spoken "je n'ai pas reussi". Silently
    succeeding would have Hey Peer announce it opened something it did not."""
    with patch("heypeer.executor.apps._open_target", side_effect=OSError("nope")):
        with pytest.raises(LaunchFailed):
            launch(App(name="X", executable="x.exe"))


def test_every_registered_app_has_some_way_to_start() -> None:
    for app in KNOWN_APPS:
        assert app.uri_scheme or app.executable, f"{app.name} has no launch route"


# --- is_running -----------------------------------------------------------
#
# Whether an app is already open, used to decide whether starting a track
# needs a follow-up press-play. Windows-only by construction; a wrong answer
# elsewhere costs one harmless extra step, never a missing one.


def test_is_running_is_false_off_windows() -> None:
    """The dev sandbox for this project is Linux; the only caller
    (spotify.play_track) must degrade to its safe default there rather than
    calling a Windows-only tool."""
    with patch("sys.platform", "linux"):
        assert is_running("Spotify.exe") is False


def test_is_running_true_when_tasklist_lists_the_process() -> None:
    output = (
        "Image Name                     PID Session Name        Session#\r\n"
        "Spotify.exe                  12345 Console                 1\r\n"
    )
    with patch("sys.platform", "win32"), patch("subprocess.check_output", return_value=output):
        assert is_running("Spotify.exe") is True


def test_is_running_false_when_tasklist_finds_nothing() -> None:
    """tasklist with a /FI filter that matches nothing still exits 0 and
    prints an "INFO: No tasks..." line - there is no process row to find."""
    output = 'INFO: No tasks are running which match the specified criteria.\r\n'
    with patch("sys.platform", "win32"), patch("subprocess.check_output", return_value=output):
        assert is_running("Spotify.exe") is False


def test_is_running_false_when_tasklist_itself_fails() -> None:
    """Must degrade rather than raise: this runs before every track playback,
    and a shell quirk on the user's machine must not block music over it."""
    with patch("sys.platform", "win32"), patch("subprocess.check_output", side_effect=OSError("no")):
        assert is_running("Spotify.exe") is False


# --- Start Menu shortcut search (round 33) ---------------------------------
#
# "ouvre discord" was reported not working. Root cause, reasoned rather than
# observed (no real Windows box here): Discord installs to a per-user,
# versioned folder under %LOCALAPPDATA% that is never on PATH, its real
# launcher (Update.exe) needs a command-line argument os.startfile cannot
# pass, and its discord: URI scheme (kept as a free first attempt) is not a
# documented, verified one the way Spotify's and Steam's are. The Start Menu
# shortcut - which every installer, Squirrel included, creates specifically
# so the shell can find the app - is the mechanism that actually works.


@pytest.fixture
def start_menu(tmp_path: Path) -> Path:
    (tmp_path / "Discord.lnk").write_text("")
    (tmp_path / "Steam.lnk").write_text("")
    (tmp_path / "VLC media player.lnk").write_text("")
    nested = tmp_path / "Microsoft Office Tools"
    nested.mkdir()
    (nested / "Word.lnk").write_text("")
    return tmp_path


def test_finds_a_shortcut_by_exact_name(start_menu: Path) -> None:
    from heypeer.executor.apps import _find_start_menu_shortcut

    found = _find_start_menu_shortcut(App(name="Discord", aliases=("discorde",)), roots=(str(start_menu),))

    assert found == start_menu / "Discord.lnk"


def test_finds_a_shortcut_by_alias(start_menu: Path) -> None:
    from heypeer.executor.apps import _find_start_menu_shortcut

    found = _find_start_menu_shortcut(
        App(name="VLC", aliases=("vlc media player",)), roots=(str(start_menu),)
    )

    assert found == start_menu / "VLC media player.lnk"


def test_finds_a_shortcut_nested_in_a_publisher_subfolder(start_menu: Path) -> None:
    """"Word.lnk" sits under "Microsoft Office Tools", not directly under
    Programs - a non-recursive search would miss it."""
    from heypeer.executor.apps import _find_start_menu_shortcut

    found = _find_start_menu_shortcut(
        App(name="Word", aliases=("microsoft word",)), roots=(str(start_menu),)
    )

    assert found == start_menu / "Microsoft Office Tools" / "Word.lnk"


def test_declines_rather_than_guessing_at_an_unrelated_shortcut(start_menu: Path) -> None:
    from heypeer.executor.apps import _find_start_menu_shortcut

    assert _find_start_menu_shortcut(App(name="Machin"), roots=(str(start_menu),)) is None


def test_a_missing_start_menu_root_does_not_raise(tmp_path: Path) -> None:
    from heypeer.executor.apps import _find_start_menu_shortcut

    missing = tmp_path / "does_not_exist"
    assert _find_start_menu_shortcut(App(name="Discord"), roots=(str(missing),)) is None


def test_launch_tries_the_shortcut_between_the_uri_and_the_executable() -> None:
    """The actual fix, end to end: a URI failure falls through to the
    shortcut, not straight to a bare/unresolved executable name."""
    order: list = []
    with (
        patch("sys.platform", "win32"),
        patch("shutil.which", return_value=None),  # Discord is never really on PATH
        patch(
            "heypeer.executor.apps._find_start_menu_shortcut",
            return_value=Path(r"C:\Users\tom\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Discord.lnk"),
        ),
        patch(
            "heypeer.executor.apps._open_target",
            side_effect=lambda t: (order.append(t), (_ for _ in ()).throw(OSError("no handler")))[1]
            if t == "discord:"
            else order.append(t),
        ),
    ):
        launch(App(name="Discord", uri_scheme="discord:", executable="discord"))

    assert order == [
        "discord:",
        r"C:\Users\tom\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Discord.lnk",
    ]


def test_launch_never_searches_the_start_menu_off_windows() -> None:
    """The dev sandbox for this project is Linux; the search must not run
    (and must not raise) there."""
    with (
        patch("sys.platform", "linux"),
        patch("heypeer.executor.apps._find_start_menu_shortcut") as find_shortcut,
        patch("heypeer.executor.apps._open_target"),
    ):
        launch(App(name="Discord", uri_scheme="discord:"))

    find_shortcut.assert_not_called()


def test_discord_has_no_bare_update_exe_fallback() -> None:
    """Round 33's actual bug: os.startfile on a bare Update.exe path opens
    Squirrel's own updater UI, not Discord - `launch` "succeeding" at that
    would be worse than failing honestly. Confirms the fix stayed removed
    rather than only working around it for one test."""
    discord = next(app for app in KNOWN_APPS if app.name == "Discord")

    assert not any("update.exe" in p.lower() for p in discord.windows_paths)

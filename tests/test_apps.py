"""Tests for launching applications by name.

The interesting property here is not that the right app starts - it is that a
name Hey Peer does not recognise never reaches the OS. Everything on this path
originates in a speech transcript that then passed through a language model,
so "run whatever it said" would be handing a model's output to the shell.
"""

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
    the first attempt must not end the launch."""
    with patch("heypeer.executor.apps._open_target", side_effect=[OSError("no handler"), None]) as o:
        launch(App(name="X", uri_scheme="x:", executable="x.exe"))

    assert [c.args[0] for c in o.call_args_list] == ["x:", "x.exe"]


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

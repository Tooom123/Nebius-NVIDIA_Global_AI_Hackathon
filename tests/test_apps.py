"""Tests for launching applications by name.

The interesting property here is not that the right app starts - it is that a
name Hey Peer does not recognise never reaches the OS. Everything on this path
originates in a speech transcript that then passed through a language model,
so "run whatever it said" would be handing a model's output to the shell.
"""

from unittest.mock import patch

import pytest

from heypeer.executor.apps import KNOWN_APPS, App, LaunchFailed, launch, resolve_app


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

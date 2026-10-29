"""Which screen the overlays go on - see `tray/overlay.stage_rect`."""

from heypeer.tray import overlay


def test_the_stage_screen_comes_from_the_environment(monkeypatch) -> None:
    """The demo's left screen sits at a negative x."""
    monkeypatch.setenv("HEYPEER_STAGE_SCREEN", "-1920,0,1920,1080")
    assert overlay.stage_rect() == (-1920, 0, 1920, 1080)


def test_a_malformed_setting_falls_back_to_the_primary_screen(monkeypatch) -> None:
    monkeypatch.setenv("HEYPEER_STAGE_SCREEN", "left")
    left, top, width, height = overlay.stage_rect()
    assert (left, top) == (0, 0) and width > 0 and height > 0

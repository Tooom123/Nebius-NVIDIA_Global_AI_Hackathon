"""The screen-edge glow - see `heypeer/tray/screen_glow_render.py`."""

import numpy as np

from heypeer.tray import screen_glow_render as glow


def _alpha(image):
    return np.asarray(image)[..., 3]


def test_the_middle_of_the_screen_is_untouched() -> None:
    """It sits over the user's work for as long as Hey Peer is up. Anything
    in the middle would be in the way, not ambient."""
    a = _alpha(glow.render(400, 300))
    assert a[150, 200] == 0


def test_all_four_edges_glow() -> None:
    """The whole point - iOS glows the perimeter, not one side."""
    a = _alpha(glow.render(400, 300))
    assert a[0, 200] > 0, "top"
    assert a[299, 200] > 0, "bottom"
    assert a[150, 0] > 0, "left"
    assert a[150, 399] > 0, "right"


def test_it_fades_inward_from_every_edge() -> None:
    a = _alpha(glow.render(400, 300))
    depth = glow.depth_for(400, 300)
    assert a[0, 200] > a[depth // 2, 200] > a[depth - 1, 200]


def test_the_corners_do_not_blot() -> None:
    """Two bands overlap there. Added rather than maximised, a corner would
    be twice as opaque as the edges and read as four bright spots."""
    a = _alpha(glow.render(400, 300))
    assert a[0, 0] <= a[0, 200] + 1


def test_the_hue_travels_with_the_phase() -> None:
    """Otherwise the border just pulses, rather than light circling it."""
    assert glow.render(200, 150, phase=0.0).tobytes() != glow.render(200, 150, phase=3.0).tobytes()


def test_intensity_scales_it_and_zero_is_invisible() -> None:
    """So it can fade in and out rather than appearing and vanishing."""
    assert _alpha(glow.render(200, 150, intensity=1.0)).max() > _alpha(
        glow.render(200, 150, intensity=0.4)
    ).max()
    assert _alpha(glow.render(200, 150, intensity=0.0)).max() == 0


def test_the_band_scales_with_the_screen_but_stays_bounded() -> None:
    """A fraction alone would be a hairline on a small display and a
    quarter of a large one."""
    assert glow.depth_for(3840, 2160) <= glow.MAX_DEPTH_PX
    assert glow.depth_for(320, 240) >= glow.MIN_DEPTH_PX
    assert glow.depth_for(1920, 1080) > glow.depth_for(800, 600)


def test_a_tiny_screen_does_not_produce_a_broken_frame() -> None:
    image = glow.render(40, 30)
    assert image.size == (40, 30)


def test_it_uses_the_same_palette_as_the_blob() -> None:
    """One system, not two: the border says Hey Peer is active and the blob
    says where it is."""
    import inspect

    assert "blob_render" in inspect.getsource(glow)

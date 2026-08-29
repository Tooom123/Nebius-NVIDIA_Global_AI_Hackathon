from heypeer.tray.icon_images import COLORS, make_icon_image


def test_icon_image_has_requested_size_and_mode() -> None:
    image = make_icon_image("listening", size=48)
    assert image.size == (48, 48)
    assert image.mode == "RGBA"


def test_icon_image_center_pixel_matches_status_color() -> None:
    for status, color in COLORS.items():
        image = make_icon_image(status, size=32)
        assert image.getpixel((16, 16)) == color


def test_unknown_status_falls_back_to_off_color() -> None:
    image = make_icon_image("does_not_exist", size=16)
    assert image.getpixel((8, 8)) == COLORS["off"]

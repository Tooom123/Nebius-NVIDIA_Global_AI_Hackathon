"""Generates the small colored-dot icons shown in the system tray, one per
Hey Peer status. Kept as pure PIL drawing (no I/O) so it's trivial to test.
"""

from PIL import Image, ImageDraw

# (R, G, B, A) per status name.
COLORS: dict[str, tuple[int, int, int, int]] = {
    "off": (128, 128, 128, 255),  # gris — mode auto désactivé
    "listening": (46, 204, 113, 255),  # vert — actif, à l'écoute
    "executing": (52, 152, 219, 255),  # bleu — exécution d'un skill en cours
    "error": (231, 76, 60, 255),  # rouge — erreur
}


def make_icon_image(status: str, size: int = 64) -> Image.Image:
    color = COLORS.get(status, COLORS["off"])
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = size // 8
    draw.ellipse([margin, margin, size - margin, size - margin], fill=color)
    return image

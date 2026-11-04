"""Draw OwlCheck's icons and installer images from one 16x16 sprite.

Run from the repo root: python packaging/make_icons.py (needs only Pillow).
Icons go to app/assets/, Inno Setup wizard images to packaging/installer/.

From 16 to 48 px the sprite is drawn at whole-number scales so it stays sharp.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ASSETS = Path(__file__).resolve().parent.parent / "app" / "assets"
INSTALLER = Path(__file__).resolve().parent / "installer"

# '#' is ink, '.' lets the background show through
OWL = [
    "................",
    ".#............#.",
    "..##........##..",
    "..############..",
    ".##...####...##.",
    ".#.....##.....#.",
    ".#..##.##.##..#.",
    ".#..##.##.##..#.",
    ".##...#..#...##.",
    ".######..######.",
    "..#.########.#..",
    "..#.########.#..",
    "..##.######.##..",
    "...##########...",
    ".....##..##.....",
    "################",
]
# No branch and no empty border, so the owl fills 16 and 32 px icons
OWL_TIGHT = [row[1:15] for row in OWL[1:15]]

INK = (22, 22, 26)
BG_TOP = (255, 255, 255)        # top left
BG_BOTTOM = (214, 218, 226)     # bottom right, cool gray
RADIUS = 0.225                  # corner radius as a fraction of the side


def _gradient(size):
    n = 256
    small = Image.new("RGB", (n, n))
    px = small.load()
    for y in range(n):
        for x in range(n):
            t = ((x + y) / (2 * (n - 1))) ** 1.6
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM))
    return small.resize((size, size), Image.BILINEAR)


def _rounded_mask(size):
    s = 4  # supersample so the curve comes out smooth
    m = Image.new("L", (size * s, size * s), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size * s - 1, size * s - 1), radius=round(size * s * RADIUS), fill=255)
    return m.resize((size, size), Image.LANCZOS)


def _layout(size):
    """Return (sprite, cell size, x offset, y offset) for an icon size."""
    if size <= 16:
        return OWL_TIGHT, 1, (size - 14) // 2, (size - 14) // 2
    if size <= 24:
        return OWL, 1, (size - 16) // 2, (size - 16) // 2
    if size <= 32:
        return OWL_TIGHT, 2, (size - 28) // 2, (size - 28) // 2
    if size <= 48:
        return OWL, 2, (size - 32) // 2, (size - 32) // 2
    cell = int(size * 0.62 / 16 + 0.6)
    off = (size - 16 * cell) // 2
    return OWL, cell, off, off + cell // 3


def tile(size):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    im.paste(_gradient(size), (0, 0), _rounded_mask(size))
    if size >= 64:  # faint outline so the tile doesn't vanish on light backgrounds
        s = 4
        ring = Image.new("L", (size * s, size * s), 0)
        ImageDraw.Draw(ring).rounded_rectangle((0, 0, size * s - 1, size * s - 1), radius=round(size * s * RADIUS),
                                               outline=255, width=max(s, round(size * s / 340)))
        ring = ring.resize((size, size), Image.LANCZOS).point(lambda v: v * 28 // 255)
        im.paste((0, 0, 0, 255), (0, 0), ring)
    rows, cell, ox, oy = _layout(size)
    d = ImageDraw.Draw(im)
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch == "#":
                x, y = ox + c * cell, oy + r * cell
                d.rectangle((x, y, x + cell - 1, y + cell - 1), fill=INK)
    return im


def mac_tile(size):
    """Apple's icon grid: the tile is 824 of 1024 px with a soft drop shadow."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inner = round(size * 824 / 1024)
    off = (size - inner) // 2
    if size >= 64:
        shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        shadow.paste((0, 0, 0, 70), (off, off + max(1, size // 100)), _rounded_mask(inner))
        canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(max(1, size / 90))))
    canvas.alpha_composite(tile(inner), (off, off))
    return canvas


def sprite(scale=8):
    """The bare owl on transparency, used as the mascot in the app UI."""
    im = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    for r, row in enumerate(OWL):
        for c, ch in enumerate(row):
            if ch == "#":
                im.putpixel((c, r), INK + (255,))
    return im.resize((16 * scale, 16 * scale), Image.NEAREST)


def write_ico(path, frames):
    """Write a classic .ico (BGRA bitmap plus AND mask per frame) instead of Pillow's.

    Pillow stores every frame as PNG. Explorer is fine with that, but .NET Framework's
    System.Drawing.Icon, which the app window uses on Windows, rejects PNG frames and the
    app crashes at startup with "Argument 'picture' must be a picture that can be used as a Icon".
    """
    import struct
    entries, blobs = [], []
    for im in frames:
        im = im.convert("RGBA")
        w, h = im.size
        px = im.load()
        rows = []
        for y in range(h - 1, -1, -1):  # DIB rows go bottom-up
            rows.append(b"".join(bytes((px[x, y][2], px[x, y][1], px[x, y][0], px[x, y][3])) for x in range(w)))
        mask_stride = ((w + 31) // 32) * 4  # 1-bit mask, rows padded to 4 bytes
        mask = bytearray()
        for y in range(h - 1, -1, -1):
            bits = bytearray(mask_stride)
            for x in range(w):
                if px[x, y][3] == 0:
                    bits[x // 8] |= 0x80 >> (x % 8)
            mask += bits
        header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, w * h * 4 + len(mask), 0, 0, 0, 0)
        blob = header + b"".join(rows) + bytes(mask)
        entries.append((w, h, len(blob)))
        blobs.append(blob)
    offset = 6 + 16 * len(frames)
    out = bytearray(struct.pack("<HHH", 0, 1, len(frames)))
    for (w, h, size) in entries:
        out += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32, size, offset)
        offset += size
    for blob in blobs:
        out += blob
    Path(path).write_bytes(bytes(out))


# Installer wizard images, in the app's ink-and-paper style

UI_INK, UI_PAPER, UI_MID, UI_DOT = (17, 17, 17), (242, 241, 236), (140, 139, 134), (46, 46, 50)


def _silk(size, bold=True):
    name = "silkscreen-latin-700-normal.woff2" if bold else "silkscreen-latin-400-normal.woff2"
    return ImageFont.truetype(str(ASSETS / "fonts" / name), size)


def _owl_sprite(cell, color):
    im = Image.new("RGBA", (16 * cell, 16 * cell), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for r, row in enumerate(OWL):
        for c, ch in enumerate(row):
            if ch == "#":
                d.rectangle((c * cell, r * cell, (c + 1) * cell - 1, (r + 1) * cell - 1), fill=color)
    return im


def wizard_large(width):
    """Side panel for the welcome and finish pages (Inno Setup's 164x314 ratio)."""
    u = width / 240
    W, H = width, round(width * 459 / 240)
    im = Image.new("RGB", (W, H), UI_INK)
    d = ImageDraw.Draw(im)
    dot, step = max(1, round(u)), max(4, round(11 * u))
    for y in range(step // 2, H, step):              # dot grid, like the app's home screen
        for x in range(step // 2, W, step):
            d.rectangle((x, y, x + dot - 1, y + dot - 1), fill=UI_DOT)
    m, L, t = round(14 * u), round(22 * u), max(2, round(4 * u))   # corner brackets
    for x, y, sx, sy in ((m, m, 1, 1), (W - m, m, -1, 1), (m, H - m, 1, -1), (W - m, H - m, -1, -1)):
        d.rectangle((min(x, x + sx * L), min(y, y + sy * t), max(x, x + sx * L), max(y, y + sy * t)), fill=UI_PAPER)
        d.rectangle((min(x, x + sx * t), min(y, y + sy * L), max(x, x + sx * t), max(y, y + sy * L)), fill=UI_PAPER)
    owl = _owl_sprite(max(2, round(8 * u)), UI_PAPER)
    im.paste(owl, ((W - owl.width) // 2, round(118 * u)), owl)

    def centered(y, text, font, fill):
        d.text(((W - d.textlength(text, font=font)) / 2, round(y * u)), text, font=font, fill=fill)
    centered(268, "OWLCHECK", _silk(round(26 * u)), UI_PAPER)
    centered(302, "PRE-RELEASE CHECKER", _silk(max(7, round(9 * u)), bold=False), UI_MID)
    centered(410, "OWLGORITHM RESEARCH", _silk(max(7, round(8 * u)), bold=False), UI_MID)
    return im


def wizard_small(size):
    """Top-right square on the inner wizard pages."""
    im = Image.new("RGB", (size, size), UI_PAPER)
    owl = _owl_sprite(max(1, size * 3 // 55), UI_INK)
    im.paste(owl, ((size - owl.width) // 2, (size - owl.height) // 2), owl)
    return im


def installer_images():
    INSTALLER.mkdir(exist_ok=True)
    for pct, w in ((100, 164), (150, 246), (200, 328)):
        wizard_large(w).save(INSTALLER / f"wizard-large-{pct}.bmp")
    for pct, s in ((100, 55), (150, 83), (200, 110)):
        wizard_small(s).save(INSTALLER / f"wizard-small-{pct}.bmp")


def main():
    ico_sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [tile(s) for s in ico_sizes]
    write_ico(ASSETS / "icon.ico", frames)
    icns = [mac_tile(s) for s in (16, 32, 64, 128, 256, 512, 1024)]
    icns[-1].save(ASSETS / "icon.icns", append_images=icns[:-1])
    tile(512).save(ASSETS / "icon.png")
    sprite().save(ASSETS / "owl.png")
    installer_images()
    print("Icons written to", ASSETS, "and installer images to", INSTALLER)


if __name__ == "__main__":
    main()

"""A pixel canvas using the vendored Pixoo bitmap fonts.

Drawing primitives (draw_pixel/draw_character/draw_text/draw_image/
draw_filled_rectangle/draw_line) are adapted from gickowtf/pixoo-homeassistant
(MIT) so that a screen config renders identically to the Pixoo. The canvas is
normally 64x64 (Pixoo-native) and scaled up to the Times Gate's 128 with
nearest-neighbour, keeping pixel art crisp.
"""
from __future__ import annotations

from PIL import Image

from .vendor_pixoo._font import (
    CLOCK,
    ELEVEN_PIX,
    FIVE_PIX,
    FONT_GICKO,
    FONT_PICO_8,
    PIX24,
    retrieve_glyph,
    retrieve_glyph_width,
)

FONTS = {
    "pico_8": FONT_PICO_8,
    "gicko": FONT_GICKO,
    "five_pix": FIVE_PIX,
    "eleven_pix": ELEVEN_PIX,
    "clock": CLOCK,
    "pix24": PIX24,
}


def font_by_name(name: str | None):
    return FONTS.get((name or "").lower(), FONT_PICO_8)


class PixelCanvas:
    """A small RGB pixel buffer with Pixoo-compatible drawing."""

    def __init__(self, size: int = 64) -> None:
        self.size = size
        self._img = Image.new("RGB", (size, size), (0, 0, 0))
        self._px = self._img.load()

    def draw_pixel(self, xy: tuple[int, int], rgb) -> None:
        x, y = int(xy[0]), int(xy[1])
        if 0 <= x < self.size and 0 <= y < self.size:
            self._px[x, y] = (int(rgb[0]), int(rgb[1]), int(rgb[2]))

    def draw_character(self, character: str, xy, rgb, font) -> None:
        matrix = retrieve_glyph(character, font)
        if matrix is None:
            return
        x_size = matrix[-1]
        for index, bit in enumerate(matrix):
            if bit == 1 and index != len(matrix) - 1:
                local_x = index % x_size
                local_y = index // x_size
                self.draw_pixel((xy[0] + local_x, xy[1] + local_y), rgb)

    def get_text_width(self, text: str, font) -> int:
        length = 0
        for character in text:
            length += retrieve_glyph_width(character, font) + 1
        return length - 1

    def draw_text(self, text: str, xy, rgb, font, align: str = "left") -> None:
        y_offset = 0
        for line in text.split("\n"):
            if align == "center":
                x_offset = int(self.get_text_width(line, font) / 2) * -1
            elif align == "right":
                x_offset = self.get_text_width(line, font) * -1
            else:
                x_offset = 0
            for character in line:
                if retrieve_glyph(character, font) is None:
                    character = "?"
                self.draw_character(character, (x_offset + xy[0], y_offset + xy[1]), rgb, font)
                x_offset += retrieve_glyph(character, font)[-1] + 1
            dummy = retrieve_glyph("0", font)
            height = int((len(dummy) - 1) / dummy[-1])
            y_offset += height + 1

    def draw_filled_rectangle(self, top_left, bottom_right, rgb) -> None:
        for y in range(int(top_left[1]), int(bottom_right[1]) + 1):
            for x in range(int(top_left[0]), int(bottom_right[0]) + 1):
                self.draw_pixel((x, y), rgb)

    def draw_line(self, start, stop, rgb) -> None:
        x0, y0 = int(start[0]), int(start[1])
        x1, y1 = int(stop[0]), int(stop[1])
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        while True:
            self.draw_pixel((x0, y0), rgb)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def draw_image(self, img: Image.Image, xy) -> None:
        rgba = img.convert("RGBA")
        for y in range(rgba.size[1]):
            for x in range(rgba.size[0]):
                pixel = rgba.getpixel((x, y))
                if pixel[3] != 0:
                    self.draw_pixel((xy[0] + x, xy[1] + y), pixel[:3])

    def to_image(self, target_size: int) -> Image.Image:
        if target_size == self.size:
            return self._img
        return self._img.resize((target_size, target_size), Image.NEAREST)

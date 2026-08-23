"""A pixel canvas using the vendored Pixoo bitmap fonts.

Drawing primitives (draw_pixel/draw_character/draw_text/draw_image/
draw_filled_rectangle/draw_line) are adapted from gickowtf/pixoo-homeassistant
(MIT) so that a screen config renders identically to the Pixoo. The canvas is
normally 64x64 (Pixoo-native) and scaled up to the Times Gate's 128 with
nearest-neighbour, keeping pixel art crisp.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from PIL import Image, ImageFont, _imaging

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

# A vendored bitmap font maps a character to a flat list of on/off bits with the
# glyph width appended as the final element.
type GlyphFont = dict[str, list[int]]

# Coordinates and colours arrive from JSON page configs, so they may be lists as
# well as tuples. Accept any integer sequence rather than forcing a runtime shape.
type Point = Sequence[int]
type Rgb = Sequence[int]

# A cached font is whichever concrete class Pillow hands back: load_default()
# returns a bitmap ImageFont on old Pillow and a FreeTypeFont on current ones.
type LoadedFont = ImageFont.FreeTypeFont | ImageFont.ImageFont

FONTS: dict[str, GlyphFont] = {
    "pico_8": FONT_PICO_8,
    "gicko": FONT_GICKO,
    "five_pix": FIVE_PIX,
    "eleven_pix": ELEVEN_PIX,
    "clock": CLOCK,
    "pix24": PIX24,
}


def font_by_name(name: str | None) -> GlyphFont:
    font: GlyphFont = FONTS.get((name or "").lower(), FONT_PICO_8)
    return font


_SCALABLE_CACHE: dict[int, LoadedFont] = {}


def _scalable_font(size: int) -> LoadedFont:
    """A scalable TrueType font at the given pixel size (for native-128 screens)."""
    if size not in _SCALABLE_CACHE:
        try:
            _SCALABLE_CACHE[size] = ImageFont.load_default(size)
        except TypeError:  # very old Pillow without size arg
            _SCALABLE_CACHE[size] = ImageFont.load_default()
    return _SCALABLE_CACHE[size]


class PixelCanvas:
    """A small RGB pixel buffer with Pixoo-compatible drawing."""

    def __init__(self, size: int = 64) -> None:
        self.size = size
        self._img = Image.new("RGB", (size, size), (0, 0, 0))
        # load() is typed Optional for images that fail to decode; a freshly
        # allocated buffer always has pixel access.
        self._px = cast("_imaging.PixelAccess", self._img.load())

    def draw_pixel(self, xy: Point, rgb: Rgb) -> None:
        x, y = int(xy[0]), int(xy[1])
        if 0 <= x < self.size and 0 <= y < self.size:
            self._px[x, y] = (int(rgb[0]), int(rgb[1]), int(rgb[2]))

    def draw_character(self, character: str, xy: Point, rgb: Rgb, font: GlyphFont) -> None:
        matrix = retrieve_glyph(character, font)
        if matrix is None:
            return
        x_size = matrix[-1]
        for index, bit in enumerate(matrix):
            if bit == 1 and index != len(matrix) - 1:
                local_x = index % x_size
                local_y = index // x_size
                self.draw_pixel((xy[0] + local_x, xy[1] + local_y), rgb)

    def get_text_width(self, text: str, font: GlyphFont) -> int:
        length = 0
        for character in text:
            length += retrieve_glyph_width(character, font) + 1
        return length - 1

    def draw_text(
        self, text: str, xy: Point, rgb: Rgb, font: GlyphFont, align: str = "left"
    ) -> None:
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

    def draw_filled_rectangle(self, top_left: Point, bottom_right: Point, rgb: Rgb) -> None:
        for y in range(int(top_left[1]), int(bottom_right[1]) + 1):
            for x in range(int(top_left[0]), int(bottom_right[0]) + 1):
                self.draw_pixel((x, y), rgb)

    def draw_line(self, start: Point, stop: Point, rgb: Rgb) -> None:
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

    def draw_image(self, img: Image.Image, xy: Point) -> None:
        rgba = img.convert("RGBA")
        for y in range(rgba.size[1]):
            for x in range(rgba.size[0]):
                # An RGBA image always yields a 4-tuple per pixel.
                pixel = cast("tuple[int, int, int, int]", rgba.getpixel((x, y)))
                if pixel[3] != 0:
                    self.draw_pixel((xy[0] + x, xy[1] + y), pixel[:3])

    def to_image(self, target_size: int) -> Image.Image:
        if target_size == self.size:
            return self._img
        return self._img.resize((target_size, target_size), Image.Resampling.NEAREST)

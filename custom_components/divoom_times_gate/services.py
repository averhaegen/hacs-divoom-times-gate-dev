"""Services for Divoom Times Gate: set_clock_face, show_message."""
from __future__ import annotations

from io import BytesIO

import voluptuous as vol
from PIL import Image, ImageDraw

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN, SCREEN_COUNT, SCREEN_SIZE
from .canvas import _scalable_font  # reuse the scalable font loader

SERVICE_SET_CLOCK_FACE = "set_clock_face"
SERVICE_SHOW_MESSAGE = "show_message"

_SCREEN = vol.All(vol.Coerce(int), vol.Range(min=0, max=SCREEN_COUNT - 1))

_SET_CLOCK_FACE_SCHEMA = vol.Schema(
    {
        vol.Required("screen"): _SCREEN,
        vol.Required("clock_id"): vol.Coerce(int),
    }
)
_SHOW_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required("screen"): _SCREEN,
        vol.Required("text"): cv.string,
        vol.Optional("duration", default=10): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("color", default="#FFFFFF"): cv.string,
    }
)


def _coordinators(hass: HomeAssistant):
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.runtime_data is not None:
            yield entry.runtime_data


def _render_message(text: str, color_hex: str) -> bytes:
    img = Image.new("RGB", (SCREEN_SIZE, SCREEN_SIZE), (0, 0, 0))
    d = ImageDraw.Draw(img)
    try:
        fill = (int(color_hex[1:3], 16), int(color_hex[3:5], 16), int(color_hex[5:7], 16))
    except (ValueError, IndexError):
        fill = (255, 255, 255)
    # auto-shrink to fit width
    size = 30
    font = _scalable_font(size)
    while size > 8 and d.textbbox((0, 0), text, font=font)[2] > SCREEN_SIZE - 8:
        size -= 2
        font = _scalable_font(size)
    bbox = d.textbbox((0, 0), text, font=font)
    d.text(((SCREEN_SIZE - (bbox[2] - bbox[0])) / 2, 52), text, font=font, fill=fill)
    buf = BytesIO()
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_CLOCK_FACE):
        return

    async def _set_clock_face(call: ServiceCall) -> None:
        screen = call.data["screen"]
        clock_id = call.data["clock_id"]
        for coord in _coordinators(hass):
            await coord.device.set_clock_face(screen, clock_id)

    async def _show_message(call: ServiceCall) -> None:
        screen = call.data["screen"]
        jpeg = await hass.async_add_executor_job(
            _render_message, call.data["text"], call.data["color"]
        )
        for coord in _coordinators(hass):
            await coord.device.send_jpeg(jpeg, screen)
            # The temporary message bypassed the hash cache; invalidate so the
            # screen repaints its normal content when we revert.
            coord.invalidate(screen)

            async def _restore(_now, c=coord) -> None:
                await c.async_request_refresh()

            async_call_later(hass, call.data["duration"], _restore)

    hass.services.async_register(
        DOMAIN, SERVICE_SET_CLOCK_FACE, _set_clock_face, schema=_SET_CLOCK_FACE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SHOW_MESSAGE, _show_message, schema=_SHOW_MESSAGE_SCHEMA
    )

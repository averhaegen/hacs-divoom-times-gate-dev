"""Services for Divoom Times Gate: set_clock_face, show_message, show_image."""
from __future__ import annotations

from io import BytesIO

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_call_later
from PIL import Image, ImageDraw
import voluptuous as vol

from .canvas import _scalable_font  # reuse the scalable font loader
from .const import DOMAIN, SCREEN_COUNT, SCREEN_SIZE
from .screens import render_image_frames

SERVICE_SET_CLOCK_FACE = "set_clock_face"
SERVICE_SHOW_MESSAGE = "show_message"
SERVICE_SHOW_IMAGE = "show_image"

_SCREEN = vol.All(vol.Coerce(int), vol.Range(min=0, max=SCREEN_COUNT - 1))
_DEVICE_ID_FIELD = {vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string])}

_SET_CLOCK_FACE_SCHEMA = vol.Schema(
    {
        vol.Required("screen"): _SCREEN,
        vol.Required("clock_id"): vol.Coerce(int),
        **_DEVICE_ID_FIELD,
    }
)
_SHOW_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required("screen"): _SCREEN,
        vol.Required("text"): cv.string,
        vol.Optional("duration", default=10): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("color", default="#FFFFFF"): cv.string,
        **_DEVICE_ID_FIELD,
    }
)
_SHOW_IMAGE_SCHEMA = vol.Schema(
    {
        vol.Required("screen"): _SCREEN,
        vol.Exclusive("image_path", "source"): cv.string,
        vol.Exclusive("image_url", "source"): cv.string,
        vol.Optional("fit", default="cover"): vol.In(["cover", "contain"]),
        # 0 = keep showing until the next config change / refresh
        vol.Optional("duration", default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
        **_DEVICE_ID_FIELD,
    }
)


def _coordinators(hass: HomeAssistant):
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.runtime_data is not None:
            yield entry.runtime_data


def _target_coordinators(hass: HomeAssistant, call: ServiceCall):
    """Coordinators targeted by ``call``.

    With no ``device_id``, falls back to every configured Times Gate (the
    previous, broadcast-to-all behaviour) for backward compatibility. With
    ``device_id`` (from the service's device target picker, or supplied
    directly), only the matching device(s) are affected — otherwise two
    Times Gates would both show the same message/image/face.
    """
    device_ids = call.data.get("device_id")
    if not device_ids:
        yield from _coordinators(hass)
        return

    device_registry = dr.async_get(hass)
    domain_entry_ids = {entry.entry_id for entry in hass.config_entries.async_entries(DOMAIN)}
    seen: set[str] = set()
    for device_id in device_ids:
        device = device_registry.async_get(device_id)
        if device is None:
            raise ServiceValidationError(f"Unknown device_id: {device_id}")
        matched = device.config_entries & domain_entry_ids
        if not matched:
            raise ServiceValidationError(
                f"Device {device_id} is not a Divoom Times Gate"
            )
        for entry_id in matched:
            if entry_id in seen:
                continue
            seen.add(entry_id)
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None and entry.runtime_data is not None:
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
        for coord in _target_coordinators(hass, call):
            await coord.device.set_clock_face(screen, clock_id)

    async def _show_message(call: ServiceCall) -> None:
        screen = call.data["screen"]
        jpeg = await hass.async_add_executor_job(
            _render_message, call.data["text"], call.data["color"]
        )
        for coord in _target_coordinators(hass, call):
            await coord.device.send_jpeg(jpeg, screen)
            coord.record_frame(screen, jpeg)
            # The temporary message bypassed the hash cache; invalidate so the
            # screen repaints its normal content when we revert.
            coord.invalidate(screen)

            async def _restore(_now, c=coord) -> None:
                await c.async_request_refresh()

            async_call_later(hass, call.data["duration"], _restore)

    async def _show_image(call: ServiceCall) -> None:
        screen = call.data["screen"]
        page = {k: call.data[k] for k in ("image_path", "image_url", "fit") if k in call.data}
        if "image_path" not in page and "image_url" not in page:
            raise vol.Invalid("show_image needs image_path or image_url")
        frames, speed = await render_image_frames(hass, page)
        for coord in _target_coordinators(hass, call):
            await coord.device.send_animation(frames, screen, speed)
            coord.record_frame(screen, frames[0])
            # Bypassed the hash cache; make sure the next tick can repaint.
            coord.invalidate(screen)
            if call.data["duration"]:
                async def _restore(_now, c=coord) -> None:
                    await c.async_request_refresh()

                async_call_later(hass, call.data["duration"], _restore)

    hass.services.async_register(
        DOMAIN, SERVICE_SET_CLOCK_FACE, _set_clock_face, schema=_SET_CLOCK_FACE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SHOW_IMAGE, _show_image, schema=_SHOW_IMAGE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SHOW_MESSAGE, _show_message, schema=_SHOW_MESSAGE_SCHEMA
    )

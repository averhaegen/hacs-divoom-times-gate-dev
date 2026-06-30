"""Divoom Times Gate local HTTP API client.

The Times Gate uses the same ``POST http://IP/post`` API as the Divoom Pixoo,
but with several Times-Gate-specific requirements (verified against the device
and the official docs, page 133):

  * every request must include an integer ``LocalToken`` (shown in the Divoom
    app) — without it the device returns ``{"error_code": "DeviceToken is err"}``.
  * ``Draw/SendHttpGif`` ``PicData`` must be base64-encoded **JPEG**, NOT raw RGB
    (raw RGB sends with error_code 0 but leaves the screen stuck on "loading").
  * ``LcdArray`` (length 5, e.g. ``[1,0,0,0,0]``) selects which screen(s) to draw.
  * ``PicID`` must be monotonically increasing. We reset the counter once at
    startup (``Draw/ResetHttpGifId``) then increment a small counter for every
    push across all screens. Random or oversized ids cause silent drops or a
    stuck "loading" state.
"""
from __future__ import annotations

import base64
import logging

import aiohttp

from .const import SCREEN_COUNT, SCREEN_SIZE

_LOGGER = logging.getLogger(__name__)


class TimesGate:
    """Async client for the Divoom Times Gate local HTTP API."""

    def __init__(
        self,
        ip: str,
        local_token: int,
        session: aiohttp.ClientSession,
        hardware: int = 400,
    ) -> None:
        self._ip = ip
        self._local_token = int(local_token)
        self._session = session
        # Hardware revision selects the endpoint (official docs): 402 uses port
        # 9000 / divoom_api; everything else (400) uses port 80 / post.
        if int(hardware) == 402:
            self._url = f"http://{ip}:9000/divoom_api"
        else:
            self._url = f"http://{ip}/post"
        self._pic_id = 0

    async def _send(self, command: dict) -> dict:
        """POST a command with the LocalToken injected. Returns parsed JSON."""
        payload = {**command, "LocalToken": self._local_token}
        try:
            async with self._session.post(
                self._url, json=payload, timeout=aiohttp.ClientTimeout(total=9)
            ) as resp:
                data = await resp.json(content_type=None)
                if data.get("error_code") not in (0, None):
                    _LOGGER.warning(
                        "Times Gate %s rejected %s: %s",
                        self._ip,
                        command.get("Command"),
                        data.get("error_code"),
                    )
                return data
        except Exception as err:  # noqa: BLE001 - surface any transport error
            _LOGGER.error("Error communicating with Times Gate at %s: %s", self._ip, err)
            return {"error_code": "exception", "exception": str(err)}

    async def ping(self) -> bool:
        """Return True if the device accepts our LocalToken."""
        data = await self._send({"Command": "Channel/GetAllConf"})
        return data.get("error_code") == 0

    async def get_conf(self) -> dict:
        """Return the device config (brightness, light switch, etc.)."""
        return await self._send({"Command": "Channel/GetAllConf"})

    async def reset_pic_counter(self) -> None:
        """Reset the device's animation id counter and our local counter.

        Call once before a batch of screen pushes (e.g. on startup or if a send
        ever leaves a screen stuck). Works fine as long as LocalToken is sent.
        """
        await self._send({"Command": "Draw/ResetHttpGifId"})
        self._pic_id = 0

    async def set_brightness(self, brightness: int) -> None:
        await self._send(
            {"Command": "Channel/SetBrightness", "Brightness": max(0, min(100, int(brightness)))}
        )

    async def turn_on(self) -> None:
        await self._send({"Command": "Channel/OnOffScreen", "OnOff": 1})

    async def turn_off(self) -> None:
        await self._send({"Command": "Channel/OnOffScreen", "OnOff": 0})

    async def set_rgb(
        self, light_index: int, on: bool, color_hex: str, brightness: int
    ) -> dict:
        """Control the RGB lighting. light_index: 0=all, 1=edge strip, 2=backlight."""
        return await self._send(
            {
                "Command": "Channel/SetRGBInfo",
                "OnOff": 1 if on else 0,
                "Color": color_hex,
                "ColorCycle": 0,
                "Brightness": max(0, min(100, int(brightness))),
                "SelectLightIndex": int(light_index),
                "LightList": [{"SelectEffect": 0}, {"SelectEffect": 0}, {"SelectEffect": 0}],
            }
        )

    async def play_buzzer(self, active_ms: int = 500, off_ms: int = 500, total_ms: int = 3000) -> None:
        await self._send(
            {
                "Command": "Device/PlayBuzzer",
                "ActiveTimeInCycle": active_ms,
                "OffTimeInCycle": off_ms,
                "PlayTotalTime": total_ms,
            }
        )

    async def set_clock_face(
        self, screen: int, clock_id: int, independence_id: int | None = None
    ) -> dict:
        """Show a native face on one screen (0-4), in Independent Display mode."""
        if screen not in range(SCREEN_COUNT):
            raise ValueError(f"Screen must be 0-{SCREEN_COUNT - 1}, got {screen}")
        payload: dict = {
            "Command": "Channel/SetClockSelectId",
            "ClockId": int(clock_id),
            "LcdIndex": screen,
        }
        if independence_id:
            payload["LcdIndependence"] = int(independence_id)
        return await self._send(payload)

    async def set_whole_face(self, clock_id: int) -> dict:
        """Overall Display: one face spanning all 5 screens."""
        return await self._send(
            {"Command": "Channel/Set5LcdWholeClockId", "ClockId": int(clock_id)}
        )

    async def set_independent_preset(self, independence_id: int) -> dict:
        """Independent Display: activate a native preset (ControlN)."""
        return await self._send(
            {
                "Command": "Channel/Set5LcdChannelType",
                "ChannelType": 1,
                "LcdIndependence": int(independence_id),
            }
        )

    async def send_jpeg(self, jpeg_bytes: bytes, screen: int) -> dict:
        """Send a 128×128 JPEG image to one screen (0-4).

        ``jpeg_bytes`` is the raw bytes of a JPEG file (e.g. from
        ``PIL.Image.save(buf, "JPEG")``). PicID auto-increments monotonically.
        """
        if screen not in range(SCREEN_COUNT):
            raise ValueError(f"Screen must be 0-{SCREEN_COUNT - 1}, got {screen}")

        lcd_array = [0] * SCREEN_COUNT
        lcd_array[screen] = 1

        self._pic_id += 1

        return await self._send(
            {
                "Command": "Draw/SendHttpGif",
                "LcdArray": lcd_array,
                "PicNum": 1,
                "PicWidth": SCREEN_SIZE,
                "PicOffset": 0,
                "PicID": self._pic_id,
                "PicSpeed": 1000,
                "PicData": base64.b64encode(jpeg_bytes).decode("ascii"),
            }
        )

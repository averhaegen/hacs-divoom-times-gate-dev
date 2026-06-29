"""Coordinator that renders the 5 screens and pushes them to the device."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .device import TimesGate
from .render import SCREEN_RENDERERS

_LOGGER = logging.getLogger(__name__)


class TimesGateCoordinator(DataUpdateCoordinator):
    """Renders screens from HA state and pushes them on an interval."""

    def __init__(self, hass: HomeAssistant, device: TimesGate, interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="divoom_times_gate",
            update_interval=timedelta(seconds=interval),
        )
        self.device = device
        self._first_run = True

    async def _async_update_data(self) -> dict:
        # Reset the device's PicID counter once at startup so our small
        # monotonic ids are always accepted.
        if self._first_run:
            await self.device.reset_pic_counter()
            self._first_run = False

        results: dict[int, str] = {}
        for screen, renderer in SCREEN_RENDERERS.items():
            try:
                jpeg = await self.hass.async_add_executor_job(renderer, self.hass)
                resp = await self.device.send_jpeg(jpeg, screen)
                results[screen] = resp.get("error_code", "?")
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("Failed rendering/sending screen %s: %s", screen, err)
                results[screen] = "error"
        return {"screens": results}

    async def async_refresh_now(self) -> None:
        """Force an immediate re-render + push (used by the refresh button/service)."""
        await self.async_request_refresh()

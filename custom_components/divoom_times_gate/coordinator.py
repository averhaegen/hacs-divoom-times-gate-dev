"""Coordinator that renders the 5 screens and pushes them to the device."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .device import TimesGate
from .render import SCREEN_RENDERERS

if TYPE_CHECKING:
    from . import DivoomTimesGateConfigEntry

_LOGGER = logging.getLogger(__name__)


class TimesGateCoordinator(DataUpdateCoordinator[dict[int, str]]):
    """Renders screens from HA state and pushes them on an interval."""

    config_entry: DivoomTimesGateConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device: TimesGate,
        interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="divoom_times_gate",
            update_interval=timedelta(seconds=interval),
        )
        self.device = device
        self._first_run = True

    async def _async_update_data(self) -> dict[int, str]:
        """Render and push all five screens. Raises UpdateFailed if unreachable."""
        if self._first_run:
            await self.device.reset_pic_counter()
            self._first_run = False

        results: dict[int, str] = {}
        any_ok = False
        for screen, renderer in SCREEN_RENDERERS.items():
            jpeg = await self.hass.async_add_executor_job(renderer, self.hass)
            resp = await self.device.send_jpeg(jpeg, screen)
            code = resp.get("error_code", "?")
            results[screen] = code
            if code == 0:
                any_ok = True

        if not any_ok:
            raise UpdateFailed("Device rejected all screen updates")

        return results

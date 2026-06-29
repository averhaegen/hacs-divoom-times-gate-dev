"""Coordinator that renders/pushes the 5 screens based on their config."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_SCREENS, SCREEN_COUNT
from .defaults import DEFAULT_SCREENS
from .device import TimesGate
from .screens import is_enabled, render_black, render_page

if TYPE_CHECKING:
    from . import DivoomTimesGateConfigEntry

_LOGGER = logging.getLogger(__name__)


class TimesGateCoordinator(DataUpdateCoordinator[dict[int, str]]):
    """Renders screens from config + HA state and pushes them on an interval."""

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

    @property
    def screens(self) -> list[dict[str, Any]]:
        """The configured screen list (options override, else defaults)."""
        configured = self.config_entry.options.get(CONF_SCREENS)
        return configured if configured else DEFAULT_SCREENS

    async def _async_update_data(self) -> dict[int, str]:
        if self._first_run:
            await self.device.reset_pic_counter()
            self._first_run = False

        results: dict[int, str] = {}
        any_ok = False
        for screen in range(SCREEN_COUNT):
            cfg = self.screens[screen] if screen < len(self.screens) else {"type": "off"}
            code = await self._push_screen(screen, cfg)
            results[screen] = code
            if code == 0:
                any_ok = True

        if not any_ok:
            raise UpdateFailed("Device rejected all screen updates")
        return results

    async def _push_screen(self, screen: int, cfg: dict[str, Any]) -> Any:
        """Render+send one screen according to its config. Returns error_code."""
        # Accept both `page_type` (Pixoo-compatible) and `type` as the key.
        ptype = (cfg.get("page_type") or cfg.get("type") or "components").lower()
        try:
            if ptype == "clock":
                resp = await self.device.set_clock_face(
                    screen, int(cfg.get("clock_id", cfg.get("id", 0)))
                )
                return resp.get("error_code", "?")

            if ptype == "off":
                jpeg = await self.hass.async_add_executor_job(render_black)
            else:  # components / custom
                if not is_enabled(self.hass, cfg):
                    return "disabled"  # leave the screen's current content
                jpeg = await self.hass.async_add_executor_job(render_page, self.hass, cfg)

            resp = await self.device.send_jpeg(jpeg, screen)
            return resp.get("error_code", "?")
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Screen %s (%s) failed: %s", screen, ptype, err)
            return "error"

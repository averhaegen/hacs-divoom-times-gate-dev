"""Coordinator: renders custom screens, rotates pages, and arbitrates between
HA content and the device's native faces/presets.

Control state (driven by the Select entities):
- ``display``: the device-level Display source — one of
  ("dashboard", None) | ("overall", clock_id) | ("independent", indep_id) | ("off", None)
- ``screen_modes``: per-screen mode, only meaningful in dashboard mode —
  ("custom", None) | ("face", clock_id) | ("off", None)

When ``display`` is not "dashboard", the coordinator pushes nothing so the native
face/preset persists. In "dashboard", each "custom" screen is rendered+pushed
every tick (with page rotation); "face"/"off" screens are set once on change.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_DEVICE_ID,
    CONF_REFRESH_INTERVAL,
    CONF_SCREENS,
    DEFAULT_DURATION,
    DEFAULT_REFRESH_INTERVAL,
    SCREEN_COUNT,
)
from .defaults import DEFAULT_SCREENS
from .device import TimesGate
from .screens import (
    is_enabled,
    normalize_pages,
    page_duration,
    render_black,
    render_page,
)

if TYPE_CHECKING:
    from . import DivoomTimesGateConfigEntry

_LOGGER = logging.getLogger(__name__)


class TimesGateCoordinator(DataUpdateCoordinator[dict[int, str]]):
    """Renders/rotates custom screens and arbitrates with native faces."""

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
        self._tick = interval
        self.presets: list = []  # IndependentPreset list, filled at setup

        # Control state (defaults; overridden by restored Select states).
        self.display: tuple[str, Any] = ("dashboard", None)
        self.screen_modes: list[tuple[str, Any]] = [("custom", None)] * SCREEN_COUNT

        # Per-screen rotation state.
        self._rot_index = [0] * SCREEN_COUNT
        self._rot_elapsed = [0] * SCREEN_COUNT

    # --- config helpers ----------------------------------------------------

    @property
    def device_id(self) -> int:
        return int(self.config_entry.data.get(CONF_DEVICE_ID, 0))

    @property
    def screens(self) -> list[Any]:
        configured = self.config_entry.options.get(CONF_SCREENS)
        return configured if configured else DEFAULT_SCREENS

    def _pages_for(self, screen: int) -> list[dict[str, Any]]:
        if screen < len(self.screens):
            return normalize_pages(self.screens[screen])
        return []

    # --- control API (called by Select entities) ---------------------------

    async def async_set_display(self, kind: str, value: Any) -> None:
        """Set the device-level Display source and apply it immediately."""
        self.display = (kind, value)
        if kind == "overall":
            await self.device.set_whole_face(int(value))
        elif kind == "independent":
            await self.device.set_independent_preset(int(value))
        elif kind == "off":
            await self.device.turn_off()
        else:  # dashboard
            await self.device.turn_on()
            await self._reassert_faces()
            await self.async_request_refresh()

    async def async_set_screen(self, screen: int, kind: str, value: Any) -> None:
        """Set a per-screen mode (only acts now if in dashboard mode)."""
        self.screen_modes[screen] = (kind, value)
        self._rot_index[screen] = 0
        self._rot_elapsed[screen] = 0
        if self.display[0] != "dashboard":
            return
        if kind == "face":
            await self.device.set_clock_face(screen, int(value), self._active_independence())
        elif kind == "off":
            await self._push_black(screen)
        else:  # custom
            await self.async_request_refresh()

    def _active_independence(self) -> int | None:
        """Independence id to scope per-screen faces, if known from config."""
        return self.config_entry.options.get("active_independence")

    async def _reassert_faces(self) -> None:
        for screen, (kind, value) in enumerate(self.screen_modes):
            if kind == "face":
                await self.device.set_clock_face(screen, int(value), self._active_independence())
            elif kind == "off":
                await self._push_black(screen)

    async def _push_black(self, screen: int) -> None:
        jpeg = await self.hass.async_add_executor_job(render_black)
        await self.device.send_jpeg(jpeg, screen)

    # --- periodic render/push ---------------------------------------------

    async def _async_update_data(self) -> dict[int, str]:
        if self._first_run:
            await self.device.reset_pic_counter()
            self._first_run = False

        # Native modes: leave the device alone so the face/preset persists.
        if self.display[0] != "dashboard":
            return {"display": self.display[0]}

        results: dict[int, str] = {}
        for screen in range(SCREEN_COUNT):
            kind = self.screen_modes[screen][0]
            if kind == "custom":
                results[screen] = await self._render_custom(screen)
            # face / off were set on change; nothing to do each tick.
        return results

    async def _render_custom(self, screen: int) -> Any:
        pages = [p for p in self._pages_for(screen) if is_enabled(self.hass, p)]
        if not pages:
            return "empty"

        # Advance rotation based on the current page's duration.
        idx = self._rot_index[screen] % len(pages)
        self._rot_elapsed[screen] += self._tick
        if self._rot_elapsed[screen] >= page_duration(pages[idx], DEFAULT_DURATION):
            idx = (idx + 1) % len(pages)
            self._rot_index[screen] = idx
            self._rot_elapsed[screen] = 0

        page = pages[idx]
        ptype = (page.get("page_type") or page.get("type") or "components").lower()
        try:
            if ptype == "clock":
                resp = await self.device.set_clock_face(
                    screen, int(page.get("clock_id", page.get("id", 0))),
                    self._active_independence(),
                )
                return resp.get("error_code", "?")
            if ptype == "off":
                jpeg = await self.hass.async_add_executor_job(render_black)
            else:
                jpeg = await self.hass.async_add_executor_job(render_page, self.hass, page)
            resp = await self.device.send_jpeg(jpeg, screen)
            return resp.get("error_code", "?")
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Screen %s render failed: %s", screen, err)
            return "error"

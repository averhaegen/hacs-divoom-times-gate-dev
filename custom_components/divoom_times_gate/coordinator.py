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

import hashlib
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_DASHBOARD_BASE,
    CONF_DEVICE_ID,
    CONF_REFRESH_INTERVAL,
    CONF_SCREENS,
    DEFAULT_DURATION,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
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

        # Last-sent JPEG hash per screen, persisted across entry reloads so that
        # editing config only re-pushes (flashes) the screens that changed, and
        # periodic ticks skip unchanged screens.
        self._last_hashes: dict[int, str] = hass.data.setdefault(
            f"{DOMAIN}_hashes", {}
        ).setdefault(entry.entry_id, {})

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

    def invalidate(self, screen: int | None = None) -> None:
        """Forget the last-sent hash so the next render re-pushes."""
        if screen is None:
            self._last_hashes.clear()
        else:
            self._last_hashes.pop(screen, None)

    async def async_force_refresh(self) -> None:
        """Refresh button / service: re-push everything regardless of hashes."""
        self.invalidate()
        await self.async_request_refresh()

    async def _send_jpeg(self, screen: int, jpeg: bytes) -> Any:
        """Send a JPEG only if it differs from the last one sent to this screen."""
        digest = hashlib.md5(jpeg).hexdigest()
        if self._last_hashes.get(screen) == digest:
            return "unchanged"
        resp = await self.device.send_jpeg(jpeg, screen)
        if resp.get("error_code") == 0:
            self._last_hashes[screen] = digest
        return resp.get("error_code", "?")

    async def async_set_display(self, kind: str, value: Any) -> None:
        """Set the device-level Display source and apply it immediately."""
        prev_kind = self.display[0]
        self.display = (kind, value)
        # Native modes change the panels outside our control; force a repaint
        # of custom screens when we next return to dashboard.
        self.invalidate()
        if kind == "overall":
            await self.device.set_whole_face(int(value))
        elif kind == "independent":
            await self.device.set_independent_preset(int(value))
        elif kind == "off":
            await self.device.turn_off()
        else:  # dashboard
            # Only power on when coming back from Off. Calling turn_on otherwise
            # makes the device flash its native preset before our content paints,
            # and resets which preset is active. Leaving it alone keeps the last
            # state and lets our JPEGs overlay cleanly.
            if prev_kind == "off":
                await self.device.turn_on()
            # Optional: switch the underlying preset to a configured "base" so our
            # JPEGs overlay onto static faces, not live ones (live clock/weather
            # faces reload periodically and flash a loading spinner under us).
            if (base := self._dashboard_base_id()) is not None:
                await self.device.set_independent_preset(base)
            await self._reassert_faces()
            await self.async_request_refresh()

    def _dashboard_base_id(self) -> int | None:
        """Resolve the configured dashboard-base preset position to its id."""
        pos = self.config_entry.options.get(CONF_DASHBOARD_BASE)
        if pos in (None, ""):
            return None
        for preset in self.presets:
            if preset.position == int(pos):
                return preset.independence_id
        return None

    async def async_set_screen(self, screen: int, kind: str, value: Any) -> None:
        """Set a per-screen mode (only acts now if in dashboard mode)."""
        self.screen_modes[screen] = (kind, value)
        self._rot_index[screen] = 0
        self._rot_elapsed[screen] = 0
        self.invalidate(screen)
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
        await self._send_jpeg(screen, jpeg)

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
            # New page in the rotation: force a repaint (its image may hash the
            # same as an earlier custom page, and a clock/off page may have left
            # native content on the panel).
            self.invalidate(screen)

        page = pages[idx]
        ptype = (page.get("page_type") or page.get("type") or "components").lower()
        try:
            if ptype == "clock":
                cid = int(page.get("clock_id", page.get("id", 0)))
                return await self._apply_native(
                    screen, f"clock:{cid}",
                    lambda: self.device.set_clock_face(screen, cid, self._active_independence()),
                )
            if ptype == "gif":
                urls = page.get("gif_url") or page.get("gif_urls") or []
                if isinstance(urls, str):
                    urls = [urls]
                return await self._apply_native(
                    screen, f"gif:{urls}", lambda: self.device.play_gif(screen, urls)
                )
            if ptype == "visualizer":
                eq = int(page.get("id", page.get("eq_position", 0)))
                return await self._apply_native(
                    screen, f"viz:{eq}",
                    lambda: self.device.set_visualizer(screen, eq, self._active_independence()),
                )
            if ptype == "off":
                jpeg = await self.hass.async_add_executor_job(render_black)
            else:
                jpeg = await self.hass.async_add_executor_job(render_page, self.hass, page)
            return await self._send_jpeg(screen, jpeg)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Screen %s render failed: %s", screen, err)
            return "error"

    async def _apply_native(self, screen: int, signature: str, apply) -> Any:
        """Apply a native page command once; skip if already applied (no flicker)."""
        if self._last_hashes.get(screen) == signature:
            return "unchanged"
        resp = await apply()
        if resp.get("error_code") == 0:
            self._last_hashes[screen] = signature
        return resp.get("error_code", "?")

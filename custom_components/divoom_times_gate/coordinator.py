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
from urllib.parse import quote

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_DASHBOARD_BASE,
    CONF_DEVICE_ID,
    CONF_DISPDATA_SECRET,
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
        # RGB light entities, keyed by light_index (1=Edgelight, 2=Backlight),
        # filled by light.py's async_setup_entry so switch.py can reach them.
        self.rgb_lights: dict[int, Any] = {}

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
        """Re-apply face/off state on every screen in one batched call.

        See [[feedback-multi-screen-calls]] — always batch multi-screen updates
        into a single Draw/CommandList rather than one POST per screen.
        """
        commands = []
        for screen, (kind, value) in enumerate(self.screen_modes):
            if kind == "face":
                commands.append(
                    self.device.build_clock_face(screen, int(value), self._active_independence())
                )
            elif kind == "off":
                jpeg = await self.hass.async_add_executor_job(render_black)
                commands.append(self.device.build_jpeg(jpeg, screen))
        if commands:
            await self.device.send_command_list(commands)

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
        pending: dict[int, tuple[dict, str]] = {}
        for screen in range(SCREEN_COUNT):
            kind = self.screen_modes[screen][0]
            if kind != "custom":
                continue  # face / off were set on change; nothing to do each tick.
            status, command, signature = await self._build_custom(screen)
            if command is not None:
                pending[screen] = (command, signature)
            else:
                results[screen] = status

        if pending:
            # Batch every screen that actually changed this tick into one
            # Draw/CommandList POST instead of one per screen — see
            # [[feedback-multi-screen-calls]] and docs/API.md §5.1.
            resp = await self.device.send_command_list([cmd for cmd, _ in pending.values()])
            status = resp.get("error_code", "?")
            if status == 0:
                for screen, (_, signature) in pending.items():
                    self._last_hashes[screen] = signature
            for screen in pending:
                results[screen] = status
        return results

    async def _build_custom(self, screen: int) -> tuple[str, dict | None, str | None]:
        """Build the pending command for one screen's current page, if any.

        Returns ``(status, command, signature)``. ``command`` is ``None`` when
        there's nothing to send this tick (status is "empty"/"unchanged"/"error");
        otherwise ``command`` is a Draw/CommandList sub-command payload and
        ``status`` is "pending" (the caller fills in the real status once the
        batched call actually completes).
        """
        pages = [p for p in self._pages_for(screen) if is_enabled(self.hass, p)]
        if not pages:
            return "empty", None, None

        # Advance rotation based on the current page's duration. With a single
        # page there is nothing to rotate to, so skip the elapsed-time bookkeeping
        # entirely — otherwise every `duration` seconds we'd invalidate the hash
        # and force a full repaint/resend for no reason (visible as a reload on
        # native pages like dispdata_text, which resend their whole setup call).
        idx = self._rot_index[screen] % len(pages)
        if len(pages) > 1:
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
                command = self.device.build_clock_face(screen, cid, self._active_independence())
                return self._pending(screen, f"clock:{cid}", command)
            if ptype == "gif":
                urls = page.get("gif_url") or page.get("gif_urls") or []
                if isinstance(urls, str):
                    urls = [urls]
                command = self.device.build_play_gif(screen, urls)
                return self._pending(screen, f"gif:{urls}", command)
            if ptype == "visualizer":
                eq = int(page.get("id", page.get("eq_position", 0)))
                command = self.device.build_visualizer(screen, eq, self._active_independence())
                return self._pending(screen, f"viz:{eq}", command)
            if ptype == "dispdata_text":
                if page.get("items"):
                    return await self._build_dispdata_items(screen, page)
                return await self._build_dispdata_text(screen, page)
            if ptype == "off":
                jpeg = await self.hass.async_add_executor_job(render_black)
            else:
                jpeg = await self.hass.async_add_executor_job(render_page, self.hass, page)
            digest = hashlib.md5(jpeg).hexdigest()
            if self._last_hashes.get(screen) == digest:
                return "unchanged", None, None
            return "pending", self.device.build_jpeg(jpeg, screen), digest
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Screen %s render failed: %s", screen, err)
            return "error", None, None

    def _pending(self, screen: int, signature: str, command: dict) -> tuple[str, dict | None, str | None]:
        """Skip building a duplicate command if the signature hasn't changed."""
        if self._last_hashes.get(screen) == signature:
            return "unchanged", None, None
        return "pending", command, signature

    _DISPDATA_ROW_Y = (8, 40, 70, 100)  # default y per row, up to 4 sensors, evenly spaced
    _DISPDATA_MAX_SENSORS = 4

    async def _build_dispdata_text(
        self, screen: int, page: dict[str, Any]
    ) -> tuple[str, dict | None, str | None]:
        """Build up to 4 type-23 net-text items once; the device then self-polls
        each independently.

        See docs/DISPDATA.md. ``page`` fields:
          sensors: list of up to 4 {entity_id (required), name, color, font,
            align, y} — or a single top-level entity_id (back-compat, same as
            a 1-item sensors list.
          Shared across all rows unless overridden per sensor: x, TextWidth,
          Textheight, speed, align, font, color, update_time, background_gif.
        """
        sensors: list[dict[str, Any]] = list(page.get("sensors") or [])
        if not sensors and page.get("entity_id"):
            sensors = [{"entity_id": page["entity_id"]}]
        if not sensors:
            _LOGGER.error("dispdata_text page on screen %s has no sensors configured", screen)
            return "error", None, None
        if len(sensors) > self._DISPDATA_MAX_SENSORS:
            _LOGGER.warning(
                "dispdata_text page on screen %s has %d sensors, only the first %d are shown",
                screen, len(sensors), self._DISPDATA_MAX_SENSORS,
            )
            sensors = sensors[: self._DISPDATA_MAX_SENSORS]

        secret = self.config_entry.data.get(CONF_DISPDATA_SECRET)
        if not secret:
            _LOGGER.error("dispdata_text: no DispData secret set up yet for this entry")
            return "error", None, None

        try:
            base_url = get_url(self.hass, allow_external=False, prefer_cloud=False)
        except NoURLAvailableError:
            _LOGGER.error(
                "dispdata_text: could not resolve a local HA URL for the device to poll"
            )
            return "error", None, None

        items = []
        for row, sensor in enumerate(sensors):
            entity_id = sensor.get("entity_id")
            if not entity_id:
                _LOGGER.error("dispdata_text: sensor #%d on screen %s is missing entity_id", row, screen)
                return "error", None, None

            label = sensor.get("name")
            if label is None:
                state = self.hass.states.get(entity_id)
                label = state.name if state is not None else entity_id

            poll_url = f"{base_url}/api/divoom_times_gate/dispdata/{secret}/{entity_id}"
            if label:
                # The device's own HTTP client (issuing the poll GET) appears not to
                # handle a percent-encoded space (%20) in the query string reliably
                # — confirmed on device: a `name` with a space broke the poll.
                # Sidestep it entirely by swapping spaces for underscores before
                # quoting (dispdata.py's view swaps them back for display).
                poll_url += f"?label={quote(label.replace(' ', '_'))}"

            items.append(
                {
                    "TextId": row + 1,
                    "type": 23,
                    "x": int(sensor.get("x", page.get("x", 0))),
                    "y": int(sensor.get("y", page.get("y", self._DISPDATA_ROW_Y[row]))),
                    "dir": 0,
                    "font": int(sensor.get("font", page.get("font", 4))),
                    "TextWidth": int(sensor.get("TextWidth", page.get("TextWidth", 128))),
                    "Textheight": int(sensor.get("Textheight", page.get("Textheight", 16))),
                    "speed": int(sensor.get("speed", page.get("speed", 50))),
                    "align": int(sensor.get("align", page.get("align", 1))),
                    "color": sensor.get("color", page.get("color", "#FFFFFF")),
                    "update_time": int(sensor.get("update_time", page.get("update_time", 10))),
                    "TextString": poll_url,
                }
            )

        signature = f"dispdata:{screen}:{items}"
        background_gif = page.get(
            "background_gif", "https://dummyimage.com/128x128/000000/000000.gif"
        )
        command = self.device.build_item_list(screen, items, background_gif=background_gif)
        return self._pending(screen, signature, command)

    _DISPDATA_MAX_ITEMS = 8

    # Native SendHttpItemList element types the device renders entirely on its
    # own (clock/date/weather) — no TextString, no polling, zero HA involvement
    # once sent. See docs/API.md §4.10 "type values" table.
    _NATIVE_KIND_TYPES = {
        "second": 1,
        "minute": 2,
        "hour": 3,
        "ampm": 4,  # AM/PM marker; pair with "time_short" for a 12h clock
        "time_short": 5,  # hh:mm
        "time": 6,  # hh:mm:ss
        "clock": 6,  # alias of "time"
        "year": 7,
        "day": 8,
        "month": 9,
        "mon_year": 10,
        "month_day": 11,  # eng-month.day
        "weekday_2": 13,  # SU
        "weekday_3": 14,  # SUN
        "weekday_full": 15,  # SUNDAY
        "month_3": 16,  # JAN
        "temperature": 17,
        "temp_max": 18,
        "temp_min": 19,
        "weather": 20,  # weather word
        "noise": 21,  # dB
    }

    async def _build_dispdata_items(
        self, screen: int, page: dict[str, Any]
    ) -> tuple[str, dict | None, str | None]:
        """Build a raw list of dispdata_text items with full manual control.

        Unlike ``sensors:`` (auto-stacked "<name>: <value>" rows), ``items:``
        lets each entry be placed and coloured independently — a static
        ``kind: label``, a polling ``kind: value``, or a native device element
        (clock/date/weather, see ``_NATIVE_KIND_TYPES``) are fully separate, so
        you decide the layout yourself (side by side, stacked, different
        fonts/colours per piece) the same way you would hand-write a raw
        Draw/SendHttpItemList call. See docs/DISPDATA.md §3.

        Each entry in ``items``:
          kind: "label" (static text), "value" (polls entity_id — inferred if
            entity_id is present and kind is omitted), or one of
            ``_NATIVE_KIND_TYPES`` (e.g. "time", "time_short", "ampm",
            "weekday_3", "temperature", "weather" — rendered entirely by the
            device, no polling, no TextString).
          label items: text (required, static string).
          value items: entity_id (required), update_time, label (optional
            "<label>: " prefix on this item alone — usually left unset since
            the label is its own item).
          Common fields (all default to the page-level value, then a
          built-in default): x, y, font, color, align, TextWidth, Textheight,
          speed.
        """
        raw_items: list[dict[str, Any]] = list(page.get("items") or [])
        if not raw_items:
            _LOGGER.error("dispdata_text page on screen %s has an empty items list", screen)
            return "error", None, None
        if len(raw_items) > self._DISPDATA_MAX_ITEMS:
            _LOGGER.warning(
                "dispdata_text page on screen %s has %d items, only the first %d are shown",
                screen, len(raw_items), self._DISPDATA_MAX_ITEMS,
            )
            raw_items = raw_items[: self._DISPDATA_MAX_ITEMS]

        secret = self.config_entry.data.get(CONF_DISPDATA_SECRET)
        base_url = None
        if any(item.get("kind", "value" if item.get("entity_id") else "label") == "value" for item in raw_items):
            if not secret:
                _LOGGER.error("dispdata_text: no DispData secret set up yet for this entry")
                return "error", None, None
            try:
                base_url = get_url(self.hass, allow_external=False, prefer_cloud=False)
            except NoURLAvailableError:
                _LOGGER.error(
                    "dispdata_text: could not resolve a local HA URL for the device to poll"
                )
                return "error", None, None

        items = []
        for row, raw in enumerate(raw_items):
            kind = raw.get("kind") or ("value" if raw.get("entity_id") else "label")
            common = {
                "TextId": row + 1,
                "x": int(raw.get("x", page.get("x", 0))),
                "y": int(raw.get("y", page.get("y", 8))),
                "dir": 0,
                "font": int(raw.get("font", page.get("font", 4))),
                "TextWidth": int(raw.get("TextWidth", page.get("TextWidth", 128))),
                "Textheight": int(raw.get("Textheight", page.get("Textheight", 16))),
                "speed": int(raw.get("speed", page.get("speed", 50))),
                "align": int(raw.get("align", page.get("align", 1))),
                "color": raw.get("color", page.get("color", "#FFFFFF")),
            }

            if kind == "label":
                text = raw.get("text")
                if text is None:
                    _LOGGER.error("dispdata_text: label item #%d on screen %s is missing text", row, screen)
                    return "error", None, None
                items.append({**common, "type": 22, "TextString": text})
                continue

            if kind in self._NATIVE_KIND_TYPES:
                # Native device element (clock/date/weather) — no TextString,
                # nothing to poll, the device renders it entirely on its own.
                items.append({**common, "type": self._NATIVE_KIND_TYPES[kind]})
                continue

            if kind != "value":
                _LOGGER.error(
                    "dispdata_text: item #%d on screen %s has unknown kind %r", row, screen, kind
                )
                return "error", None, None

            entity_id = raw.get("entity_id")
            if not entity_id:
                _LOGGER.error("dispdata_text: value item #%d on screen %s is missing entity_id", row, screen)
                return "error", None, None

            poll_url = f"{base_url}/api/divoom_times_gate/dispdata/{secret}/{entity_id}"
            if label := raw.get("label"):
                # See the space/underscore note in _build_dispdata_text — the
                # device's own poll GET doesn't reliably handle %20.
                poll_url += f"?label={quote(label.replace(' ', '_'))}"

            items.append(
                {
                    **common,
                    "type": 23,
                    "update_time": int(raw.get("update_time", page.get("update_time", 10))),
                    "TextString": poll_url,
                }
            )

        signature = f"dispdata_items:{screen}:{items}"
        background_gif = page.get(
            "background_gif", "https://dummyimage.com/128x128/000000/000000.gif"
        )
        command = self.device.build_item_list(screen, items, background_gif=background_gif)
        return self._pending(screen, signature, command)

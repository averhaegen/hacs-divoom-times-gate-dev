"""Config and options flow for Divoom Times Gate."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    ObjectSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_DEVICE_ID,
    CONF_FACES,
    CONF_HARDWARE,
    CONF_IP_ADDRESS,
    CONF_LOCAL_TOKEN,
    CONF_MAC,
    CONF_REFRESH_INTERVAL,
    CONF_SCREENS,
    DEFAULT_HARDWARE,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    SCREEN_COUNT,
)
from .defaults import DEFAULT_FACES, DEFAULT_SCREENS
from .device import TimesGate
from .discovery import DiscoveredDevice, async_discover_devices


class DivoomTimesGateConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow."""

    VERSION = 1
    _discovered: list[DiscoveredDevice] = []

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        session = async_get_clientsession(self.hass)

        if not self._discovered:
            self._discovered = await async_discover_devices(session)

        if user_input is not None:
            ip = str(user_input[CONF_IP_ADDRESS]).strip()
            match = next((d for d in self._discovered if d.ip == ip), None)
            hardware = match.hardware if match else DEFAULT_HARDWARE
            device = TimesGate(ip, int(user_input[CONF_LOCAL_TOKEN]), session, hardware)
            if await device.ping():
                # Prefer the stable MAC as the unique id; fall back to the IP.
                await self.async_set_unique_id((match.mac if match else "") or ip)
                self._abort_if_unique_id_configured()
                title = f"{match.name} ({ip})" if match else f"Times Gate ({ip})"
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_IP_ADDRESS: ip,
                        CONF_LOCAL_TOKEN: int(user_input[CONF_LOCAL_TOKEN]),
                        CONF_HARDWARE: hardware,
                        CONF_MAC: match.mac if match else "",
                        CONF_DEVICE_ID: match.device_id if match else 0,
                        CONF_REFRESH_INTERVAL: user_input.get(
                            CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
                        ),
                    },
                )
            errors["base"] = "cannot_connect"

        # Discovered devices become a dropdown (still allows typing an IP manually).
        if self._discovered:
            ip_field = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=d.ip, label=f"{d.name} ({d.ip})")
                        for d in self._discovered
                    ],
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
            ip_default = self._discovered[0].ip
        else:
            ip_field = str
            ip_default = ""

        schema = vol.Schema(
            {
                vol.Required(CONF_IP_ADDRESS, default=ip_default): ip_field,
                vol.Required(CONF_LOCAL_TOKEN): int,
                vol.Optional(
                    CONF_REFRESH_INTERVAL, default=DEFAULT_REFRESH_INTERVAL
                ): int,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DivoomTimesGateOptionsFlow()


class DivoomTimesGateOptionsFlow(OptionsFlow):
    """Per-screen config split into a menu: each screen edited on its own."""

    _data: dict[str, Any] | None = None

    def _ensure(self) -> None:
        """Load a working copy of the options once."""
        if self._data is not None:
            return
        opts = self.config_entry.options
        screens = list(opts.get(CONF_SCREENS) or DEFAULT_SCREENS)
        while len(screens) < SCREEN_COUNT:
            screens.append({"page_type": "off"})
        self._data = {
            CONF_SCREENS: screens[:SCREEN_COUNT],
            CONF_FACES: opts.get(CONF_FACES) or DEFAULT_FACES,
            CONF_REFRESH_INTERVAL: opts.get(
                CONF_REFRESH_INTERVAL,
                self.config_entry.data.get(
                    CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
                ),
            ),
        }

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        self._ensure()
        return self.async_show_menu(
            step_id="init",
            menu_options={
                "screen_0": "Screen 1",
                "screen_1": "Screen 2",
                "screen_2": "Screen 3",
                "screen_3": "Screen 4",
                "screen_4": "Screen 5",
                "faces": "Faces (favorites)",
                "settings": "Settings",
                "save": "Save & close",
            },
        )

    async def _screen_step(self, index: int, user_input: dict[str, Any] | None):
        self._ensure()
        assert self._data is not None
        if user_input is not None:
            pages = user_input.get(CONF_SCREENS)
            if isinstance(pages, (list, dict)):
                self._data[CONF_SCREENS][index] = pages
                return await self.async_step_init()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCREENS, default=self._data[CONF_SCREENS][index]
                ): ObjectSelector()
            }
        )
        return self.async_show_form(step_id=f"screen_{index}", data_schema=schema)

    async def async_step_screen_0(self, user_input=None):
        return await self._screen_step(0, user_input)

    async def async_step_screen_1(self, user_input=None):
        return await self._screen_step(1, user_input)

    async def async_step_screen_2(self, user_input=None):
        return await self._screen_step(2, user_input)

    async def async_step_screen_3(self, user_input=None):
        return await self._screen_step(3, user_input)

    async def async_step_screen_4(self, user_input=None):
        return await self._screen_step(4, user_input)

    async def async_step_faces(self, user_input=None):
        self._ensure()
        assert self._data is not None
        if user_input is not None and isinstance(user_input.get(CONF_FACES), dict):
            self._data[CONF_FACES] = user_input[CONF_FACES]
            return await self.async_step_init()
        schema = vol.Schema(
            {vol.Required(CONF_FACES, default=self._data[CONF_FACES]): ObjectSelector()}
        )
        return self.async_show_form(step_id="faces", data_schema=schema)

    async def async_step_settings(self, user_input=None):
        self._ensure()
        assert self._data is not None
        if user_input is not None:
            self._data[CONF_REFRESH_INTERVAL] = int(user_input[CONF_REFRESH_INTERVAL])
            return await self.async_step_init()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_REFRESH_INTERVAL, default=self._data[CONF_REFRESH_INTERVAL]
                ): NumberSelector(
                    NumberSelectorConfig(min=5, max=3600, mode=NumberSelectorMode.BOX)
                )
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_save(self, user_input=None):
        self._ensure()
        return self.async_create_entry(title="", data=self._data)

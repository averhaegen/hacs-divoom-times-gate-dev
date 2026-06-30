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
    """Edit the per-screen configuration via a structured object (YAML) editor."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            screens = user_input.get(CONF_SCREENS)
            faces = user_input.get(CONF_FACES)
            if not isinstance(screens, list):
                errors["base"] = "invalid_screens"
            elif not isinstance(faces, dict):
                errors["base"] = "invalid_faces"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_SCREENS: screens,
                        CONF_FACES: faces,
                        CONF_REFRESH_INTERVAL: int(user_input[CONF_REFRESH_INTERVAL]),
                    },
                )

        opts = self.config_entry.options
        current_screens = opts.get(CONF_SCREENS) or DEFAULT_SCREENS
        current_faces = opts.get(CONF_FACES) or DEFAULT_FACES
        interval = opts.get(
            CONF_REFRESH_INTERVAL,
            self.config_entry.data.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_REFRESH_INTERVAL, default=interval): NumberSelector(
                    NumberSelectorConfig(min=5, max=3600, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_SCREENS, default=current_screens): ObjectSelector(),
                vol.Required(CONF_FACES, default=current_faces): ObjectSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

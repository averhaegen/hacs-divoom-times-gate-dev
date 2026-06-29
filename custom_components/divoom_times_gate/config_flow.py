"""Config and options flow for Divoom Times Gate."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
import yaml

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_IP_ADDRESS,
    CONF_LOCAL_TOKEN,
    CONF_REFRESH_INTERVAL,
    CONF_SCREENS,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
)
from .defaults import DEFAULT_SCREENS
from .device import TimesGate


class DivoomTimesGateConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            device = TimesGate(
                user_input[CONF_IP_ADDRESS], int(user_input[CONF_LOCAL_TOKEN]), session
            )
            if await device.ping():
                await self.async_set_unique_id(user_input[CONF_IP_ADDRESS])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Times Gate ({user_input[CONF_IP_ADDRESS]})",
                    data=user_input,
                )
            errors["base"] = "cannot_connect"

        schema = vol.Schema(
            {
                vol.Required(CONF_IP_ADDRESS): str,
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
    """Edit the per-screen configuration as YAML."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                screens = yaml.safe_load(user_input[CONF_SCREENS]) or []
                if not isinstance(screens, list):
                    raise ValueError("screens must be a YAML list")
            except (yaml.YAMLError, ValueError):
                errors["base"] = "invalid_yaml"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_SCREENS: screens,
                        CONF_REFRESH_INTERVAL: user_input[CONF_REFRESH_INTERVAL],
                    },
                )

        current = self.config_entry.options.get(CONF_SCREENS) or DEFAULT_SCREENS
        screens_yaml = yaml.safe_dump(current, sort_keys=False, allow_unicode=True)
        interval = self.config_entry.options.get(
            CONF_REFRESH_INTERVAL,
            self.config_entry.data.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
        )

        schema = vol.Schema(
            {
                vol.Optional(CONF_REFRESH_INTERVAL, default=interval): int,
                vol.Optional(CONF_SCREENS, default=screens_yaml): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

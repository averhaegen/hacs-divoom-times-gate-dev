"""Config flow for Divoom Times Gate."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_IP_ADDRESS,
    CONF_LOCAL_TOKEN,
    CONF_REFRESH_INTERVAL,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
)
from .device import TimesGate


class DivoomTimesGateConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Divoom Times Gate."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            device = TimesGate(
                user_input[CONF_IP_ADDRESS],
                int(user_input[CONF_LOCAL_TOKEN]),
                session,
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

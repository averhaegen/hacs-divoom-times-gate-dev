"""Light entity for the Times Gate (brightness + on/off)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DivoomTimesGateConfigEntry
from .entity import TimesGateEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DivoomTimesGateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Times Gate display light."""
    async_add_entities([TimesGateLight(entry.runtime_data)])


class TimesGateLight(TimesGateEntity, LightEntity):
    """Controls the whole device display brightness + power."""

    _attr_name = "Display"
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_display"
        self._attr_is_on = True
        self._attr_brightness = 255

    async def async_added_to_hass(self) -> None:
        """Read the current device state once added."""
        await super().async_added_to_hass()
        await self._async_pull_state()

    async def _async_pull_state(self) -> None:
        conf = await self._device.get_conf()
        if conf.get("error_code") == 0:
            self._attr_is_on = conf.get("LightSwitch", 1) == 1
            self._attr_brightness = round(conf.get("Brightness", 100) * 255 / 100)
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the display on and optionally set brightness."""
        await self._device.turn_on()
        self._attr_is_on = True
        if (bri := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            await self._device.set_brightness(round(bri * 100 / 255))
            self._attr_brightness = bri
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the display off."""
        await self._device.turn_off()
        self._attr_is_on = False
        self.async_write_ha_state()

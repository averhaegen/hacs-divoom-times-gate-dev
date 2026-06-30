"""Light entity for the Times Gate (brightness + on/off)."""
from __future__ import annotations

from typing import Any

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
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
    """Set up the Times Gate display light + RGB lights."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            TimesGateLight(coordinator),
            TimesGateRGBLight(coordinator, 1, "Edge RGB"),
            TimesGateRGBLight(coordinator, 2, "Backlight"),
        ]
    )


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


class TimesGateRGBLight(TimesGateEntity, LightEntity):
    """One of the device's RGB lighting zones (edge strip or backlight).

    The device has no read-back for RGB state, so this is an assumed-state light.
    """

    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_assumed_state = True

    def __init__(self, coordinator, light_index: int, name: str) -> None:
        super().__init__(coordinator)
        self._light_index = light_index
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_rgb_{light_index}"
        self._attr_is_on = False
        self._attr_rgb_color = (255, 255, 255)
        self._attr_brightness = 255

    async def async_turn_on(self, **kwargs: Any) -> None:
        if (rgb := kwargs.get(ATTR_RGB_COLOR)) is not None:
            self._attr_rgb_color = rgb
        if (bri := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            self._attr_brightness = bri
        color_hex = "#{:02X}{:02X}{:02X}".format(*self._attr_rgb_color)
        await self._device.set_rgb(
            self._light_index, True, color_hex, round((self._attr_brightness or 255) * 100 / 255)
        )
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._device.set_rgb(self._light_index, False, "#000000", 0)
        self._attr_is_on = False
        self.async_write_ha_state()

"""Light entities for the Times Gate (display + RGB zones)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DivoomTimesGateConfigEntry
from .entity import TimesGateEntity

PARALLEL_UPDATES = 1

# Edgelight effect IDs (0-11), used directly as SelectEffect when light_index=1.
EDGELIGHT_EFFECTS: dict[str, int] = {
    "0. Sparkle": 0,
    "1. Pendulum": 1,
    "2. Rainbow": 2,
    "3. Beetle": 3,
    "4. Bulb": 4,
    "5. Flame": 5,
    "6. Waves": 6,
    "7. Rain": 7,
    "8. Heart": 8,
    "9. Infinity": 9,
    "10. Rocket": 10,
    "11. Color wheel": 11,
}
DEFAULT_EDGELIGHT_EFFECT = "4. Bulb"
# Backlight "off" theme when used as Edgelight's secondary zone (Scenario 2).
EDGELIGHT_SECONDARY_OFF = 5

# Backlight effect IDs (0-11), used directly as SelectEffect when light_index=2.
BACKLIGHT_EFFECTS: dict[str, int] = {
    "0. Beetle": 0,
    "1. Atom": 1,
    "2. Pendulum": 2,
    "3. Sparkle": 3,
    "4. Rainbow": 4,
    "5. Bulb": 5,
    "6. Infinity": 6,
    "7. Chat": 7,
    "8. Antenna": 8,
    "9. Waves": 9,
    "10. Rain": 10,
    "11. Circles": 11,
}
DEFAULT_BACKLIGHT_EFFECT = "5. Bulb"
# Edgelight "off" theme when used as Backlight's secondary zone (Scenario 1).
BACKLIGHT_SECONDARY_OFF = 6


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DivoomTimesGateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Times Gate display light + RGB lights."""
    coordinator = entry.runtime_data
    edgelight = TimesGateRGBLight(
        coordinator, 1, "Edgelight", EDGELIGHT_EFFECTS,
        DEFAULT_EDGELIGHT_EFFECT, BACKLIGHT_SECONDARY_OFF,
    )
    backlight = TimesGateRGBLight(
        coordinator, 2, "Backlight", BACKLIGHT_EFFECTS,
        DEFAULT_BACKLIGHT_EFFECT, EDGELIGHT_SECONDARY_OFF,
    )
    coordinator.rgb_lights[1] = edgelight
    coordinator.rgb_lights[2] = backlight
    async_add_entities([TimesGateLight(coordinator), edgelight, backlight])


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
    """One of the device's two RGB lighting zones (Edgelight or Backlight).

    The device has no read-back for RGB state, so this is an assumed-state light.
    Colour cycling is controlled by a separate ``switch`` entity
    (``TimesGateColorCycleSwitch``) that reads/writes ``color_cycle`` on this light
    and re-sends the current effect. Setting one zone re-points the device's
    physical light button to control only that zone (see docs/RGB_LIGHTS.md).
    """

    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_assumed_state = True

    def __init__(
        self,
        coordinator,
        light_index: int,
        name: str,
        effects: dict[str, int],
        default_effect: str,
        secondary_off: int,
    ) -> None:
        super().__init__(coordinator)
        self._light_index = light_index
        self._effects = effects
        self._secondary_off = secondary_off
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_rgb_{light_index}"
        self._attr_effect_list = list(effects)
        self._attr_is_on = False
        self._attr_rgb_color = (255, 255, 255)
        self._attr_brightness = 255
        self._attr_effect = default_effect
        self.color_cycle = False

    async def async_turn_on(self, **kwargs: Any) -> None:
        if (rgb := kwargs.get(ATTR_RGB_COLOR)) is not None:
            self._attr_rgb_color = rgb
        if (bri := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            self._attr_brightness = bri
        if (eff := kwargs.get(ATTR_EFFECT)) in self._effects:
            self._attr_effect = eff

        await self._async_apply()
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._device.set_rgb(self._light_index, False, "#000000", 0)
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_set_color_cycle(self, enabled: bool) -> None:
        """Set colour-cycle state and re-push if the light is currently on."""
        self.color_cycle = enabled
        if self._attr_is_on:
            await self._async_apply()
        self.async_write_ha_state()

    async def _async_apply(self) -> None:
        """Push the current effect/colour/cycle state to the device."""
        select_effect = self._effects.get(self._attr_effect, self._effects[next(iter(self._effects))])
        color_hex = "#{:02X}{:02X}{:02X}".format(*self._attr_rgb_color)
        await self._device.set_rgb(
            self._light_index,
            True,
            color_hex,
            round((self._attr_brightness or 255) * 100 / 255),
            effect=select_effect,
            color_cycle=self.color_cycle,
            secondary_effect=self._secondary_off,
        )

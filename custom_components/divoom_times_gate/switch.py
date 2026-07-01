"""Switch entities for the Times Gate (colour cycle, button backlight)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
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
    """Set up the Times Gate config switches."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            TimesGateColorCycleSwitch(coordinator, 1, "Edgelight color cycle"),
            TimesGateColorCycleSwitch(coordinator, 2, "Backlight color cycle"),
            TimesGateKeyBacklightSwitch(coordinator),
        ]
    )


class TimesGateColorCycleSwitch(TimesGateEntity, SwitchEntity):
    """Toggles ColorCycle on one RGB light zone (Edgelight or Backlight).

    Delegates to the corresponding ``TimesGateRGBLight`` (looked up via
    ``coordinator.rgb_lights``) so the current effect/colour is re-sent with the
    new ColorCycle flag.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_assumed_state = True

    def __init__(self, coordinator, light_index: int, name: str) -> None:
        super().__init__(coordinator)
        self._light_index = light_index
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_color_cycle_{light_index}"

    @property
    def _light(self):
        return self.coordinator.rgb_lights.get(self._light_index)

    @property
    def is_on(self) -> bool:
        light = self._light
        return bool(light and light.color_cycle)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if light := self._light:
            await light.async_set_color_cycle(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if light := self._light:
            await light.async_set_color_cycle(False)
        self.async_write_ha_state()


class TimesGateKeyBacklightSwitch(TimesGateEntity, SwitchEntity):
    """Toggles the physical button backlight (KeyOnOff)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_name = "Button backlight"
    _attr_assumed_state = True

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_key_backlight"
        self._attr_is_on = True

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._device.set_key_backlight(True)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._device.set_key_backlight(False)
        self._attr_is_on = False
        self.async_write_ha_state()

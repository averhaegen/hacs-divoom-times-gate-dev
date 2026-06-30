"""Button entities for the Times Gate (refresh, buzzer)."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    """Set up the Times Gate buttons."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            TimesGateRefreshButton(coordinator),
            TimesGateBuzzerButton(coordinator),
        ]
    )


class TimesGateRefreshButton(TimesGateEntity, ButtonEntity):
    """Force an immediate re-render and push of all screens."""

    _attr_name = "Refresh screens"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_refresh"

    async def async_press(self) -> None:
        await self.coordinator.async_force_refresh()


class TimesGateBuzzerButton(TimesGateEntity, ButtonEntity):
    """Play the device buzzer."""

    _attr_name = "Buzzer"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_buzzer"

    async def async_press(self) -> None:
        await self._device.play_buzzer()

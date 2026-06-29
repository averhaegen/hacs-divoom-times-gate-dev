"""Button entities for the Times Gate (refresh, buzzer)."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import TimesGateCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: TimesGateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            TimesGateRefreshButton(coordinator, entry),
            TimesGateBuzzerButton(coordinator, entry),
        ]
    )


class _BaseButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: TimesGateCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._device = coordinator.device
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})


class TimesGateRefreshButton(_BaseButton):
    _attr_name = "Refresh screens"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_refresh"

    async def async_press(self) -> None:
        await self._coordinator.async_refresh_now()


class TimesGateBuzzerButton(_BaseButton):
    _attr_name = "Buzzer"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_buzzer"

    async def async_press(self) -> None:
        await self._device.play_buzzer()

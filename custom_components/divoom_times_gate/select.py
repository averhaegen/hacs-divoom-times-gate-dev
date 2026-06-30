"""Select entities: Display source (device-level) + per-screen mode."""
from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import DivoomTimesGateConfigEntry
from .const import (
    CONF_FACES,
    DISPLAY_HA_DASHBOARD,
    DISPLAY_OFF,
    PREFIX_FACE,
    PREFIX_INDEPENDENT,
    PREFIX_OVERALL,
    SCREEN_COUNT,
    SCREEN_MODE_CUSTOM,
    SCREEN_MODE_OFF,
)
from .coordinator import TimesGateCoordinator
from .defaults import DEFAULT_FACES
from .entity import TimesGateEntity

PARALLEL_UPDATES = 1


def _faces(entry: DivoomTimesGateConfigEntry) -> dict[str, list[dict]]:
    return entry.options.get(CONF_FACES) or DEFAULT_FACES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DivoomTimesGateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SelectEntity] = [DisplaySourceSelect(coordinator, entry)]
    entities += [ScreenSelect(coordinator, entry, i) for i in range(SCREEN_COUNT)]
    async_add_entities(entities)


class DisplaySourceSelect(TimesGateEntity, SelectEntity, RestoreEntity):
    """Device-level: HA Dashboard / Overall Display / Independent Display / Off."""

    _attr_name = "Display source"

    def __init__(self, coordinator: TimesGateCoordinator, entry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_display_source"
        faces = _faces(entry)

        # label -> (kind, value)
        self._map: dict[str, tuple[str, Any]] = {
            DISPLAY_HA_DASHBOARD: ("dashboard", None),
            DISPLAY_OFF: ("off", None),
        }
        for f in faces.get("overall", []):
            self._map[f"{PREFIX_OVERALL}{f['name']}"] = ("overall", f["clock_id"])
        for preset in coordinator.presets:
            self._map[f"{PREFIX_INDEPENDENT}{preset.name}"] = (
                "independent",
                preset.independence_id,
            )
        self._attr_options = list(self._map)
        self._attr_current_option = DISPLAY_HA_DASHBOARD

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) and last.state in self._map:
            self._attr_current_option = last.state
            kind, value = self._map[last.state]
            await self.coordinator.async_set_display(kind, value)

    async def async_select_option(self, option: str) -> None:
        kind, value = self._map[option]
        self._attr_current_option = option
        await self.coordinator.async_set_display(kind, value)
        self.async_write_ha_state()


class ScreenSelect(TimesGateEntity, SelectEntity, RestoreEntity):
    """Per-screen: Custom / Off / Face: <name> (active in HA Dashboard mode)."""

    def __init__(self, coordinator: TimesGateCoordinator, entry, screen: int) -> None:
        super().__init__(coordinator)
        self._screen = screen
        self._attr_name = f"Screen {screen + 1}"
        self._attr_unique_id = f"{entry.entry_id}_screen_{screen}"

        self._map: dict[str, tuple[str, Any]] = {
            SCREEN_MODE_CUSTOM: ("custom", None),
            SCREEN_MODE_OFF: ("off", None),
        }
        for f in _faces(entry).get("per_screen", []):
            self._map[f"{PREFIX_FACE}{f['name']}"] = ("face", f["clock_id"])
        self._attr_options = list(self._map)
        self._attr_current_option = SCREEN_MODE_CUSTOM

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) and last.state in self._map:
            self._attr_current_option = last.state
            kind, value = self._map[last.state]
            await self.coordinator.async_set_screen(self._screen, kind, value)

    async def async_select_option(self, option: str) -> None:
        kind, value = self._map[option]
        self._attr_current_option = option
        await self.coordinator.async_set_screen(self._screen, kind, value)
        self.async_write_ha_state()

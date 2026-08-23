"""Image entities: a live preview of what HA last rendered on each screen.

Shows the exact JPEG the coordinator pushed to the panel. When a screen shows
native device content (a face, gif, visualizer or dispdata layout) there is
nothing HA rendered, so the preview reports no image.
"""
from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DivoomTimesGateConfigEntry
from .const import SCREEN_COUNT
from .coordinator import TimesGateCoordinator
from .entity import TimesGateEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DivoomTimesGateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one preview image per screen."""
    coordinator = entry.runtime_data
    async_add_entities(
        TimesGateScreenPreview(hass, coordinator, screen)
        for screen in range(SCREEN_COUNT)
    )


class TimesGateScreenPreview(TimesGateEntity, ImageEntity):
    """The last JPEG HA rendered and pushed to one of the five panels."""

    _attr_content_type = "image/jpeg"
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, coordinator: TimesGateCoordinator, screen: int) -> None:
        TimesGateEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)
        self._screen = screen
        self._attr_name = f"Screen {screen + 1} preview"
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_screen_{screen}_preview"
        )
        self._attr_image_last_updated = coordinator.last_frame_times.get(screen)

    @callback
    def _handle_coordinator_update(self) -> None:
        stamp = self.coordinator.last_frame_times.get(self._screen)
        if stamp != self._attr_image_last_updated:
            self._attr_image_last_updated = stamp
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        return self.coordinator.last_frames.get(self._screen)

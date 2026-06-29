"""Base entity for the Divoom Times Gate."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_IP_ADDRESS, DOMAIN
from .coordinator import TimesGateCoordinator
from .device import TimesGate


class TimesGateEntity(CoordinatorEntity[TimesGateCoordinator]):
    """Common base: device info + availability from the coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TimesGateCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._device: TimesGate = coordinator.device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Divoom Times Gate",
            manufacturer="Divoom",
            model="Times Gate",
            configuration_url=f"http://{entry.data[CONF_IP_ADDRESS]}",
        )

"""Base entity for the Divoom Times Gate."""
from __future__ import annotations

from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HARDWARE, CONF_IP_ADDRESS, CONF_MAC, DOMAIN
from .coordinator import TimesGateCoordinator
from .device import TimesGate


class TimesGateEntity(CoordinatorEntity[TimesGateCoordinator]):
    """Common base: device info + availability from the coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TimesGateCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._device: TimesGate = coordinator.device

        info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Divoom Times Gate",
            manufacturer="Divoom",
            model="Times Gate",
            configuration_url=f"http://{entry.data[CONF_IP_ADDRESS]}",
        )
        if hardware := entry.data.get(CONF_HARDWARE):
            info["hw_version"] = str(hardware)
        if mac := entry.data.get(CONF_MAC):
            info["connections"] = {(CONNECTION_NETWORK_MAC, format_mac(mac))}
        self._attr_device_info = info

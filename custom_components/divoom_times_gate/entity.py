"""Base entity for the Divoom Times Gate."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HARDWARE, CONF_IP_ADDRESS, CONF_MAC, DOMAIN
from .coordinator import TimesGateCoordinator
from .device import TimesGate


def screen_device_info(entry: ConfigEntry, screen: int) -> DeviceInfo:
    """DeviceInfo for a per-screen child device, nested under the main device."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_screen_{screen}")},
        name=f"Screen {screen + 1}",
        manufacturer="Divoom",
        model="Times Gate screen",
        via_device=(DOMAIN, entry.entry_id),
    )


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

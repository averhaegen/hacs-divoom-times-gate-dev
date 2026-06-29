"""Light entity for the Times Gate (brightness + on/off)."""
from __future__ import annotations

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_IP_ADDRESS, DOMAIN
from .coordinator import TimesGateCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: TimesGateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TimesGateLight(coordinator, entry)])


class TimesGateLight(LightEntity):
    """Controls the whole device display brightness + power."""

    _attr_has_entity_name = True
    _attr_name = "Display"
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, coordinator: TimesGateCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._device = coordinator.device
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_display"
        self._attr_is_on = True
        self._attr_brightness = 255
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Divoom Times Gate",
            manufacturer="Divoom",
            model="Times Gate",
            configuration_url=f"http://{entry.data[CONF_IP_ADDRESS]}",
        )

    async def async_added_to_hass(self) -> None:
        await self.async_update()

    async def async_update(self) -> None:
        conf = await self._device.get_conf()
        if conf.get("error_code") == 0:
            self._attr_is_on = conf.get("LightSwitch", 1) == 1
            self._attr_brightness = round(conf.get("Brightness", 100) * 255 / 100)

    async def async_turn_on(self, **kwargs) -> None:
        await self._device.turn_on()
        self._attr_is_on = True
        if (bri := kwargs.get("brightness")) is not None:
            await self._device.set_brightness(round(bri * 100 / 255))
            self._attr_brightness = bri
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self._device.turn_off()
        self._attr_is_on = False
        self.async_write_ha_state()

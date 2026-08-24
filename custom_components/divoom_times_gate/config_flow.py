"""Config and options flow for Divoom Times Gate."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    ObjectSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from .const import (
    AUTH_INVALID,
    AUTH_OK,
    CONF_ACTIVE_PRESET,
    CONF_DASHBOARD_BASE,
    CONF_DEVICE_ID,
    CONF_FACES,
    CONF_HARDWARE,
    CONF_IP_ADDRESS,
    CONF_LOCAL_TOKEN,
    CONF_MAC,
    CONF_PRESETS,
    CONF_REFRESH_INTERVAL,
    CONF_SCREENS,
    DEFAULT_HARDWARE,
    DEFAULT_PRESET,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    ENERGY_PRESET,
    SCREEN_COUNT,
)
from .defaults import DEFAULT_FACES, DEFAULT_SCREENS
from .device import TimesGate
from .discovery import DiscoveredDevice, async_discover_devices
from .energy import async_discover
from .presets import (
    active_screens,
    build_energy_preset,
    describe_page,
    read_presets,
)
from .starters import async_available_starters, get_starter

PRESET_ACTION = "preset_action"
PRESET_NAME = "preset_name"
STARTER_NONE = "starter_none"


class DivoomTimesGateConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow."""

    VERSION = 1
    _discovered: list[DiscoveredDevice] = []
    _entry_title: str = ""
    _entry_data: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        session = async_get_clientsession(self.hass)

        if not self._discovered:
            self._discovered = await async_discover_devices(session)

        if user_input is not None:
            ip = str(user_input[CONF_IP_ADDRESS]).strip()
            match = next((d for d in self._discovered if d.ip == ip), None)
            hardware = match.hardware if match else DEFAULT_HARDWARE
            device = TimesGate(ip, int(user_input[CONF_LOCAL_TOKEN]), session, hardware)
            if await device.ping():
                # Prefer the stable MAC as the unique id; fall back to the IP.
                await self.async_set_unique_id((match.mac if match else "") or ip)
                # Same device re-added (e.g. it got a new DHCP lease): update the
                # existing entry's IP/token in place and reload, instead of
                # forcing the user to delete and re-create the device.
                self._abort_if_unique_id_configured(
                    updates={
                        CONF_IP_ADDRESS: ip,
                        CONF_LOCAL_TOKEN: int(user_input[CONF_LOCAL_TOKEN]),
                        CONF_DEVICE_ID: match.device_id if match else 0,
                    }
                )
                self._entry_title = (
                    f"{match.name} ({ip})" if match else f"Times Gate ({ip})"
                )
                self._entry_data = {
                    CONF_IP_ADDRESS: ip,
                    CONF_LOCAL_TOKEN: int(user_input[CONF_LOCAL_TOKEN]),
                    CONF_HARDWARE: hardware,
                    CONF_MAC: match.mac if match else "",
                    CONF_DEVICE_ID: match.device_id if match else 0,
                    CONF_REFRESH_INTERVAL: user_input.get(
                        CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
                    ),
                }
                # The device answers, so the entry is a given. Ask what to put
                # on the screens before creating it: an options flow is a
                # second trip most users never take.
                return await self.async_step_starter()
            errors["base"] = "cannot_connect"

        # Discovered devices become a dropdown (still allows typing an IP manually).
        if self._discovered:
            ip_field: SelectSelector | type[str] = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=d.ip, label=f"{d.name} ({d.ip})")
                        for d in self._discovered
                    ],
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
            ip_default = self._discovered[0].ip
        else:
            ip_field = str
            ip_default = ""

        schema = vol.Schema(
            {
                vol.Required(CONF_IP_ADDRESS, default=ip_default): ip_field,
                vol.Required(CONF_LOCAL_TOKEN): int,
                vol.Optional(
                    CONF_REFRESH_INTERVAL, default=DEFAULT_REFRESH_INTERVAL
                ): int,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_starter(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer to fill the five screens before the entry is created.

        Only starters that found something are listed, so the menu never
        promises content the system cannot produce.
        """
        available = await async_available_starters(self.hass)
        found = "; ".join(f"{s.name}: {desc}" for s, desc in available)
        return self.async_show_menu(
            step_id="starter",
            menu_options=[f"starter_{s.key}" for s, _ in available] + [STARTER_NONE],
            description_placeholders={"found": found or "nothing"},
        )

    async def _finish(self, key: str) -> ConfigFlowResult:
        """Create the entry, with the chosen starter's screens as its options.

        The screens land in the ``default`` layout as ordinary configuration.
        Nothing regenerates them afterwards, so later edits stick.
        """
        options: dict[str, Any] = {}
        if starter := get_starter(key):
            options = {
                CONF_PRESETS: {DEFAULT_PRESET: await starter.async_build(self.hass)},
                CONF_ACTIVE_PRESET: DEFAULT_PRESET,
            }
        return self.async_create_entry(
            title=self._entry_title, data=self._entry_data or {}, options=options
        )

    async def async_step_starter_energy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._finish("energy")

    async def async_step_starter_clock_weather(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._finish("clock_weather")

    async def async_step_starter_none(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the entry with no screen configuration at all."""
        return await self._finish("")

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauth: the device stopped accepting the stored LocalToken."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh LocalToken and write it to the existing entry.

        The token changes when the user re-pairs the device in the Divoom app.
        Updating the entry in place keeps entity ids, area assignments, screen
        configuration and automations, which deleting and re-adding would not.
        """
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            token = int(user_input[CONF_LOCAL_TOKEN])
            device = TimesGate(
                entry.data[CONF_IP_ADDRESS],
                token,
                async_get_clientsession(self.hass),
                entry.data.get(CONF_HARDWARE, DEFAULT_HARDWARE),
            )
            status = await device.check_auth()
            if status == AUTH_OK:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_LOCAL_TOKEN: token}
                )
            errors["base"] = (
                "invalid_auth" if status == AUTH_INVALID else "cannot_connect"
            )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_LOCAL_TOKEN): int}),
            errors=errors,
            description_placeholders={
                "device": entry.title,
                "ip_address": entry.data.get(CONF_IP_ADDRESS, ""),
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change IP/token/interval on the existing entry (HA 'Reconfigure')."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        session = async_get_clientsession(self.hass)

        if user_input is not None:
            ip = str(user_input[CONF_IP_ADDRESS]).strip()
            token = int(user_input[CONF_LOCAL_TOKEN])
            device = TimesGate(
                ip, token, session, entry.data.get(CONF_HARDWARE, DEFAULT_HARDWARE)
            )
            if await device.ping():
                # Guard against pointing the entry at a *different* device: if
                # discovery knows the MAC at this IP and the entry has one
                # stored, they must match.
                discovered = await async_discover_devices(session)
                match = next((d for d in discovered if d.ip == ip), None)
                stored_mac = entry.data.get(CONF_MAC, "")
                if match and stored_mac and match.mac and match.mac != stored_mac:
                    return self.async_abort(reason="wrong_device")
                data_updates = {
                    CONF_IP_ADDRESS: ip,
                    CONF_LOCAL_TOKEN: token,
                    CONF_REFRESH_INTERVAL: int(
                        user_input.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL)
                    ),
                }
                if match:
                    data_updates[CONF_DEVICE_ID] = match.device_id
                old_ip = entry.data.get(CONF_IP_ADDRESS, "")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=data_updates,
                    title=entry.title.replace(old_ip, ip) if old_ip else entry.title,
                )
            errors["base"] = "cannot_connect"

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_IP_ADDRESS, default=entry.data.get(CONF_IP_ADDRESS, "")
                ): str,
                vol.Required(
                    CONF_LOCAL_TOKEN, default=entry.data.get(CONF_LOCAL_TOKEN)
                ): int,
                vol.Optional(
                    CONF_REFRESH_INTERVAL,
                    default=entry.data.get(
                        CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
                    ),
                ): int,
            }
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DivoomTimesGateOptionsFlow()


class DivoomTimesGateOptionsFlow(OptionsFlow):
    """Per-screen config split into a menu: each screen edited on its own."""

    _data: dict[str, Any] | None = None

    def _ensure(self) -> None:
        """Load a working copy of the options once."""
        if self._data is not None:
            return
        opts = dict(self.config_entry.options)
        presets = read_presets(opts)
        screens = list(active_screens(opts) or DEFAULT_SCREENS)
        while len(screens) < SCREEN_COUNT:
            screens.append({"page_type": "off"})
        screens = screens[:SCREEN_COUNT]
        name = str(opts.get(CONF_ACTIVE_PRESET) or "")
        if name not in presets:
            name = DEFAULT_PRESET if DEFAULT_PRESET in presets else (
                sorted(presets)[0] if presets else DEFAULT_PRESET
            )
        presets.setdefault(name, screens)
        self._data = {
            CONF_SCREENS: screens,
            CONF_PRESETS: presets,
            CONF_ACTIVE_PRESET: name,
            CONF_FACES: opts.get(CONF_FACES) or DEFAULT_FACES,
            CONF_DASHBOARD_BASE: opts.get(CONF_DASHBOARD_BASE, ""),
            CONF_REFRESH_INTERVAL: opts.get(
                CONF_REFRESH_INTERVAL,
                self.config_entry.data.get(
                    CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
                ),
            ),
        }

    def _fold(self) -> None:
        """Write the screens being edited back into the preset they belong to."""
        assert self._data is not None
        name = str(self._data[CONF_ACTIVE_PRESET] or DEFAULT_PRESET)
        self._data[CONF_ACTIVE_PRESET] = name
        self._data[CONF_PRESETS][name] = list(self._data[CONF_SCREENS])

    def _load(self, name: str) -> None:
        """Make ``name`` the preset the screen editors act on."""
        assert self._data is not None
        screens = list(self._data[CONF_PRESETS].get(name) or [])
        while len(screens) < SCREEN_COUNT:
            screens.append({"page_type": "off"})
        self._data[CONF_ACTIVE_PRESET] = name
        self._data[CONF_SCREENS] = screens[:SCREEN_COUNT]

    def _placeholders(self) -> dict[str, str]:
        """Name the preset being edited and what each of its screens holds."""
        assert self._data is not None
        parts = []
        for index, page in enumerate(self._data[CONF_SCREENS], start=1):
            parts.append(f"{index} {describe_page(page)}")
        return {
            "preset": str(self._data[CONF_ACTIVE_PRESET] or DEFAULT_PRESET),
            "screens": ", ".join(parts),
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure()
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "preset",
                "screen_0",
                "screen_1",
                "screen_2",
                "screen_3",
                "screen_4",
                "energy",
                "settings",
                "advanced",
                "save",
            ],
            description_placeholders=self._placeholders(),
        )

    async def _screen_step(
        self, index: int, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        self._ensure()
        assert self._data is not None
        if user_input is not None:
            pages = user_input.get(CONF_SCREENS)
            if isinstance(pages, (list, dict)):
                self._data[CONF_SCREENS][index] = pages
                self._fold()
                return await self.async_step_init()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCREENS, default=self._data[CONF_SCREENS][index]
                ): ObjectSelector()
            }
        )
        placeholders = self._placeholders()
        placeholders["current"] = describe_page(self._data[CONF_SCREENS][index])
        return self.async_show_form(
            step_id=f"screen_{index}",
            data_schema=schema,
            description_placeholders=placeholders,
            last_step=False,
        )

    async def async_step_screen_0(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._screen_step(0, user_input)

    async def async_step_screen_1(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._screen_step(1, user_input)

    async def async_step_screen_2(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._screen_step(2, user_input)

    async def async_step_screen_3(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._screen_step(3, user_input)

    async def async_step_screen_4(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._screen_step(4, user_input)

    async def async_step_preset(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Switch between named sets of five screens, or add and remove one."""
        self._ensure()
        assert self._data is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            self._fold()
            chosen = str(user_input.get(CONF_ACTIVE_PRESET) or DEFAULT_PRESET)
            action = str(user_input.get(PRESET_ACTION) or "switch")
            name = str(user_input.get(PRESET_NAME) or "").strip()
            presets = self._data[CONF_PRESETS]
            if action == "switch":
                self._load(chosen)
                return await self.async_step_init()
            if action == "delete":
                if len(presets) < 2:
                    errors["base"] = "preset_last"
                else:
                    presets.pop(chosen, None)
                    self._load(sorted(presets)[0])
                    return await self.async_step_init()
            elif not name:
                errors[PRESET_NAME] = "preset_name_required"
            elif name in presets:
                errors[PRESET_NAME] = "preset_name_taken"
            elif action == "create":
                presets[name] = [{"page_type": "off"} for _ in range(SCREEN_COUNT)]
                self._load(name)
                return await self.async_step_init()
            elif action == "copy":
                presets[name] = list(presets.get(chosen) or [])
                self._load(name)
                return await self.async_step_init()
            elif action == "rename":
                presets[name] = presets.pop(chosen, list(self._data[CONF_SCREENS]))
                self._load(name)
                return await self.async_step_init()

        names = sorted(self._data[CONF_PRESETS]) or [DEFAULT_PRESET]
        actions = ["switch", "create", "copy", "rename", "delete"]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ACTIVE_PRESET,
                    default=self._data[CONF_ACTIVE_PRESET] or names[0],
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[SelectOptionDict(value=n, label=n) for n in names],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(PRESET_ACTION, default="switch"): SelectSelector(
                    SelectSelectorConfig(
                        options=actions,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="preset_action",
                    )
                ),
                vol.Optional(PRESET_NAME, default=""): str,
            }
        )
        return self.async_show_form(
            step_id="preset",
            data_schema=schema,
            errors=errors,
            description_placeholders=self._placeholders(),
            last_step=False,
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit every preset at once, for copying a set of screens in or out."""
        self._ensure()
        assert self._data is not None
        if user_input is not None:
            presets = user_input.get(CONF_PRESETS)
            if isinstance(presets, dict):
                self._data[CONF_PRESETS] = {
                    str(name): list(screens)
                    for name, screens in presets.items()
                    if isinstance(screens, list)
                }
                name = str(self._data[CONF_ACTIVE_PRESET] or DEFAULT_PRESET)
                self._load(name if name in self._data[CONF_PRESETS] else
                           (sorted(self._data[CONF_PRESETS]) or [DEFAULT_PRESET])[0])
            return await self.async_step_init()

        self._fold()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PRESETS, default=self._data[CONF_PRESETS]
                ): ObjectSelector()
            }
        )
        return self.async_show_form(
            step_id="advanced",
            data_schema=schema,
            description_placeholders=self._placeholders(),
            last_step=False,
        )

    async def async_step_energy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Fill all five screens from the Home Assistant energy dashboard.

        The generated pages are written into the working copy as ordinary
        screens, so you can edit any of them afterwards and the generator will
        not touch them again unless you come back here.
        """
        self._ensure()
        assert self._data is not None
        found = await async_discover(self.hass)
        if user_input is not None:
            # Keep whatever was being edited under its own name before the
            # generated screens take over.
            self._fold()
            name = str(user_input.get(PRESET_NAME) or "").strip() or ENERGY_PRESET
            self._data[CONF_PRESETS][name] = build_energy_preset(found)
            self._load(name)
            return await self.async_step_init()

        parts = []
        if found.price_now:
            parts.append("price")
        if found.has_solar:
            parts.append("solar")
        if found.has_battery:
            parts.append("battery")
        if found.has_electricity:
            parts.append("grid")
        if found.gas_stat:
            parts.append("gas")
        if found.water_stats:
            parts.append("water")
        return self.async_show_form(
            step_id="energy",
            data_schema=vol.Schema(
                {vol.Optional(PRESET_NAME, default=ENERGY_PRESET): str}
            ),
            description_placeholders={
                "found": ", ".join(parts) or "nothing (check your energy dashboard)"
            },
            last_step=False,
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure()
        assert self._data is not None
        if user_input is not None:
            self._data[CONF_REFRESH_INTERVAL] = int(user_input[CONF_REFRESH_INTERVAL])
            self._data[CONF_DASHBOARD_BASE] = user_input.get(CONF_DASHBOARD_BASE, "")
            if isinstance(user_input.get(CONF_FACES), dict):
                self._data[CONF_FACES] = user_input[CONF_FACES]
            return await self.async_step_init()

        # Build the base-preset options from the device's presets.
        coordinator = self.config_entry.runtime_data
        presets = getattr(coordinator, "presets", []) if coordinator else []
        base_options = [SelectOptionDict(value="", label="Leave device as-is")]
        base_options += [
            SelectOptionDict(value=str(p.position), label=p.name) for p in presets
        ]

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_REFRESH_INTERVAL, default=self._data[CONF_REFRESH_INTERVAL]
                ): NumberSelector(
                    NumberSelectorConfig(min=5, max=3600, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_DASHBOARD_BASE,
                    default=str(self._data.get(CONF_DASHBOARD_BASE, "")),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=base_options, mode=SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required(
                    CONF_FACES, default=self._data[CONF_FACES]
                ): ObjectSelector(),
            }
        )
        return self.async_show_form(
            step_id="settings", data_schema=schema, last_step=False
        )

    async def async_step_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure()
        # _ensure() always populates _data.
        assert self._data is not None
        # The screen editors always act on the active preset, so fold the edits
        # back into it before saving.
        self._fold()
        return self.async_create_entry(title="", data=dict(self._data))

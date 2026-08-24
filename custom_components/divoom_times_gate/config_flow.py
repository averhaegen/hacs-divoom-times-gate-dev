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
    EntitySelector,
    EntitySelectorConfig,
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

from . import page_forms
from .cards import MAX_SLOTS, THEMES
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
from .starters import (
    async_available_starters,
    describe_energy,
    get_starter,
    pad,
)

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
    """A menu over the five screens, with every step committing on its own.

    There is no "save and close" here. An options edit reloads the config entry
    either way, so holding a working copy across steps bought nothing and cost
    everything a user typed the moment they navigated away.
    """

    _data: dict[str, Any] | None = None
    _index: int = 0

    def _ensure(self) -> None:
        """Load the options into the shape the steps work on."""
        if self._data is not None:
            return
        opts = dict(self.config_entry.options)
        presets = read_presets(opts)
        screens = pad(list(active_screens(opts) or DEFAULT_SCREENS))
        name = str(opts.get(CONF_ACTIVE_PRESET) or "")
        if name not in presets:
            name = DEFAULT_PRESET if DEFAULT_PRESET in presets else (
                sorted(presets)[0] if presets else DEFAULT_PRESET
            )
        # Pad here rather than at read time: every step below indexes all five
        # screens, and a layout stored short would raise on screen 5.
        presets[name] = pad(list(presets.get(name) or screens))
        self._data = {
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

    @property
    def _screens(self) -> list[Any]:
        """The five screens of the layout being edited."""
        assert self._data is not None
        screens: list[Any] = self._data[CONF_PRESETS][self._data[CONF_ACTIVE_PRESET]]
        return screens

    def _write(self, index: int, pages: Any) -> ConfigFlowResult:
        """Store one screen and commit."""
        assert self._data is not None
        screens = list(self._screens)
        screens[index] = pages
        self._data[CONF_PRESETS][self._data[CONF_ACTIVE_PRESET]] = screens
        return self._commit()

    def _load(self, name: str) -> None:
        """Make ``name`` the layout the screen editors act on."""
        assert self._data is not None
        self._data[CONF_ACTIVE_PRESET] = name
        self._data[CONF_PRESETS][name] = pad(
            list(self._data[CONF_PRESETS].get(name) or [])
        )

    def _commit(self) -> ConfigFlowResult:
        """Write the options back and let Home Assistant reload the entry.

        ``screens`` is deliberately not written any more. It is still read
        forever, because ``read_presets`` folds a pre-layout ``screens`` list
        into the ``default`` layout, but keeping a second copy of the active
        layout in the options only invited the two to drift apart.
        """
        assert self._data is not None
        return self.async_create_entry(title="", data=dict(self._data))

    def _placeholders(self) -> dict[str, str]:
        """Name the layout being edited and what each of its screens holds."""
        assert self._data is not None
        parts = [
            f"{index} {describe_page(page)}"
            for index, page in enumerate(self._screens, start=1)
        ]
        return {
            "preset": str(self._data[CONF_ACTIVE_PRESET] or DEFAULT_PRESET),
            "screens": ", ".join(parts),
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The menu. Screens first, each labelled with what it holds."""
        self._ensure()
        assert self._data is not None
        menu: dict[str, str] = {
            f"screen_{index}": f"Screen {index + 1}: {describe_page(page)}"
            for index, page in enumerate(self._screens)
        }
        menu["energy"] = "Build energy screens"
        # One layout is just "the screens", so the switcher is noise until
        # there is something to switch between.
        if len(self._data[CONF_PRESETS]) > 1:
            menu["layout"] = f"Layout: {self._data[CONF_ACTIVE_PRESET]}"
        menu["settings"] = "Settings and faces"
        menu["advanced"] = "Edit all layouts as YAML"
        return self.async_show_menu(
            step_id="init",
            menu_options=menu,
            description_placeholders=self._placeholders(),
        )

    # --- screens -----------------------------------------------------------

    async def _screen_step(
        self, index: int, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """A menu per screen, offering only the editors this page survives."""
        self._ensure()
        self._index = index
        pages = self._screens[index]
        reason = page_forms.unsupported_reason(pages)
        placeholders = self._placeholders()
        placeholders["current"] = describe_page(pages)
        placeholders["reason"] = (
            ""
            if reason is None
            else (
                f"This screen can only be edited as YAML, because {reason}. "
                "A form would drop that."
            )
        )
        menu = (
            ["screen_yaml"]
            if reason is not None
            else ["screen_sensors", "screen_face", "screen_off", "screen_yaml"]
        )
        return self.async_show_menu(
            step_id=f"screen_{index}",
            menu_options=menu,
            description_placeholders=placeholders,
        )

    def _screen_placeholders(self) -> dict[str, str]:
        placeholders = self._placeholders()
        placeholders["screen"] = str(self._index + 1)
        placeholders["current"] = describe_page(self._screens[self._index])
        return placeholders

    async def async_step_screen_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick entities and a theme; the rest of the card is derived."""
        self._ensure()
        errors: dict[str, str] = {}
        defaults = page_forms.sensor_defaults(self._screens[self._index])
        if user_input is not None:
            entities = list(user_input.get(page_forms.CONF_ENTITIES) or [])
            if not entities:
                errors[page_forms.CONF_ENTITIES] = "entities_required"
            elif len(entities) > MAX_SLOTS:
                errors[page_forms.CONF_ENTITIES] = "too_many_entities"
            else:
                return self._write(self._index, page_forms.sensor_page(user_input))
            defaults = dict(user_input)
        schema = vol.Schema(
            {
                vol.Required(
                    page_forms.CONF_ENTITIES,
                    default=defaults[page_forms.CONF_ENTITIES],
                ): EntitySelector(EntitySelectorConfig(multiple=True)),
                vol.Required(
                    page_forms.CONF_THEME, default=defaults[page_forms.CONF_THEME]
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=name, label=name.replace("_", " "))
                            for name in sorted(THEMES)
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    page_forms.CONF_DURATION, default=defaults[page_forms.CONF_DURATION]
                ): NumberSelector(
                    NumberSelectorConfig(min=5, max=600, mode=NumberSelectorMode.BOX)
                ),
            }
        )
        placeholders = self._screen_placeholders()
        placeholders["max"] = str(MAX_SLOTS)
        return self.async_show_form(
            step_id="screen_sensors",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    def _face_options(self, current: str) -> list[SelectOptionDict]:
        """The configured favorites, plus whatever this screen already shows."""
        assert self._data is not None
        faces = self._data.get(CONF_FACES) or {}
        per_screen = faces.get("per_screen") or []
        options = [
            SelectOptionDict(value=str(face["clock_id"]), label=str(face["name"]))
            for face in per_screen
            if isinstance(face, dict) and face.get("clock_id") is not None
        ]
        if current not in {option["value"] for option in options} and current != "0":
            options.insert(0, SelectOptionDict(value=current, label=f"Face {current}"))
        return options

    async def async_step_screen_face(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Hand the screen back to a native face."""
        self._ensure()
        defaults = page_forms.face_defaults(self._screens[self._index])
        if user_input is not None:
            return self._write(self._index, page_forms.face_page(user_input))
        options = self._face_options(str(defaults[page_forms.CONF_CLOCK_ID]))
        if not options:
            return self.async_abort(reason="no_faces")
        current = str(defaults[page_forms.CONF_CLOCK_ID])
        schema = vol.Schema(
            {
                vol.Required(
                    page_forms.CONF_CLOCK_ID,
                    default=current
                    if current in {option["value"] for option in options}
                    else options[0]["value"],
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=options, mode=SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required(
                    page_forms.CONF_DURATION, default=defaults[page_forms.CONF_DURATION]
                ): NumberSelector(
                    NumberSelectorConfig(min=5, max=600, mode=NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(
            step_id="screen_face",
            data_schema=schema,
            description_placeholders=self._screen_placeholders(),
        )

    async def async_step_screen_off(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Turn the screen black. No form, there is nothing to ask."""
        self._ensure()
        return self._write(self._index, page_forms.off_page())

    async def async_step_screen_yaml(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The escape hatch. Everything a form refuses stays editable here."""
        self._ensure()
        index = self._index
        if user_input is not None:
            pages = user_input.get(CONF_SCREENS)
            if isinstance(pages, list | dict):
                return self._write(index, pages)
        schema = vol.Schema(
            {vol.Required(CONF_SCREENS, default=self._screens[index]): ObjectSelector()}
        )
        return self.async_show_form(
            step_id="screen_yaml",
            data_schema=schema,
            description_placeholders=self._screen_placeholders(),
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

    # --- layouts -----------------------------------------------------------

    def _layout_select(self, key: str) -> vol.Schema:
        """A dropdown of layout names, defaulting to the active one."""
        assert self._data is not None
        names = sorted(self._data[CONF_PRESETS]) or [DEFAULT_PRESET]
        default = str(self._data[CONF_ACTIVE_PRESET] or names[0])
        return vol.Schema(
            {
                vol.Required(key, default=default): SelectSelector(
                    SelectSelectorConfig(
                        options=[SelectOptionDict(value=n, label=n) for n in names],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

    async def async_step_layout(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """One action per menu entry, instead of one form with an action field."""
        self._ensure()
        return self.async_show_menu(
            step_id="layout",
            menu_options=["layout_switch", "layout_copy", "layout_delete"],
            description_placeholders=self._placeholders(),
        )

    async def async_step_layout_switch(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Swap all five screens at once."""
        self._ensure()
        if user_input is not None:
            self._load(str(user_input[CONF_ACTIVE_PRESET]))
            return self._commit()
        return self.async_show_form(
            step_id="layout_switch",
            data_schema=self._layout_select(CONF_ACTIVE_PRESET),
            description_placeholders=self._placeholders(),
        )

    async def async_step_layout_copy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Save the screens being edited under a second name."""
        self._ensure()
        assert self._data is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            name = str(user_input.get(PRESET_NAME) or "").strip()
            if not name:
                errors[PRESET_NAME] = "preset_name_required"
            elif name in self._data[CONF_PRESETS]:
                errors[PRESET_NAME] = "preset_name_taken"
            else:
                self._data[CONF_PRESETS][name] = list(self._screens)
                self._load(name)
                return self._commit()
        return self.async_show_form(
            step_id="layout_copy",
            data_schema=vol.Schema({vol.Required(PRESET_NAME, default=""): str}),
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    async def async_step_layout_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove a layout, never the last one."""
        self._ensure()
        assert self._data is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            name = str(user_input[CONF_ACTIVE_PRESET])
            if len(self._data[CONF_PRESETS]) < 2:
                errors["base"] = "preset_last"
            else:
                self._data[CONF_PRESETS].pop(name, None)
                self._load(sorted(self._data[CONF_PRESETS])[0])
                return self._commit()
        return self.async_show_form(
            step_id="layout_delete",
            data_schema=self._layout_select(CONF_ACTIVE_PRESET),
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    # --- everything else ---------------------------------------------------

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit every layout at once, for copying a set of screens in or out."""
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
            return self._commit()

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
        )

    async def async_step_energy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Fill all five screens from the Home Assistant energy dashboard.

        The generated pages are written as ordinary screens, so you can edit
        any of them afterwards and the generator will not touch them again
        unless you come back here.
        """
        self._ensure()
        assert self._data is not None
        found = await async_discover(self.hass)
        if user_input is not None:
            name = str(user_input.get(PRESET_NAME) or "").strip() or ENERGY_PRESET
            self._data[CONF_PRESETS][name] = build_energy_preset(found)
            self._load(name)
            return self._commit()

        return self.async_show_form(
            step_id="energy",
            data_schema=vol.Schema(
                {vol.Optional(PRESET_NAME, default=ENERGY_PRESET): str}
            ),
            description_placeholders={
                "found": describe_energy(found)
                or "nothing (check your energy dashboard)"
            },
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
            return self._commit()

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
        return self.async_show_form(step_id="settings", data_schema=schema)

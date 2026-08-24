"""Tests for the config, reconfigure, and options flows.

Home Assistant's Bronze rule ``config-flow-test-coverage`` asks for every step
and every abort or error path of ``config_flow.py``.

One note on error strings: this flow has no ``invalid_auth``. A wrong
``LocalToken`` makes the device answer ``error_code != 0``, so ``ping()``
returns ``False`` and the user sees ``cannot_connect``, same as an unreachable
IP. The tests assert that on purpose.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.divoom_times_gate.const import (
    CONF_DASHBOARD_BASE,
    CONF_DEVICE_ID,
    CONF_FACES,
    CONF_HARDWARE,
    CONF_IP_ADDRESS,
    CONF_LOCAL_TOKEN,
    CONF_MAC,
    CONF_REFRESH_INTERVAL,
    CONF_SCREENS,
    DEFAULT_HARDWARE,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
)
from custom_components.divoom_times_gate.discovery import IndependentPreset

from .conftest import make_discovered

FLOW = "custom_components.divoom_times_gate.config_flow"


def patch_discovery(devices=None):
    """Patch cloud LAN discovery as used by the config flow."""
    return patch(f"{FLOW}.async_discover_devices", AsyncMock(return_value=devices or []))


def patch_ping(result: bool = True):
    """Patch ``TimesGate.ping`` without touching the network."""
    return patch(f"{FLOW}.TimesGate.ping", AsyncMock(return_value=result))


def patch_setup():
    """Stop the entry from actually being set up after creation."""
    return patch(
        "custom_components.divoom_times_gate.async_setup_entry",
        AsyncMock(return_value=True),
    )


async def leave_screens_empty(hass, result):
    """Walk the starter menu past the last user step without generating pages."""
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "starter"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "starter_none"}
    )


# --- user step -------------------------------------------------------------


async def test_user_step_shows_form_when_nothing_is_discovered(hass) -> None:
    """With no discovery hits the IP field is a plain text box."""
    with patch_discovery():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_user_step_offers_discovered_devices_as_a_dropdown(hass) -> None:
    """Discovery results become dropdown options, defaulting to the first."""
    devices = [
        make_discovered(name="Times Gate", ip="192.168.1.25"),
        make_discovered(name="Pixoo64", ip="192.168.1.30", mac="11:22:33:44:55:66"),
    ]
    with patch_discovery(devices):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

    assert result["type"] is FlowResultType.FORM
    markers = {str(key): key for key in result["data_schema"].schema}
    assert markers[CONF_IP_ADDRESS].default() == "192.168.1.25"


async def test_user_step_creates_entry_from_a_discovered_device(hass) -> None:
    """A discovered match supplies the MAC, hardware, device id, and title."""
    device = make_discovered(name="Times Gate", hardware=400, device_id=4242)

    with patch_discovery([device]), patch_ping(True), patch_setup():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_IP_ADDRESS: "192.168.1.25", CONF_LOCAL_TOKEN: 123456},
        )
        result = await leave_screens_empty(hass, result)
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Times Gate (192.168.1.25)"
    assert result["data"] == {
        CONF_IP_ADDRESS: "192.168.1.25",
        CONF_LOCAL_TOKEN: 123456,
        CONF_HARDWARE: 400,
        CONF_MAC: "aa:bb:cc:dd:ee:ff",
        CONF_DEVICE_ID: 4242,
        CONF_REFRESH_INTERVAL: DEFAULT_REFRESH_INTERVAL,
    }
    assert result["result"].unique_id == "aa:bb:cc:dd:ee:ff"


async def test_user_step_accepts_a_manually_typed_ip(hass) -> None:
    """No discovery match means default hardware, no MAC, IP as the unique id."""
    with patch_discovery(), patch_ping(True), patch_setup():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_IP_ADDRESS: "  10.0.0.9  ",
                CONF_LOCAL_TOKEN: 654321,
                CONF_REFRESH_INTERVAL: 30,
            },
        )
        result = await leave_screens_empty(hass, result)
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Times Gate (10.0.0.9)"
    assert result["data"][CONF_IP_ADDRESS] == "10.0.0.9"
    assert result["data"][CONF_LOCAL_TOKEN] == 654321
    assert result["data"][CONF_HARDWARE] == DEFAULT_HARDWARE
    assert result["data"][CONF_MAC] == ""
    assert result["data"][CONF_DEVICE_ID] == 0
    assert result["data"][CONF_REFRESH_INTERVAL] == 30
    assert result["result"].unique_id == "10.0.0.9"


async def test_user_step_reports_cannot_connect_when_ping_fails(hass) -> None:
    """An unreachable device or a wrong LocalToken both surface the same way."""
    with patch_discovery(), patch_ping(False):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_IP_ADDRESS: "192.168.1.25", CONF_LOCAL_TOKEN: 1},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_step_recovers_after_a_failed_attempt(hass) -> None:
    """The user can fix the token and continue in the same flow."""
    with patch_discovery(), patch_ping(False):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_IP_ADDRESS: "192.168.1.25", CONF_LOCAL_TOKEN: 1}
        )
    assert result["errors"] == {"base": "cannot_connect"}

    with patch_discovery(), patch_ping(True), patch_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_IP_ADDRESS: "192.168.1.25", CONF_LOCAL_TOKEN: 123456}
        )
        result = await leave_screens_empty(hass, result)
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_step_aborts_when_the_device_is_already_configured(
    hass, mock_config_entry
) -> None:
    """Re-adding the same MAC aborts instead of creating a duplicate entry."""
    mock_config_entry.add_to_hass(hass)
    device = make_discovered(mac="aa:bb:cc:dd:ee:ff", ip="192.168.1.99", device_id=9999)

    with patch_discovery([device]), patch_ping(True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_IP_ADDRESS: "192.168.1.99", CONF_LOCAL_TOKEN: 777},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # A new DHCP lease should update the entry in place, not force a re-add.
    assert mock_config_entry.data[CONF_IP_ADDRESS] == "192.168.1.99"
    assert mock_config_entry.data[CONF_LOCAL_TOKEN] == 777
    assert mock_config_entry.data[CONF_DEVICE_ID] == 9999


async def test_user_step_runs_discovery_only_once_per_flow(hass) -> None:
    """The cached result stops a cloud call on every form redisplay."""
    discover = AsyncMock(return_value=[make_discovered()])
    with patch(f"{FLOW}.async_discover_devices", discover), patch_ping(False):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_IP_ADDRESS: "192.168.1.25", CONF_LOCAL_TOKEN: 1}
        )

    assert discover.await_count == 1


# --- reconfigure step ------------------------------------------------------


async def test_reconfigure_shows_the_current_values(hass, mock_config_entry) -> None:
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    markers = {str(key): key for key in result["data_schema"].schema}
    assert markers[CONF_IP_ADDRESS].default() == "192.168.1.25"
    assert markers[CONF_LOCAL_TOKEN].default() == 123456


async def test_reconfigure_updates_ip_token_and_title(hass, mock_config_entry) -> None:
    """The title carries the IP, so it has to follow the new address."""
    mock_config_entry.add_to_hass(hass)
    device = make_discovered(ip="192.168.1.77", device_id=8888)

    with patch_discovery([device]), patch_ping(True), patch_setup():
        result = await mock_config_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_IP_ADDRESS: "192.168.1.77",
                CONF_LOCAL_TOKEN: 999,
                CONF_REFRESH_INTERVAL: 45,
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_IP_ADDRESS] == "192.168.1.77"
    assert mock_config_entry.data[CONF_LOCAL_TOKEN] == 999
    assert mock_config_entry.data[CONF_REFRESH_INTERVAL] == 45
    assert mock_config_entry.data[CONF_DEVICE_ID] == 8888
    assert mock_config_entry.title == "Times Gate (192.168.1.77)"


async def test_reconfigure_without_a_discovery_match_keeps_the_device_id(
    hass, mock_config_entry
) -> None:
    """Nothing found at the new IP means the stored device id stays untouched."""
    mock_config_entry.add_to_hass(hass)

    with patch_discovery(), patch_ping(True), patch_setup():
        result = await mock_config_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_IP_ADDRESS: "192.168.1.88", CONF_LOCAL_TOKEN: 123456},
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_DEVICE_ID] == 4242
    assert mock_config_entry.data[CONF_REFRESH_INTERVAL] == DEFAULT_REFRESH_INTERVAL


async def test_reconfigure_keeps_the_title_when_no_ip_is_stored(hass) -> None:
    """An entry without an IP has nothing to substitute in the title."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Times Gate",
        unique_id="no-ip",
        data={CONF_LOCAL_TOKEN: 123456, CONF_HARDWARE: DEFAULT_HARDWARE},
    )
    entry.add_to_hass(hass)

    with patch_discovery(), patch_ping(True), patch_setup():
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_IP_ADDRESS: "192.168.1.25", CONF_LOCAL_TOKEN: 123456},
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.title == "Times Gate"


async def test_reconfigure_reports_cannot_connect(hass, mock_config_entry) -> None:
    mock_config_entry.add_to_hass(hass)

    with patch_ping(False):
        result = await mock_config_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_IP_ADDRESS: "192.168.1.99", CONF_LOCAL_TOKEN: 123456},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert mock_config_entry.data[CONF_IP_ADDRESS] == "192.168.1.25"


async def test_reconfigure_aborts_when_the_ip_belongs_to_another_device(
    hass, mock_config_entry
) -> None:
    """Repointing an entry at a different unit would silently swap devices."""
    mock_config_entry.add_to_hass(hass)
    other = make_discovered(ip="192.168.1.50", mac="99:88:77:66:55:44")

    with patch_discovery([other]), patch_ping(True):
        result = await mock_config_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_IP_ADDRESS: "192.168.1.50", CONF_LOCAL_TOKEN: 123456},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert mock_config_entry.data[CONF_IP_ADDRESS] == "192.168.1.25"


@pytest.mark.parametrize(
    ("stored_mac", "found_mac"),
    [
        ("", "99:88:77:66:55:44"),  # entry has no MAC to compare against
        ("aa:bb:cc:dd:ee:ff", ""),  # discovery returned no MAC
        ("aa:bb:cc:dd:ee:ff", "aa:bb:cc:dd:ee:ff"),  # same device, new lease
    ],
)
async def test_reconfigure_allows_the_move_when_macs_cannot_disagree(
    hass, mock_config_entry, stored_mac, found_mac
) -> None:
    """The wrong_device guard only fires when both MACs are known and differ."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_MAC: stored_mac}
    )
    found = make_discovered(ip="192.168.1.50", mac=found_mac)

    with patch_discovery([found]), patch_ping(True), patch_setup():
        result = await mock_config_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_IP_ADDRESS: "192.168.1.50", CONF_LOCAL_TOKEN: 123456},
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_IP_ADDRESS] == "192.168.1.50"


# --- options flow ----------------------------------------------------------


async def test_options_flow_opens_a_menu(hass, mock_config_entry) -> None:
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == [
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
    ]
    # The menu names the preset being edited and what each screen holds.
    assert result["description_placeholders"]["preset"]
    assert result["description_placeholders"]["screens"]


@pytest.mark.parametrize("index", [0, 1, 2, 3, 4])
async def test_each_screen_step_stores_its_own_pages(
    hass, mock_config_entry, index
) -> None:
    """Each screen is its own rotating page list, edited independently."""
    mock_config_entry.add_to_hass(hass)
    pages = [{"page_type": "clock", "clock_id": 61, "duration": 8}]

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": f"screen_{index}"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == f"screen_{index}"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCREENS: pages}
    )
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "save"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SCREENS][index] == pages


async def test_screen_step_redisplays_the_form_for_a_non_container_value(
    hass, mock_config_entry
) -> None:
    """A scalar is not a page list, so it must not be written to the options."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "screen_0"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCREENS: "not-a-page-list"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "screen_0"


async def test_options_pad_missing_screens_with_off(hass, mock_config_entry) -> None:
    """A short screens list must still cover all five physical screens."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={**mock_config_entry.options, CONF_SCREENS: [[{"page_type": "clock"}]]},
    )

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "save"}
    )

    screens = result["data"][CONF_SCREENS]
    assert len(screens) == 5
    assert screens[1:] == [{"page_type": "off"}] * 4


async def test_settings_step_lists_independent_presets_by_position(
    hass, mock_config_entry
) -> None:
    """Independence ids are per-unit, so the dropdown keys on the slot instead."""
    mock_config_entry.add_to_hass(hass)
    coordinator = type(
        "Coordinator",
        (),
        {
            "presets": [
                IndependentPreset("Control1", 111, 0),
                IndependentPreset("Control2", 222, 1),
            ]
        },
    )()
    mock_config_entry.runtime_data = coordinator

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )

    assert result["type"] is FlowResultType.FORM
    fields = {str(key): value for key, value in result["data_schema"].schema.items()}
    options = fields[CONF_DASHBOARD_BASE].config["options"]
    assert [entry["value"] for entry in options] == ["", "0", "1"]
    assert [entry["label"] for entry in options] == [
        "Leave device as-is",
        "Control1",
        "Control2",
    ]


async def test_settings_step_without_a_loaded_coordinator(
    hass, mock_config_entry
) -> None:
    """Editing options before setup finishes must not crash the flow."""
    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = None

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )

    fields = {str(key): value for key, value in result["data_schema"].schema.items()}
    options = fields[CONF_DASHBOARD_BASE].config["options"]
    assert [entry["value"] for entry in options] == [""]


async def test_settings_step_without_a_presets_attribute(
    hass, mock_config_entry
) -> None:
    """A coordinator that never read the presets is treated as having none."""
    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = object()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )

    fields = {str(key): value for key, value in result["data_schema"].schema.items()}
    assert fields[CONF_DASHBOARD_BASE].config["options"] == [
        {"value": "", "label": "Leave device as-is"}
    ]


async def test_settings_step_saves_interval_base_and_faces(
    hass, mock_config_entry
) -> None:
    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = type(
        "Coordinator", (), {"presets": [IndependentPreset("Control3", 333, 2)]}
    )()
    faces = {"Clock": 61, "Weather": 62}

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_REFRESH_INTERVAL: "20", CONF_DASHBOARD_BASE: "2", CONF_FACES: faces},
    )
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "save"}
    )

    assert result["data"][CONF_REFRESH_INTERVAL] == 20
    assert result["data"][CONF_DASHBOARD_BASE] == "2"
    assert result["data"][CONF_FACES] == faces


async def test_settings_step_ignores_a_non_dict_face_map(
    hass, mock_config_entry
) -> None:
    """Faces map names to ClockIds; anything else keeps the previous map."""
    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = None
    original = dict(mock_config_entry.options[CONF_FACES])

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_REFRESH_INTERVAL: 15, CONF_FACES: ["not", "a", "map"]}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "save"}
    )

    assert result["data"][CONF_FACES] == original
    assert result["data"][CONF_DASHBOARD_BASE] == ""


async def test_options_fall_back_to_defaults_when_unset(hass) -> None:
    """An entry with empty options still yields a full, valid working copy."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Times Gate (192.168.1.25)",
        unique_id="bare",
        data={
            CONF_IP_ADDRESS: "192.168.1.25",
            CONF_LOCAL_TOKEN: 1,
            CONF_HARDWARE: DEFAULT_HARDWARE,
            CONF_REFRESH_INTERVAL: 42,
        },
        options={},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "save"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(result["data"][CONF_SCREENS]) == 5
    assert result["data"][CONF_FACES]
    assert result["data"][CONF_DASHBOARD_BASE] == ""
    # The interval falls back to the value stored on the entry data.
    assert result["data"][CONF_REFRESH_INTERVAL] == 42

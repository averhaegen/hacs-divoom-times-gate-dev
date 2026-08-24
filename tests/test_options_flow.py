"""Tests for the options flow.

Two properties matter most here and both are regressions waiting to happen:

* Every step commits on its own. The flow used to hold a working copy that was
  only written by a "Save & close" step, so navigating away silently discarded
  everything the user had typed.
* An edit lands in the layout the clock is actually showing, and leaves the
  other layouts alone.
"""
from __future__ import annotations

import pytest

from custom_components.divoom_times_gate.config_flow import DivoomTimesGateOptionsFlow
from custom_components.divoom_times_gate.const import (
    CONF_ACTIVE_PRESET,
    CONF_DASHBOARD_BASE,
    CONF_FACES,
    CONF_PRESETS,
    CONF_REFRESH_INTERVAL,
    CONF_SCREENS,
    DEFAULT_PRESET,
    SCREEN_COUNT,
)
from custom_components.divoom_times_gate.discovery import IndependentPreset

OFF = {"page_type": "off"}
CLOCK = {"page_type": "clock"}


async def open_options(hass, entry, options: dict | None = None):
    """Add the entry, set its options, and open the options menu."""
    entry.add_to_hass(hass)
    if options is not None:
        hass.config_entries.async_update_entry(entry, options=options)
    return await hass.config_entries.options.async_init(entry.entry_id)


async def pick(hass, result, step: str):
    """Choose a menu entry."""
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


async def submit(hass, result, payload: dict):
    """Submit a form."""
    return await hass.config_entries.options.async_configure(
        result["flow_id"], payload
    )


async def yaml_editor(hass, result, index: int):
    """Open a screen's menu and step into its YAML editor."""
    result = await pick(hass, result, f"screen_{index}")
    return await pick(hass, result, "screen_yaml")


def coordinator_with(*presets):
    """A stand-in coordinator exposing only the presets the settings step reads."""
    return type("Coordinator", (), {"presets": list(presets)})()


def base_options(result):
    """The dashboard base dropdown's options out of a settings form."""
    fields = {str(key): value for key, value in result["data_schema"].schema.items()}
    return fields[CONF_DASHBOARD_BASE].config["options"]


TWO_LAYOUTS = {
    CONF_PRESETS: {DEFAULT_PRESET: [OFF] * 5, "energy": [CLOCK] * 5},
    CONF_ACTIVE_PRESET: "energy",
}


# --- the menu --------------------------------------------------------------


async def test_menu_labels_every_screen_with_what_it_holds(
    hass, mock_config_entry
) -> None:
    """A screen entry has to say what is on that screen, not just its number."""
    result = await open_options(
        hass,
        mock_config_entry,
        {
            CONF_PRESETS: {
                DEFAULT_PRESET: [
                    {"page_type": "card", "card": "sensor_grid"},
                    OFF,
                    OFF,
                    OFF,
                    OFF,
                ]
            },
            CONF_ACTIVE_PRESET: DEFAULT_PRESET,
        },
    )

    assert result["menu_options"]["screen_0"] == "Screen 1: sensor_grid"
    assert result["menu_options"]["screen_1"] == "Screen 2: off"


async def test_menu_hides_layouts_until_there_are_two(hass, mock_config_entry) -> None:
    """One layout is just 'the screens', so the switcher would be noise."""
    result = await open_options(
        hass,
        mock_config_entry,
        {CONF_PRESETS: {DEFAULT_PRESET: [OFF] * 5}, CONF_ACTIVE_PRESET: DEFAULT_PRESET},
    )

    assert "layout" not in result["menu_options"]


async def test_menu_shows_layouts_once_a_second_one_exists(
    hass, mock_config_entry
) -> None:
    result = await open_options(hass, mock_config_entry, dict(TWO_LAYOUTS))

    assert result["menu_options"]["layout"] == "Layout: energy"


async def test_menu_never_offers_save_and_close(hass, mock_config_entry) -> None:
    """Every step commits, so there is nothing left for a save step to do."""
    result = await open_options(hass, mock_config_entry, dict(TWO_LAYOUTS))

    assert "save" not in result["menu_options"]


# --- screens ---------------------------------------------------------------


@pytest.mark.parametrize("index", range(SCREEN_COUNT))
async def test_each_screen_step_commits_on_its_own(
    hass, mock_config_entry, index
) -> None:
    """One edit, one write. No second step is needed to make it stick."""
    result = await open_options(
        hass,
        mock_config_entry,
        {CONF_PRESETS: {DEFAULT_PRESET: [OFF] * 5}, CONF_ACTIVE_PRESET: DEFAULT_PRESET},
    )
    result = await yaml_editor(hass, result, index)
    result = await submit(hass, result, {CONF_SCREENS: {"page_type": "image"}})

    screens = result["data"][CONF_PRESETS][DEFAULT_PRESET]
    assert screens[index] == {"page_type": "image"}
    assert [page for i, page in enumerate(screens) if i != index] == [OFF] * 4


async def test_a_screen_edit_lands_in_the_active_layout(
    hass, mock_config_entry
) -> None:
    """The clock shows the active layout, so that is what an edit must change."""
    result = await open_options(hass, mock_config_entry, dict(TWO_LAYOUTS))
    result = await yaml_editor(hass, result, 0)
    result = await submit(hass, result, {CONF_SCREENS: OFF})

    presets = result["data"][CONF_PRESETS]
    assert presets["energy"][0] == OFF
    assert presets["energy"][1] == CLOCK
    assert presets[DEFAULT_PRESET] == [OFF] * 5


async def test_options_never_write_a_second_copy_of_the_screens(
    hass, mock_config_entry
) -> None:
    """``screens`` is still read forever, but writing it invited a drift."""
    result = await open_options(hass, mock_config_entry, dict(TWO_LAYOUTS))
    result = await yaml_editor(hass, result, 0)
    result = await submit(hass, result, {CONF_SCREENS: OFF})

    assert CONF_SCREENS not in result["data"]


async def test_a_pre_layout_screen_list_still_opens_and_survives(
    hass, mock_config_entry
) -> None:
    """A config written before layouts existed folds into the default layout."""
    result = await open_options(
        hass, mock_config_entry, {CONF_SCREENS: [CLOCK, OFF, OFF, OFF, OFF]}
    )
    result = await yaml_editor(hass, result, 1)
    result = await submit(hass, result, {CONF_SCREENS: {"page_type": "image"}})

    screens = result["data"][CONF_PRESETS][DEFAULT_PRESET]
    assert screens[0] == CLOCK
    assert screens[1] == {"page_type": "image"}


async def test_short_screen_lists_are_padded_with_off_pages(
    hass, mock_config_entry
) -> None:
    """Every layout covers all five screens, however few were configured."""
    result = await open_options(
        hass,
        mock_config_entry,
        {CONF_PRESETS: {DEFAULT_PRESET: [CLOCK]}, CONF_ACTIVE_PRESET: DEFAULT_PRESET},
    )

    assert len(result["menu_options"]) >= SCREEN_COUNT
    assert result["menu_options"]["screen_4"] == "Screen 5: off"


async def test_options_fall_back_to_the_neutral_defaults(
    hass, mock_config_entry
) -> None:
    """With no options at all the editor opens on the shipped fallback."""
    result = await open_options(hass, mock_config_entry, {})

    assert result["menu_options"]["screen_0"] == "Screen 1: clock"


# --- screen forms ----------------------------------------------------------


async def test_a_screen_menu_offers_the_forms_when_the_page_fits_one(
    hass, mock_config_entry
) -> None:
    result = await open_options(
        hass,
        mock_config_entry,
        {CONF_PRESETS: {DEFAULT_PRESET: [OFF] * 5}, CONF_ACTIVE_PRESET: DEFAULT_PRESET},
    )
    result = await pick(hass, result, "screen_0")

    assert result["menu_options"] == [
        "screen_sensors",
        "screen_face",
        "screen_off",
        "screen_yaml",
    ]
    assert result["description_placeholders"]["reason"] == ""


async def test_a_hand_written_screen_is_offered_yaml_only(
    hass, mock_config_entry
) -> None:
    """The protection rule. A form that cannot say it must not get to write it."""
    hand_written = {
        "page_type": "card",
        "card": "sensor_grid",
        "slots": [{"entity_id": "sensor.a", "value_template": "{{ states(x) }}"}],
    }
    result = await open_options(
        hass,
        mock_config_entry,
        {
            CONF_PRESETS: {DEFAULT_PRESET: [hand_written] + [OFF] * 4},
            CONF_ACTIVE_PRESET: DEFAULT_PRESET,
        },
    )
    result = await pick(hass, result, "screen_0")

    assert result["menu_options"] == ["screen_yaml"]
    assert "value_template" in result["description_placeholders"]["reason"]


async def test_a_hand_written_screen_survives_the_yaml_editor_untouched(
    hass, mock_config_entry
) -> None:
    """Open it, submit the default, get back exactly what was stored."""
    hand_written = {
        "page_type": "components",
        "components": [{"type": "text", "content": "hi", "x": 1, "y": 2}],
    }
    result = await open_options(
        hass,
        mock_config_entry,
        {
            CONF_PRESETS: {DEFAULT_PRESET: [OFF, hand_written, OFF, OFF, OFF]},
            CONF_ACTIVE_PRESET: DEFAULT_PRESET,
        },
    )
    result = await pick(hass, result, "screen_1")
    assert result["menu_options"] == ["screen_yaml"]
    result = await pick(hass, result, "screen_yaml")
    result = await submit(hass, result, {CONF_SCREENS: hand_written})

    assert result["data"][CONF_PRESETS][DEFAULT_PRESET][1] == hand_written


async def test_the_sensor_form_writes_a_sensor_grid_card(
    hass, mock_config_entry
) -> None:
    result = await open_options(
        hass,
        mock_config_entry,
        {CONF_PRESETS: {DEFAULT_PRESET: [OFF] * 5}, CONF_ACTIVE_PRESET: DEFAULT_PRESET},
    )
    result = await pick(hass, result, "screen_2")
    result = await pick(hass, result, "screen_sensors")
    result = await submit(
        hass,
        result,
        {"entities": ["sensor.a", "sensor.b"], "theme": "navy", "duration": 20},
    )

    assert result["data"][CONF_PRESETS][DEFAULT_PRESET][2] == {
        "page_type": "card",
        "card": "sensor_grid",
        "theme": "navy",
        "duration": 20,
        "slots": [{"entity_id": "sensor.a"}, {"entity_id": "sensor.b"}],
    }


async def test_the_sensor_form_refuses_more_than_eight_entities(
    hass, mock_config_entry
) -> None:
    result = await open_options(
        hass,
        mock_config_entry,
        {CONF_PRESETS: {DEFAULT_PRESET: [OFF] * 5}, CONF_ACTIVE_PRESET: DEFAULT_PRESET},
    )
    result = await pick(hass, result, "screen_0")
    result = await pick(hass, result, "screen_sensors")
    result = await submit(
        hass,
        result,
        {
            "entities": [f"sensor.s{i}" for i in range(9)],
            "theme": "dark",
            "duration": 15,
        },
    )

    assert result["type"] == "form"
    assert result["errors"] == {"entities": "too_many_entities"}


async def test_the_off_entry_needs_no_form(hass, mock_config_entry) -> None:
    result = await open_options(
        hass,
        mock_config_entry,
        {
            CONF_PRESETS: {DEFAULT_PRESET: [CLOCK] * 5},
            CONF_ACTIVE_PRESET: DEFAULT_PRESET,
        },
    )
    result = await pick(hass, result, "screen_3")
    result = await pick(hass, result, "screen_off")

    assert result["type"] == "create_entry"
    assert result["data"][CONF_PRESETS][DEFAULT_PRESET][3] == {"page_type": "off"}


async def test_the_face_form_lists_the_configured_favorites(
    hass, mock_config_entry
) -> None:
    result = await open_options(
        hass,
        mock_config_entry,
        {
            CONF_PRESETS: {DEFAULT_PRESET: [OFF] * 5},
            CONF_ACTIVE_PRESET: DEFAULT_PRESET,
            CONF_FACES: {"per_screen": [{"name": "Big Time", "clock_id": 152}]},
        },
    )
    result = await pick(hass, result, "screen_0")
    result = await pick(hass, result, "screen_face")
    fields = {str(key): value for key, value in result["data_schema"].schema.items()}
    assert fields["clock_id"].config["options"] == [
        {"value": "152", "label": "Big Time"}
    ]

    result = await submit(hass, result, {"clock_id": "152", "duration": 15})
    assert result["data"][CONF_PRESETS][DEFAULT_PRESET][0] == {
        "page_type": "clock",
        "clock_id": 152,
        "duration": 15,
    }


# --- layouts ---------------------------------------------------------------


async def test_layout_menu_splits_the_actions(hass, mock_config_entry) -> None:
    """One action per entry, instead of one form with an action dropdown."""
    result = await open_options(hass, mock_config_entry, dict(TWO_LAYOUTS))
    result = await pick(hass, result, "layout")

    assert result["menu_options"] == [
        "layout_switch",
        "layout_copy",
        "layout_delete",
    ]


async def test_layout_switch_swaps_every_screen(hass, mock_config_entry) -> None:
    result = await open_options(hass, mock_config_entry, dict(TWO_LAYOUTS))
    result = await pick(hass, result, "layout")
    result = await pick(hass, result, "layout_switch")
    result = await submit(hass, result, {CONF_ACTIVE_PRESET: DEFAULT_PRESET})

    assert result["data"][CONF_ACTIVE_PRESET] == DEFAULT_PRESET
    assert result["data"][CONF_PRESETS]["energy"] == [CLOCK] * 5


async def test_layout_copy_keeps_the_original(hass, mock_config_entry) -> None:
    """"Save as copy" is how a layout is branched, so the source must survive."""
    result = await open_options(hass, mock_config_entry, dict(TWO_LAYOUTS))
    result = await pick(hass, result, "layout")
    result = await pick(hass, result, "layout_copy")
    result = await submit(hass, result, {"preset_name": "night"})

    assert result["data"][CONF_ACTIVE_PRESET] == "night"
    assert result["data"][CONF_PRESETS]["night"] == [CLOCK] * 5
    assert result["data"][CONF_PRESETS]["energy"] == [CLOCK] * 5


@pytest.mark.parametrize(
    ("name", "error"),
    [("", "preset_name_required"), ("energy", "preset_name_taken")],
)
async def test_layout_copy_refuses_a_bad_name(
    hass, mock_config_entry, name, error
) -> None:
    result = await open_options(hass, mock_config_entry, dict(TWO_LAYOUTS))
    result = await pick(hass, result, "layout")
    result = await pick(hass, result, "layout_copy")
    result = await submit(hass, result, {"preset_name": name})

    assert result["step_id"] == "layout_copy"
    assert error in result["errors"].values()


async def test_layout_delete_removes_one_and_activates_another(
    hass, mock_config_entry
) -> None:
    result = await open_options(hass, mock_config_entry, dict(TWO_LAYOUTS))
    result = await pick(hass, result, "layout")
    result = await pick(hass, result, "layout_delete")
    result = await submit(hass, result, {CONF_ACTIVE_PRESET: "energy"})

    assert sorted(result["data"][CONF_PRESETS]) == [DEFAULT_PRESET]
    assert result["data"][CONF_ACTIVE_PRESET] == DEFAULT_PRESET


async def test_layout_delete_refuses_the_last_layout(hass, mock_config_entry) -> None:
    """Deleting the only layout would leave the device with no configuration.

    The menu hides the layout entry while there is only one, so this guard is
    reached by driving the step directly. It stays in because the step id is
    part of the flow's public surface once a URL or a translation names it.
    """
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            CONF_PRESETS: {DEFAULT_PRESET: [OFF] * 5},
            CONF_ACTIVE_PRESET: DEFAULT_PRESET,
        },
    )
    flow = DivoomTimesGateOptionsFlow()
    flow.hass = hass
    flow.handler = mock_config_entry.entry_id

    result = await flow.async_step_layout_delete({CONF_ACTIVE_PRESET: DEFAULT_PRESET})

    assert result["step_id"] == "layout_delete"
    assert result["errors"] == {"base": "preset_last"}


# --- generators and settings ----------------------------------------------


async def test_energy_step_writes_to_the_layout_you_name(
    hass, mock_config_entry
) -> None:
    """Generating screens leaves the layout you were editing alone."""
    result = await open_options(
        hass,
        mock_config_entry,
        {CONF_PRESETS: {"night": [CLOCK] * 5}, CONF_ACTIVE_PRESET: "night"},
    )
    result = await pick(hass, result, "energy")
    result = await submit(hass, result, {"preset_name": "power"})

    assert result["data"][CONF_ACTIVE_PRESET] == "power"
    assert result["data"][CONF_PRESETS]["night"] == [CLOCK] * 5
    assert len(result["data"][CONF_PRESETS]["power"]) == SCREEN_COUNT


async def test_advanced_step_replaces_every_layout(hass, mock_config_entry) -> None:
    """The YAML editor is how a set of screens is pasted in or copied out."""
    result = await open_options(hass, mock_config_entry, dict(TWO_LAYOUTS))
    result = await pick(hass, result, "advanced")
    result = await submit(hass, result, {CONF_PRESETS: {"solo": [CLOCK] * 5}})

    assert sorted(result["data"][CONF_PRESETS]) == ["solo"]
    assert result["data"][CONF_ACTIVE_PRESET] == "solo"


async def test_settings_step_lists_independent_presets_by_position(
    hass, mock_config_entry
) -> None:
    """Independence ids are per-unit, so the dropdown keys on the slot instead."""
    mock_config_entry.runtime_data = coordinator_with(
        IndependentPreset("Control1", 111, 0), IndependentPreset("Control2", 222, 1)
    )
    result = await open_options(hass, mock_config_entry, dict(TWO_LAYOUTS))
    result = await pick(hass, result, "settings")

    options = base_options(result)
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
    mock_config_entry.runtime_data = None
    result = await open_options(hass, mock_config_entry, dict(TWO_LAYOUTS))
    result = await pick(hass, result, "settings")

    assert [entry["value"] for entry in base_options(result)] == [""]


async def test_settings_step_without_a_presets_attribute(
    hass, mock_config_entry
) -> None:
    """A coordinator that never read the presets is treated as having none."""
    mock_config_entry.runtime_data = object()
    result = await open_options(hass, mock_config_entry, dict(TWO_LAYOUTS))
    result = await pick(hass, result, "settings")

    assert base_options(result) == [{"value": "", "label": "Leave device as-is"}]


async def test_settings_step_saves_interval_base_and_faces(
    hass, mock_config_entry
) -> None:
    mock_config_entry.runtime_data = coordinator_with(
        IndependentPreset("Control3", 333, 2)
    )
    result = await open_options(hass, mock_config_entry, dict(TWO_LAYOUTS))
    result = await pick(hass, result, "settings")
    faces = {"Clock": 61, "Weather": 62}
    result = await submit(
        hass,
        result,
        {CONF_REFRESH_INTERVAL: "20", CONF_DASHBOARD_BASE: "2", CONF_FACES: faces},
    )

    assert result["data"][CONF_REFRESH_INTERVAL] == 20
    assert result["data"][CONF_DASHBOARD_BASE] == "2"
    assert result["data"][CONF_FACES] == faces


async def test_settings_step_ignores_a_non_dict_face_map(
    hass, mock_config_entry
) -> None:
    """Faces map names to ClockIds; anything else keeps the previous map."""
    mock_config_entry.runtime_data = None
    original = dict(mock_config_entry.options[CONF_FACES])
    result = await open_options(hass, mock_config_entry)
    result = await pick(hass, result, "settings")
    result = await submit(
        hass,
        result,
        {CONF_REFRESH_INTERVAL: 60, CONF_DASHBOARD_BASE: "", CONF_FACES: []},
    )

    assert result["data"][CONF_FACES] == original


async def test_options_read_the_interval_from_the_entry_when_unset(
    hass, mock_config_entry
) -> None:
    """An entry with empty options still yields a complete, valid result."""
    mock_config_entry.runtime_data = None
    result = await open_options(hass, mock_config_entry, {})
    result = await pick(hass, result, "settings")
    result = await submit(
        hass,
        result,
        {CONF_REFRESH_INTERVAL: 42, CONF_DASHBOARD_BASE: ""},
    )

    assert result["data"][CONF_FACES]
    assert result["data"][CONF_DASHBOARD_BASE] == ""
    assert result["data"][CONF_REFRESH_INTERVAL] == 42
    assert len(result["data"][CONF_PRESETS][DEFAULT_PRESET]) == SCREEN_COUNT

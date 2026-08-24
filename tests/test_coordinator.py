"""Tests for the per-tick coordinator.

The behaviour this file pins hardest is the push-suppression invariant from
``DESIGN.md``: HA content is a JPEG overlay that overrides native faces, so the
coordinator must not push to a screen that is showing a native face or an
Independent Display preset. Pushing anyway clobbers the face on the next tick.
"""
from __future__ import annotations

from collections.abc import Generator
from datetime import timedelta
from io import BytesIO
from unittest.mock import AsyncMock, patch

from homeassistant.helpers.network import NoURLAvailableError
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from PIL import Image
import pytest

from custom_components.divoom_times_gate.const import (
    CONF_DASHBOARD_BASE,
    CONF_DEVICE_ID,
    CONF_DISPDATA_SECRET,
    CONF_IP_ADDRESS,
    CONF_MAC,
    CONF_SCREENS,
    DOMAIN,
    NATIVE_KIND_TYPES,
    SCREEN_COUNT,
)
from custom_components.divoom_times_gate.coordinator import TimesGateCoordinator
from custom_components.divoom_times_gate.discovery import IndependentPreset

from .conftest import make_discovered

COORD = "custom_components.divoom_times_gate.coordinator"

BLACK_PAGES = [{"page_type": "off"}]
CLOCK_PAGES = [{"page_type": "clock", "clock_id": 61}]


def render_gif() -> bytes:
    """A real one-frame GIF, so the card preview conversion has something to do."""
    buffer = BytesIO()
    Image.new("RGB", (128, 128), (10, 20, 30)).save(buffer, format="GIF")
    return buffer.getvalue()


def command_names(device) -> list[str]:
    """Return the name of every device call the coordinator made."""
    return [call[0] for call in device.calls]


def batched_commands(device) -> list[dict]:
    """Flatten every Draw/CommandList the coordinator sent."""
    return [
        command
        for name, args, _ in device.calls
        if name == "send_command_list"
        for command in args[0]
    ]


@pytest.fixture
def coordinator(hass, mock_config_entry, fake_times_gate) -> Generator[TimesGateCoordinator]:
    """Return a coordinator wired to a network-free fake device."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={**mock_config_entry.options, CONF_SCREENS: [CLOCK_PAGES] * SCREEN_COUNT},
    )
    coord = TimesGateCoordinator(hass, mock_config_entry, fake_times_gate, 15)
    coord._first_run = False  # the PicID reset is exercised separately
    yield coord
    # async_request_refresh arms a debouncer; leave it running and the HA test
    # harness fails the test for a lingering timer.
    coord._debounced_refresh.async_cancel()


# --- push suppression: device-level Display source --------------------------


@pytest.mark.parametrize(
    ("kind", "value"),
    [("overall", 581), ("independent", 4242), ("off", None)],
)
async def test_native_display_source_pushes_nothing(coordinator, kind, value) -> None:
    """Any Display source other than HA Dashboard means hands off the panels."""
    coordinator.display = (kind, value)
    coordinator.device.calls.clear()

    data = await coordinator._async_update_data()

    assert data == {"display": kind}
    assert coordinator.device.calls == []


async def test_dashboard_display_source_does_push(coordinator) -> None:
    """The dashboard is the only mode where HA owns the panels."""
    coordinator.display = ("dashboard", None)

    data = await coordinator._async_update_data()

    assert command_names(coordinator.device) == ["send_command_list"]
    assert set(data) == set(range(SCREEN_COUNT))


async def test_native_display_stays_silent_across_repeated_ticks(coordinator) -> None:
    """A native face must survive every tick, not just the first one."""
    coordinator.display = ("independent", 4242)
    coordinator.device.calls.clear()

    for _ in range(5):
        await coordinator._async_update_data()

    assert coordinator.device.calls == []


# --- push suppression: per-screen mode -------------------------------------


@pytest.mark.parametrize(("kind", "value"), [("face", 61), ("off", None)])
async def test_non_custom_screens_are_skipped_every_tick(
    coordinator, kind, value
) -> None:
    """Face and Off screens are set once on change, never re-pushed per tick."""
    coordinator.screen_modes = [(kind, value)] * SCREEN_COUNT

    data = await coordinator._async_update_data()

    assert coordinator.device.calls == []
    assert data == {}


async def test_only_custom_screens_are_pushed(coordinator) -> None:
    """A mixed layout pushes exactly the Custom screens and nothing else."""
    coordinator.screen_modes = [
        ("custom", None),
        ("face", 61),
        ("custom", None),
        ("off", None),
        ("face", 62),
    ]

    data = await coordinator._async_update_data()

    assert sorted(data) == [0, 2]
    assert len(batched_commands(coordinator.device)) == 2


async def test_a_face_screen_is_not_clobbered_by_later_ticks(coordinator) -> None:
    """Switching one screen to a Face stops that screen's pushes immediately."""
    await coordinator._async_update_data()
    coordinator.device.calls.clear()

    await coordinator.async_set_screen(2, "face", 61)
    coordinator.device.calls.clear()

    await coordinator._async_update_data()

    for command in batched_commands(coordinator.device):
        assert command.get("LcdIndex") != 2
        assert command.get("LcdArray", [0] * 5)[2] == 0


# --- tick mechanics --------------------------------------------------------


async def test_first_run_resets_the_device_pic_counter(
    hass, mock_config_entry, fake_times_gate
) -> None:
    """PicID must climb; the device counter is reset once per setup."""
    mock_config_entry.add_to_hass(hass)
    coord = TimesGateCoordinator(hass, mock_config_entry, fake_times_gate, 15)

    await coord._async_update_data()
    await coord._async_update_data()

    assert command_names(fake_times_gate).count("reset_pic_counter") == 1


async def test_changed_screens_are_batched_into_one_command_list(
    coordinator,
) -> None:
    """One POST per tick, not one per screen (docs/API.md §5.1)."""
    await coordinator._async_update_data()

    assert command_names(coordinator.device) == ["send_command_list"]
    assert len(batched_commands(coordinator.device)) == SCREEN_COUNT


async def test_unchanged_screens_send_nothing_on_the_next_tick(coordinator) -> None:
    """The signature cache is what keeps a static dashboard quiet."""
    await coordinator._async_update_data()
    coordinator.device.calls.clear()

    data = await coordinator._async_update_data()

    assert coordinator.device.calls == []
    assert set(data.values()) == {"unchanged"}


async def test_signatures_are_only_recorded_when_the_device_accepted(
    coordinator,
) -> None:
    """A rejected batch must be retried, so the hashes stay unwritten."""
    coordinator.device.send_command_list = AsyncMock(return_value={"error_code": 5})

    await coordinator._async_update_data()

    assert coordinator._last_hashes == {}


async def test_hashes_survive_a_reload_so_only_changed_screens_repaint(
    hass, mock_config_entry, fake_times_gate
) -> None:
    """Editing options should not flash every screen; hashes live on hass.data."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={**mock_config_entry.options, CONF_SCREENS: [CLOCK_PAGES] * SCREEN_COUNT},
    )
    first = TimesGateCoordinator(hass, mock_config_entry, fake_times_gate, 15)
    first._first_run = False
    await first._async_update_data()

    second = TimesGateCoordinator(hass, mock_config_entry, fake_times_gate, 15)
    second._first_run = False
    fake_times_gate.calls.clear()

    await second._async_update_data()

    assert fake_times_gate.calls == []


async def test_empty_screen_config_reports_empty(coordinator) -> None:
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={**coordinator.config_entry.options, CONF_SCREENS: [[]] * SCREEN_COUNT},
    )

    data = await coordinator._async_update_data()

    assert set(data.values()) == {"empty"}
    assert coordinator.device.calls == []


async def test_screens_beyond_the_configured_list_are_empty(coordinator) -> None:
    """A short config must not raise; the extra screens simply have no pages."""
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={**coordinator.config_entry.options, CONF_SCREENS: [CLOCK_PAGES]},
    )

    data = await coordinator._async_update_data()

    assert data[4] == "empty"


async def test_render_failures_are_contained_to_one_screen(coordinator) -> None:
    """One bad page must not take the whole tick down."""
    coordinator.device.build_clock_face = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("boom")
    )

    data = await coordinator._async_update_data()

    assert set(data.values()) == {"error"}


# --- page rotation ---------------------------------------------------------


async def test_single_page_screens_do_not_accumulate_elapsed_time(
    coordinator,
) -> None:
    """Regression: single-page screens used to repaint every ``duration``."""
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={
            **coordinator.config_entry.options,
            CONF_SCREENS: [[{"page_type": "clock", "clock_id": 61, "duration": 5}]] * 5,
        },
    )

    for _ in range(10):
        await coordinator._async_update_data()

    assert coordinator._rot_elapsed == [0] * SCREEN_COUNT
    assert coordinator._rot_index == [0] * SCREEN_COUNT
    assert command_names(coordinator.device).count("send_command_list") == 1


async def test_multi_page_screens_advance_once_the_duration_elapses(
    coordinator,
) -> None:
    """Rotation is implicit in a screen's page list plus ``duration``."""
    pages = [
        {"page_type": "clock", "clock_id": 61, "duration": 15},
        {"page_type": "clock", "clock_id": 62, "duration": 15},
    ]
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={**coordinator.config_entry.options, CONF_SCREENS: [pages] * 5},
    )

    await coordinator._async_update_data()
    assert coordinator._rot_index[0] == 1  # a 15s tick consumes a 15s page

    coordinator.device.calls.clear()
    await coordinator._async_update_data()

    assert coordinator._rot_index[0] == 0
    clock_ids = {command["ClockId"] for command in batched_commands(coordinator.device)}
    assert clock_ids == {61}


async def test_disabled_pages_drop_out_of_the_rotation(coordinator) -> None:
    pages = [
        {"page_type": "clock", "clock_id": 61, "enabled": "{{ false }}"},
        {"page_type": "clock", "clock_id": 62},
    ]
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={**coordinator.config_entry.options, CONF_SCREENS: [pages] * 5},
    )

    await coordinator._async_update_data()

    clock_ids = {command["ClockId"] for command in batched_commands(coordinator.device)}
    assert clock_ids == {62}


# --- page types ------------------------------------------------------------


async def test_clock_page_sets_a_native_face_and_clears_the_preview(
    coordinator,
) -> None:
    """A native face is not HA-rendered, so there is no frame to preview."""
    await coordinator._async_update_data()

    assert batched_commands(coordinator.device)[0]["Command"] == (
        "Channel/SetClockSelectId"
    )
    assert coordinator.last_frames[0] is None


@pytest.mark.parametrize(
    ("page", "expected_command"),
    [
        ({"page_type": "gif", "gif_url": "http://x/a.gif"}, "Device/PlayGif"),
        (
            {"page_type": "gif", "gif_urls": ["http://x/a.gif", "http://x/b.gif"]},
            "Device/PlayGif",
        ),
        ({"page_type": "visualizer", "id": 3}, "Channel/SetEqPosition"),
    ],
)
async def test_native_page_types_build_their_own_command(
    coordinator, page, expected_command
) -> None:
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={**coordinator.config_entry.options, CONF_SCREENS: [[page]] * 5},
    )

    await coordinator._async_update_data()

    assert batched_commands(coordinator.device)[0]["Command"] == expected_command


async def test_gif_page_accepts_a_single_url_string(coordinator) -> None:
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={
            **coordinator.config_entry.options,
            CONF_SCREENS: [[{"page_type": "gif", "gif_url": "http://x/a.gif"}]] * 5,
        },
    )

    await coordinator._async_update_data()

    assert batched_commands(coordinator.device)[0]["FileName"] == ["http://x/a.gif"]


async def test_off_page_pushes_a_black_jpeg(coordinator) -> None:
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={**coordinator.config_entry.options, CONF_SCREENS: [BLACK_PAGES] * 5},
    )

    await coordinator._async_update_data()

    commands = batched_commands(coordinator.device)
    assert all(command["Command"] == "Draw/SendHttpGif" for command in commands)
    assert coordinator.last_frames[0] is not None


async def test_unknown_card_type_is_reported_as_an_error(coordinator) -> None:
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={
            **coordinator.config_entry.options,
            CONF_SCREENS: [[{"page_type": "card", "card": "does-not-exist"}]] * 5,
        },
    )

    data = await coordinator._async_update_data()

    assert set(data.values()) == {"error"}
    assert coordinator.device.calls == []


async def test_card_without_a_dispdata_secret_is_reported_as_an_error(
    coordinator,
) -> None:
    """Cards need a signed poll URL; without the secret there is nothing to send."""
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={
            **coordinator.config_entry.options,
            CONF_SCREENS: [[{"page_type": "card", "card": "sensor_grid"}]] * 5,
        },
    )

    data = await coordinator._async_update_data()

    assert set(data.values()) == {"error"}


async def test_dispdata_text_without_a_secret_is_reported_as_an_error(
    coordinator,
) -> None:
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={
            **coordinator.config_entry.options,
            CONF_SCREENS: [
                [{"page_type": "dispdata_text", "entity_id": "sensor.x"}]
            ] * 5,
        },
    )

    data = await coordinator._async_update_data()

    assert set(data.values()) == {"error"}


async def test_dispdata_items_without_a_secret_is_reported_as_an_error(
    coordinator,
) -> None:
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={
            **coordinator.config_entry.options,
            CONF_SCREENS: [
                [
                    {
                        "page_type": "dispdata_text",
                        "items": [{"kind": "value", "entity_id": "sensor.x"}],
                    }
                ]
            ] * 5,
        },
    )

    data = await coordinator._async_update_data()

    assert set(data.values()) == {"error"}


# --- availability ----------------------------------------------------------


async def test_three_consecutive_transport_failures_mark_the_device_gone(
    coordinator,
) -> None:
    """Device-level rejections keep the entry available; transport loss does not."""
    coordinator.device.consecutive_failures = 3

    with pytest.raises(UpdateFailed, match="unreachable"):
        await coordinator._async_update_data()

    assert coordinator._was_unavailable is True


async def test_two_failures_are_not_enough_to_go_unavailable(coordinator) -> None:
    coordinator.device.consecutive_failures = 2

    await coordinator._async_update_data()

    assert coordinator._was_unavailable is False


async def test_recovery_clears_the_unavailable_flag(coordinator) -> None:
    coordinator._was_unavailable = True
    coordinator.device.consecutive_failures = 0

    await coordinator._async_update_data()

    assert coordinator._was_unavailable is False


# --- control API -----------------------------------------------------------


async def test_set_display_to_overall_uses_the_whole_face_command(
    coordinator,
) -> None:
    await coordinator.async_set_display("overall", 581)

    assert coordinator.display == ("overall", 581)
    assert command_names(coordinator.device) == ["set_whole_face"]


async def test_set_display_to_independent_selects_the_preset(coordinator) -> None:
    await coordinator.async_set_display("independent", 4242)

    assert command_names(coordinator.device) == ["set_independent_preset"]
    assert coordinator.device.calls[0][1] == (4242,)


async def test_set_display_to_off_turns_the_screens_off(coordinator) -> None:
    await coordinator.async_set_display("off", None)

    assert command_names(coordinator.device) == ["turn_off"]


async def test_returning_to_dashboard_from_off_powers_the_screens_back_on(
    coordinator,
) -> None:
    coordinator.display = ("off", None)

    await coordinator.async_set_display("dashboard", None)
    await coordinator.hass.async_block_till_done()

    assert "turn_on" in command_names(coordinator.device)


async def test_returning_to_dashboard_from_a_face_does_not_power_cycle(
    coordinator,
) -> None:
    """turn_on makes the device flash its native preset before HA paints."""
    coordinator.display = ("overall", 581)

    await coordinator.async_set_display("dashboard", None)
    await coordinator.hass.async_block_till_done()

    assert "turn_on" not in command_names(coordinator.device)


async def test_dashboard_applies_the_configured_base_preset(coordinator) -> None:
    """Overlaying onto a static preset avoids native faces reloading under HA."""
    coordinator.presets = [
        IndependentPreset("Control1", 111, 0),
        IndependentPreset("Control3", 333, 2),
    ]
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={**coordinator.config_entry.options, CONF_DASHBOARD_BASE: "2"},
    )

    await coordinator.async_set_display("dashboard", None)
    await coordinator.hass.async_block_till_done()

    presets_set = [
        args[0] for name, args, _ in coordinator.device.calls
        if name == "set_independent_preset"
    ]
    assert presets_set == [333]


@pytest.mark.parametrize("configured", [None, "", "9"])
async def test_dashboard_base_is_skipped_when_it_cannot_be_resolved(
    coordinator, configured
) -> None:
    """An unset or unmatched position leaves the device's preset alone."""
    coordinator.presets = [IndependentPreset("Control1", 111, 0)]
    options = {**coordinator.config_entry.options}
    if configured is None:
        options.pop(CONF_DASHBOARD_BASE, None)
    else:
        options[CONF_DASHBOARD_BASE] = configured
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry, options=options
    )

    assert coordinator._dashboard_base_id() is None


async def test_set_screen_to_a_face_applies_it_immediately(coordinator) -> None:
    await coordinator.async_set_screen(1, "face", 61)

    assert coordinator.screen_modes[1] == ("face", 61)
    assert command_names(coordinator.device) == ["set_clock_face"]


async def test_set_screen_to_off_pushes_black(coordinator) -> None:
    await coordinator.async_set_screen(1, "off", None)

    assert command_names(coordinator.device) == ["send_jpeg"]


async def test_set_screen_does_no_device_io_outside_dashboard_mode(
    coordinator,
) -> None:
    """Touching the panels here would break out of the selected native preset."""
    coordinator.display = ("independent", 4242)
    coordinator.device.calls.clear()

    await coordinator.async_set_screen(1, "face", 61)

    assert coordinator.device.calls == []
    assert coordinator.screen_modes[1] == ("face", 61)


async def test_set_screen_resets_that_screens_rotation(coordinator) -> None:
    coordinator._rot_index[3] = 2
    coordinator._rot_elapsed[3] = 99

    await coordinator.async_set_screen(3, "custom", None)
    await coordinator.hass.async_block_till_done()

    assert coordinator._rot_index[3] == 0
    assert coordinator._rot_elapsed[3] == 0


async def test_reassert_faces_batches_face_and_off_screens(coordinator) -> None:
    coordinator.screen_modes = [
        ("face", 61),
        ("custom", None),
        ("off", None),
        ("face", 62),
        ("custom", None),
    ]

    await coordinator._reassert_faces()

    assert command_names(coordinator.device) == ["send_command_list"]
    commands = batched_commands(coordinator.device)
    assert [command["Command"] for command in commands] == [
        "Channel/SetClockSelectId",
        "Draw/SendHttpGif",
        "Channel/SetClockSelectId",
    ]
    assert coordinator.last_frames[0] is None
    assert coordinator.last_frames[2] is not None


async def test_reassert_faces_sends_nothing_when_every_screen_is_custom(
    coordinator,
) -> None:
    await coordinator._reassert_faces()

    assert coordinator.device.calls == []


# --- restored state --------------------------------------------------------


async def test_restore_display_touches_no_hardware(coordinator) -> None:
    """Select restore runs during setup, when the device may be unreachable."""
    coordinator.restore_display("independent", 4242)

    assert coordinator.display == ("independent", 4242)
    assert coordinator.device.calls == []


async def test_restore_screen_touches_no_hardware(coordinator) -> None:
    coordinator._rot_index[0] = 3

    coordinator.restore_screen(0, "face", 61)

    assert coordinator.screen_modes[0] == ("face", 61)
    assert coordinator._rot_index[0] == 0
    assert coordinator.device.calls == []


@pytest.mark.parametrize(
    ("kind", "value", "expected"),
    [
        ("overall", 581, "set_whole_face"),
        ("independent", 4242, "set_independent_preset"),
        ("off", None, "turn_off"),
    ],
)
async def test_apply_restored_state_pushes_the_restored_mode(
    coordinator, kind, value, expected
) -> None:
    coordinator.restore_display(kind, value)

    await coordinator.async_apply_restored_state()

    assert command_names(coordinator.device) == [expected]


async def test_apply_restored_state_reasserts_faces_in_dashboard_mode(
    coordinator,
) -> None:
    coordinator.restore_screen(0, "face", 61)

    await coordinator.async_apply_restored_state()
    await coordinator.hass.async_block_till_done()

    assert "send_command_list" in command_names(coordinator.device)


async def test_apply_restored_state_never_raises(coordinator) -> None:
    """It runs as a background task, so an unreachable device must not bubble up."""
    coordinator.restore_display("overall", 581)
    coordinator.device.set_whole_face = AsyncMock(side_effect=OSError("no route"))

    await coordinator.async_apply_restored_state()


# --- preview frames --------------------------------------------------------


def test_record_frame_keeps_the_timestamp_when_nothing_changed(coordinator) -> None:
    """Otherwise the preview entity looks like it updates every tick."""
    coordinator.record_frame(0, b"jpeg")
    first = coordinator.last_frame_times[0]

    coordinator.record_frame(0, b"jpeg")

    assert coordinator.last_frame_times[0] == first

    coordinator.record_frame(0, b"other")
    assert coordinator.last_frame_times[0] != first


def test_invalidate_clears_one_screen_or_all(coordinator) -> None:
    coordinator._last_hashes.update({0: "a", 1: "b"})

    coordinator.invalidate(0)
    assert coordinator._last_hashes == {1: "b"}

    coordinator.invalidate()
    assert coordinator._last_hashes == {}


async def test_force_refresh_repushes_everything(coordinator) -> None:
    await coordinator._async_update_data()
    coordinator.device.calls.clear()

    await coordinator.async_force_refresh()
    await coordinator.hass.async_block_till_done()

    assert "send_command_list" in command_names(coordinator.device)


async def test_send_jpeg_skips_an_identical_frame(coordinator) -> None:
    assert await coordinator._send_jpeg(0, b"frame") == 0
    coordinator.device.calls.clear()

    assert await coordinator._send_jpeg(0, b"frame") == "unchanged"
    assert coordinator.device.calls == []


async def test_send_jpeg_does_not_cache_a_rejected_frame(coordinator) -> None:
    coordinator.device.send_jpeg = AsyncMock(return_value={"error_code": 5})

    assert await coordinator._send_jpeg(0, b"frame") == 5
    assert coordinator._last_hashes == {}


# --- IP self-healing -------------------------------------------------------


async def test_heal_is_not_attempted_below_the_failure_threshold(
    coordinator,
) -> None:
    coordinator.device.consecutive_failures = 2

    coordinator._maybe_heal_ip()

    assert coordinator._heal_in_progress is False
    assert coordinator._last_heal_attempt is None


async def test_heal_is_rate_limited(coordinator) -> None:
    """Discovery is a cloud call, so a dead device must not spam it every tick."""
    coordinator.device.consecutive_failures = 5
    coordinator._last_heal_attempt = dt_util.utcnow()

    coordinator._maybe_heal_ip()

    assert coordinator._heal_in_progress is False


async def test_heal_runs_again_once_the_cooldown_expires(coordinator) -> None:
    coordinator.device.consecutive_failures = 5
    coordinator._last_heal_attempt = dt_util.utcnow() - timedelta(minutes=6)

    with patch(f"{COORD}.async_discover_devices", AsyncMock(return_value=[])):
        coordinator._maybe_heal_ip()
        await coordinator.hass.async_block_till_done()

    assert coordinator._heal_in_progress is False


async def test_a_heal_already_in_flight_is_not_started_twice(coordinator) -> None:
    coordinator.device.consecutive_failures = 5
    coordinator._heal_in_progress = True

    coordinator._maybe_heal_ip()

    assert coordinator._last_heal_attempt is None


async def test_heal_follows_the_device_to_a_new_lease_by_mac(coordinator) -> None:
    """The MAC is the only stable handle across a DHCP change."""
    moved = make_discovered(ip="192.168.1.99", mac="aa:bb:cc:dd:ee:ff", device_id=4242)

    with patch(f"{COORD}.async_discover_devices", AsyncMock(return_value=[moved])):
        await coordinator._heal_ip()

    assert coordinator.config_entry.data[CONF_IP_ADDRESS] == "192.168.1.99"
    assert coordinator.config_entry.title == "Times Gate (192.168.1.99)"
    assert coordinator._heal_in_progress is False


async def test_heal_falls_back_to_the_device_id_when_no_mac_matches(
    coordinator,
) -> None:
    """Discovery does not always report a MAC, but the DeviceId is stable."""
    moved = make_discovered(ip="192.168.1.99", mac="", device_id=4242)

    with patch(f"{COORD}.async_discover_devices", AsyncMock(return_value=[moved])):
        await coordinator._heal_ip()

    assert coordinator.config_entry.data[CONF_IP_ADDRESS] == "192.168.1.99"
    assert coordinator.config_entry.data[CONF_DEVICE_ID] == 4242


async def test_heal_does_nothing_when_the_ip_has_not_changed(coordinator) -> None:
    same = make_discovered(ip="192.168.1.25")

    with patch(f"{COORD}.async_discover_devices", AsyncMock(return_value=[same])):
        await coordinator._heal_ip()

    assert coordinator.config_entry.data[CONF_IP_ADDRESS] == "192.168.1.25"
    assert coordinator.config_entry.title == "Times Gate (192.168.1.25)"


async def test_heal_does_nothing_when_the_device_is_not_on_the_lan(
    coordinator,
) -> None:
    other = make_discovered(ip="192.168.1.99", mac="99:99:99:99:99:99", device_id=1)

    with patch(f"{COORD}.async_discover_devices", AsyncMock(return_value=[other])):
        await coordinator._heal_ip()

    assert coordinator.config_entry.data[CONF_IP_ADDRESS] == "192.168.1.25"


async def test_heal_gives_up_when_the_entry_has_no_identifiers(
    hass, mock_config_entry, fake_times_gate
) -> None:
    """Without a MAC or DeviceId there is no safe way to pick a device."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_MAC: "", CONF_DEVICE_ID: 0},
    )
    coord = TimesGateCoordinator(hass, mock_config_entry, fake_times_gate, 15)
    found = make_discovered(ip="192.168.1.99")

    with patch(f"{COORD}.async_discover_devices", AsyncMock(return_value=[found])):
        await coord._heal_ip()

    assert mock_config_entry.data[CONF_IP_ADDRESS] == "192.168.1.25"


async def test_a_tick_triggers_healing_once_the_device_looks_gone(
    coordinator,
) -> None:
    coordinator.device.consecutive_failures = 3

    with (
        patch(f"{COORD}.async_discover_devices", AsyncMock(return_value=[])) as discover,
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()
    await coordinator.hass.async_block_till_done()

    assert discover.await_count == 1


# --- misc ------------------------------------------------------------------


def test_device_id_and_host_come_from_the_entry(coordinator) -> None:
    assert coordinator.device_id == 4242
    assert coordinator._device_host() == "192.168.1.25"


def test_screens_fall_back_to_the_shipped_defaults(coordinator) -> None:
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={**coordinator.config_entry.options, CONF_SCREENS: []},
    )

    assert coordinator.screens
    assert coordinator._pages_for(0)


def test_hashes_are_namespaced_per_entry(hass, mock_config_entry, fake_times_gate) -> None:
    mock_config_entry.add_to_hass(hass)
    coord = TimesGateCoordinator(hass, mock_config_entry, fake_times_gate, 15)
    coord._last_hashes[0] = "abc"

    assert hass.data[f"{DOMAIN}_hashes"][mock_config_entry.entry_id] == {0: "abc"}


# --- image pages -----------------------------------------------------------


def set_pages(coordinator, page: dict) -> None:
    """Point every screen at a single page."""
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={**coordinator.config_entry.options, CONF_SCREENS: [[page]] * SCREEN_COUNT},
    )


def patch_frames(frames: list[bytes], speed: int = 200):
    return patch(f"{COORD}.render_image_frames", AsyncMock(return_value=(frames, speed)))


async def test_single_frame_image_rides_the_batched_jpeg_path(coordinator) -> None:
    set_pages(coordinator, {"page_type": "image", "url": "http://x/a.png"})

    with patch_frames([b"one-frame"]):
        data = await coordinator._async_update_data()

    assert command_names(coordinator.device) == ["send_command_list"]
    assert set(data.values()) == {0}
    assert coordinator.last_frames[0] == b"one-frame"


async def test_an_unchanged_single_frame_image_sends_nothing(coordinator) -> None:
    set_pages(coordinator, {"page_type": "image", "url": "http://x/a.png"})

    with patch_frames([b"one-frame"]):
        await coordinator._async_update_data()
        coordinator.device.calls.clear()
        data = await coordinator._async_update_data()

    assert coordinator.device.calls == []
    assert set(data.values()) == {"unchanged"}


async def test_animations_are_sent_outside_the_command_list(coordinator) -> None:
    """Frames share one PicID and need sequential POSTs, so they cannot batch."""
    set_pages(coordinator, {"page_type": "image", "url": "http://x/a.gif"})

    with patch_frames([b"f1", b"f2", b"f3"], speed=120):
        data = await coordinator._async_update_data()

    assert command_names(coordinator.device) == ["send_animation"] * SCREEN_COUNT
    assert coordinator.device.calls[0][1][2] == 120
    assert set(data.values()) == {"0"}


async def test_an_unchanged_animation_is_not_resent(coordinator) -> None:
    set_pages(coordinator, {"page_type": "image", "url": "http://x/a.gif"})

    with patch_frames([b"f1", b"f2"]):
        await coordinator._async_update_data()
        coordinator.device.calls.clear()
        await coordinator._async_update_data()

    assert coordinator.device.calls == []


async def test_a_rejected_animation_is_retried_next_tick(coordinator) -> None:
    set_pages(coordinator, {"page_type": "image", "url": "http://x/a.gif"})
    coordinator.device.send_animation = AsyncMock(return_value={"error_code": 5})

    with patch_frames([b"f1", b"f2"]):
        data = await coordinator._async_update_data()

    assert set(data.values()) == {"5"}
    assert coordinator._last_hashes == {}


@pytest.mark.parametrize("err", [ValueError("bad image"), OSError("gone")])
async def test_an_unreadable_image_is_reported_as_an_error(coordinator, err) -> None:
    set_pages(coordinator, {"page_type": "image", "url": "http://x/a.png"})

    with patch(f"{COORD}.render_image_frames", AsyncMock(side_effect=err)):
        data = await coordinator._async_update_data()

    assert set(data.values()) == {"error"}
    assert coordinator.device.calls == []


# --- dispdata pages --------------------------------------------------------


@pytest.fixture
def dispdata_coordinator(coordinator):
    """Coordinator with a DispData secret and a resolvable local HA URL."""
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        data={**coordinator.config_entry.data, CONF_DISPDATA_SECRET: "s3cret"},
    )
    with patch(f"{COORD}.get_url", return_value="http://homeassistant.local:8123"):
        yield coordinator


def sent_items(device) -> list[dict]:
    return batched_commands(device)[0]["ItemList"]


async def test_dispdata_text_builds_one_polling_item_per_sensor(
    dispdata_coordinator,
) -> None:
    set_pages(
        dispdata_coordinator,
        {
            "page_type": "dispdata_text",
            "sensors": [
                {"entity_id": "sensor.a", "name": "Living Room"},
                {"entity_id": "sensor.b", "name": ""},
            ],
        },
    )

    await dispdata_coordinator._async_update_data()

    items = sent_items(dispdata_coordinator.device)
    assert [item["TextId"] for item in items] == [1, 2]
    assert all(item["type"] == 23 for item in items)
    # The device mishandles %20 in the poll query, so labels use underscores.
    assert items[0]["TextString"].endswith(
        "/api/divoom_times_gate/dispdata/s3cret/sensor.a?label=Living_Room"
    )
    assert "?" not in items[1]["TextString"]


async def test_dispdata_text_accepts_a_single_top_level_entity(
    dispdata_coordinator,
) -> None:
    """Back-compat: a bare entity_id behaves like a one-sensor list."""
    dispdata_coordinator.hass.states.async_set("sensor.a", "21", {"friendly_name": "Hall"})
    set_pages(dispdata_coordinator, {"page_type": "dispdata_text", "entity_id": "sensor.a"})

    await dispdata_coordinator._async_update_data()

    items = sent_items(dispdata_coordinator.device)
    assert len(items) == 1
    assert items[0]["TextString"].endswith("?label=Hall")


async def test_dispdata_text_falls_back_to_the_entity_id_as_a_label(
    dispdata_coordinator,
) -> None:
    set_pages(dispdata_coordinator, {"page_type": "dispdata_text", "entity_id": "sensor.gone"})

    await dispdata_coordinator._async_update_data()

    assert sent_items(dispdata_coordinator.device)[0]["TextString"].endswith(
        "?label=sensor.gone"
    )


async def test_dispdata_text_caps_at_four_sensors(dispdata_coordinator) -> None:
    """There are only four default row positions on a 128x128 panel."""
    set_pages(
        dispdata_coordinator,
        {
            "page_type": "dispdata_text",
            "sensors": [{"entity_id": f"sensor.s{i}"} for i in range(6)],
        },
    )

    await dispdata_coordinator._async_update_data()

    assert len(sent_items(dispdata_coordinator.device)) == 4


async def test_dispdata_text_without_sensors_is_an_error(dispdata_coordinator) -> None:
    set_pages(dispdata_coordinator, {"page_type": "dispdata_text"})

    data = await dispdata_coordinator._async_update_data()

    assert set(data.values()) == {"error"}


async def test_dispdata_text_sensor_without_an_entity_is_an_error(
    dispdata_coordinator,
) -> None:
    set_pages(
        dispdata_coordinator,
        {"page_type": "dispdata_text", "sensors": [{"name": "no entity"}]},
    )

    data = await dispdata_coordinator._async_update_data()

    assert set(data.values()) == {"error"}


async def test_dispdata_text_needs_a_resolvable_local_url(coordinator) -> None:
    """The device polls HA directly, so an external-only URL is no use."""
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        data={**coordinator.config_entry.data, CONF_DISPDATA_SECRET: "s3cret"},
    )
    set_pages(coordinator, {"page_type": "dispdata_text", "entity_id": "sensor.a"})

    with patch(f"{COORD}.get_url", side_effect=NoURLAvailableError):
        data = await coordinator._async_update_data()

    assert set(data.values()) == {"error"}


async def test_an_unchanged_dispdata_layout_is_not_resent(dispdata_coordinator) -> None:
    """The device self-polls values, so only a layout change needs a resend."""
    set_pages(dispdata_coordinator, {"page_type": "dispdata_text", "entity_id": "sensor.a"})

    await dispdata_coordinator._async_update_data()
    dispdata_coordinator.device.calls.clear()
    data = await dispdata_coordinator._async_update_data()

    assert dispdata_coordinator.device.calls == []
    assert set(data.values()) == {"unchanged"}


async def test_dispdata_items_mixes_labels_values_and_native_elements(
    dispdata_coordinator,
) -> None:
    set_pages(
        dispdata_coordinator,
        {
            "page_type": "dispdata_text",
            "items": [
                {"kind": "label", "text": "Temp"},
                {"entity_id": "sensor.a", "label": "Living Room"},
                {"kind": "time"},
            ],
        },
    )

    await dispdata_coordinator._async_update_data()

    items = sent_items(dispdata_coordinator.device)
    assert items[0]["type"] == 22
    assert items[0]["TextString"] == "Temp"
    assert items[1]["type"] == 23
    assert items[1]["TextString"].endswith("?label=Living_Room")
    assert items[2]["type"] == NATIVE_KIND_TYPES["time"]
    assert "TextString" not in items[2]


async def test_dispdata_items_of_only_native_kinds_needs_no_secret(
    coordinator,
) -> None:
    """Native elements are device-rendered, so there is nothing to poll."""
    set_pages(
        coordinator,
        {"page_type": "dispdata_text", "items": [{"kind": "time"}]},
    )

    data = await coordinator._async_update_data()

    assert set(data.values()) == {0}


async def test_dispdata_items_caps_at_eight_items(dispdata_coordinator) -> None:
    set_pages(
        dispdata_coordinator,
        {
            "page_type": "dispdata_text",
            "items": [{"kind": "label", "text": str(i)} for i in range(12)],
        },
    )

    await dispdata_coordinator._async_update_data()

    assert len(sent_items(dispdata_coordinator.device)) == 8


@pytest.mark.parametrize(
    "item",
    [
        {"kind": "label"},  # missing text
        {"kind": "nonsense"},  # unknown kind
        {"kind": "value"},  # missing entity_id
    ],
)
async def test_malformed_dispdata_items_are_reported_as_errors(
    dispdata_coordinator, item
) -> None:
    set_pages(dispdata_coordinator, {"page_type": "dispdata_text", "items": [item]})

    data = await dispdata_coordinator._async_update_data()

    assert set(data.values()) == {"error"}


async def test_dispdata_items_needs_a_resolvable_local_url(coordinator) -> None:
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        data={**coordinator.config_entry.data, CONF_DISPDATA_SECRET: "s3cret"},
    )
    set_pages(
        coordinator,
        {"page_type": "dispdata_text", "items": [{"entity_id": "sensor.a"}]},
    )

    with patch(f"{COORD}.get_url", side_effect=NoURLAvailableError):
        data = await coordinator._async_update_data()

    assert set(data.values()) == {"error"}


# --- card pages ------------------------------------------------------------


async def test_card_publishes_a_background_and_sends_an_item_list(
    dispdata_coordinator,
) -> None:
    """A card is an HA-rendered background GIF plus self-polling overlays."""
    gif = render_gif()
    items = [{"TextId": 1, "type": 23, "TextString": "http://x/poll"}]
    set_pages(dispdata_coordinator, {"page_type": "card", "card": "sensor_grid"})

    with (
        patch.dict(
            "custom_components.divoom_times_gate.cards.CARD_RENDERERS",
            {"sensor_grid": lambda hass, page, poll_base: (gif, items)},
        ),
        patch(f"{COORD}.publish_card_background") as publish,
    ):
        data = await dispdata_coordinator._async_update_data()

    assert set(data.values()) == {0}
    command = batched_commands(dispdata_coordinator.device)[0]
    assert command["Command"] == "Draw/SendHttpItemList"
    assert command["ItemList"] == items
    assert "/api/divoom_times_gate/cardbg/s3cret/" in command["BackgroudGif"]
    assert publish.call_count == SCREEN_COUNT
    # The preview shows the HA-rendered background; values live on the device.
    assert dispdata_coordinator.last_frames[0] is not None


async def test_a_card_without_overlays_pushes_artwork_instead_of_an_item_list(
    dispdata_coordinator,
) -> None:
    """An empty ItemList crashes the panel, so a card with no overlays sends a JPEG.

    The 24 hour history card bakes every figure into its artwork, so it returns
    no items to poll.
    """
    gif = render_gif()
    set_pages(dispdata_coordinator, {"page_type": "card", "card": "sensor_grid"})

    with (
        patch.dict(
            "custom_components.divoom_times_gate.cards.CARD_RENDERERS",
            {"sensor_grid": lambda hass, page, poll_base: (gif, [])},
        ),
        patch(f"{COORD}.publish_card_background") as publish,
    ):
        data = await dispdata_coordinator._async_update_data()

    assert set(data.values()) == {0}
    command = batched_commands(dispdata_coordinator.device)[0]
    assert command["Command"] == "Draw/SendHttpGif"
    # Nothing polls the background, so there is no need to serve it either.
    assert publish.call_count == 0
    assert dispdata_coordinator.last_frames[0] is not None


async def test_an_unchanged_card_does_not_flash_the_screen(
    dispdata_coordinator,
) -> None:
    """Resending the setup call repaints the panel, so only do it on a change."""
    gif = render_gif()
    items = [{"TextId": 1, "type": 23, "TextString": "http://x/poll"}]
    set_pages(dispdata_coordinator, {"page_type": "card", "card": "sensor_grid"})

    with (
        patch.dict(
            "custom_components.divoom_times_gate.cards.CARD_RENDERERS",
            {"sensor_grid": lambda hass, page, poll_base: (gif, items)},
        ),
        patch(f"{COORD}.publish_card_background"),
    ):
        await dispdata_coordinator._async_update_data()
        dispdata_coordinator.device.calls.clear()
        data = await dispdata_coordinator._async_update_data()

    assert dispdata_coordinator.device.calls == []
    assert set(data.values()) == {"unchanged"}


async def test_a_card_renderer_rejecting_its_config_is_an_error(
    dispdata_coordinator,
) -> None:
    def boom(hass, page, poll_base):
        raise ValueError("slot 3 has no entity_id")

    set_pages(dispdata_coordinator, {"page_type": "card", "card": "sensor_grid"})

    with patch.dict(
        "custom_components.divoom_times_gate.cards.CARD_RENDERERS",
        {"sensor_grid": boom},
    ):
        data = await dispdata_coordinator._async_update_data()

    assert set(data.values()) == {"error"}


async def test_card_without_a_resolvable_local_url_is_an_error(coordinator) -> None:
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        data={**coordinator.config_entry.data, CONF_DISPDATA_SECRET: "s3cret"},
    )
    set_pages(coordinator, {"page_type": "card", "card": "sensor_grid"})

    with patch(f"{COORD}.get_url", side_effect=NoURLAvailableError):
        data = await coordinator._async_update_data()

    assert set(data.values()) == {"error"}


async def test_dispdata_value_items_may_omit_a_label(dispdata_coordinator) -> None:
    set_pages(
        dispdata_coordinator,
        {"page_type": "dispdata_text", "items": [{"entity_id": "sensor.a"}]},
    )

    await dispdata_coordinator._async_update_data()

    assert "?" not in sent_items(dispdata_coordinator.device)[0]["TextString"]


async def test_restoring_the_dashboard_reasserts_the_independent_base(
    coordinator,
) -> None:
    """The base preset holds the five-screen layout HA then draws over."""
    coordinator.presets = [IndependentPreset("Control3", 333, 2)]
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={**coordinator.config_entry.options, CONF_DASHBOARD_BASE: "2"},
    )
    coordinator.restore_display("dashboard", None)

    await coordinator.async_apply_restored_state()

    assert ("set_independent_preset", (333,), {}) in coordinator.device.calls


async def test_a_reload_repopulates_the_preview_without_resending(
    coordinator, hass, mock_config_entry, fake_times_gate
) -> None:
    """Hashes survive a reload but the frame cache does not, so the preview
    would otherwise stay blank until the screen's content changed."""
    set_pages(coordinator, {"page_type": "off"})
    await coordinator._async_update_data()

    reloaded = TimesGateCoordinator(hass, mock_config_entry, fake_times_gate, 15)
    fake_times_gate.calls.clear()
    data = await reloaded._async_update_data()
    reloaded._debounced_refresh.async_cancel()

    assert set(data.values()) == {"unchanged"}
    assert command_names(fake_times_gate) == ["reset_pic_counter"]
    assert reloaded.last_frames[0] is not None


async def test_the_unavailable_warning_is_logged_once(coordinator, caplog) -> None:
    """A device that stays down must not fill the log on every tick."""
    coordinator.device.consecutive_failures = 3

    for _ in range(2):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    assert caplog.text.count("became unavailable") == 1


async def test_a_page_shorter_than_its_duration_does_not_advance(coordinator) -> None:
    """Rotation is time based, so a 60s page survives a 15s tick."""
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry,
        options={
            **coordinator.config_entry.options,
            CONF_SCREENS: [
                [
                    {"page_type": "clock", "clock_id": 61, "duration": 60},
                    {"page_type": "clock", "clock_id": 62, "duration": 60},
                ]
            ]
            * SCREEN_COUNT,
        },
    )

    await coordinator._async_update_data()
    await coordinator._async_update_data()

    assert coordinator._rot_index[0] == 0

"""Tests for the ``TimesGate`` local HTTP client.

The contract these tests pin down (see ``docs/API.md`` §0.1/§0.2 and §5):

* ``_send`` never raises. Transport failures come back as a dict with
  ``error_code == "exception"``; device rejections come back with whatever
  ``error_code`` the device sent.
* every command carries an integer ``LocalToken``.
* ``PicID`` increases monotonically across screens.
* hardware revision 402 talks to port 9000 ``/divoom_api``; 400 uses port 80
  ``/post``.
"""
from __future__ import annotations

import asyncio

from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest

from custom_components.divoom_times_gate.device import TimesGate

HW_400_URL = "http://192.168.1.25/post"
HW_402_URL = "http://192.168.1.25:9000/divoom_api"


def _bodies(aioclient_mock) -> list[dict]:
    """Return the JSON body of every request the client made."""
    return [call[2] for call in aioclient_mock.mock_calls]


@pytest.fixture
def device(hass, aioclient_mock):
    """Return a hardware-400 client wired to Home Assistant's mocked session."""
    return TimesGate("192.168.1.25", 123456, async_get_clientsession(hass), 400)


# --- endpoint selection ----------------------------------------------------


async def test_hardware_400_uses_port_80_post(hass, aioclient_mock) -> None:
    """The test unit (HW 400) posts to port 80 /post."""
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})
    client = TimesGate("192.168.1.25", 123456, async_get_clientsession(hass), 400)

    await client.ping()

    assert aioclient_mock.call_count == 1
    assert str(aioclient_mock.mock_calls[0][1]) == HW_400_URL


async def test_hardware_402_uses_port_9000_divoom_api(hass, aioclient_mock) -> None:
    """HW 402 routes to the Frame-family endpoint on port 9000."""
    aioclient_mock.post(HW_402_URL, json={"error_code": 0})
    client = TimesGate("192.168.1.25", 123456, async_get_clientsession(hass), 402)

    await client.ping()

    assert str(aioclient_mock.mock_calls[0][1]) == HW_402_URL


@pytest.mark.parametrize("hardware", [400, 401, 403, 4000])
async def test_unknown_hardware_falls_back_to_port_80(
    hass, aioclient_mock, hardware
) -> None:
    """Anything that is not 402 uses the default port 80 endpoint."""
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})
    client = TimesGate("192.168.1.25", 1, async_get_clientsession(hass), hardware)

    await client.ping()

    assert str(aioclient_mock.mock_calls[0][1]) == HW_400_URL


# --- LocalToken ------------------------------------------------------------


async def test_local_token_is_injected_into_every_command(
    device, aioclient_mock
) -> None:
    """Without LocalToken the device rejects even read-only commands."""
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})

    await device.ping()
    await device.set_brightness(50)
    await device.turn_on()
    await device.set_whole_face(581)
    await device.send_jpeg(b"jpeg-bytes", 0)

    bodies = _bodies(aioclient_mock)
    assert len(bodies) == 5
    assert all(body["LocalToken"] == 123456 for body in bodies)
    assert all(isinstance(body["LocalToken"], int) for body in bodies)


async def test_local_token_is_coerced_to_int(hass, aioclient_mock) -> None:
    """A token typed as a string in the config entry still goes out as an int."""
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})
    client = TimesGate("192.168.1.25", "987654", async_get_clientsession(hass), 400)

    await client.ping()

    assert _bodies(aioclient_mock)[0]["LocalToken"] == 987654


async def test_command_list_carries_token_only_on_the_wrapper(
    device, aioclient_mock
) -> None:
    """Sub-commands must not repeat LocalToken (docs/API.md §5.1)."""
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})
    sub = device.build_clock_face(0, 61)

    await device.send_command_list([sub])

    body = _bodies(aioclient_mock)[0]
    assert body["Command"] == "Draw/CommandList"
    assert body["LocalToken"] == 123456
    assert "LocalToken" not in body["CommandList"][0]


# --- the _send error contract ---------------------------------------------


async def test_send_returns_exception_dict_instead_of_raising(
    device, aioclient_mock
) -> None:
    """Transport failure is reported, never raised."""
    aioclient_mock.post(HW_400_URL, exc=TimeoutError("timed out"))

    result = await device.send_jpeg(b"x", 0)

    assert result["error_code"] == "exception"
    assert "timed out" in result["exception"]


@pytest.mark.parametrize(
    "boom",
    [
        TimeoutError("timeout"),
        ValueError("bad json"),
        OSError("connection refused"),
    ],
)
async def test_send_swallows_every_transport_error(device, aioclient_mock, boom) -> None:
    """``_send`` catches broadly on purpose so one bad tick cannot kill setup."""
    aioclient_mock.post(HW_400_URL, exc=boom)

    result = await device.get_conf()

    assert result["error_code"] == "exception"


async def test_send_lets_cancellation_propagate(device, aioclient_mock) -> None:
    """``CancelledError`` is a BaseException, so shutdown is not swallowed."""
    aioclient_mock.post(HW_400_URL, exc=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        await device.get_conf()


async def test_transport_failures_increment_consecutive_failures(
    device, aioclient_mock
) -> None:
    """The coordinator watches this counter to trigger IP self-healing."""
    aioclient_mock.post(HW_400_URL, exc=TimeoutError("nope"))

    await device.ping()
    await device.ping()
    await device.ping()

    assert device.consecutive_failures == 3


async def test_successful_round_trip_resets_failure_counter(
    device, aioclient_mock
) -> None:
    """One good response clears the streak."""
    device.consecutive_failures = 7
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})

    await device.ping()

    assert device.consecutive_failures == 0


async def test_device_level_rejection_is_not_a_transport_failure(
    device, aioclient_mock
) -> None:
    """A non-zero error_code means the device answered, so it is reachable."""
    device.consecutive_failures = 2
    aioclient_mock.post(HW_400_URL, json={"error_code": "DeviceToken is err"})

    result = await device.get_conf()

    assert result == {"error_code": "DeviceToken is err"}
    assert device.consecutive_failures == 0


async def test_ping_is_true_only_on_error_code_zero(device, aioclient_mock) -> None:
    """``ping`` answers "does the device accept our LocalToken"."""
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})
    assert await device.ping() is True

    aioclient_mock.clear_requests()
    aioclient_mock.post(HW_400_URL, json={"error_code": "DeviceToken is err"})
    assert await device.ping() is False

    aioclient_mock.clear_requests()
    aioclient_mock.post(HW_400_URL, exc=TimeoutError("gone"))
    assert await device.ping() is False


# --- screen index guards ---------------------------------------------------


@pytest.mark.parametrize("bad_screen", [-1, 5, 99])
def test_build_jpeg_rejects_out_of_range_screen(device, bad_screen) -> None:
    with pytest.raises(ValueError, match="Screen must be 0-4"):
        device.build_jpeg(b"x", bad_screen)


@pytest.mark.parametrize("bad_screen", [-1, 5, 99])
def test_build_clock_face_rejects_out_of_range_screen(device, bad_screen) -> None:
    with pytest.raises(ValueError, match="Screen must be 0-4"):
        device.build_clock_face(bad_screen, 61)


@pytest.mark.parametrize("bad_screen", [-1, 5, 99])
def test_build_item_list_rejects_out_of_range_screen(device, bad_screen) -> None:
    with pytest.raises(ValueError, match="Screen must be 0-4"):
        device.build_item_list(bad_screen, [])


async def test_send_animation_rejects_out_of_range_screen(device) -> None:
    """The guard also fires on the multi-frame path, before any POST."""
    with pytest.raises(ValueError, match="Screen must be 0-4"):
        await device.send_animation([b"a", b"b"], 5)


@pytest.mark.parametrize("screen", [0, 1, 2, 3, 4])
def test_every_valid_screen_index_is_accepted(device, screen) -> None:
    payload = device.build_jpeg(b"x", screen)

    expected = [0] * 5
    expected[screen] = 1
    assert payload["LcdArray"] == expected


# --- PicID monotonicity ----------------------------------------------------


def test_pic_id_increases_monotonically_across_screens(device) -> None:
    """Random or repeated ids cause silent drops or a stuck "loading"."""
    ids = [device.build_jpeg(b"frame", screen)["PicID"] for screen in range(5)]

    assert ids == [1, 2, 3, 4, 5]


def test_pic_id_advances_even_when_the_payload_is_never_sent(device) -> None:
    """``build_jpeg`` bumps the counter on build, so batched commands stay unique."""
    device.build_jpeg(b"a", 0)

    assert device.build_jpeg(b"b", 0)["PicID"] == 2


async def test_reset_pic_counter_resets_local_and_device_counters(
    device, aioclient_mock
) -> None:
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})
    device.build_jpeg(b"a", 0)
    device.build_jpeg(b"b", 0)

    await device.reset_pic_counter()

    assert _bodies(aioclient_mock)[0]["Command"] == "Draw/ResetHttpGifId"
    assert device.build_jpeg(b"c", 0)["PicID"] == 1


# --- payload shapes --------------------------------------------------------


def test_build_jpeg_base64_encodes_the_image(device) -> None:
    """PicData is base64 JPEG, never raw RGB (docs/API.md §5)."""
    payload = device.build_jpeg(b"jpeg-bytes", 2)

    assert payload["Command"] == "Draw/SendHttpGif"
    assert payload["PicData"] == "anBlZy1ieXRlcw=="
    assert payload["PicWidth"] == 128
    assert payload["PicNum"] == 1
    assert payload["PicOffset"] == 0


def test_build_clock_face_omits_independence_when_not_given(device) -> None:
    payload = device.build_clock_face(3, 61)

    assert payload == {
        "Command": "Channel/SetClockSelectId",
        "ClockId": 61,
        "LcdIndex": 3,
    }


def test_build_clock_face_includes_independence_when_given(device) -> None:
    payload = device.build_clock_face(3, 61, 987)

    assert payload["LcdIndependence"] == 987


def test_build_clock_face_treats_zero_independence_as_absent(device) -> None:
    """0 is not a real independence id, so it must not be sent."""
    assert "LcdIndependence" not in device.build_clock_face(0, 61, 0)


def test_build_visualizer_shapes(device) -> None:
    assert device.build_visualizer(1, 3) == {
        "Command": "Channel/SetEqPosition",
        "EqPosition": 3,
        "LcdIndex": 1,
    }
    assert device.build_visualizer(1, 3, 77)["LcdIndependence"] == 77


def test_build_play_gif_selects_one_screen_via_lcd_array(device) -> None:
    payload = device.build_play_gif(4, ["http://x/a.gif"])

    assert payload["Command"] == "Device/PlayGif"
    assert payload["LcdArray"] == [0, 0, 0, 0, 1]
    assert payload["FileName"] == ["http://x/a.gif"]


def test_build_item_list_rejects_an_empty_item_list(device) -> None:
    """An empty ItemList crashes the panel, so it never leaves the client."""
    with pytest.raises(ValueError, match="at least one item"):
        device.build_item_list(0, [])


def test_build_item_list_sets_new_flag_from_background_gif(device) -> None:
    """A background GIF means a full repaint (NewFlag 1); items-only is 0."""
    with_bg = device.build_item_list(0, [{"TextId": 1}], "http://ha/bg.gif")
    without_bg = device.build_item_list(0, [{"TextId": 1}])

    assert with_bg["NewFlag"] == 1
    assert with_bg["BackgroudGif"] == "http://ha/bg.gif"
    assert without_bg["NewFlag"] == 0
    assert "BackgroudGif" not in without_bg


# --- higher level commands -------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"), [(-20, 0), (0, 0), (55, 55), (100, 100), (250, 100)]
)
async def test_set_brightness_clamps_to_0_100(
    device, aioclient_mock, given, expected
) -> None:
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})

    await device.set_brightness(given)

    assert _bodies(aioclient_mock)[0]["Brightness"] == expected


async def test_turn_on_and_off_use_on_off_screen(device, aioclient_mock) -> None:
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})

    await device.turn_on()
    await device.turn_off()

    bodies = _bodies(aioclient_mock)
    assert bodies[0] == {
        "Command": "Channel/OnOffScreen",
        "OnOff": 1,
        "LocalToken": 123456,
    }
    assert bodies[1]["OnOff"] == 0


async def test_set_whole_face_uses_overall_display_command(
    device, aioclient_mock
) -> None:
    """Overall Display spans all five screens (ChannelType 0)."""
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})

    await device.set_whole_face(581)

    body = _bodies(aioclient_mock)[0]
    assert body["Command"] == "Channel/Set5LcdWholeClockId"
    assert body["ClockId"] == 581


async def test_set_independent_preset_sends_channel_type_1(
    device, aioclient_mock
) -> None:
    """Independent Display is ChannelType 1 plus the preset's LcdIndependence."""
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})

    await device.set_independent_preset(4242)

    body = _bodies(aioclient_mock)[0]
    assert body["Command"] == "Channel/Set5LcdChannelType"
    assert body["ChannelType"] == 1
    assert body["LcdIndependence"] == 4242


async def test_set_rgb_edgelight_places_effect_at_index_1(
    device, aioclient_mock
) -> None:
    """Edgelight (light_index 1): LightList[1]=effect, [2]=secondary."""
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})

    await device.set_rgb(1, True, "#FF0000", 80, effect=3, secondary_effect=6)

    body = _bodies(aioclient_mock)[0]
    assert body["OnOff"] == 1
    assert body["SelectLightIndex"] == 1
    assert [entry["SelectEffect"] for entry in body["LightList"]] == [0, 3, 6]


async def test_set_rgb_backlight_swaps_the_light_list_slots(
    device, aioclient_mock
) -> None:
    """Backlight (light_index 2): LightList[1]=secondary, [2]=effect."""
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})

    await device.set_rgb(2, False, "#00FF00", 40, effect=9, secondary_effect=5)

    body = _bodies(aioclient_mock)[0]
    assert body["OnOff"] == 0
    assert [entry["SelectEffect"] for entry in body["LightList"]] == [0, 5, 9]


async def test_set_rgb_color_cycle_flag(device, aioclient_mock) -> None:
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})

    await device.set_rgb(1, True, "#FFFFFF", 100, color_cycle=True)

    assert _bodies(aioclient_mock)[0]["ColorCycle"] == 1


async def test_set_key_backlight(device, aioclient_mock) -> None:
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})

    await device.set_key_backlight(True)

    body = _bodies(aioclient_mock)[0]
    assert body["Command"] == "Channel/SetRGBInfo"
    assert body["KeyOnOff"] == 1


async def test_play_buzzer_passes_the_timing_triplet(device, aioclient_mock) -> None:
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})

    await device.play_buzzer(100, 200, 900)

    body = _bodies(aioclient_mock)[0]
    assert body["Command"] == "Device/PlayBuzzer"
    assert body["ActiveTimeInCycle"] == 100
    assert body["OffTimeInCycle"] == 200
    assert body["PlayTotalTime"] == 900


async def test_send_item_list_and_play_gif_and_set_visualizer_post(
    device, aioclient_mock
) -> None:
    """The async wrappers post exactly what their build_* counterpart returns."""
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})

    await device.send_item_list(0, [{"TextId": 1}])
    await device.play_gif(1, ["http://x/a.gif"])
    await device.set_visualizer(2, 5)
    await device.set_clock_face(3, 61)

    commands = [body["Command"] for body in _bodies(aioclient_mock)]
    assert commands == [
        "Draw/SendHttpItemList",
        "Device/PlayGif",
        "Channel/SetEqPosition",
        "Channel/SetClockSelectId",
    ]


# --- animations ------------------------------------------------------------


async def test_single_frame_animation_falls_back_to_send_jpeg(
    device, aioclient_mock
) -> None:
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})

    await device.send_animation([b"only"], 0, 500)

    body = _bodies(aioclient_mock)[0]
    assert body["PicNum"] == 1
    assert body["PicSpeed"] == 1000  # send_jpeg's fixed speed, not speed_ms


async def test_animation_frames_share_one_pic_id_and_increment_offset(
    device, aioclient_mock
) -> None:
    """docs/API.md §5: one PicID for the animation, PicOffset per frame."""
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})

    await device.send_animation([b"a", b"b", b"c"], 1, 200)

    bodies = _bodies(aioclient_mock)
    assert len(bodies) == 3
    assert {body["PicID"] for body in bodies} == {1}
    assert [body["PicOffset"] for body in bodies] == [0, 1, 2]
    assert all(body["PicNum"] == 3 for body in bodies)
    assert all(body["LcdArray"] == [0, 1, 0, 0, 0] for body in bodies)


async def test_animation_speed_has_a_floor_of_50ms(device, aioclient_mock) -> None:
    aioclient_mock.post(HW_400_URL, json={"error_code": 0})

    await device.send_animation([b"a", b"b"], 0, 5)

    assert all(body["PicSpeed"] == 50 for body in _bodies(aioclient_mock))


async def test_animation_stops_at_the_first_failed_frame(
    device, aioclient_mock
) -> None:
    """No point streaming the rest of the frames once one is rejected."""
    aioclient_mock.post(HW_400_URL, json={"error_code": 5})

    result = await device.send_animation([b"a", b"b", b"c"], 0, 200)

    assert result["error_code"] == 5
    assert aioclient_mock.call_count == 1

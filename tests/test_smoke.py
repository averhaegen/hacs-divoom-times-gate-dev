"""Smoke tests proving the shared pytest/Home Assistant harness works."""
from __future__ import annotations

from custom_components.divoom_times_gate.const import (
    CONF_IP_ADDRESS,
    CONF_LOCAL_TOKEN,
    CONF_REFRESH_INTERVAL,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    SCREEN_COUNT,
)


async def test_fake_times_gate_fixture_records_calls(fake_times_gate) -> None:
    """The fake device fixture should behave like an awaitable network-free client."""
    assert await fake_times_gate.ping() is True

    response = await fake_times_gate.set_whole_face(581)

    assert response == {"error_code": 0}
    assert fake_times_gate.calls == [
        ("ping", (), {}),
        ("set_whole_face", (581,), {}),
    ]


def test_constants_import_smoke() -> None:
    """Importing integration constants should work in the pytest harness."""
    assert DOMAIN == "divoom_times_gate"
    assert CONF_IP_ADDRESS == "ip_address"
    assert CONF_LOCAL_TOKEN == "local_token"
    assert SCREEN_COUNT == 5


async def test_mock_config_entry_fixture_can_be_added_to_hass(
    hass, mock_config_entry
) -> None:
    """The shared config entry fixture should be ready for future HA tests."""
    mock_config_entry.add_to_hass(hass)

    entry = hass.config_entries.async_entries(DOMAIN)[0]

    assert entry.data[CONF_IP_ADDRESS] == "192.168.1.25"
    assert entry.data[CONF_LOCAL_TOKEN] == 123456
    assert entry.options[CONF_REFRESH_INTERVAL] == DEFAULT_REFRESH_INTERVAL

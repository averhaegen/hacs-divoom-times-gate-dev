"""Tests for the IP self-healing path in the integration's setup."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest

from custom_components.divoom_times_gate import _try_heal_ip
from custom_components.divoom_times_gate.const import (
    CONF_DEVICE_ID,
    CONF_IP_ADDRESS,
    CONF_MAC,
)

from .conftest import make_discovered

INIT = "custom_components.divoom_times_gate"


@pytest.fixture
def entry(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    return mock_config_entry


def patch_discovery(devices):
    return patch(f"{INIT}.async_discover_devices", AsyncMock(return_value=devices))


async def test_heal_matches_on_mac_and_returns_a_client_on_the_new_ip(
    hass, entry
) -> None:
    """A DHCP change keeps the MAC, so that is the primary handle."""
    moved = make_discovered(ip="192.168.1.99", mac="aa:bb:cc:dd:ee:ff", device_id=4242)
    session = async_get_clientsession(hass)

    with patch_discovery([moved]):
        device = await _try_heal_ip(hass, entry, session)

    assert device is not None
    assert device._url == "http://192.168.1.99/post"
    assert entry.data[CONF_IP_ADDRESS] == "192.168.1.99"
    assert entry.title == "Times Gate (192.168.1.99)"


async def test_heal_falls_back_to_the_device_id(hass, entry) -> None:
    """Discovery does not always report a MAC; the DeviceId still identifies it."""
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_MAC: ""})
    moved = make_discovered(ip="192.168.1.99", mac="", device_id=4242)
    session = async_get_clientsession(hass)

    with patch_discovery([moved]):
        device = await _try_heal_ip(hass, entry, session)

    assert device is not None
    assert entry.data[CONF_DEVICE_ID] == 4242


async def test_heal_skips_devices_that_match_neither_identifier(hass, entry) -> None:
    other = make_discovered(ip="192.168.1.99", mac="99:99:99:99:99:99", device_id=7)
    session = async_get_clientsession(hass)

    with patch_discovery([other]):
        assert await _try_heal_ip(hass, entry, session) is None

    assert entry.data[CONF_IP_ADDRESS] == "192.168.1.25"


async def test_heal_does_nothing_when_the_ip_is_unchanged(hass, entry) -> None:
    """The device answered discovery but is still at the stored address."""
    session = async_get_clientsession(hass)

    with patch_discovery([make_discovered(ip="192.168.1.25")]):
        assert await _try_heal_ip(hass, entry, session) is None


async def test_heal_does_nothing_when_discovery_is_empty(hass, entry) -> None:
    session = async_get_clientsession(hass)

    with patch_discovery([]):
        assert await _try_heal_ip(hass, entry, session) is None


async def test_heal_carries_the_stored_token_and_hardware_over(hass, entry) -> None:
    """The healed client must keep talking to the same device, not a default one."""
    moved = make_discovered(ip="192.168.1.99")
    session = async_get_clientsession(hass)

    with patch_discovery([moved]):
        device = await _try_heal_ip(hass, entry, session)

    assert device._local_token == 123456
    assert device._url == "http://192.168.1.99/post"


async def test_heal_gives_up_when_the_entry_has_no_identifiers(hass, entry) -> None:
    """Without a MAC or DeviceId, picking any discovered device would be a guess."""
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_MAC: "", CONF_DEVICE_ID: 0}
    )
    session = async_get_clientsession(hass)

    with patch_discovery([make_discovered(ip="192.168.1.99")]):
        assert await _try_heal_ip(hass, entry, session) is None

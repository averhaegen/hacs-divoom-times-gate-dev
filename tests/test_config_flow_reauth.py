"""Tests for the LocalToken reauthentication flow (issue #6)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.divoom_times_gate.const import (
    AUTH_INVALID,
    AUTH_OK,
    AUTH_UNREACHABLE,
    CONF_HARDWARE,
    CONF_IP_ADDRESS,
    CONF_LOCAL_TOKEN,
)

NEW_TOKEN = 987654


def _patch_device(*auth_results: str):
    """Patch the config flow's TimesGate so check_auth returns given results."""
    device = AsyncMock()
    device.check_auth.side_effect = list(auth_results)
    return patch(
        "custom_components.divoom_times_gate.config_flow.TimesGate",
        return_value=device,
    ), device


async def test_reauth_updates_token_in_place(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A valid new token is written to the existing entry, no new entry."""
    mock_config_entry.add_to_hass(hass)
    old_token = mock_config_entry.data[CONF_LOCAL_TOKEN]

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    patcher, device = _patch_device(AUTH_OK)
    with patcher as times_gate, patch(
        "custom_components.divoom_times_gate.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_LOCAL_TOKEN: NEW_TOKEN}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_LOCAL_TOKEN] == NEW_TOKEN
    assert mock_config_entry.data[CONF_LOCAL_TOKEN] != old_token
    assert len(hass.config_entries.async_entries(mock_config_entry.domain)) == 1

    # The probe must use the entry's own address and hardware revision, not
    # defaults, so a revision 402 unit is validated on port 9000/divoom_api.
    args = times_gate.call_args.args
    assert args[0] == mock_config_entry.data[CONF_IP_ADDRESS]
    assert args[1] == NEW_TOKEN
    assert args[3] == mock_config_entry.data[CONF_HARDWARE]


async def test_reauth_rejects_wrong_token(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A token the device refuses re-shows the form and leaves the entry alone."""
    mock_config_entry.add_to_hass(hass)
    old_token = mock_config_entry.data[CONF_LOCAL_TOKEN]

    result = await mock_config_entry.start_reauth_flow(hass)
    patcher, _ = _patch_device(AUTH_INVALID, AUTH_OK)
    with patcher, patch(
        "custom_components.divoom_times_gate.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_LOCAL_TOKEN: 111111}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}
        assert mock_config_entry.data[CONF_LOCAL_TOKEN] == old_token

        # Recovery on a second attempt still works within the same flow.
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_LOCAL_TOKEN: NEW_TOKEN}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_LOCAL_TOKEN] == NEW_TOKEN


async def test_reauth_unreachable_device_is_not_an_auth_error(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """No answer at all reports cannot_connect, not a bad token."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    patcher, _ = _patch_device(AUTH_UNREACHABLE)
    with patcher:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_LOCAL_TOKEN: NEW_TOKEN}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_check_auth_separates_rejection_from_silence() -> None:
    """The discriminator: _send never raises, so the return shape decides."""
    from custom_components.divoom_times_gate.device import TimesGate

    device = TimesGate("192.168.1.25", 123456, None)
    cases = {
        AUTH_OK: {"error_code": 0},
        AUTH_UNREACHABLE: {"error_code": "exception", "exception": "timeout"},
        AUTH_INVALID: {"error_code": "DeviceToken is err"},
    }
    for expected, response in cases.items():
        with patch.object(TimesGate, "_send", AsyncMock(return_value=response)):
            assert await device.check_auth() == expected

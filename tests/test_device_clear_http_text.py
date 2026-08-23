"""Draw/ClearHttpText payload building, used to tear down DispData overlays."""
from __future__ import annotations

import pytest

from custom_components.divoom_times_gate.const import SCREEN_COUNT
from custom_components.divoom_times_gate.device import TimesGate


def _device() -> TimesGate:
    return TimesGate("192.168.1.25", 123456, session=None)  # type: ignore[arg-type]


def test_clear_http_text_defaults_to_clearing_every_overlay() -> None:
    """A negative TextId clears all text on the screen (docs/API.md 4.8)."""
    assert _device().build_clear_http_text(2) == {
        "Command": "Draw/ClearHttpText",
        "LcdId": 2,
        "TextId": -1,
    }


def test_clear_http_text_accepts_a_single_text_id() -> None:
    assert _device().build_clear_http_text(0, 3)["TextId"] == 3


@pytest.mark.parametrize("screen", [-1, SCREEN_COUNT])
def test_clear_http_text_rejects_an_out_of_range_screen(screen: int) -> None:
    with pytest.raises(ValueError):
        _device().build_clear_http_text(screen)

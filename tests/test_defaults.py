"""Tests for the fallback screen configuration.

``coordinator._screens()`` falls back to ``DEFAULT_SCREENS`` whenever no
options exist, so whatever is in there is what a fresh install puts on the
device. It used to be the maintainer's own entity ids, which rendered as five
confident labels over sensors nobody else has. These tests keep it neutral.
"""
from __future__ import annotations

import json

from custom_components.divoom_times_gate.const import SCREEN_COUNT
from custom_components.divoom_times_gate.defaults import DEFAULT_FACES, DEFAULT_SCREENS


def test_default_screens_cover_every_screen() -> None:
    """The fallback fills all five screens, so no screen is left undefined."""
    assert len(DEFAULT_SCREENS) == SCREEN_COUNT


def test_default_screens_name_no_entity() -> None:
    """No entity id, template or domain reference may reach the defaults."""
    dumped = json.dumps(DEFAULT_SCREENS)
    assert "{{" not in dumped
    assert "states(" not in dumped
    for domain in ("sensor.", "weather.", "binary_sensor.", "climate."):
        assert domain not in dumped


def test_default_screens_are_a_clock_then_off() -> None:
    """Screen 1 shows a native face; screens 2-5 stay black."""
    first, *rest = DEFAULT_SCREENS
    assert first["page_type"] == "clock"
    assert isinstance(first["clock_id"], int)
    assert all(page == {"page_type": "off"} for page in rest)


def test_default_clock_face_is_offered_by_the_screen_select() -> None:
    """The default face is a per-screen favorite, so it stays selectable."""
    known = {face["clock_id"] for face in DEFAULT_FACES["per_screen"]}
    assert DEFAULT_SCREENS[0]["clock_id"] in known

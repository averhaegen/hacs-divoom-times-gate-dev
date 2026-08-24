"""Tests for the page-dict/form conversion.

The rule these pin down: a form only ever gets offered when it can write back
everything the page already holds. A screen someone hand-wrote must come out of
the options flow exactly as it went in.
"""
from __future__ import annotations

import pytest

from custom_components.divoom_times_gate import page_forms
from custom_components.divoom_times_gate.const import DEFAULT_DURATION

SENSOR_PAGE = {
    "page_type": "card",
    "card": "sensor_grid",
    "theme": "navy",
    "duration": 30,
    "slots": [{"entity_id": "sensor.a"}, {"entity_id": "sensor.b", "name": "B"}],
}


@pytest.mark.parametrize(
    ("pages", "kind"),
    [
        ({"page_type": "off"}, page_forms.KIND_OFF),
        ({"page_type": "clock", "clock_id": 152}, page_forms.KIND_FACE),
        (SENSOR_PAGE, page_forms.KIND_SENSORS),
        ([SENSOR_PAGE], page_forms.KIND_SENSORS),
        ({"page_type": "gif", "url": "x"}, None),
        ({"page_type": "card", "card": "graph"}, None),
        ({"components": []}, None),
        ([{"page_type": "off"}, {"page_type": "off"}], None),
    ],
)
def test_page_kind(pages, kind) -> None:
    assert page_forms.page_kind(pages) == kind


@pytest.mark.parametrize(
    ("pages", "fragment"),
    [
        ([{"page_type": "off"}, {"page_type": "off"}], "rotates"),
        ({"page_type": "gif", "url": "x"}, "gif page"),
        ({"page_type": "card", "card": "graph"}, "graph card"),
        (
            {**SENSOR_PAGE, "slots": [{"entity_id": "sensor.a", "value_template": "x"}]},
            "value_template",
        ),
        (
            {**SENSOR_PAGE, "background": "#ff0000"},
            "background",
        ),
        (
            {**SENSOR_PAGE, "slots": [{"entity_id": f"sensor.s{i}"} for i in range(9)]},
            "more than 8",
        ),
    ],
)
def test_unsupported_reason_names_what_would_be_lost(pages, fragment) -> None:
    """The user is told which thing the form would drop, not which rule fired."""
    reason = page_forms.unsupported_reason(pages)
    assert reason is not None
    assert fragment in reason


@pytest.mark.parametrize("pages", [SENSOR_PAGE, {"page_type": "off"}, [SENSOR_PAGE]])
def test_supported_pages_have_no_reason(pages) -> None:
    assert page_forms.unsupported_reason(pages) is None


def test_sensor_round_trip_keeps_entities_theme_and_duration() -> None:
    defaults = page_forms.sensor_defaults(SENSOR_PAGE)
    assert defaults[page_forms.CONF_ENTITIES] == ["sensor.a", "sensor.b"]
    assert defaults[page_forms.CONF_THEME] == "navy"
    assert defaults[page_forms.CONF_DURATION] == 30

    page = page_forms.sensor_page(defaults)
    assert page["card"] == "sensor_grid"
    assert page["theme"] == "navy"
    assert page["duration"] == 30
    assert [slot["entity_id"] for slot in page["slots"]] == ["sensor.a", "sensor.b"]


def test_sensor_defaults_are_empty_for_a_foreign_page() -> None:
    """A form opened on a page it does not own starts blank, never half-read."""
    defaults = page_forms.sensor_defaults({"page_type": "gif", "url": "x"})
    assert defaults[page_forms.CONF_ENTITIES] == []
    assert defaults[page_forms.CONF_DURATION] == DEFAULT_DURATION


def test_sensor_page_caps_at_eight_entities_and_falls_back_to_a_known_theme() -> None:
    page = page_forms.sensor_page(
        {
            page_forms.CONF_ENTITIES: [f"sensor.s{i}" for i in range(12)],
            page_forms.CONF_THEME: "not_a_theme",
            page_forms.CONF_DURATION: 15,
        }
    )
    assert len(page["slots"]) == 8
    assert page["theme"] == "dark"


def test_face_round_trip() -> None:
    defaults = page_forms.face_defaults({"page_type": "clock", "clock_id": 152})
    assert defaults[page_forms.CONF_CLOCK_ID] == "152"
    assert page_forms.face_page(defaults) == {
        "page_type": "clock",
        "clock_id": 152,
        "duration": DEFAULT_DURATION,
    }


def test_a_legacy_id_key_is_read_as_the_clock_id() -> None:
    """gickowtf configs write 'id' where this integration writes 'clock_id'."""
    assert page_forms.face_defaults({"page_type": "clock", "id": 61})[
        page_forms.CONF_CLOCK_ID
    ] == "61"

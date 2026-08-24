"""Guards on the user-facing strings for the config and options flows.

These lock in the two defects the owner reported:

* The per-screen menu rendered rows with no text, because a menu option key had
  no matching label. Every key the screen step can emit must resolve to a
  non-empty label here.
* The Settings step's ``dashboard_base`` field had no explanation. It must carry
  a ``data_description``.

``strings.json`` is the source and ``translations/en.json`` must match it byte
for byte, so both files are checked for equality.
"""
from __future__ import annotations

import json
from pathlib import Path

_COMPONENT = Path("custom_components/divoom_times_gate")
_STRINGS = _COMPONENT / "strings.json"
_EN = _COMPONENT / "translations" / "en.json"

# Every menu option key async_step_screen_* can emit, from config_flow.py.
_SCREEN_MENU_KEYS = (
    "screen_template",
    "screen_sensors",
    "screen_face",
    "screen_off",
    "screen_yaml",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_strings_and_english_translation_are_identical() -> None:
    """en.json must carry the exact text of strings.json."""
    assert _STRINGS.read_text(encoding="utf-8") == _EN.read_text(encoding="utf-8")


def test_every_screen_menu_option_has_a_label() -> None:
    """Each per-screen menu key resolves to a non-empty label in both files."""
    for source in (_STRINGS, _EN):
        steps = _load(source)["options"]["step"]
        for index in range(5):
            menu = steps[f"screen_{index}"]["menu_options"]
            for key in _SCREEN_MENU_KEYS:
                assert menu.get(key), f"{source.name}: screen_{index} missing {key}"


def test_settings_step_explains_the_dashboard_base_field() -> None:
    """The dashboard_base field carries a label and a one-line explanation."""
    for source in (_STRINGS, _EN):
        settings = _load(source)["options"]["step"]["settings"]
        assert settings["data"]["dashboard_base"]
        assert settings["data_description"]["dashboard_base"]

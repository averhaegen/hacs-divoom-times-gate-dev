# Divoom Times Gate — Copilot Instructions

A Home Assistant (HACS) custom integration for the Divoom Times Gate (5 ×
128×128 screen desk clock). Pure Python, `custom_components/divoom_times_gate/`.

## Build, test and lint

There is a test suite (`tests/`, pytest + `pytest-homeassistant-custom-component`),
strict mypy config in `pyproject.toml`, and a CI workflow running hassfest, HACS
validation, ruff, mypy and pytest on Python 3.14. No virtualenv is checked in;
run the tools through `uvx`:

- `uvx ruff check .`
- `uvx --with homeassistant --with pytest-homeassistant-custom-component pytest -q`
- `uvx --with homeassistant --with pillow mypy custom_components/divoom_times_gate`

Do not lower `python_version` below 3.14 in `pyproject.toml`: mypy aborts while
parsing `homeassistant/config_entries.py` on 3.13. `vendor_pixoo/` is excluded
from mypy.

Also validate by:
- Reading against Home Assistant's own dev conventions (this follows core
  integration patterns: `ConfigEntry`, `DataUpdateCoordinator`, platforms).
- Cross-checking device behavior against `docs/API.md` (the reverse-engineered
  local HTTP API reference) — it marks each fact ✅ verified-on-device, 📄
  documented-only, or ❓ open question. Don't contradict a ✅ fact without new
  evidence.
- There's no way to hit a real device in CI; changes touching `device.py` /
  `coordinator.py` push logic should be reasoned through carefully and cross-
  referenced with `docs/API.md`.

## Architecture

- **`device.py`** — `TimesGate`: thin async HTTP client for the local
  `POST http://<ip>/post` API. Every command needs `LocalToken` injected;
  images must be base64 **JPEG** (not raw RGB); `PicID` must be monotonically
  increasing (reset once at startup, then incremented). Hardware `402` uses a
  different port/endpoint (`:9000/divoom_api`) than the default `400`.
- **`coordinator.py`** — `TimesGateCoordinator` (DataUpdateCoordinator): the
  per-tick engine. Each refresh, for each of the 5 screens, decides whether to
  push HA-rendered content or leave a native face alone — see "Display modes"
  below. Also owns IP self-healing (re-discovers the device via cloud LAN
  discovery if it stopped responding, matching on MAC/DeviceId).
- **`screens.py`** + **`canvas.py`** — render one screen from a Pixoo-compatible
  "page" config (`page_type: components | clock | off`, etc.) into a PIL image.
  Pages are designed to be portable from `gickowtf/pixoo-homeassistant`
  (Pixoo 64×64 configs drop in and get nearest-neighbour scaled to the Times
  Gate's native 128×128).
- **`cards.py`** — higher-level "card" page type (`page_type: card`): turns a
  handful of sensors into a prebuilt themed layout. Uses a hybrid rendering
  pattern — HA renders/serves a static background GIF (icons, labels, frames)
  once, while live values are pushed as **type-23 overlay items** that the
  device itself polls, so value ticks never re-send the panel image.
- **`dispdata.py`** — the HTTP view backing type-23 polling (`Draw/SendHttpItemList`
  type 23): the device polls this endpoint itself for one entity's current
  state. Registered **once globally** (not per config entry) since aiohttp
  allows only one route per URL pattern — valid secrets for all entries live in
  `hass.data[DOMAIN]["dispdata_secrets"]` (see `docs/DISPDATA.md`).
- **`vendor_pixoo/`** — vendored font/color rendering code adapted from
  `gickowtf/pixoo-homeassistant` (MIT) so bitmap fonts (`pico_8`, `gicko`,
  `five_pix`, `eleven_pix`, `clock`, `pix24`) render pixel-identically to a
  Pixoo. Don't hand-edit unless syncing upstream changes.
- **`discovery.py`** — cloud LAN discovery + reading a device's Independent
  Display presets (`Get5LcdInfoV2`); used both at setup and for IP self-healing.
- **`entity.py`** — shared `TimesGateEntity` base (device info block, MAC
  connections, `has_entity_name`); all platform entities (`light.py`,
  `button.py`, `select.py`, `switch.py`, `image.py`) subclass it.

## Domain model — read `DESIGN.md` before touching display-mode logic

Terminology is locked to match the Divoom app verbatim (see `DESIGN.md`
"Terminology"): **Overall Display**, **Independent Display**, **Control1–5**,
**Face**, **HA Dashboard**, **Off**. Don't invent new names for these concepts.

Key rule: HA's custom content is an *overlay* pushed via JPEG that overrides
native faces. Whenever a native face/Independent-Display preset is selected
(device-level "Display source" select ≠ `HA Dashboard`, or a per-screen select
≠ `Custom`), **the coordinator must stop pushing to that screen/device** or it
will clobber the native face on the next tick. This push-suppression logic is
the crux of `coordinator.py` — read `DESIGN.md`'s "Coordinator behaviour"
section before changing it.

Never hard-code a specific unit's DeviceId, LocalToken, or independence-group
ids — these are always read live from the device/cloud per `DESIGN.md`
"Confirmed device facts".

## Conventions

- Config/const keys live in `const.py` (`CONF_*`, `DEFAULT_*`, mode-string
  constants like `DISPLAY_HA_DASHBOARD`, `SCREEN_MODE_CUSTOM`). Add new
  config/option keys there, not as inline string literals.
- Page/component schema (page_type, component types, color formats) must stay
  compatible with `gickowtf/pixoo-homeassistant` — check `docs/CARDS.md` /
  README "Configuring screens" section before changing page schema shape.
- Colors accept `[r,g,b]`, `#RRGGBB`, CSS name, or a Jinja2 template — handled
  centrally in `vendor_pixoo/_colors.render_color`; reuse it rather than
  re-implementing color parsing.
- Progress toward the HA Integration Quality Scale (target: Platinum) is
  tracked in `quality_scale.yaml` — update the relevant rule's status when a
  change satisfies (or breaks) one.
- `BACKLOG.md` tracks planned work and open decisions; check it (and update it)
  when picking up or finishing a feature.
- Docs live in `docs/` (`API.md`, `CARDS.md`, `DISPDATA.md`, `FONTS.md`,
  `FONTS_CATALOG.md`, `RGB_LIGHTS.md`, `SPEC_CARD_GALLERY.md`, `FACES_*.md`).
  Update the relevant doc alongside behavior changes — these are the only
  record of reverse-engineered device behavior.

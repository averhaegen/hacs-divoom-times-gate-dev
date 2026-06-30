# Backlog

Tracked enhancements, not yet implemented. The integration is functional today
(5 configurable screens, brightness/on-off light, refresh + buzzer buttons,
options-flow YAML editor, diagnostics).

## Feature ports from pixoo-homeassistant

- [x] **Per-screen page rotation** — each screen is a single page or a list of
  pages that rotate by `duration`; `enabled` skips a page. Pixoo-config drop-in.
- [x] **`show_message` service** — flash a text page on a screen for N seconds,
  then revert.
- [ ] **`play_buzzer` service** — buzzer with configurable cycle/total times
  (we have a buzzer button; a parameterised service is still TODO).
- [ ] **Prebuilt layout page types** — ship `progress_bar` / `solar` / `fuel`
  ready-made pages for quick polished screens without hand-building components.
- [ ] **`current_page` sensor** — exposes the active page index per screen.

## Display modes & faces (built)

- [x] **Display source select** — HA Dashboard / Overall Display:\<face\> /
  Independent Display:Control1–5 / Off. HA backs off pushing for native modes.
- [x] **Per-screen selects** — Custom / Off / Face:\<name\> in Dashboard mode.
- [x] **Whole-device faces** (`Set5LcdWholeClockId`) and **native presets**
  (`Set5LcdChannelType`, read via `Get5LcdInfoV2`).
- [x] **`set_clock_face` service** — any native face on a screen.
- [x] **Faces favorites** in options (`overall` / `per_screen`), small defaults.

## Device controls (Phase B)

- [x] **Edge-RGB light entities** — `Channel/SetRGBInfo` exposed as two RGB
  lights (Edge RGB, Backlight) with color + brightness. (Effects/ColorCycle not
  yet exposed.)
- [ ] **Rotation / mirror controls** — select/switch entities.

## Efficiency

- [ ] **Two-layer rendering / native self-updating overlays** — static background
  via `Draw/SendHttpGif` + live values via `Draw/SendHttpItemList`. The big prize
  is **type 23 ("net text")**: the device polls a URL every `update_time` secs and
  renders `{"DispData": "..."}` itself — so the integration registers a small HTTP
  view returning a templated value, and the device self-updates with **zero push**
  (smooth native text, near-zero traffic, survives HA hiccups).
  - **Tested on device:** `SendHttpItemList` IS accepted (`error_code 0`) — unlike
    `SendHttpText` which returns "illegal json". BUT a background+itemlist push to
    one screen while the device was in Overall/whole-face mode left the screen
    **stuck on "Loading"**. Recovery: `Draw/ClearHttpText {LcdId, TextId:-1}` +
    `Draw/ResetHttpGifId` + restore a mode.
  - **Open questions before building:** does it need the screen in independent/
    custom mode first (mode prerequisite)? Is the "Loading" the type-23 net-text
    hanging on the URL, or a stuck panel? Test type 22 alone in a clean per-screen
    state, then type 23 against a known-good local URL. Item fields: TextId(<40),
    type, x, y, dir, font(0-7), TextWidth, Textheight, TextString, speed, color
    (#RRGGBB), align(1/2/3), update_time; TimeGate adds LcdIndex, NewFlag.
  - Needs an HA-served endpoint returning `{"DispData": ...}` + device→HA
    reachability + a path secret for light auth.

## Quality scale → Platinum (parked)

- [ ] **CI** — GitHub Actions: hassfest, HACS validation, ruff, mypy --strict.
- [ ] **Bronze** — brands (icon/logo PR to home-assistant/brands), removal docs,
  config-flow test coverage.
- [ ] **Silver** — reauthentication flow (LocalToken can change → catch
  `"DeviceToken is err"`), log-when-unavailable, test coverage.
- [~] **Gold** — discovery **done** (cloud LAN lookup picker in the config
  flow, MAC as unique id); still: reconfiguration flow, repair issues, entity
  translations/categories/device-classes, extensive docs.
- [ ] **Platinum** — strict typing across the codebase, enforced by mypy in CI.

## Notes / dead ends

- **No diagnostic sensors planned.** Device internal temperature is NOT available
  over the local HTTP API (`Device/GetDeviceTemp` → "Request data illegal json";
  it's a Bluetooth-only command). `Device/GetWeatherInfo` works but returns
  cloud weather for the configured location (CurTemp/Pressure/Humidity/WindSpeed)
  — redundant with users' own weather sensors, so intentionally not exposed.
  `GetAllConf` is settings-only (exposed as controls, not sensors).

## i18n

- [ ] Translations (de, pt, …) once the strings stabilise.

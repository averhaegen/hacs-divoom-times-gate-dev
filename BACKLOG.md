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
- [x] **PV / solar layout** — works as a `components` page; pixoo icon assets
  vendored under `img/` with an `image_asset:` shorthand. (progress_bar / fuel
  not shipped as prebuilt types — buildable from components.)
- [x] **`gif` page type** — `Device/PlayGif` (per-screen, net GIF URLs).
- [x] **`visualizer` page type** — `Channel/SetEqPosition` (per-screen).
- [ ] **`channel` page type** — n/a per-screen on Times Gate (channels derive
  from the assigned face); whole-device channels via the Display source select.
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

- [x] **RGB light entities** — `Channel/SetRGBInfo` as two independent lights
  (Surround lights, Back lights) with colour + brightness + **effects**
  (Solid/Rainbow/colour animations/party). Colour only applies on SelectEffect
  3/4/6/7/9; ColorCycle = Rainbow; OnOff 1=on/0=off. Possible future: a
  `KeyOnOff` switch for the button light, per-screen back-light colours, friendly
  effect names from the app.
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

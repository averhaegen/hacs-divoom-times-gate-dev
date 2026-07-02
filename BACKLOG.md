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

## API-driven work (from `docs/API.md`)

- [x] **Split face catalogs into two documents.** `scripts/get_face_ids.py` now
  writes `docs/FACES_OVERALL.md` (Overall Display / whole dial, 27) and
  `docs/FACES_INDEPENDENT.md` (Independent Display / per-screen, 537) from their
  two disjoint cloud sources; combined `FACES.md` removed.
- [x] **`SendHttpItemList` — confirmed WORKING on Times Gate.** Requires `LcdIndex`
  (target screen) + `NewFlag: 1` + `BackgroudGif` (gif URL as background). Without
  these the device shows loading and reverts. All types confirmed: type 6 (hh:mm:ss),
  type 14 (weekday), type 22 (static text), type 23 (URL-poll `DispData`) ✅.
- [x] **DispData HTTP view.** `custom_components/divoom_times_gate/dispdata.py`
  serves `{"DispData": "<state>"}` for any `entity_id`, no-auth, gated by a
  per-config-entry secret in the URL path. Registered once globally (shared
  aiohttp route across entries) in `__init__.py`; secret persisted in
  `entry.data[CONF_DISPDATA_SECRET]`. See `docs/DISPDATA.md`.
- [x] **`dispdata_text` page type — up to 4 sensors per screen.**
  `coordinator._apply_dispdata_text` + `device.send_item_list`. `sensors:` list
  (or a single-sensor `entity_id` shorthand) builds one type-23 item per sensor,
  auto-stacked at y `8/40/70/100`. Each poll URL carries an optional `?label=`
  query param that `dispdata.py`'s view uses to prefix the value
  (`"<name>: <state><unit>"`); unit_of_measurement is appended automatically.
  Sends one `Draw/SendHttpItemList` (`NewFlag: 1`) setup call per screen when
  the page's config changes (signature-based, like other native page types),
  then never pushes again — the device self-polls each item independently.
  See `docs/DISPDATA.md` §3 for the YAML and field defaults. Confirmed on a
  real device (temp + solar sensors).
- [x] **Fixed: single-page screens were invalidated every `duration` seconds
  for no reason.** `coordinator._build_custom` (formerly `_render_custom`) was
  calling `self.invalidate(screen)` whenever elapsed time crossed the page
  duration, even with only one page (nothing to rotate to) — this forced a
  full repaint/resend every ~15s, visible as a periodic reload on
  `dispdata_text` pages (which resend their whole `NewFlag: 1` setup on every
  invalidate). Now only invalidates when there's more than one page to rotate
  between.
- [x] **Batch all changed screens into one `Draw/CommandList` call per tick.**
  Per [[feedback-multi-screen-calls]]. `device.py` gained `build_*` variants
  (`build_jpeg`, `build_clock_face`, `build_play_gif`, `build_visualizer`,
  `build_item_list`) that construct a sub-command payload without sending, plus
  `send_command_list()` wrapping `Draw/CommandList`. `coordinator._async_update_data`
  now builds every screen's pending command first, then sends them all in a
  single POST (instead of one POST per screen) — same for `_reassert_faces`.
  On-demand single-screen actions (`async_set_screen`, native face pushes)
  still send immediately, since batching only pays off when multiple screens
  change in the same update.
- [ ] **Investigate: rotating `dispdata_text` with `gif`/`visualizer` on the
  same screen leaves the panel stuck on "Loading".** Confirmed on device —
  disabling `gif`/`visualizer` pages on a screen that also has `dispdata_text`
  resolved it immediately. Both native modes likely disrupt the
  `Draw/SendHttpItemList` item-list state in a way that isn't restored when
  rotating back. Workaround documented in `docs/DISPDATA.md` §6 (don't mix
  them in one rotation); root cause not yet identified — possibly needs a
  full `NewFlag: 1` re-setup specifically when returning to `dispdata_text`
  from a `gif`/`visualizer` page (currently `invalidate()` only fires when
  page duration elapses, which should already cover this — needs a repro to
  confirm whether that path is actually taken).
- [x] **Fixed: `dispdata_text` `name` containing a space broke the device's
  own polling.** The Times Gate's outbound poll GET doesn't reliably handle a
  percent-encoded space (`%20`) in the query string. `coordinator._build_dispdata_text`
  now swaps spaces for underscores before building the poll URL;
  `dispdata.py`'s view swaps them back for display. See `docs/DISPDATA.md` §3.
- [x] **`dispdata_text` `items:` — full manual per-item layout.**
  `coordinator._build_dispdata_items`, up to 8 items (`_DISPDATA_MAX_ITEMS`),
  each independently a static `kind: label` (type 22) or polling `kind: value`
  (type 23) with its own x/y/font/color/align — mirrors raw
  `Draw/SendHttpItemList` item construction instead of the auto-stacked
  `sensors:` "<name>: <value>" combined-row shorthand. Lets a label and its
  value use different colours/fonts/positions (e.g. label above, value below,
  or side by side). Takes priority over `sensors:`/`entity_id` when both are
  present. See `docs/DISPDATA.md` §3b. **Not yet tested on a real device.**
- [x] **`dispdata_text` `items:` — native device kinds (clock/date/weather).**
  `coordinator._NATIVE_KIND_TYPES` maps 21 `kind` names (`time`, `time_short`,
  `ampm`, `weekday_3`, `temperature`, `weather`, …) to the device's built-in
  SendHttpItemList types (1-21, `docs/API.md` §4.10) — zero polling, zero HA
  involvement after setup, the panel renders these natively. A 12h clock is
  `time_short` + `ampm` as two adjacent items. Documented in
  `docs/DISPDATA.md` §3b. **Not yet tested on a real device.**
- [x] **Documented when to use `components` vs. `dispdata_text`.**
  `docs/DISPDATA.md` §3c compares the two rendering systems (HA-side Pillow
  JPEG push vs. device-native/self-polling) so it's clear which to pick per
  page — key trade-off: `components` supports live conditional colour,
  `dispdata_text` doesn't (colour is fixed at setup time).

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

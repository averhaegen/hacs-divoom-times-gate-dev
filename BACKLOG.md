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
    **stuck on "Loading"**. Root cause found and fixed in 0.3.0 (issue #9): the
    item list leaves a device-side self-polling overlay that `Device/PlayGif`
    and `Channel/SetEqPosition` never tear down. The coordinator now sends
    `Draw/ClearHttpText {LcdId, TextId: -1}` ahead of the new command whenever a
    screen leaves a `dispdata_text` page. See docs/DISPDATA.md §6.
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

- [x] **CI** — GitHub Actions: hassfest, HACS validation, ruff, pytest.
- [x] **CI typing** — `mypy --strict` runs in the workflow.
- [ ] **Bronze** — brands (icon/logo PR to home-assistant/brands), removal docs,
  config-flow test coverage.
- [ ] **Final repo name + brands submission** — decide the definitive repo
  (this is the `-dev` repo) and whether the `divoom_times_gate` domain stays;
  then finalize the draft icon in `brands/` (validate design with Alexander
  first) and submit the one-shot PR to home-assistant/brands. Releases are
  live since v0.2.0, so HACS shows proper version numbers already.
- [ ] **Silver** — reauthentication flow (LocalToken can change → catch
  `"DeviceToken is err"`), log-when-unavailable, test coverage.
- [~] **Gold** — discovery **done** (cloud LAN lookup picker in the config
  flow, MAC as unique id); still: reconfiguration flow, repair issues, entity
  translations/categories/device-classes, extensive docs.
- [x] **Reconfigure flow** (`async_step_reconfigure`) — "Reconfigure" on the
  entry changes IP/token/interval in place (`async_update_reload_and_abort`),
  with a MAC-mismatch guard against pointing the entry at a different device.
  Re-adding the device also updates IP/token in place via
  `_abort_if_unique_id_configured(updates=...)`. Done 2026-07-04.
- [x] **IP self-healing** — after 3 consecutive transport failures (rate-
  limited to one attempt per 5 min) the coordinator re-runs cloud discovery,
  matches on MAC (DeviceId fallback), updates the entry's IP and reloads.
  Also runs once at setup when the stored IP doesn't ping (HA restarted
  after the lease changed). Done 2026-07-04. Still open: `dhcp` manifest
  discovery (match on MAC OUI) as the zero-touch variant.
- [ ] **Platinum** — strict typing across the codebase, enforced by mypy in CI.

## Firmware / device introspection (exploratory, 2026-07-08)

- [ ] **Firmware version + update trigger — found the endpoints, blocked on
  account auth.** Captured the real Divoom app's traffic via mitmproxy
  (TLS-intercept on iPhone) — guessing local/cloud command names got nowhere,
  but the real app calls two cloud endpoints, now documented in
  `docs/API.md` §6.2/§6.3: `Device/GetListV2` returns each device's current
  `DeviceVersion` (confirmed `4000170` on this Times Gate); `Device/GetUpdateInfo`
  returns `CanUpdate` + a changelog blurb (not a version number). **Both
  require a Divoom account session `Token`/`UserId`** — a completely
  different auth mechanism from the device's own `LocalToken` that our
  integration uses everywhere else. Building this feature means adding a
  Divoom account login flow (storing account credentials/session token in
  HA), a materially bigger scope than anything else in the integration so
  far. No update-*trigger* endpoint has been found yet (only update-*check*).
  Decision (2026-07-08): worth documenting, not worth building yet — revisit
  if/when account-auth becomes worthwhile for other reasons too.
- [ ] **`UserLogin` single-session conflict — confirmed live, is a hard
  blocker as-is.** Only one `Token` is valid per Divoom account at a time —
  logging in externally (e.g. from HA) immediately invalidates whatever
  token the real phone app is holding, and vice versa. Confirmed live: a
  test login from this dev environment instantly kicked the user's phone
  app with a visible **"Information mismatch, please login again"** error.
  Force-quit/reopen of the phone app does *not* trigger a fresh `UserLogin`
  (it silently reuses its cached token), so this conflict only fires on an
  actual login event — but any HA-side re-auth (e.g. after its own token
  goes stale) would cause it again. This makes a naive "HA logs into your
  personal Divoom account" design actively hostile to normal phone app use,
  not just a security tradeoff — **treat this as a hard blocker**, not a
  risk to mitigate, unless solved via account separation (see next item).
- [ ] **Possible fix: Divoom's "Add friend's device" / share-code feature
  (buddy system).** The app has a device-level "share code" ("scan this
  share code to connect to your device and send photos or pixel
  animations — friends only need to do this once") under device settings,
  backed by APK-confirmed commands `ApplyBuddy`/`ConfirmBuddy`/`RefuseBuddy`/
  `RemoveBuddy`/`GetBuddyInfo` (found via `Grayda/pixoo_api`'s decompiled
  command list — a separate mechanism from `Device/ShareDevice`, also in
  that list but not yet located in the app's UI). If a second, dedicated
  "Home Assistant" Divoom account could be buddy-linked to the device this
  way, HA could authenticate as *that* account — a fully separate token
  pool from the user's personal phone session, solving the conflict above
  entirely, with a smaller blast radius (throwaway account) if ever leaked.
  **Unverified**: the share-code wording ("send photos or pixel
  animations") suggests this may only grant one-directional content-push
  access, not the read access `Device/GetListV2`/`Device/GetUpdateInfo`
  would need for a buddy-linked account's own `Token`. Needs a second
  Divoom account to actually test. Parked 2026-07-08 pending that test —
  do this before any further cloud-auth design work, since it changes the
  entire feasibility picture if it works.
- [ ] **Research pass done — no existing OSS project polls firmware
  endpoints; best practice found is a 23h token cache + negative-cache
  cooldown, but none solve the session-conflict problem.** Surveyed
  `ztomer/divoom_lib`, `konst3658-crypto/divoom-times-frame-research`,
  `tidyhf/Pixoo64-Advanced-Tools`, `fabkury/makapix`, `redphx/apixoo`,
  `Grayda/pixoo_api` (both repos spot-checked and confirmed to exist).
  None implement `Device/GetListV2`/`Device/GetUpdateInfo` at all — no
  prior art for polling behavior/frequency. `ztomer/divoom_lib` is the
  most security-mature (email+password in `~/.config/divoom-control/
  config.ini` at `0o600`, session cached to `auth_token.json` at `0o600`
  with a 23h TTL, a 120s negative-auth-fail cooldown to avoid hammering
  Divoom's servers, log-redaction helper for tokens, and an alternate
  **guest login** path (`User/NewGuest`, HMAC-MD5(UTC) signed with a
  hardcoded APK key, no account needed at all) — but nobody has verified
  whether a guest token can read `Device/GetListV2`/`GetUpdateInfo` for a
  specific device, so it's unclear if guest login sidesteps the whole
  credentials question too. No project handles the single-session-token
  conflict (`ReturnCode: 11`) automatically. No Divoom ToS statement
  found anywhere prohibiting third-party/unofficial API use, but also none
  confirming it's fine — `docs/legal/` now has the real privacy
  policy/user agreement (captured 2026-07-08) for a proper review before
  building anything here.
- [x] **Guest login (`User/NewGuest`) tested live — dead end, endpoint no
  longer exists on Divoom's current backend.** Replayed
  `ztomer/divoom_lib`'s documented HMAC-MD5(UTC) algorithm exactly
  (`HMAC_KEY = b"DivoomBluetoothDevice<>?"` from their APK analysis)
  against `appin.divoom-gz.com`, both with and without a valid session
  token attached, and using both server-reported and local UTC. Every
  attempt returned `{"ReturnCode":10,"ReturnMessage":"Command is not
  match","Name":"IndexDefaultMethod"}` — a **routing 404**, not an auth
  rejection (contrast with real endpoints like `Device/GetUpdateInfo`
  called with no token, which correctly resolve and return
  `{"ReturnCode":11,"ReturnMessage":"Token is not match"}`). Also
  confirmed as a side-effect that `APP/GetServerUTC` itself now requires
  a valid `Token`/`UserId` (`ReturnCode:11` without one, `ReturnCode:0`
  with a real token) — contradicting `ztomer/divoom_lib`'s assumption
  that it's a public unauthenticated endpoint. Conclusion: guest login
  is either removed or moved to a path/host we haven't found; not worth
  further guessing without new evidence (e.g. a newer decompiled APK).
  Also separately confirmed (2026-07-08) that a real phone session token,
  extracted live from a mitmproxy capture of the user's own login, reads
  `Device/GetListV2` (`DeviceVersion: 4000170`) and `Device/GetUpdateInfo`
  fine with **no session-conflict side effect** — only a fresh
  `UserLogin` call invalidates the other party's token, confirming
  read-only polling calls are safe once a token is already in hand; the
  problem is purely how a non-phone client (HA) would obtain one without
  either storing the user's real password or forcing a `UserLogin` that
  kicks the phone.
- [x] **Refresh-token angle tested live — dead end, confirmed structurally
  impossible with this API.** Probed 14 plausible refresh/re-auth endpoint
  names (`User/RefreshToken`, `Token/Refresh`, `User/RenewToken`,
  `User/KeepAlive`, `User/Heartbeat`, `APP/RefreshToken`, `User/CheckToken`,
  `User/CheckLogin`, `User/ValidateToken`, `User/AutoLogin`,
  `User/TokenLogin`, `User/GetToken`, `User/ReLogin`, `User/Refresh`)
  against `appin.divoom-gz.com` with a valid live token attached — every
  single one returned the same routing-404
  (`{"ReturnCode":10,"ReturnMessage":"Command is not
  match","Name":"IndexDefaultMethod"}`), meaning none of these routes
  exist server-side. More importantly, re-examined what the phone actually
  does on relaunch (already established earlier: force-quit/reopen fires
  **zero** network calls related to auth) — this proves there is no
  server-side refresh *concept* to find. The phone's "auto-login" is
  entirely client-side: it just caches the one `Token`/`UserId` pair
  locally after the last real `UserLogin` and re-sends that same literal
  value on every subsequent API call, forever, with no renewal round-trip.
  Combined with `Grayda/pixoo_api`'s note that `Token` looks like a bare
  Unix timestamp, this points to the server implementing a flat
  "does this Token match the last one issued for this UserId?" check —
  i.e. **one account = one valid Token slot, last `UserLogin` wins,
  no independent per-client sessions, no OAuth-style access/refresh
  split.** There is no way for two clients (a phone + HA) to each hold
  their own independently-valid token for the same account with this API
  as it currently stands. **Overall conclusion for this whole investigation
  thread (guest login + refresh token, both closed 2026-07-08):** the
  cloud firmware endpoints are real and useful in isolation, but cloud
  auth cannot be added to this integration today without either (a) the
  user accepting that HA and the phone app can never both be freshly
  logged in without kicking the other, or (b) the buddy/share-code lead
  above (still unverified, needs a second account to test) turning out to
  grant a buddy account read access to `Device/GetListV2`/`GetUpdateInfo`
  for someone else's device. Until one of those is resolved, cloud-auth
  firmware features should stay out of scope for the integration.
- [x] **"Replicate 5 custom text screens" investigated — not viable as a
  content-read.** `Channel/Get5LcdInfoV2` (cloud) does return live per-screen
  `ClockId`s for each "Control" preset (confirmed screens 0/1/3/4 populated,
  matching what's set in the app), but each screen only resolves to a
  `ClockImagePixelId` — a CDN path (`f.divoom-gz.com/...`) to a pre-rendered
  face design in Divoom's own proprietary compressed pixel/animation format,
  not the literal typed text. There's no way to recover the original text
  string via the API. Building "custom text screens" in HA isn't blocked by
  this though — it's just our own `card`/`components` page types doing the
  same job independently (already supported).

## Card gallery (v2) — see docs/SPEC_CARD_GALLERY.md

Agreed direction 2026-07-03 (three tiers: pixoo-compat frozen, native card
gallery, experimental native-face authoring). In priority order:

- [x] **Hybrid card MVP — `sensor_grid` shipped 2026-07-05** (docs/CARDS.md):
  `page_type: card`, 2-8 slots with auto-densest layout, bundled MDI icons
  in the HA-rendered background, cardbg HTTP view (digest URL as
  cache-buster), type-23 value overlays, per-slot color/color_template.
  Device-verified 2026-07-05 (background GIF fetch, icons, type-23 polling).
  Since extended with: named themes + `background`/`primary`/`secondary`
  (palette index-0 transparency worked around via a reserved sentinel), MDI icons with
  dynamic battery levels, per-slot `value_template`, `page_type: image` +
  `show_image` service. Still open from the original MVP:
  - Animated background (Solar card with moving sun rays) — needs an
    animated GIF variant of the background renderer.
  - Bar-string/formatter option in `dispdata.py` (e.g. `█████░░░░ 47%`);
    test block-glyph coverage in device fonts first, fallback `|||` / `===`.
  - Label scrolling does not work on the test unit (type-22 items don't
    scroll regardless of dir/speed/font) — investigate `SendHttpText` or
    accept truncation.
- [ ] **Card framework** — card manifest (slots: entity count +
  device_classes, options), registry, `page_type: card` in the coordinator.
- [ ] **Gallery cards** — battery, range_bar, grid_power, energy_cost,
  climate, weather, gauge, text_value (variants = same card, more slots).
- [ ] **Split value/unit text boxes** — option to render a slot's value and
  unit as two independent text components instead of one concatenated
  string (e.g. `72` + `°F`, `12` + `km/h`). Motivation: several bitmap fonts
  ship dedicated glyphs for `°C`/`°F`/arrows/units that look better isolated
  than mixed into a variable-width value string, and letting each box
  align independently (value right-aligned in its box, unit left-aligned
  in its own, positioned right after) keeps the layout tidy regardless of
  how many digits the value has. Needs: a `value`/`unit` pair (or
  `unit_position: right|stacked`) in the component/card slot schema,
  independent `font`/`color` per box (so the unit can use a symbol font
  while the value uses a numeric one), and fallback to today's single
  concatenated string when `unit` isn't set (no breaking change).
- [ ] **Multi-frame animation renderer** — `Draw/SendHttpGif` with shared
  `PicID` / incrementing `PicOffset` (≤ ~40 frames) as fallback for layouts
  overlays can't express (charts, sparklines).
- [x] **Tier 3 gate: probed 2026-07-04 — NEGATIVE on HW 400.** The watchface
  commands (`GetLocalClockInfo`, `GetScreenSnapshot`, `GetTimeDialFontV2`,
  `GetLocalFontList`) are unknown on port 80 `/post` — even with the Frame
  envelope + unpack-stub fields — and port 9000 is closed. Also rules out
  `GetScreenSnapshot` as a preview source for native faces on HW 400.
- [ ] **Tier 3 (reframed): Divoom-ecosystem faces via DataRule polling** —
  design a dial in Divoom's official `DivoomClockConfig.exe` designer that
  polls an HA endpoint (DataRule "Normal" JSON shape:
  `{"AppName", "DispData":[{"AppTitle","AppData"}]}`), like Divoom's own
  Spotify/YouTube cards. "Send device" works without review for personal
  use. First steps: HA view serving the Normal shape; hands-on designer
  test on the Times Gate (tool is Pixoo64-oriented, 0-63 coords). See
  SPEC_CARD_GALLERY.md Tier 3 and reference/DivoomClockConfig.
- [ ] **Device-local authoring re-probe on HW 402** — the second Times Gate
  hardware revision uses port 9000 `/divoom_api` (the Frame-family API where
  `Device/CreateLocalClock` is proven; `device.py` already routes 402
  there). Needs access to a HW 402 device.

## Energy screens (spec review 2026-08-24, see `.agents/notes/energy-spec-review.md`)

Shipped from the review's "simpler path that captures most of the value", plus
the solar/battery merge and the history card the review flagged but that were
built anyway:

- [x] **`units.quantize_fraction`** — one shared helper for the SoC bar, the
  price marker and the bipolar power bar, so a live value only repaints the
  artwork once it crosses a band.
- [x] **Cheapest and priciest hour on the price screen.** The clock time of the
  day's low and high price, baked under each figure. Highest value-per-hour item
  in the review.
- [x] **Solar goal bar and battery charge-level icon.** The goal bar reads
  toward today's Forecast.Solar target (`config_entry_solar_forecast`), and an
  MDI battery band icon carries the charge direction in place of the word.
- [x] **Merged `solar_battery` screen with a bipolar power bar.** Solar and
  battery share one screen; the bar's charging and discharging ends come from
  the sensor's own seven-day min/max, with `power_min`/`power_max` overrides.
  Font 184 has no minus glyph, so the power figure strips its sign and leans on
  colour and fill direction.
- [x] **24 hour history graph on the fifth screen.** 24 hourly buckets from
  local midnight on the same axis as the day-ahead price graph, stacked per
  source in the energy dashboard's palette and sign convention: solar, grid
  import and battery discharge up, grid export and battery charge down, with the
  derived house consumption as a light grey line over the top. Only the sources
  the home reports get a band or a legend entry.
- [x] **Hour axis and window options on the graph cards.** Both 24 hour graphs
  label every sixth hour and dot a grey rule at it, taking the gap between two
  bars and running on beside the label. The `graph` card takes `hours`,
  `window` (rolling or static) and the `hours_back`/`hours_forward` offsets, so
  a 48 hour price forecast can draw six hours of history and a day ahead.
- [x] **Compact house screen.** Import and export collapse onto one line, each
  behind an MDI arrow, and the gas and water footer moves here from the price
  graph, which goes back to full height.
- [x] **Two-step energy config flow.** The first step reports the entity or
  statistic behind each screen and the missing source for any blank one; the
  second offers a checkbox per fillable screen, and a cleared screen is written
  off in its own slot so the order never shifts.
- [x] **Today's totals read in kWh.** The recorder is asked for kilowatt hours
  whatever the meter reports, so a watt-hour meter no longer reads a thousand
  times too high. Gas and water keep the meter's own unit.
- [ ] **Dropped: capaciteitstarief half-circle gauge (spec §7).** The review
  cut it: at 128px a horizontal banded bar reads fill fraction as well as a 180°
  arc for a fraction of the code, and the audience is BE-only manual YAML.
- [ ] **Dropped: six-block power-flow card (spec §8).** The review cut it: six
  4-hour buckets flatten the solar midday peak and four overlaid filled series
  read as mud at 128px. The 24 hour history card above carries the honest
  version (two series, 24 buckets).

## Configuration UX (left over after the 2026-08 redesign)

- [ ] **A second layout cannot be created from the menu.** The layout entry is
  hidden until more than one layout exists, and "Save as copy" lives inside
  it, so the first extra layout can only come from the energy generator or
  from **Edit all layouts as YAML**. Either surface "Save as copy" one level
  up, or drop the hide rule.
- [ ] **No form for graph cards, gif, visualizer or image pages.** Those page
  types get the YAML editor and a sentence saying why. `page_forms.py` is the
  place to add them; each new form needs a matching entry in
  `unsupported_reason` or it will start silently dropping keys.
- [ ] **Generated screens that use `value_template` are YAML-only afterwards.**
  Weather, the calendar agenda and the energy panels read attributes, which
  the sensor form cannot express, so their screens fall back to the YAML
  editor. Either teach the form about templates or add a per-slot
  attribute picker.
- [ ] **Media player and statistics starters.** Deferred in the design: both
  need choices the registry cannot make on its own (which player, which
  statistic, over which period).
- [ ] **Per-screen faces are picked from the whole-device catalog.** The device
  reports one face list; whether every id in it renders on a single screen is
  unverified beyond hardware revision 400.
- [ ] **Face ids are still unverified on hardware other than 400.** A generated
  clock screen now resolves its face against Divoom's live catalog
  (`starters.async_clock_face`), which guarantees the id has not been retired
  and gives a fallback when it has. It guarantees nothing about rendering:
  `Channel/GetDialType` and `Channel/GetDialList` take no DeviceId, so every
  LCD device gets the identical catalog. Confirming a face looks right on a
  402 needs a 402.
- [ ] **`DEFAULT_SCREENS` still pins face 152 statically.** That path is the
  coordinator's fallback for an entry with no options at all, and it must not
  make a cloud call, so it cannot use the resolver. If Divoom ever retires 152,
  that one path shows a broken face until the user configures a screen.

## Notes / dead ends

- **No diagnostic sensors planned.** Device internal temperature is NOT available
  over the local HTTP API (`Device/GetDeviceTemp` → "Request data illegal json";
  it's a Bluetooth-only command). `Device/GetWeatherInfo` works but returns
  cloud weather for the configured location (CurTemp/Pressure/Humidity/WindSpeed)
  — redundant with users' own weather sensors, so intentionally not exposed.
  `GetAllConf` is settings-only (exposed as controls, not sensors).
- **`manifest.json` Pillow pin.** `requirements: ["Pillow>=10.1.0"]` is a floor
  only (no ceiling) so HA core's own exact pin (`Pillow==X.Y.Z` in
  `package_constraints.txt`) always wins. Keep this floor comfortably below
  whatever the oldest HA version we support ships, so a future bump never
  raises our minimum above HA's current pin (which would break dependency
  resolution for the whole HA install, not just this integration).

## i18n

- [ ] Translations (de, pt, …) once the strings stabilise.

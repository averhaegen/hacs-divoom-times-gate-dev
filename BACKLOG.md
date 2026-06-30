# Backlog

Tracked enhancements, not yet implemented. The integration is functional today
(5 configurable screens, brightness/on-off light, refresh + buzzer buttons,
options-flow YAML editor, diagnostics).

## Feature ports from pixoo-homeassistant

- [ ] **Per-screen page rotation** — let each of the 5 screens cycle through
  multiple pages with per-page `duration` and `enabled`. Config becomes a list
  of pages per screen. The standout feature; especially useful across 5 screens.
- [ ] **`show_message` service** — flash a temporary page on a chosen screen for
  N seconds, then revert to the configured content. Great for alerts.
- [ ] **`play_buzzer` service** — buzzer with configurable cycle/total times,
  callable from automations (complements the existing button).
- [ ] **Prebuilt layout page types** — ship `progress_bar` / `solar` / `fuel`
  ready-made pages for quick polished screens without hand-building components.
- [ ] **`current_page` sensor** — exposes the active page (only meaningful once
  rotation exists).

## Device controls (Phase B)

- [x] **Edge-RGB light entities** — `Channel/SetRGBInfo` exposed as two RGB
  lights (Edge RGB, Backlight) with color + brightness. (Effects/ColorCycle not
  yet exposed.)
- [ ] **Rotation / mirror controls** — select/switch entities.
- [ ] **Per-screen native faces** — `page_type: clock` exists; add a friendly
  picker (needs the cloud dial list / `Get5LcdInfoV2`).

## Efficiency

- [ ] **Two-layer rendering** — static background via `Draw/SendHttpGif` + live
  values via `Draw/SendHttpItemList` text overlays (cheaper refreshes, crisper
  text, free native time/weather). See API notes.

## Quality scale → Platinum (parked)

- [ ] **CI** — GitHub Actions: hassfest, HACS validation, ruff, mypy --strict.
- [ ] **Bronze** — brands (icon/logo PR to home-assistant/brands), removal docs,
  config-flow test coverage.
- [ ] **Silver** — reauthentication flow (LocalToken can change → catch
  `"DeviceToken is err"`), log-when-unavailable, test coverage.
- [ ] **Gold** — discovery, reconfiguration flow, repair issues, entity
  translations/categories/device-classes, extensive docs.
- [ ] **Platinum** — strict typing across the codebase, enforced by mypy in CI.

## i18n

- [ ] Translations (de, pt, …) once the strings stabilise.

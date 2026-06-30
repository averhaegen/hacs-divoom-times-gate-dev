# Design: screens, modes, and controls

Target architecture for managing the 5 screens. Agreed during design; not all
implemented yet (see BACKLOG.md for status).

## Mental model

The Times Gate = up to 5 independent "Pixoo-like" screens, plus a device-level
mode that can instead show one face spanning all 5 screens.

Three things can be on a screen:
1. **Custom** — HA-rendered content (templated components, with rotation).
2. **Native face** — a device dial (per-screen, or a whole-device spanning face).
3. **Off** — black.

HA's custom content is an *overlay* pushed via JPEG; it overrides native faces.
So whenever a native face is selected, **HA must stop pushing to that screen**
(or the whole device) or it will clobber the face on the next refresh tick.

## Config (per-screen, split)

Each screen is configured independently (target: one HA **config subentry** per
screen; interim: 5 fields in the options flow). Because the config is split,
each screen's config is simply its own list of pages that rotate — i.e. each
screen IS a Pixoo `pages_data`. No separate `playlist` / screen-object wrapper
needed. A single-page list = a static screen.

```yaml
# one screen's config (its own subentry)
pages:
  - page_type: components
    duration: 15            # seconds before rotating (only matters with >1 page)
    enabled: "{{ ... }}"    # skipped in rotation if false
    components: [...]
  - page_type: clock
    clock_id: 61
    duration: 8
```

Migration from Pixoo: paste a Pixoo `pages_data` into one screen → that screen
rotates exactly like the old Pixoo.

Page types are just `components`, `clock`, `off`. There is **no** `playlist`
type — rotation is implicit in a screen's multi-page config + `duration`, exactly
like Pixoo's `pages_data`. (Decided: the config split makes a playlist wrapper
redundant.)

## Control entities

- **Device-level Select — "Display source":**
  `HA Dashboard` (push custom to all 5) | `Whole face: <name>` (spanning face via
  `Set5LcdWholeClockId`) | `Independent: <preset>` (a native scene, see below) |
  `Off`. When not `HA Dashboard`, the coordinator **stops pushing** so native
  faces persist.

  **Independent Display presets:** the device stores up to 5 native scenes
  (the app's "Independent Displays", `Control1`..`Control5`), each a set of 5
  per-screen faces. Switching is `Channel/Set5LcdChannelType{ChannelType:1,
  LcdIndependence:<id>}`. So users build scenes in the app and switch them from
  HA. This unit's presets (example): Control1=840167, Control2=841103,
  Control3=841105, Control4=841107, Control5=841109. (`0` in a preset = an unset
  screen.) The integration reads these via cloud `Get5LcdInfoV2` to build the
  Select options.
- **Per-screen Select (independent mode):** `Custom` | `Off` | `<favorite faces>`.
  A face calls `SetClockSelectId` for that LCD (independence group); `Custom`
  hands the screen back to its rendered config; `Off` = black.
- Selects use RestoreEntity, so the chosen mode survives restarts (it IS the
  runtime override).
- Existing: Display light (brightness/on-off), Edge RGB + Backlight lights,
  Refresh + Buzzer buttons.

## Favorites (face IDs)

A `faces` list in options drives the Select option lists: `{name, clock_id}`
entries for whole-device spanning faces and per-screen faces. IDs come from the
Divoom app.

We ship a **small fixed default list** (editable in options), e.g.:

```yaml
whole_faces:                 # device-level "Display source" options
  - name: Neon
    clock_id: 1040
  - name: Clock face
    clock_id: 581
  - name: City Time
    clock_id: 697
per_screen_faces:            # per-screen Select options
  - name: ...
    clock_id: ...
```

These are just a starting point — the "best 5 default full-screen faces" are TBD
(to be curated later). Users add their own IDs (grabbed from the app) to extend.
Optional later: seed from the device's cloud read, but it only reflects app state.

### Docs requirement
The README must include a **"Updating the faces list"** section that:
- explains the integration ships only a **few defaults** on purpose,
- shows how to find a face's `clock_id` (from the Divoom app) and add it,
- distinguishes whole-device (spanning) faces from per-screen faces.

## Coordinator behaviour

Per tick (refresh interval):
- Device mode = whole-face or device off → push nothing (native face persists).
- Device mode = HA Dashboard / Independent → for each screen:
  - screen select = Custom → render current page (rotating by `duration`) and push.
  - screen select = face/off → set once on change; don't push each tick.

## Diagnostics (optional, disabled by default, cloud-polled)

- "Assigned face" per screen (from `Get5LcdInfoV2`) — soft hint; reflects app
  changes only, NOT HA's local changes. Label accordingly.
- "Current channel" (`Channel/GetIndex`) — best-effort; can't reliably catch a
  transient physical Mode-button press because HA re-asserts custom each tick.

## Services (dynamic control)

- `show_message` — flash a temporary page on a screen for N seconds, then revert.
- `set_clock_face(screen, clock_id)` — arbitrary face by id, for scripts.
- (`select.select_option` already covers picking modes/faces from scripts.)

## Confirmed device facts

- This unit: DeviceId 300405795, independence group 840167, Neon whole-face 1040.
- `Set5LcdWholeClockId` (local) and `SetClockSelectId` (local) both work.
- Cloud `Get5LcdInfoV2` mirrors **app** changes, not local-API changes.

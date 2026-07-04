# Spec: Card Gallery architecture (v2 direction)

Status: draft, agreed direction 2026-07-03. Complements DESIGN.md (screen/mode
model stays as-is); this spec covers *what gets rendered on a Custom screen*.

## Motivation

Today a Custom screen is composed from low-level Pixoo-style components
(text, templated values) inherited from pixoo-homeassistant. That works, but
users assemble everything by hand at 64×64-era granularity. The PoC repo
(johnpc/divoom-time-gate) showed the appealing end state: purpose-built
full-screen "cards" (solar, battery, climate, weather) — but hardcoded in
TypeScript. This spec turns that idea into a reusable, HA-configurable card
gallery, while keeping backward compatibility.

## Architecture: three rendering tiers

### Tier 1 — Pixoo compatibility mode (frozen)

- The existing `vendor_pixoo` component set (64×64 semantics, upscaled),
  kept working exactly as today for users migrating from pixoo-homeassistant.
- Maintenance policy: bugfix-only. No new features land here.
- Config: a screen's `mode: pixoo_compat` selects this renderer.

### Tier 2 — Native Times Gate cards (the core of v2)

A **card** is a self-contained 128×128 layout template bound to 1–3 HA
entities, rendered by us and pushed as JPEG (or animated GIF, see below).

- Canvas: 128×128, full RGB, JPEG-encoded (device requirement; never raw RGB).
- Each card = a Python class implementing `render(entities, now) -> Frame | list[Frame]`.
  Returning multiple frames produces an animation (see Animation).
- Cards declare a **manifest**: `card_type`, `slots` (how many entities, which
  device_classes/units they accept), `options` (colors, labels, icon choice).
- Config per screen: ordered list of cards + rotation interval (reuses the
  existing rotation machinery from DESIGN.md).

#### Initial gallery (v2.0)

| Card | Slots | Typical entities | Visual |
|---|---|---|---|
| `battery` | 1 (+1 optional: charging state) | EV/home battery SoC | Battery outline, fill level, % text, charge bolt |
| `range_bar` | 1 (+1 optional: unit/label) | Fuel/EV range | Horizontal progress bar with car glyph, km/mi text |
| `solar` | 1–2 | PV power now, daily yield | Sun icon, big W value, small kWh total |
| `grid_power` | 1–2 | Grid import/export | Pylon icon, signed value, direction arrow/color |
| `energy_cost` | 1–2 | Price now, cost today | € value, sparkline of today (needs history) |
| `climate` | 2–3 | Temp, humidity, setpoint | Thermometer, current/target |
| `weather` | 1 (weather entity) | Forecast | Condition icon, temp hi/lo |
| `gauge` | 1 | Any numeric sensor | Radial gauge, generic fallback card |
| `text_value` | 1 | Any sensor | Big value + name — simplest generic card |

Variants ("2/3 entity versions") are the same card with more slots filled;
the layout adapts (e.g. `solar` with only power shows it bigger).

Asset reuse: the icon set extracted from the PoC customizations
(`poc-customizations/icons/`) seeds the shared icon library (`docs/icons/`
pipeline already exists).

#### Animation (new capability, from eriksalo/DivoomTimesGate docs)

Multi-frame push via `Draw/SendHttpGif`: same `PicID` for all frames,
`PicNum` = frame count, `PicOffset` = index, `PicSpeed` = ms/frame.
Constraints: ≤ ~40 frames, 128×128 JPEG per frame, unique `PicID` per new
animation (device caches by ID), `Draw/ResetHttpGifId` when stuck.
Cards opt in by returning multiple frames; renderer handles batching into
the existing `Draw/CommandList` flow where possible.

#### Hybrid cards: animated GIF background + self-updating overlays

The preferred pattern for animated cards with live values, because it
eliminates the repaint flash on value changes entirely:

- **Background**: an animated GIF (sun with moving rays, pulsing charge
  animation) set as `background_gif` on `Draw/SendHttpItemList`. Sent
  once; the device downloads and loops it natively — HA pushes nothing
  per frame.
- **Live values**: type-23 overlay items that self-poll our existing
  dispdata HTTP endpoint every `update_time` seconds. A value change
  (40% → 60%) is just a new string at the next poll — no image resend,
  no loading flash. Max 8 items per screen.
- **Progress bars as text**: the poll endpoint returns a pre-formatted
  bar string (e.g. `█████░░░░ 47%`) instead of the bare value. Needs a
  small formatter/template extension in `dispdata.py`, plus a device
  test of block-glyph coverage in the native fonts (fallback: `|||`,
  `===`).

Implications:
- The GIF must be URL-reachable from the device: serve card backgrounds
  from HA itself via an HTTP view next to the dispdata one (assets
  pre-rendered per card variant, parameterized by colors/options).
- The device caches GIFs by URL — include a cache-busting query param
  (content hash) whenever a background actually changes.
- Anything animated *and* value-dependent (e.g. fill level drawn inside
  the animation) still requires a background resend; prefer value
  overlays on top of a value-independent animation.
- Full-JPEG/multi-frame rendering (above) stays as the fallback for
  layouts that text overlays can't express (charts, sparklines, icons
  per state).

### Tier 3 — Native Divoom faces (experimental track)

Goal: author a card once and install it as a *device-native* clock face
(survives without HA pushing), possibly shareable via Divoom's ecosystem.

The DivoomDevelop toolchain (visual editor v2 + mcp-divoom-lan) documents
this for the "Frame" family: `Device/CreateLocalClock` multipart upload,
`ItemList[]` with `disp` widget ids, integer font ids, `Channel/SetClockSelectId`
to activate. The Times Gate shares the firmware command-registry architecture
and already answers `Channel/SetClockSelectId`, but the clock-authoring
commands are **unverified on Times Gate**.

**Gate result (probed live 2026-07-04): NEGATIVE on HW 400, open question
on HW 402.** On HW 400 (port 80 `/post`), `Device/GetLocalClockInfo`,
`GetScreenSnapshot`, `GetTimeDialFontV2` and `GetLocalFontList` all return
"Request data illegal json" — including with the full Frame envelope and
response-unpack stub fields — and port 9000 is closed. The port-80 handler
answers in the old Pixoo style (`error_code`, not `ReturnCode`), so the
Frame API genuinely isn't there. However, the Times Gate has two hardware
revisions and **HW 402 uses port 9000 `/divoom_api`** (already routed that
way in `device.py`) — the Frame-family API where these commands are proven.
Tier 3 is dead for HW 400; re-probe if a HW 402 device becomes available.

## Migration & compatibility

- Existing configs keep working: current component-based screens map to
  `mode: pixoo_compat` on upgrade, no user action needed.
- New configs default to Tier 2 cards.
- Services: card selection/config exposed via options flow per screen;
  a `divoom_times_gate.show_card` service for automations (push a card
  on demand, e.g. "show charging card when car plugged in").

## Non-goals (for v2.0)

- No Lovelace card designer UI; configuration is options-flow + YAML.
- No user-defined custom card layouts yet (a `template_card` taking a
  picture-elements-like schema is a v2.x candidate).
- No dependency on Divoom cloud services.

## Open questions

1. History-based cards (`energy_cost` sparkline) need the recorder API —
   acceptable dependency, or make sparkline optional?
2. Animation cadence vs. device Wi-Fi stability: max concurrent animated
   screens (likely limit to 1–2 of 5)?
3. Icon format: keep PNG assets or move to drawn primitives for crispness
   at 128×128?

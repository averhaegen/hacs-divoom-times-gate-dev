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

#### `sensor_grid` — the generic multi-sensor card (refined 2026-07-04)

One generic card takes 2–8 sensor slots and **auto-picks the densest
fitting layout** by count: 2 = large halves, 3–4 = quadrant, 5–6 = two
columns, 7–8 = compact rows. More sensors → more compact. Hard ceiling is
8 (the device's SendHttpItemList item limit; one type-23 value overlay per
sensor).

- **HA icons on the card**: each slot renders its entity's MDI icon into
  the HA-rendered background — bundle the Material Design Icons TTF +
  name→codepoint map, draw with Pillow at any size/color. Fallback for
  entities without an explicit `icon`: a small device_class→mdi table
  (default icons are frontend-side in HA, not readable from the backend).
- **Division of labor**: background (icons, labels, frames, optional
  animation) is HA-rendered and sent once with a content-hash cache-buster;
  live values are type-23 overlays the device polls itself — flash-free
  value updates.
- **State-dependent icon colors** (e.g. battery icon red < 20%): the
  background re-renders and re-pushes only when a color threshold is
  crossed — rare, brief repaint accepted.
- **Value refresh**: type-23 device polling is the default for all cards;
  a per-card `render_mode: push` escape hatch stays available for cards
  whose value zone needs graphics (bars, sparklines) rather than text.

#### Configuration UX

Options-flow, two equivalent editors over the same config (approximating
the Lovelace "visual editor ⇄ YAML" toggle, which isn't available to
integration options):

1. **Form**: card-type dropdown + entity selectors per slot + option
   fields.
2. **"Edit as YAML"** menu step: the same card object in the raw
   ObjectSelector editor.

A custom Lovelace card with live preview is a possible later shell on top
of the same config schema (out of scope for v2.0).

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

### Tier 3 — Divoom-ecosystem faces (designer + DataRule polling)

Goal: design a face with Divoom's own tooling that **polls HA itself** for
its data (the same mechanism behind Divoom's built-in Spotify/YouTube/
weather cards), so it runs device-native with zero HA pushing and is usable
straight from the Divoom app. Optionally publish it to Divoom's community
gallery. The most involved route, but potentially the most user-friendly
for Divoom-app users.

Documented in `reference/DivoomClockConfig` (official Divoom repo):

- **Designer**: `DivoomClockConfig.exe` (Windows), login with the Divoom
  app account. Compose background + display elements + fonts. **"Send
  device"** pushes the dial directly to your own online device — private
  use needs no review. "Submit for review" → Divoom admin review (~1 week)
  → public in the dial community.
- **Data polling (DivoomDataRule.pdf)**: a dial element can fetch a URL and
  extract values from the JSON response. *Normal* mode expects
  `{"AppName":..., "DispData":[{"AppTitle":..., "AppData":...}, ...]}`;
  *Custom* mode uses rules like `"DispData,UserInfo,n:Level"` (with array
  aggregation `[List:x-y]`).
- **HA side**: a small HTTP view serving the Normal-mode shape from HA
  entities (trivial next to the existing dispdata view) makes any
  designer-built dial display HA data natively.

Caveats / to verify:
- The designer targets 0–63 coordinates (Pixoo64-oriented); whether Times
  Gate dials use the same pipeline/resolution needs a hands-on test.
- Windows-only tool; needs the device online in the Divoom cloud.
- A published dial has its poll URL baked in — fine for personal use;
  gallery distribution to *other* HA users likely can't parameterize their
  HA URL.

Side note (probed live 2026-07-04): the *device-local* Frame authoring API
(`Device/CreateLocalClock` etc., from the visual-editor-v2/mcp-divoom-lan
toolchain) does **not** exist on Times Gate HW 400 (port 80 answers in old
Pixoo style; port 9000 closed). HW 402 routes to port 9000 `/divoom_api`
and might support it — re-probe if such a device becomes available. That
negative result does not affect the cloud-designer route above.

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

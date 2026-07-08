# Card pages (`page_type: card`)

Gallery cards render a polished 128×128 layout from a few entities — see
SPEC_CARD_GALLERY.md for the architecture. Rendering is hybrid: HA draws the
**background** (MDI icons, labels, separators) and serves it to the device
once; the **values** are type-23 items the device polls itself every
`update_time` seconds. Value changes therefore never flash the panel; the
background only re-sends when its content changes (config edit, a
`color_template` crossing to a different colour).

## `sensor_grid`

1–8 sensors. `layout: auto` (default) picks by count; `layout: list` or
`layout: grid` forces a style:

| Layout | Shape |
|---|---|
| `list` (auto for 3–5) | Full-width rows: icon left, label on the top line, value below it. Optional native header (clock by default) top-right. |
| `grid` (2–4) | Cells: label on top, large centered icon, value centered underneath. |
| auto 1–2 | Two big rows (32px icon, label + value beside it). |
| auto/any 6–8 | Compact 2-column grid: icon + value only. |

The 8-slot ceiling is a readability choice, not a device limit.

### Page schema

```yaml
page_type: card
card: sensor_grid        # currently the only card type
theme: dark              # dark | light | navy | forest | sunset | terminal | cyberpunk | neon | sci_fi
# background: "#0B1E3B"  # override the theme's canvas colour
# primary: "#FFB300"     # override the theme's icon/value colour
# secondary: "#8C6200"   # override the theme's label colour
# foreground: "#FFB300"  # legacy alias for `primary` (pre-2026-07-08 configs)
layout: auto             # auto | list | grid
header: time_short       # list layout: native element top-right (hh:mm).
                         # Any dispdata native kind (time, weekday_3,
                         # temperature, ...) or "none" to disable.
update_time: 10          # poll interval (s), page default
font: 4                  # device font id for values (see docs/FONTS.md)
slots:
  - entity_id: sensor.solar_power
    name: Solar          # label; default: the entity's friendly name
    icon: mdi:solar-power  # default: entity icon, else device_class icon
    color: "#FFB300"     # icon + value colour (overrides theme's primary)
  - entity_id: sensor.home_battery_soc
    color_template: >-   # state-dependent colour (icon + value)
      {% set s = states('sensor.home_battery_soc') | int %}
      {% if s < 20 %}#FF3B30{% elif s < 50 %}#FF9500{% else %}#34C759{% endif %}
  - entity_id: sensor.grid_power
    value_template: >-   # transform the shown value (renders per poll)
      {{ (states('sensor.grid_power') | float * 1000) | round }} W
    update_time: 5       # per-slot poll override
    font: 2              # per-slot font override
```

**Colours & themes.** Pick a named `theme` (below) or set `background` /
`primary` / `secondary` directly (each overrides the theme individually).
`primary` is the default for icons and values; `secondary` is the default
label colour; a per-slot `color` or `color_template` still overrides
`primary` for that entity. `foreground` is still accepted as a legacy alias
for `primary`. Separators derive automatically from `background`/`primary`.

| Theme | Background | Primary (icon/value) | Secondary (label) |
|---|---|---|---|
| `dark` (default) | black | white | dim white |
| `light` | white | near-black | dimmer near-black |
| `navy` | deep blue | amber | dim amber |
| `forest` | dark green | green | dim green |
| `sunset` | dark plum | coral | dim coral |
| `terminal` | near-black | CRT green | dim CRT green |
| `cyberpunk` | black | cyan | hazard yellow |
| `neon` | black | magenta glow | circuit cyan |
| `sci_fi` | black | circuit cyan | bright cyan highlight |

The last three are sampled from the Divoom app's own Cyberpunk/Neon/Sci-Fi
dial themes for a matching look — those three genuinely use two accent
colours in the source app (value vs. label), unlike the first six.

`value_template` values are rendered fresh in HA on every device poll (via
the `dispdata_tpl` endpoint), so unit conversions, rounding and formatting
always reflect the current state. Battery-class entities without an explicit
icon get a dynamic fill-level icon (`mdi:battery-70` etc.), like HA's own UI.

**Scrolling labels** (`scroll_labels: true`, the default in list/rows
layouts): labels are sent as device text items (type 22) instead of being
baked into the background — the device scrolls them automatically when the
name is wider than the row, so long entity names stay fully readable.
Options: `label_font` (default 2), `label_color` (default: a dimmed
foreground), `label_speed` (scroll ms/step, default 60). Set
`scroll_labels: false` for static truncated labels in the background. Grid
cells keep baked centered labels. (Note: label scrolling depends on device
firmware support — not observed on all units yet.)

### Notes

- Icons come from the bundled Material Design Icons font (any `mdi:*` name);
  entities without an explicit icon fall back to a `device_class` mapping,
  then to `mdi:eye`.
- A `color_template` change re-renders and re-pushes the background (brief
  repaint) — use thresholds, not continuously-varying colours.
- Values are `<state><unit>` from the dispdata endpoint. HA must be
  reachable from the device over LAN (same requirement as dispdata_text).
- The screen-preview image entity shows the rendered background; live
  values exist only on the device.

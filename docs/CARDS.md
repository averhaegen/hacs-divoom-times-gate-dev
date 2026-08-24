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
card: sensor_grid        # see the other card types below
theme: dark              # dark | light | navy | forest | sunset | terminal | cyberpunk | neon | sci_fi
# background: "#0B1E3B"  # override the theme's canvas colour
# primary: "#FFB300"     # override the theme's icon/value colour
# secondary: "#8C6200"   # override the theme's label colour
# dividers: true          # false hides the separator lines between rows/cells
# divider_color: "#333333" # override the default blended divider colour
layout: auto             # auto | list | grid
header: time_short       # list layout: native element top-right (hh:mm).
                         # Any dispdata native kind (time, weekday_3,
                         # temperature, ...) or "none" to disable.
update_time: 10          # poll interval (s), page default
font: 4                  # device font id for values (see docs/FONTS.md).
                         # Energy panels and graphs default to 160 instead.
# Note: this is a numeric device font id (native Pixoo fonts, see
# docs/FONTS.md) — a different naming system from `components` pages,
# where `font:` is one of six bitmap font *names* (pico_8, gicko, ...).
# Card/dispdata_text pages always use numeric ids; components pages
# always use names. They are not interchangeable.
label_render: native      # native (device-scrolled text item, default) | static (baked into background, no scroll)
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
`primary` for that entity. Divider lines between rows/cells derive
automatically from `background`/`primary`, or set `divider_color` to
override, or `dividers: false` to hide them entirely.

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

**Label rendering** (`label_render: native`, the default in list/rows
layouts): labels are sent as device text items (type 22) instead of being
baked into the background — the device scrolls them automatically when the
name is wider than the row, so long entity names stay fully readable.
Options: `label_font` (default 2), `label_color` (default: the theme's
`secondary`), `label_speed` (scroll ms/step, default 60, native only). Set
`label_render: static` for labels baked directly into the background image —
never scrolls, always truncated to a fixed length. Grid cells always keep
baked centered labels regardless of `label_render`. (Note: label scrolling
depends on device firmware support — not observed on all units yet.)

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

## `energy_panel`

The energy panels the **Build energy screens** step generates (see
[the README](../README.md#energy-screens)). Each panel is a hybrid card like
`sensor_grid`: HA bakes the background (title, bars, icons, daily totals read
from the recorder), the device polls the live figures as type-23 items. Live
values read in kW; the daily totals baked behind them read in kWh, so a
watt-hour meter no longer reads a thousand times too high.

A panel picks its layout from `mode`:

| Mode | Layout |
|---|---|
| `price` | Current price large, a min-to-max bar marking where it sits, and the clock time of the cheapest and priciest hour under the bar. |
| `power` | House load large, one line of today's grid import and export each behind an arrow, then the gas and water footer band. |
| `battery` | State-of-charge bar, percentage large, watts with a direction word. |
| `solar` | Current production large, today's yield below, the day's curve behind. |
| `solar_battery` | Solar on top with a goal bar, battery below with a charge-level icon and a bipolar power bar. Falls back to the plain `solar` or `battery` layout when only one side has a source, and to a blank screen when neither does. |

The generator writes these pages for you. Document them here so you can edit a
generated page or hand-write one.

### `solar_battery` page schema

```yaml
page_type: card
card: energy_panel
mode: solar_battery
name: Energy              # default "Energy"; the generator writes "Solar" or
                         # "Battery" for a single-source home
# --- solar half (optional; omit to draw the battery half full height) ---
solar_power_entity: sensor.solar_power   # live production, the hero figure
solar_stat: sensor.solar_energy          # production statistic: today's yield + day curve
color: "#FF9800"         # solar accent; default the dashboard's solar orange
goal: 0                  # today's target in kWh for the goal bar. 0 or absent
                         # means no goal: the caption stays "x.x kWh today"
# goal_template: >-       # a template producing the goal number; overrides `goal`.
#   {{ states('sensor.solar_energy_production_today') | float(0) }}
                         # the generator fills this from the Forecast.Solar entity
                         # recorded under `config_entry_solar_forecast`
# --- battery half (optional; omit to draw the solar half full height) ---
battery_soc: sensor.battery_soc          # state of charge: icon, percentage, bar
battery_power_entity: sensor.battery_power  # power: sign picks charge vs discharge
power_entity: sensor.battery_power       # the live power figure drawn above the bar
# power_min: -2500       # bipolar bar's charging (negative) end, in the sensor's
# power_max: 800         # own unit, and its discharging (positive) end. Both
                         # optional: without them the ends come from the sensor's
                         # own minimum and maximum over the last seven days, and
                         # fall back to a symmetric span when the recorder is empty
# invert_power: false    # true when a positive reading means charging
# charge_color: "#F06292"    # override the charging colour (default pink)
# discharge_color: "#4DB6AC"  # override the discharging colour (default teal)
# row_font: 184          # device font id for the percentage and power figures
# background: "#000000"
```

**Optional keys and what happens without them.** With no `solar_stat` and no
`solar_power_entity` the panel draws the battery half full height; with no
`battery_soc` and no `battery_power_entity` it draws the solar half full height;
with neither side it draws nothing. Without `goal` or `goal_template` (or with
`goal: 0`) the solar half keeps its plain `x.x kWh today` caption instead of a
progress bar. Without `power_min` / `power_max` the bipolar bar reads its ends
from the last seven days of recorder statistics, so you never configure them by
hand. The charge direction rides the battery icon (an MDI battery band), so no
direction word is spent; font 184 carries no minus glyph, so the power figure's
sign is stripped and colour plus fill direction carry charge versus discharge.

### `price` page keys for the cheapest and priciest hour

The `price` mode gained the clock time of the day's cheapest and priciest hour,
baked under the min and max prices:

```yaml
cheapest_time: "13:00"   # baked under the low price; empty draws nothing
priciest_time: "07:00"   # baked under the high price; empty draws nothing
# cheapest_time_template / priciest_time_template: templates the generator writes
# to read the time off the day-ahead price list. A missing or malformed list
# renders empty, and the panel then draws no time.
```

## `energy_history`

The fifth energy screen: today's production and consumption per hour on the same
24 hour axis the day-ahead price graph uses, so the two read as a pair. It draws
two series only, because four filled areas at 128 pixels read as mud: solar
production as bars, house consumption as a line on top. Consumption is derived
per hour the way the house panel derives it (import minus export plus solar plus
battery discharge minus battery charge). The background is baked artwork; there
are no live overlays.

```yaml
page_type: card
card: energy_history
title: Today             # optional; the legend tucks in beside it, or leads without one
unit: kWh                # axis unit label
solar_stat: sensor.solar_energy       # solar production statistic (the bars)
import_stat: sensor.from_grid         # the four consumption statistics below are
export_stat: sensor.to_grid           # summed per hour into the consumption line
battery_in_stat: sensor.battery_charge
battery_out_stat: sensor.battery_discharge
solar_color: "#FF9800"   # bars; default #FFB300
consumption_color: "#FFFFFF"  # line; default white
# background: "#000000"
```

**Optional keys and what happens without them.** The graph draws whichever
series it has data for. With no `solar_stat` it draws consumption alone; with no
grid or battery statistic it draws solar alone rather than a line that only
mirrors the bars; with neither it prints `no data`. Hours later than the current
hour stay empty rather than drawing a zero. A `title` is optional: set it and the
`solar`/`use` legend tucks in beside it, leave it out and the legend leads.

## Other page types

`card` is specific to this integration. The page types that come from
`gickowtf/pixoo-homeassistant` are documented separately in
[PIXOO_PAGES.md](PIXOO_PAGES.md): the fixed layouts `pv`, `progress_bar` and
`fuel`, plus the image and `templatable` components a `components` page can
use. Unlike cards, none of those push type-23 items; they render a plain
image.

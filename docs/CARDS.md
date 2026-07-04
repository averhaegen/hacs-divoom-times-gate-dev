# Card pages (`page_type: card`)

Gallery cards render a polished 128×128 layout from a few entities — see
SPEC_CARD_GALLERY.md for the architecture. Rendering is hybrid: HA draws the
**background** (MDI icons, labels, separators) and serves it to the device
once; the **values** are type-23 items the device polls itself every
`update_time` seconds. Value changes therefore never flash the panel; the
background only re-sends when its content changes (config edit, a
`color_template` crossing to a different colour).

## `sensor_grid`

2–8 sensors, densest-fitting layout chosen automatically:

| Slots | Layout |
|---|---|
| 2 | Two large rows — 28px icon, label, big value |
| 3–4 | Quadrants — small icon + label on top, value across the cell |
| 5–6 | 2 columns × 3 rows — icon + value, no label |
| 7–8 | 2 columns × 4 rows — icon + value, no label |

The 8-slot ceiling is a readability choice, not a device limit.

### Page schema

```yaml
page_type: card
card: sensor_grid        # currently the only card type
update_time: 10          # poll interval (s), page default
font: 4                  # device font id for values, page default
slots:
  - entity_id: sensor.solar_power
    name: Solar          # label; default: the entity's friendly name
    icon: mdi:solar-power  # default: entity icon, else device_class icon
    color: "#FFB300"     # icon + value colour (default white)
  - entity_id: sensor.home_battery_soc
    color_template: >-   # state-dependent colour (icon + value)
      {% set s = states('sensor.home_battery_soc') | int %}
      {% if s < 20 %}#FF3B30{% elif s < 50 %}#FF9500{% else %}#34C759{% endif %}
  - entity_id: sensor.grid_power
    update_time: 5       # per-slot poll override
    font: 2              # per-slot font override
```

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

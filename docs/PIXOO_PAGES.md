# Pixoo compatibility pages

The page schema exists so a config written for
[`gickowtf/pixoo-homeassistant`](https://github.com/gickowtf/pixoo-homeassistant)
drops into this integration unchanged. The Pixoo draws at 64x64; every page
here renders on a 64x64 canvas and is scaled nearest-neighbour to the Times
Gate's native 128x128, so pixel art stays crisp instead of blurring.

This file covers the fixed-layout page types (`pv`, `progress_bar`, `fuel`)
and the image sources available to `components` pages. For `page_type: card`,
which is specific to this integration, see [CARDS.md](CARDS.md).

Key names match upstream exactly. If a key is optional upstream it is optional
here, with the same default.

## Templatable image sources

Inside a `components` page, `type: image` takes its picture from one of four
mutually exclusive keys. **All four are Jinja2 templates**, rendered through
Home Assistant's template helpers on every tick, so they can key off entity
state and update as the state changes.

| Key | Value |
| --- | --- |
| `image_path` | Absolute path on the HA host |
| `image_url` | `http://` or `https://` URL, fetched each render |
| `image_data` | Base64-encoded image bytes |
| `image_asset` | File name of an icon bundled with this integration (`img/`) |

```yaml
- type: image
  position: [0, 0]
  image_path: >-
    {% if is_state('binary_sensor.front_door', 'on') %}
      /config/www/door_open.png
    {% else %}
      /config/www/door_closed.png
    {% endif %}
```

`image_asset` resolves inside the integration's own `img/` directory and any
directory component is stripped, so a template cannot escape it with `../`.

Optional keys: `width` and `height` resize the image, and `resample_mode`
picks the filter (`nearest`, `box`, `bilinear`, `hamming`, `bicubic`,
`lanczos`; default `box`). Leave `width`/`height` unset to draw at native size.

### `type: templatable`

A `templatable` component renders one template that must produce a **list of
component dicts**, which are then inserted in place. Use it to build a
variable number of components:

```yaml
- type: templatable
  template: >-
    [{'type': 'text', 'content': '{{ s.name }}', 'position': [1, {{ loop.index * 8 }}],
      'color': 'white', 'font': 'five_pix'}
     ...]
```

If the template renders to anything other than a list of dicts, the component
is skipped and the reason is logged. Earlier versions passed the result
straight to `list()`, which silently turned a plain string into a list of
single characters and produced one error per character per tick.

## `page_type: pv`

A solar overview: generation, battery, house load and grid draw. Ported from
upstream `pages/solar.py`.

All six fields are required and all are templates.

| Key | Meaning |
| --- | --- |
| `power` | Current PV generation (number) |
| `storage` | Battery charge in percent (number) |
| `discharge` | Battery flow, negative means discharging (number) |
| `powerhousetotal` | House consumption (number) |
| `vomNetz` | Grid draw (number) |
| `time` | Text shown top right, usually a timestamp |

There is nothing to configure beyond that: upstream derives the icons and
colours from the values, and this port keeps that behaviour so the page looks
the same. Generation is yellow at 1 or above and grey below. Battery flow is
green while charging and red at 0 or below. The battery icon steps through
five bands at 0, 20, 40, 60 and 80 percent. House total is blue, grid draw is
grey.

```yaml
- page_type: pv
  power: "{{ states('sensor.pv_power') }}"
  storage: "{{ states('sensor.battery_level') }}"
  discharge: "{{ states('sensor.battery_flow') }}"
  powerhousetotal: "{{ states('sensor.house_load') }}"
  vomNetz: "{{ states('sensor.grid_import') }}"
  time: "{{ now().strftime('%H:%M') }}"
```

The five icons ship with the integration, so no absolute path to a
`custom_components` directory is needed the way it is upstream.

## `page_type: progress_bar`

A header, a percentage bar, the current time, an optional finish time and a
footer. Ported from upstream `pages/progress_bar.py`. Suits anything with a
percentage and an ETA, such as a washing machine or a download.

| Key | Required | Default |
| --- | --- | --- |
| `header` | yes | |
| `progress` | yes | (number, 0-100) |
| `footer` | yes | |
| `time_end` | no | empty |
| `bg_color` | no | `[0, 123, 255]` |
| `header_font_color` | no | white |
| `progress_bar_color` | no | `[255, 0, 68]` |
| `progress_text_color` | no | white |
| `time_color` | no | `[51, 51, 51]` |
| `time_end_color` | no | `[151, 151, 151]` |
| `footer_font_color` | no | white |
| `header_offset` | no | `2` |
| `footer_offset` | no | `2` |

`time_end` is drawn in the `clock` font, which carries only digits and a
colon, so every other character is stripped before drawing. Feed it something
like `{{ as_timestamp(...) | timestamp_custom('%H:%M') }}`.

```yaml
- page_type: progress_bar
  header: Washing machine
  progress: "{{ state_attr('sensor.washer', 'progress') }}"
  time_end: "{{ state_attr('sensor.washer', 'finish_at') }}"
  footer: "{{ states('sensor.washer_program') }}"
```

## `page_type: fuel`

Three fuel grades with prices, plus a station name, an opening status and the
current day, time and date. Ported from upstream `pages/fuel.py`.

Required, all templates: `title`, `name1`, `price1`, `name2`, `price2`,
`name3`, `price3`, `status`.

| Optional key | Default |
| --- | --- |
| `font_color` | white |
| `bg_color` | `[255, 230, 0]` |
| `price_color` | white |
| `title_color` | black |
| `stripe_color` | the resolved `font_color` |
| `title_offset` | `2` |

The title is drawn in `eleven_pix`, which has no lowercase glyphs, so it is
uppercased before drawing (upstream does the same). Everything else is drawn
verbatim.

```yaml
- page_type: fuel
  title: Shell
  name1: E10
  price1: "{{ states('sensor.station_e10') }}"
  name2: E5
  price2: "{{ states('sensor.station_e5') }}"
  name3: Diesel
  price3: "{{ states('sensor.station_diesel') }}"
  status: "{{ 'open' if is_state('binary_sensor.station', 'on') else 'closed' }}"
```

## Colours

Every `*_color` key accepts `[r, g, b]`, `#RRGGBB`, a CSS colour name, or a
Jinja2 template rendering to one of those.

## Failure behaviour

If a required field is missing, or a value that must be a number is not one,
the page is skipped for that tick and the screen keeps whatever it was
showing. The reason is logged.

## Relationship to dispdata

These three page types render a plain image and push it. They use no type-23
overlay items, so they cannot take part in the rotation problem described in
[DISPDATA.md](DISPDATA.md) section 6.

# Divoom Times Gate — Home Assistant integration (dev)

A custom [Home Assistant](https://www.home-assistant.io/) integration for the
**Divoom Times Gate**, the desk clock with five independent 128×128 screens.
It renders your Home Assistant sensor data across the 5 screens, lets you switch
between HA content and the device's native faces, and exposes device controls:
display brightness/on-off, two RGB lights (edge strip + backlight), a **Display
source** select, a **Screen 1–5** select each, a refresh button, and a buzzer.
Each screen also exposes a **preview image** entity showing what HA last
rendered on it.

The quickest way to get your data on screen is a **card** (`page_type: card`) —
drop in 2–8 sensors and it renders a themed, icon-labelled layout for you (see
[docs/CARDS.md](docs/CARDS.md)). For full manual control, `components` pages
give you pixel-level drawing.

> ⚠️ **Development repo.** Under active development. The default screens use the
> author's entity IDs as worked examples — edit them via **Configure** to match
> your own sensors.

> ℹ️ This is an unofficial, community-maintained integration. It is not
> affiliated with, endorsed by, or supported by Divoom.

## How it works

The Times Gate exposes a local HTTP API (`POST http://<ip>/post`). Key facts
this integration relies on (reverse-engineered + confirmed against the
[official docs](https://docin.divoom-gz.com/web/#/5)):

- Every request needs a `LocalToken` (an integer shown in the Divoom app under
  the device's settings). Without it the device replies `DeviceToken is err`.
- Images are sent with `Draw/SendHttpGif` as **base64 JPEG** (not raw RGB like
  the Pixoo), `PicWidth: 128`, and an `LcdArray` selecting one of the 5 screens.
- `PicID` must be monotonically increasing; we reset the counter on startup and
  increment from there.

## Installation (HACS custom repository)

1. HACS → ⋮ → **Custom repositories** → add
   `https://github.com/averhaegen/hacs-divoom-times-gate-dev` as an
   **Integration**.
2. Install **Divoom Times Gate**, then restart Home Assistant.
3. Settings → Devices & Services → **Add Integration** → *Divoom Times Gate*.
4. Enter the device **IP address** and the **LocalToken** from the Divoom app.

## Display modes (Display source select)

The **Display source** select controls what the whole device shows. When it's
**not** "HA Dashboard", the integration stops pushing so the native face stays:

- **HA Dashboard** — HA renders content to the screens (per the Screen selects).
- **Overall Display: \<face\>** — one face spanning all 5 screens (the app's
  "Overall display"). Options come from your *overall* faces (see below).
- **Independent Display: Control1…5** — a native per-screen preset you built in
  the Divoom app ("Independent display"). Read live from the device.
- **Off** — screens off.

In **HA Dashboard**, each **Screen N** select chooses that screen's mode:
**Custom** (render your config), **Off**, or **Face: \<name\>** (a native face).

These selects work from the dashboard and from automations
(`select.select_option`), and remember their choice across restarts.

## Updating the faces list

Face dropdowns are built from a small **faces** list you edit in **Configure**.
The integration ships only a **few defaults** — add your own. Find a face's
`clock_id` in the Divoom app, then:

```yaml
overall:                 # whole-device (Overall Display) spanning faces
  - name: Neon
    clock_id: 1040
  - name: Clock face
    clock_id: 581
per_screen:              # single-screen faces (Screen N -> Face: ...)
  - name: Weather
    clock_id: 182
```

`overall` faces appear in the **Display source** select; `per_screen` faces in
each **Screen N** select.

## Configuring screens

Each screen is configured independently. A screen is **either** a single page
**or a list of pages that rotate** (by each page's `duration`, in seconds) — the
same model as a Pixoo's page list, so a Pixoo config drops straight in. Edit via
**Configure** (options) as YAML.

### Easiest: a card

A `card` page turns a handful of sensors into a polished layout — icons
(auto-picked from each entity), labels, live-polled values, and a colour theme —
without drawing anything by hand:

```yaml
- page_type: card
  card: sensor_grid
  theme: navy            # dark | light | navy | forest | sunset | terminal
  slots:
    - entity_id: sensor.solar_power
      color: "#FFB300"
    - entity_id: sensor.home_battery_soc   # battery icon fills with the level
    - entity_id: sensor.grid_power
      value_template: "{{ (states('sensor.grid_power')|float * 1000)|round }} W"
```

2–8 sensors, layout chosen automatically. Full options — themes, per-slot
colours/icons/fonts, value templates, headers — in **[docs/CARDS.md](docs/CARDS.md)**.

### Full control: a components page

The page schema matches
[pixoo-homeassistant](https://github.com/gickowtf/pixoo-homeassistant), so pages
are portable between a Pixoo 64 and a Times Gate. Components pages always render
on a 64×64 Pixoo canvas and are then upscaled to the Times Gate's 128×128.

```yaml
- page_type: components
  enabled: "{{ true }}"
  variables:
    soc: "{{ states('sensor.battery')|int }}"
  components:
    - type: text
      content: "{{ soc }}%"
      position: [32, 18]
      align: center        # left | center | right
      font: eleven_pix     # see "Fonts" below
      color: "{% if soc|int < 20 %}red{% else %}green{% endif %}"
    - type: rectangle
      position: [10, 42]
      size: [44, 6]
      color: [80, 80, 80]
      filled: false
    - type: image
      image_path: /config/www/icon.png   # or image_url / image_data (base64)
      position: [0, 0]
```

### Fonts — bitmap Pixoo fonts

Set `font` to a bitmap font name — `pico_8`, `gicko`, `five_pix`,
`eleven_pix`, `clock`, `pix24`. These match the Pixoo's pixel fonts; text is
uppercased like the Pixoo and the 64×64 result is scaled up to 128 with
nearest-neighbour.

`dispdata_text` and `card` pages use **device font ids** instead (rendered by
the device, not HA). See **[docs/FONTS.md](docs/FONTS.md)** for a
use-case-sorted shortlist (which fonts do letters, digits, `%`, `.`, `:`) and
[docs/FONTS_CATALOG.md](docs/FONTS_CATALOG.md) for all 308 with exact charsets.

### Other page types

- `page_type: card` — a prebuilt sensor layout (see above and
  [docs/CARDS.md](docs/CARDS.md)).
- `page_type: image` — a photo or animated GIF on the screen, from
  `image_path: /config/www/photo.jpg` or `image_url:` (`fit: cover` | `contain`).
  Animated GIFs play as an animation (up to ~40 frames).
- `page_type: dispdata_text` — device-native text that **self-polls HA** (no
  per-tick push). Good for lightweight always-fresh values and native clock/
  date/weather elements. See [docs/DISPDATA.md](docs/DISPDATA.md).
- `page_type: clock` — a native device face. `clock_id: 61`.
- `page_type: gif` — play animated GIF(s) on the screen (device-native, sizes
  16/32/64/128). `gif_url: "https://…/x.gif"` (or `gif_urls: [url, url]`).
- `page_type: visualizer` — an audio visualizer. `id: 0` (visualizer index).
- `page_type: off` — black screen.
- `enabled: "{{ ... }}"` — if it renders false, that screen is left unchanged.

> Device channels (Faces/Cloud/Visualizer/Custom) for the *whole* device are
> selected with the **Display source** entity, not a per-screen page type.

Colors accept an `[r, g, b]` list, a `#RRGGBB` string, a CSS color name, or a
Jinja2 template returning any of those.

### Rotating pages

Give a screen multiple pages to rotate through them:

```yaml
# one screen that alternates a custom page and a native weather face
- - page_type: components
    duration: 20
    components:
      - { type: text, content: "{{ states('sensor.power') }} W", position: [32, 26], align: center, font: eleven_pix }
  - page_type: clock
    clock_id: 182
    duration: 10
```

A single page = a static screen. `enabled: "{{ ... }}"` skips a page in rotation.

## Bundled icons & the PV (solar) card

The integration bundles the pixoo-homeassistant icon set (sun, battery levels,
house, industry, trash, weather). Reference them in an `image` component with
`image_asset:` (no install path needed):

```yaml
- type: image
  image_asset: sunpower.png        # see custom_components/.../img/
  position: [2, 1]
```

The **PV / solar card** is a `components` page using these icons + bitmap fonts.
Adjust the `variables` to your own sensors:

```yaml
- page_type: components
  variables:
    power: "{{ states('sensor.solaredge_i1_ac_power')|int }}"
    storage: "{{ states('sensor.YOUR_BATTERY_SOC')|int }}"          # percentage
    discharge: "{{ states('sensor.YOUR_BATTERY_POWER')|int }}"
    powerhousetotal: "{{ states('sensor.YOUR_HOUSE_POWER')|int }}"
    gridpower: "{{ states('sensor.YOUR_GRID_POWER')|int }}"
    time: "{{ now().strftime('%H:%M') }}"
  components:
    - { type: image, image_asset: sunpower.png, position: [2, 1] }
    - { type: text, content: "{{ power }}", font: gicko, position: [17, 8],
        color: "{{ [255,175,0] if power|int >= 1 else [131,131,131] }}" }
    - type: image
      position: [2, 17]
      image_asset: "{{ 'akku80-100.png' if storage|int >= 80 else 'akku60-80.png' if storage|int >= 60 else 'akku40-60.png' if storage|int >= 40 else 'akku20-40.png' if storage|int >= 20 else 'akku00-20.png' }}"
    - { type: text, content: "{{ discharge }}", font: gicko, position: [17, 18],
        color: "{{ [255,0,68] if discharge|int <= 0 else [4,204,2] }}" }
    - { type: text, content: "{{ storage }}%", color: white, font: pico_8, position: [17, 25] }
    - { type: image, image_asset: haus.png, position: [2, 33] }
    - { type: text, content: "{{ powerhousetotal }}", color: [0,123,255], font: gicko, position: [17, 40] }
    - { type: image, image_asset: industry.png, position: [2, 49] }
    - { type: text, content: "{{ gridpower }}", color: [131,131,131], font: gicko, position: [17, 56] }
    - { type: text, content: "{{ time }}", color: white, font: pico_8, position: [44, 1] }
```

## Services

- **`divoom_times_gate.set_clock_face`** — `screen` (0–4), `clock_id`. Show any
  native face on a screen.
- **`divoom_times_gate.show_message`** — `screen`, `text`, optional `duration`
  and `color`. Flash a message, then revert to normal content.
- **`divoom_times_gate.show_image`** — `screen`, `image_path` or `image_url`,
  optional `fit` (cover/contain) and `duration` (0 = keep showing). Quickly
  throw a photo or animated GIF onto a screen.

## RGB lighting

Two independent RGB light entities, matching the Divoom app's zones:
- **Surround lights** — the curved edge strips
- **Back lights** — the lighting behind the 5 screens

Each supports **colour + brightness**, plus an **effect** list:
- **Solid** — static chosen colour (default)
- **Rainbow** — auto colour-cycle (ignores the chosen colour)
- **Colour 4 / 6 / 7 / 9** — animations that honour the chosen colour
- **Party 0 / 1 / 2 / 5 / 8 / 10 / 11** — fixed multicolour animations (ignore the
  chosen colour)

The two zones are independent (e.g. blue surround + green back at the same time).

## Credits

Rendering approach and overall design are informed by
[gickowtf/pixoo-homeassistant](https://github.com/gickowtf/pixoo-homeassistant)
(MIT). This project is a separate implementation for the Times Gate's
multi-screen / JPEG / LocalToken API.

## License

MIT — see [LICENSE](LICENSE).

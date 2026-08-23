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

## Supported devices

This integration supports the **Divoom Times Gate** only. No other Divoom device
speaks the same 5-screen local API.

| Hardware revision | Local endpoint | Status |
| --- | --- | --- |
| 400 | `POST http://<ip>/post` | Tested. Every reverse-engineered fact in these docs comes from one revision 400 unit. |
| 402 | `POST http://<ip>:9000/divoom_api` | Supported in code, following Divoom's official documentation. Nobody has run this integration against a revision 402 device, so treat it as unverified. |

The revision comes from Divoom's LAN discovery response and defaults to `400`
when discovery does not report one. Port 9000 is confirmed closed on revision
400, so the two endpoints are not interchangeable.

The integration talks to the device over your local network. It calls Divoom's
cloud twice, and only for convenience: once at setup to find devices that share
your public IP address, and again when building the face and preset option lists.
Neither call signs in to your Divoom account. See
[docs/LIMITATIONS.md, no Divoom cloud account features](docs/LIMITATIONS.md#no-divoom-cloud-account-features).

## Supported functions

### Entities

The integration creates one device with 19 entities.

| Entity | Platform | What it does |
| --- | --- | --- |
| **Display** | light | Turns the whole display on or off and sets its brightness. |
| **Edgelight** | light | The curved edge strips. Colour, brightness, and 12 device effects. |
| **Backlight** | light | The lighting behind the 5 screens. Colour, brightness, and 12 device effects. |
| **Display source** | select | Chooses what drives the device: `HA Dashboard`, `Off`, an `Overall Display: <name>` face, or an `Independent Display: <name>` preset. |
| **Screen 1** to **Screen 5** | select | Per-screen mode while the display source is `HA Dashboard`: `Custom`, `Off`, or `Face: <name>`. |
| **Screen 1 preview** to **Screen 5 preview** | image | The last frame Home Assistant rendered for that screen. Not a screenshot. |
| **Refresh screens** | button | Forces a full repaint of every screen on the next poll. |
| **Buzzer** | button | Sounds the device buzzer. |
| **Edgelight color cycle** | switch | Cycles the edge strip through colours instead of holding the chosen one. |
| **Backlight color cycle** | switch | Cycles the backlight through colours instead of holding the chosen one. |
| **Button backlight** | switch | Lights the physical buttons. |

The three switches are configuration entities and report an assumed state,
because the device does not report these settings back.

### Screen content

Configure each screen through the integration's **Configure** dialog. A screen
holds one page, or a list of pages that rotate. See
[Configuring screens](#configuring-screens) for the page types: `card`,
`components`, `image`, `dispdata_text`, `clock`, `gif`, `visualizer`, and `off`.

### Actions

| Action | What it does |
| --- | --- |
| `divoom_times_gate.set_clock_face` | Shows a native device face on one screen. |
| `divoom_times_gate.show_message` | Flashes text on one screen, then reverts. |
| `divoom_times_gate.show_image` | Shows a photo or animated GIF on one screen. |

All three take an optional `device_id` so you can target one Times Gate when you
have several. Full field lists are in [Services](#services).

### Diagnostics

Download diagnostics from the device page's three-dot menu. The file contains the
config entry data, the screen configuration, and the result of the last push per
screen. The LocalToken, the DispData secret, and the MAC address are redacted.

## Data updates

The integration polls. Its `DataUpdateCoordinator` runs on the **refresh
interval**, which defaults to **60 seconds** and accepts **5 to 3600 seconds** in
**Configure > Settings & faces**.

What happens on each tick depends on the **Display source**:

- If the display source is not `HA Dashboard`, the coordinator sends nothing. The
  device keeps showing its own face and Home Assistant stays out of the way.
- If it is `HA Dashboard`, the coordinator renders every screen set to `Custom`,
  hashes the result, and skips any screen whose hash has not changed. Screens set
  to `Off` or to a face are written once when you change them, not on every tick.
- Everything that did change goes to the device in a single `Draw/CommandList`
  request, so one tick is one HTTP call however many screens changed.

A `dispdata_text` page works differently, and does not use the refresh interval
at all. Home Assistant sends the background and the layout once, when the page
first becomes active. After that **the device polls Home Assistant** at
`http://<home-assistant-ip>:8123/api/divoom_times_gate/dispdata/<secret>/<entity_id>`
every `update_time` seconds (10 seconds by default) and redraws the value itself.
Home Assistant sends nothing again unless the page configuration changes. Use it
for a value you want fresh without paying for a full screen repaint. Setup and
network requirements are in [docs/DISPDATA.md](docs/DISPDATA.md).

If a poll fails, the coordinator retries on the next tick. After 3 failures in a
row it marks the entities unavailable, and it re-runs discovery to find the device
at a new IP address. See
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md#all-entities-show-as-unavailable).

## Use cases

What people set this up for. Each one links to a worked example.

- **Watch solar and battery at a glance.** Give one screen a `card` page with
  your production, load, and state-of-charge sensors, and read it from across the
  room. See [the solar example](docs/EXAMPLES.md#watch-solar-and-battery-at-a-glance).
- **Get alerted without your phone.** Flash a message or a camera snapshot on one
  screen when the doorbell rings or the washing machine finishes, then let the
  screen go back to normal on its own. See
  [the doorbell example](docs/EXAMPLES.md#flash-a-doorbell-alert-on-the-middle-screen).
- **Keep the clock a clock.** Leave four screens on the device's own faces and
  hand one to Home Assistant. See
  [the mixed-mode example](docs/EXAMPLES.md#keep-native-faces-most-of-the-time-and-one-home-assistant-screen).
- **Show a live value cheaply.** A `dispdata_text` page is set up once and then
  refreshed by the device itself, so a number stays current without repainting
  the screen. See
  [the dispdata example](docs/EXAMPLES.md#show-a-live-sensor-value-without-repainting-the-screen).
- **Turn the clock into a status light.** Drive the edge strip from your alarm
  state or another sensor. See
  [the RGB example](docs/EXAMPLES.md#use-the-rgb-lights-as-a-house-status-indicator).
- **Change what the device shows on a schedule.** Switch the display source at
  night and back in the morning. See
  [the night mode example](docs/EXAMPLES.md#switch-the-whole-device-back-to-its-own-faces-at-night).

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

## Installation & configuration parameters

The integration has one short **installation** form, and the **Configure**
dialog (options flow) for everything you can tweak later.

### During installation (and HA "Reconfigure")

| Field | What it does | Valid values / default |
| --- | --- | --- |
| **IP address** (`ip_address`) | The device's current LAN IP. If discovery finds your Times Gate first, HA offers it in a dropdown; you can also type it manually. | Required. Default: the first discovered Times Gate if HA finds one, otherwise blank. |
| **LocalToken** (`local_token`) | Required on every local API call. This is the integer shown in the Divoom app under the device's settings. | Required integer. No default. |
| **Refresh interval** (`refresh_interval`) | How often Home Assistant refreshes the integration while HA is managing the display. | Integer seconds. Default: `60`. In **Configure → Settings & faces**, HA validates `5`–`3600` seconds. |

### In Configure → Settings & faces

| Field | What it does | Valid values / default |
| --- | --- | --- |
| **Refresh interval (seconds)** (`refresh_interval`) | Same setting as above, but editable later from the options flow. | `5`–`3600` seconds. Default: `60`. |
| **Dashboard base preset** (`dashboard_base`) | Optional native **Independent display** preset that HA overlays onto when **Display source** is **HA Dashboard**. Pick a static face (or blank preset) if you want to avoid native live faces reloading underneath the HA overlay. | Dropdown built from the device's current independent presets, plus **Leave device as-is**. Default: **Leave device as-is** (empty value). |
| **Faces (favorites)** (`faces`) | The favorites lists used to build the native-face dropdowns in Home Assistant. `overall` populates **Display source → Overall Display: ...**; `per_screen` populates **Screen N → Face: ...**. | Object/YAML with two keys: `overall` and `per_screen`, each a list of `{name, clock_id}` objects. Default: a small starter set shipped with the integration (see below). |

Default `faces` value:

```yaml
overall:
  - name: Neon
    clock_id: 1040
  - name: Clock face
    clock_id: 581
  - name: City Time
    clock_id: 697
per_screen:
  - name: Weather ONE
    clock_id: 182
  - name: Big Time
    clock_id: 152
  - name: Pinkclock
    clock_id: 669
  - name: DIY Digital Clock
    clock_id: 284
  - name: Retro web cute pastel
    clock_id: 662
```

### In Configure → Screen 1–5

Each screen has its own **Pages** (`screens`) editor. This is an object/YAML
field: enter either a **single page object** or a **list of page objects** that
rotate by each page's `duration` (seconds). The default for each screen is the
integration's shipped example page set; as noted above, those examples use the
author's entity IDs and are meant to be replaced with your own.

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
  theme: navy            # dark | light | navy | forest | sunset | terminal | cyberpunk | neon | sci_fi
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
- `page_type: pv` — a solar overview: production, consumption, grid flow and
  battery state on one screen. See [docs/PIXOO_PAGES.md](docs/PIXOO_PAGES.md).
- `page_type: progress_bar` — one or more horizontal bars driven by a sensor
  value between `min` and `max`. See
  [docs/PIXOO_PAGES.md](docs/PIXOO_PAGES.md).
- `page_type: fuel` — a fuel-price board with up to four price rows. See
  [docs/PIXOO_PAGES.md](docs/PIXOO_PAGES.md).
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

- **`divoom_times_gate.set_clock_face`**: `screen` (0 to 4), `clock_id`. Shows any
  native face on a screen.
- **`divoom_times_gate.show_message`**: `screen`, `text`, optional `duration`
  (1 to 600 seconds) and `color` (`#RRGGBB`). Flashes a message, then reverts to
  normal content.
- **`divoom_times_gate.show_image`**: `screen`, `image_path` or `image_url`,
  optional `fit` (cover or contain) and `duration` (0 to 86400 seconds, where 0
  keeps showing). Throws a photo or animated GIF onto a screen.

Each service also takes an optional `device_id`. For automations that use these,
see [docs/EXAMPLES.md](docs/EXAMPLES.md).

## RGB lighting

Two independent RGB light entities, one per lighting zone:

- **Edgelight**, the curved edge strips.
- **Backlight**, the lighting behind the 5 screens.

Each takes a colour and a brightness, and each has its own list of 12 device
effects. The lists differ per zone, because the device numbers them differently.
Effects marked "custom color" render in the colour you set on the light. Effects
marked "fixed color" ignore it and play their own palette.

| Effect id | Edgelight | Backlight |
| --- | --- | --- |
| 0 | Sparkle (fixed color) | Beetle (fixed color) |
| 1 | Pendulum (fixed color) | Atom (fixed color) |
| 2 | Rainbow (fixed color) | Pendulum (fixed color) |
| 3 | Beetle (fixed color) | Sparkle (fixed color) |
| 4 | Bulb (custom color, default) | Rainbow (custom color) |
| 5 | Flame (fixed color) | Bulb (custom color, default) |
| 6 | Waves (fixed color) | Infinity (custom color) |
| 7 | Rain (fixed color) | Chat (custom color) |
| 8 | Heart (custom color) | Antenna (custom color) |
| 9 | Infinity (custom color) | Waves (custom color) |
| 10 | Rocket (fixed color) | Rain (custom color) |
| 11 | Color wheel (custom color) | Circles (custom color) |

The **Edgelight color cycle** and **Backlight color cycle** switches make a zone
cycle through colours instead of holding the one you picked. The **Button
backlight** switch lights the physical buttons.

The two zones are independent, so you can run a blue edge strip and a green
backlight at the same time. For the device commands behind this, see
[docs/RGB_LIGHTS.md](docs/RGB_LIGHTS.md).

## Known limitations

Read [docs/LIMITATIONS.md](docs/LIMITATIONS.md) before you file a bug. It covers
what the device cannot do and why, including no Divoom account features, no
sensor entities for device state, no way to read back what a screen shows, labels
that do not scroll, and the rotation combination that leaves a screen on
"Loading".

## Troubleshooting

[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) lists symptoms with their
causes and fixes: discovery finding nothing, a rejected LocalToken, entities
going unavailable, a device that changed IP address, a screen stuck on "Loading",
and a `dispdata_text` value that never arrives.

## Removing the integration

To remove the integration from Home Assistant, go to **Settings → Devices &
Services**, find **Divoom Times Gate**, open the **...** menu, and choose
**Delete**.

If you also want to remove the downloaded custom integration from HACS
afterward, go to **HACS → Integrations**, open **Divoom Times Gate**, open the
**...** menu, and choose **Remove**.

Removing the integration does **not** reset or change anything on the physical
Times Gate itself — Home Assistant simply stops managing it locally.

## Energy screens

Open the integration options and pick **Build energy screens**. The integration
reads your Home Assistant energy dashboard configuration and fills all five
screens:

1. Current electricity price, with a bar marking where it sits between today's
   cheapest and dearest hour.
2. House load, with import and export below it and today's totals per direction.
3. Battery charge, coloured pink while charging and teal while discharging.
4. Solar production, with today's yield and the day's curve behind it.
5. The day-ahead price graph, with gas and water along the bottom.

Colours follow the ones the energy dashboard uses, so blue means import and
purple means export. Screens for a source you do not have stay blank. The
generated pages are ordinary screen configurations, so you can edit any of them
afterwards and the generator will not touch them again unless you run it again.

Numbers refresh on the device's own poll, roughly every 10 seconds, while the
artwork behind them is only re-sent when it actually changes.

## Presets

A preset is a named set of five screens. Generating the energy screens stores
them as the `energy` preset and keeps whatever you had as `default`, and a
**Screen preset** select entity switches between them. Add your own under the
`presets` option:

```yaml
presets:
  night:
    - page_type: clock
    - page_type: "off"
    - page_type: "off"
    - page_type: "off"
    - page_type: "off"
```

## Credits

Rendering approach and overall design are informed by
[gickowtf/pixoo-homeassistant](https://github.com/gickowtf/pixoo-homeassistant)
(MIT). This project is a separate implementation for the Times Gate's
multi-screen / JPEG / LocalToken API.

## Support

This integration is a spare-time project. If it saved you an evening of
reverse engineering, you can
[buy me a coffee](https://buymeacoffee.com/averhaegen).

## License

MIT — see [LICENSE](LICENSE).

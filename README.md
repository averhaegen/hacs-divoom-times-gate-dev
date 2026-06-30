# Divoom Times Gate — Home Assistant integration (dev)

A custom [Home Assistant](https://www.home-assistant.io/) integration for the
**Divoom Times Gate**, the desk clock with five independent 128×128 screens.
It renders your Home Assistant sensor data across the 5 screens and exposes
device controls: display brightness/on-off, two RGB lights (edge strip +
backlight, with colour), a refresh button, and a buzzer button.

> ⚠️ **Development repo.** Under active development. The default screens use the
> author's entity IDs as worked examples — edit them via **Configure** to match
> your own sensors.

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

## Configuring screens

Each of the 5 screens is a "page" rendered from a list of components. Edit them
via **Configure** (options) as YAML. The schema matches
[pixoo-homeassistant](https://github.com/gickowtf/pixoo-homeassistant), so pages
are portable between a Pixoo 64 and a Times Gate.

```yaml
- page_type: components
  size: 128            # 128 = native (default); 64 = Pixoo canvas, scaled up
  enabled: "{{ true }}"
  variables:
    soc: "{{ states('sensor.battery')|int }}"
  components:
    - type: text
      content: "{{ soc }}%"
      position: [64, 26]
      align: center        # left | center | right
      font: 42             # see "Fonts" below
      color: "{% if soc|int < 20 %}red{% else %}green{% endif %}"
    - type: rectangle
      position: [20, 84]
      size: [88, 12]
      color: [80, 80, 80]
      filled: false
    - type: image
      image_path: /config/www/icon.png   # or image_url / image_data (base64)
      position: [0, 0]
```

### Fonts — two modes

- **Scalable (native, recommended):** set `font` to a **number** (the pixel
  size), e.g. `font: 42`. Smooth anti-aliased text, mixed case. Best on the
  Times Gate's full 128×128.
- **Bitmap (Pixoo-compatible):** set `font` to a **name** — `pico_8`, `gicko`,
  `five_pix`, `eleven_pix`, `clock`, `pix24`. These match the Pixoo's pixel
  fonts (text is uppercased, like the Pixoo). Use with `size: 64` so a page
  copied from a Pixoo config renders identically (it's scaled up to 128 with
  nearest-neighbour).

### Other page types

- `page_type: clock` with `clock_id: 61` — a native device clock/face.
- `page_type: off` — black screen.
- `enabled: "{{ ... }}"` — if it renders false, that screen is left unchanged.

Colors accept an `[r, g, b]` list, a `#RRGGBB` string, a CSS color name, or a
Jinja2 template returning any of those.

## Credits

Rendering approach and overall design are informed by
[gickowtf/pixoo-homeassistant](https://github.com/gickowtf/pixoo-homeassistant)
(MIT). This project is a separate implementation for the Times Gate's
multi-screen / JPEG / LocalToken API.

## License

MIT — see [LICENSE](LICENSE).

# Divoom Times Gate — Home Assistant integration (dev)

A custom [Home Assistant](https://www.home-assistant.io/) integration for the
**Divoom Times Gate**, the desk clock with five independent 128×128 screens.
It renders your Home Assistant sensor data across the 5 screens and exposes
device controls (brightness, on/off, refresh, buzzer).

> ⚠️ **Development repo.** This is a proof-of-concept under active development.
> The five screens and their entity IDs are currently hard-coded; configurable
> screens are planned.

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

Each of the 5 screens is a "page" using the **same component schema as
[pixoo-homeassistant](https://github.com/gickowtf/pixoo-homeassistant)**, so a
page can be copied between a Pixoo 64 and a Times Gate. Edit them via
**Configure** (options) as YAML:

```yaml
- page_type: components
  size: 64            # 64 = Pixoo-native (scaled to the Gate's 128); or 128
  enabled: "{{ true }}"
  variables:
    soc: "{{ states('sensor.battery')|int }}"
  components:
    - type: text
      content: "{{ soc }}%"
      position: [32, 14]
      align: center        # left | center | right
      font: pix24          # pico_8 | gicko | five_pix | eleven_pix | clock | pix24
      color: "{% if soc|int < 20 %}red{% else %}green{% endif %}"
    - type: rectangle
      position: [10, 44]
      size: [44, 7]
      color: [80, 80, 80]
      filled: false
    - type: image
      image_path: /config/www/icon.png   # or image_url / image_data (base64)
      position: [0, 0]
```

Other page types: `page_type: clock` (`clock_id: 61`, a native device face) and
`page_type: off` (black). Pages render on a 64×64 canvas by default and scale to
128 with nearest-neighbour, so copied Pixoo pages look identical.

## Credits

Rendering approach and overall design are informed by
[gickowtf/pixoo-homeassistant](https://github.com/gickowtf/pixoo-homeassistant)
(MIT). This project is a separate implementation for the Times Gate's
multi-screen / JPEG / LocalToken API.

## License

MIT — see [LICENSE](LICENSE).

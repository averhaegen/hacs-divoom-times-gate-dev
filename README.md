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

## Credits

Rendering approach and overall design are informed by
[gickowtf/pixoo-homeassistant](https://github.com/gickowtf/pixoo-homeassistant)
(MIT). This project is a separate implementation for the Times Gate's
multi-screen / JPEG / LocalToken API.

## License

MIT — see [LICENSE](LICENSE).

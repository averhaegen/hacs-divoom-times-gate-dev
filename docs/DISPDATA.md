# DispData — push-free sensor text on the Times Gate

How to show a live HA entity's state on a screen **without HA repeatedly
pushing a JPEG** — the device polls HA itself. Background: `Draw/SendHttpItemList`
type 23 (see `docs/API.md` §4.10) lets the device fetch a URL every
`update_time` seconds and expects `{"DispData": "<value>"}` back.

---

## 1. Does HA already expose entity states over an API?

**Yes, but not usable here.** HA's built-in `/api/states/<entity_id>` requires
a bearer auth token in the request header. The Times Gate can only make a
plain unauthenticated `GET` — it has no way to attach a token. So this
integration adds its **own** endpoint that needs no HA auth, instead gated by
a random secret baked into the URL path:

```
http://<HA-ip>:8123/api/divoom_times_gate/dispdata/<secret>/<entity_id>
→ {"DispData": "<state of entity_id>"}
```

- The `<secret>` is generated once per config entry (16 random URL-safe bytes)
  when the integration is first set up, and stored internally — you never type
  it in yourself, the integration constructs full URLs for you (see §3).
- HA does **not** expose all entities by default: this view only serves the
  literal `entity_id` in the URL. There is no listing/enumeration endpoint —
  you cannot discover other entities' data by guessing the secret, only by
  also knowing (or guessing) an exact `entity_id`, which is far more limited
  than a full state dump.
- Because there's no per-entity allowlist, treat the secret **like a
  read-capability password**: anyone with the URL can read the state of *any*
  entity_id they know, for as long as this integration is loaded. Don't post
  the URL publicly.

## 2. Do I need a list of entities set up first?

No separate "expose this entity" step. Any `entity_id` that exists in your HA
instance can be requested — you just reference it directly (e.g.
`sensor.living_room_temperature`) when you configure a screen page (§3). There
is no allowlist to maintain; the secret alone is the gate.

## 3. How do you set this up on a screen / "the card"?

Add a `dispdata_text` page to a screen in the options-flow YAML editor. It
supports **up to 4 sensors** on one screen, stacked as separate rows:

```yaml
- page_type: dispdata_text
  sensors:
    - entity_id: sensor.living_room_temperature
      name: "Living room"    # optional label prefix, e.g. "Living room: 21.4°C"
      color: "#00FF00"
    - entity_id: sensor.bedroom_temperature
      name: "Bedroom"
      color: "#00FFFF"
    - entity_id: sensor.outside_temperature
      name: "Outside"
      color: "#FF8800"
  # Shared defaults for every row below (each can also be overridden per sensor):
  font: 4                 # see docs/API.md §4.9 for the confirmed font id list
  align: 1                # 1 left / 3 centre / 5 right
  TextWidth: 128
  Textheight: 16
  speed: 50
  update_time: 10         # seconds between device-side polls
  # background_gif: "https://dummyimage.com/128x128/000000/000000.gif"  # optional override
```

A single-sensor shorthand still works (no `sensors:` list needed):

```yaml
- page_type: dispdata_text
  entity_id: sensor.living_room_temperature
  color: "#00FF00"
```

Each entry under `sensors:` accepts the same per-row fields (`x`, `y`, `font`,
`color`, `align`, `TextWidth`, `Textheight`, `speed`, `update_time`) — set them
on a sensor to override the page-level default just for that row. `name` sets
the label shown in front of the value (`"<name>: <value>"`); if omitted, the
entity's HA friendly name is used. `y` defaults to one of 4 evenly-spaced rows
(`8, 40, 70, 100`) based on the sensor's position in the list, so a 1–4 sensor
page looks reasonable without setting `y` at all.

The integration then:

1. For each sensor, builds a poll URL: `http://<HA local IP>:8123/api/divoom_times_gate/dispdata/<secret>/<entity_id>?label=<name>`
   (HA's own reachable local URL is resolved via
   `homeassistant.helpers.network.get_url(..., allow_external=False)` — this
   deliberately never returns your Nabu Casa/external URL, since the device
   is a LAN client). The view appends the entity's `unit_of_measurement` to
   the value automatically (e.g. `21.4°C`), and prefixes `label` if given.
2. Sends **one** `Draw/SendHttpItemList` call with `NewFlag: 1` (background +
   up to 4 type-23 items, one per sensor) the first time the page becomes
   active on a screen — after that, the device polls each item on its own; HA
   does not push again for this page on later coordinator ticks. Changing the
   page's config (position, color, sensors, …) is detected and re-triggers
   the one-time setup call.
3. If several screens change in the same coordinator tick, their commands
   (including any `dispdata_text` setup calls) are batched into a single
   `Draw/CommandList` POST rather than one request per screen.

| Field | Default | Notes |
|---|---|---|
| `sensors` | — | list of up to 4 `{entity_id, name?, color?, font?, ...}`; or use the single-sensor `entity_id` shorthand |
| `x` / `y` | `0` / auto-stacked | `y` auto-picks one of `8, 40, 70, 100` per row unless set |
| `font` | `4` | see `docs/API.md` §4.9 for confirmed working ids |
| `color` | `#FFFFFF` | `#RRGGBB`; ignored for fonts with a built-in colour (256, 260) |
| `align` | `1` | `1` left / `3` centre / `5` right |
| `TextWidth` | `128` | up to full screen width |
| `Textheight` | `16` | use `64` for the large fonts (256, 260) |
| `speed` | `50` | ms per scroll step, only relevant if text overflows `TextWidth` |
| `update_time` | `10` | seconds between the device's own polls |
| `items` | — | full manual control instead of `sensors:` — see §3b below; takes priority over `sensors`/`entity_id` if both are set |
| `background_gif` | a solid black 128×128 gif | background shown behind all rows; **must be `.gif`** — `.jpg`/`.png` are accepted (`error_code 0`) but fail to render, see `docs/API.md` §4.10 |

> ⚠️ **`name` with a space** ✅ (confirmed on device): the Times Gate's own
> outbound poll GET does not reliably handle a percent-encoded space (`%20`)
> in the query string — a `name` containing a space broke the device's polling.
> Handled automatically: spaces in `name` are swapped for underscores before
> being placed in the poll URL, and swapped back to spaces by the DispData view
> before display, so `name: "Grid pwr"` still shows as `Grid pwr: 340W` on the
> panel. You don't need to avoid spaces yourself — this is just documented in
> case you're inspecting the raw poll URL and wonder why it has underscores.

## 3b. Full manual layout with `items:`

`sensors:` always renders one combined `"<name>: <value>"` row per sensor, in
one colour, auto-stacked vertically. If you want the label and the value in
**different colours**, side by side, or in a completely custom layout, use
`items:` instead — this mirrors how you'd hand-write a raw
`Draw/SendHttpItemList` call (`docs/API.md` §4.10): every piece is its own
item with its own position/colour/font, and you decide the layout.

```yaml
- page_type: dispdata_text
  items:
    - kind: label            # static text, never polled
      text: "Grid pwr"
      x: 0
      y: 40
      font: 4
      color: "#FFFF00"
    - kind: value             # polls entity_id via DispData
      entity_id: sensor.energyhome_electrical_power_from_grid
      x: 0
      y: 56                   # placed below the label instead of beside it
      font: 32
      color: "#00CCFF"
      update_time: 10
```

Each entry:

| Field | Applies to | Notes |
|---|---|---|
| `kind` | — | `"label"`, `"value"`, or a native kind (table below); inferred as `"value"` from `entity_id` being present, else `"label"`, if omitted |
| `text` | `label` | required; static string, not templated |
| `entity_id` | `value` | required |
| `label` | `value` | optional — prefixes just this item's own value with `"<label>: "`, same space→underscore handling as `sensors:`. Usually left unset since the label is its own separate item. |
| `update_time` | `value` | default `10` (or page-level default) |
| `x` / `y` / `font` / `color` / `align` / `TextWidth` / `Textheight` / `speed` | all | per-item, falling back to the page-level default, then a built-in default (same as `sensors:`) |

Up to **8 items** total (`_DISPDATA_MAX_ITEMS`), any mix of `label`/`value`/native.
`items:` takes priority over `sensors:`/`entity_id` if both are present on the
same page — pick one style per page.

### Native device elements (clock, date, weather — zero polling)

Besides `label`/`value`, `kind` also accepts any of the device's **built-in**
elements — the panel renders these entirely on its own, no HA involvement at
all after the one-time setup call (not even a poll, unlike `value`):

| `kind` | Device element | | `kind` | Device element |
|---|---|---|---|---|
| `second` | seconds | | `weekday_2` | 2-letter weekday (`SU`) |
| `minute` | minutes | | `weekday_3` | 3-letter weekday (`SUN`) |
| `hour` | hours | | `weekday_full` | full weekday (`SUNDAY`) |
| `ampm` | AM/PM marker | | `month_3` | 3-letter month (`JAN`) |
| `time_short` | clock, `hh:mm` | | `temperature` | current temperature |
| `time` (alias `clock`) | clock, `hh:mm:ss` | | `temp_max` | today's max temperature |
| `year` | year | | `temp_min` | today's min temperature |
| `day` | day of month | | `weather` | weather word (e.g. `Sunny`) |
| `month` | month | | `noise` | ambient noise (dB) |
| `mon_year` | month-year | | `month_day` | `eng-month.day` |

A 12-hour clock is two adjacent items — `time_short` alone shows no AM/PM
marker, so pair it with `ampm` positioned right after it:

```yaml
- page_type: dispdata_text
  items:
    - kind: time_short   # "hh:mm"
      x: 0
      TextWidth: 90
      color: "#FFFFFF"
    - kind: ampm          # "AM"/"PM"
      x: 90
      TextWidth: 38
      color: "#AAAAAA"
```

For a 24-hour clock, `time` (`hh:mm:ss`) or `time_short` (`hh:mm`) alone is
enough — no `ampm` item needed. Temperature/weather kinds reflect the
location configured on the device itself (`Sys/LogAndLat`), not an HA
weather entity — if you want an HA-side weather sensor's value instead, use
`kind: value` with that entity's `entity_id`.

## 3c. Two rendering systems — `components` vs. `dispdata_text`, which to use

This integration ships **two independent ways** to put content on a screen,
and picking the right one for each page matters:

| | `page_type: components` | `page_type: dispdata_text` |
|---|---|---|
| Who renders? | **HA** — Pillow draws a JPEG locally | **The device itself** — native rendering |
| Format origin | Ported from `gickowtf/pixoo-homeassistant` (Pixoo `components` schema) | This integration's own layer over Divoom's `Draw/SendHttpItemList` |
| Update mechanism | HA pushes a new JPEG whenever the rendered content changes | Device polls itself (`kind: value`) or self-updates natively (`kind: time`/`weather`/…); HA pushes once at setup |
| Network traffic | One push per screen per change (batched with other changed screens into one `Draw/CommandList`, see §3) | Zero after setup, except when the page's *config* changes |
| Colour can react live to the value? | **Yes** — full Jinja templating, e.g. red/orange/green by threshold | **No** — colour is fixed at setup time; the device only re-fetches the *text*, not styling |
| Content types | `text` (Jinja templated), `image` (icons/photos), `rectangle` (bars/borders), `templatable` (dynamic component lists) | `label` (static text), `value` (polled entity), native `kind:` (clock/date/weather) |
| Best for | Dashboards with icons, progress bars, conditional colours, anything visual/composed | Simple always-on text/number readouts you want to be maintenance-free and low-traffic |

**Rule of thumb:** if a page needs an icon, a bar, or a colour that changes
with the value, use `components`. If it's plain text/numbers that don't need
conditional colour, prefer `dispdata_text` — it's lighter on the network and
self-heals less often needs re-pushing. Nothing stops you from mixing page
types across different screens, or rotating between a `components` page and a
`dispdata_text` page on the *same* screen — just avoid mixing `dispdata_text`
with `gif`/`visualizer` pages in the same rotation (§6).

## 4. Network requirements — same LAN, VLANs, and firewalls

The Times Gate must be able to reach HA's HTTP port (default `8123`) directly
over the network — it is not routed through Nabu Casa / cloud, and it does
**not** go through HA's authentication proxy. Practical implications:

- **Same flat LAN (default):** works with no extra config — just make sure
  `http.server_port` / `http.local_only` in HA's `configuration.yaml` isn't
  blocking LAN clients, and that no reverse proxy in front of HA insists on
  auth for all paths (this view sets `requires_auth = False`, but a proxy
  layer like nginx or an Ingress add-on may still enforce its own auth ahead
  of HA — allowlist this URL path there if so).
- **IoT VLAN, isolated from the HA VLAN:** by design a segmented IoT VLAN
  usually **cannot** reach other VLANs (that's the point of the segmentation).
  You need an explicit firewall rule allowing the Times Gate's IP (or its
  whole VLAN) to reach HA's IP on TCP 8123 — nothing else. This is a narrower
  hole than giving the IoT VLAN general LAN access, and is the recommended way
  to keep using DispData if your devices are normally isolated:
  1. Give the Times Gate a static IP/DHCP reservation (needed anyway for the
     `LocalToken`/`ip_address` config of this integration).
  2. Add a firewall rule: `<TimesGate IP>` → `<HA IP>:8123`, protocol TCP,
     allow. No return-path rule is needed beyond stateful established/related.
  3. Leave all other IoT↔HA-VLAN traffic blocked as before.
- **HA behind HTTPS/reverse proxy only:** if HA is only reachable over HTTPS
  with a proxy that terminates TLS, the device (an embedded HTTP client) may
  not support the proxy's TLS setup. Simplest fix: also expose HA's plain
  `http://<lan-ip>:8123` on the LAN (not internet-facing) for this one path,
  or run the poll through a lightweight local reverse-proxy rule that forwards
  just `/api/divoom_times_gate/dispdata/*` in plain HTTP to HA.

## 5. Rotating / revoking the secret

The secret is stored in the config entry's data and currently has no UI
control to regenerate it. To rotate it: remove and re-add the integration
(a fresh secret is generated on first setup), or manually clear
`dispdata_secret` from the config entry's stored data before reload. A
"regenerate secret" button is a reasonable future addition if this becomes a
concern (e.g. after accidentally sharing a URL).

## 6. Mixing `dispdata_text` with `gif` / `visualizer` in the same rotation

Confirmed on a real device: rotating a screen between `dispdata_text` and
native `gif` or `visualizer` pages was observed to leave the panel stuck on a
"Loading" screen. Both `gif` (`Device/PlayGif`) and `visualizer`
(`Channel/SetEqPosition`) switch the panel into a different native rendering
mode than the `Draw/SendHttpItemList` overlay `dispdata_text` depends on;
switching back doesn't reliably restore the item-list state. **Until this is
root-caused, avoid combining `dispdata_text` with `gif`/`visualizer` pages in
the same screen's rotation** — a screen dedicated solely to `dispdata_text`
(optionally rotating with `components`/`clock`/`off` pages) has been confirmed
stable. See BACKLOG.md for the open investigation.

## 7. Recovering a stuck panel — HA has no read-back

Once the one-time `Draw/SendHttpItemList` setup call succeeds, HA considers
the page "done" and stops sending anything for it — by design, that's the
whole point of DispData. The trade-off: **HA cannot detect if the panel
itself later stops updating** (a device reboot, a background-gif fetch
hiccup, a momentary network drop on the device's side, …), because nothing
about the *page config* changed, only the device's live state — and HA only
re-sends when the config's signature changes.

- **Manual recovery:** press the **"Refresh screens"** button (or call the
  `divoom_times_gate.refresh` service). This clears every screen's
  change-tracking signature and forces a full repaint next tick, including a
  fresh `NewFlag: 1` setup call for any `dispdata_text` page — same fix as for
  a stuck JPEG page.
- **Automatic recovery:** this integration intentionally does **not**
  periodically re-send DispData setups on its own (that would undercut the
  "zero push" design). If you want a safety net, build a small HA automation
  instead — e.g. call the refresh button/service every N hours, or trigger it
  off a template condition (like a `binary_sensor` you maintain that flags
  "this screen looks stale"). Keeping this outside the integration means you
  control the trade-off between resilience and push frequency yourself,
  instead of the integration forcing one default on everyone.

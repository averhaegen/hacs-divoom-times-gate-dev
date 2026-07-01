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
3. A `dispdata_text` page currently uses one `Draw/SendHttpItemList` call per
   screen (not yet batched into a single `Draw/CommandList` across screens —
   see BACKLOG.md).

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
| `background_gif` | a solid black 128×128 gif | background shown behind all rows; **must be `.gif`** — `.jpg`/`.png` are accepted (`error_code 0`) but fail to render, see `docs/API.md` §4.10 |

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

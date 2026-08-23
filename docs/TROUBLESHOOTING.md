# Troubleshooting

Find your symptom below. Each entry gives the cause, the check, and the fix.
Error strings and log lines are reproduced exactly as the device or Home
Assistant emits them.

To see the integration's own logs, add this to `configuration.yaml` and restart
Home Assistant:

```yaml
logger:
  default: warning
  logs:
    custom_components.divoom_times_gate: debug
```

To attach data to a bug report, open **Settings > Devices & services > Divoom
Times Gate**, open the three-dot menu, and choose **Download diagnostics**. The
LocalToken, the DispData secret, and the MAC address are redacted for you.

## Setup finds no devices

**Symptom.** The device dropdown in the config flow is empty.

**Cause.** Discovery is a cloud call. The integration posts to
`https://app.divoom-gz.com/Device/ReturnSameLANDevice`, and Divoom returns the
devices that share your public IP address. It fails if Home Assistant has no
internet access, if Home Assistant and the Times Gate leave your network through
different public IP addresses (a VPN on the Home Assistant host does this), or if
the device has never been online since you set it up in the phone app.

**Fix.** Type the device's IP address into the same field by hand. Find it in the
Divoom app under device settings, or in your router's client list. Discovery is a
convenience only. Everything after setup is local.

## Setup rejects the device

**Symptom.** The config flow shows:

```
Could not reach the device, or the LocalToken was rejected. Check the IP and token.
```

**Causes, in the order worth checking.**

1. The LocalToken is wrong. Read it again from the Divoom app under device
   settings. It is an integer, and the integration sends it in the request body.
   A wrong or missing token makes the device answer every command with
   `{"error_code": "DeviceToken is err"}`.
2. The IP address is wrong or stale.
3. Home Assistant cannot reach the device on TCP port 80. If the Times Gate is on
   an IoT VLAN, add a firewall rule from the Home Assistant host to the device on
   port 80.

## All entities show as unavailable

**Symptom.** Every entity is unavailable, and the log contains a line like:

```
Times Gate at 192.168.1.50 became unavailable after 3 consecutive failures
```

**Cause.** Three polls in a row failed to reach the device. The coordinator marks
the device unavailable at that point rather than after the first blip.

**Checks.**

- Ping the device from the Home Assistant host.
- Look for the underlying transport error, logged one line per failure as
  `Error communicating with Times Gate at 192.168.1.50: <error>`.
- Confirm the device is powered and joined to Wi-Fi. A Times Gate that has
  dropped off Wi-Fi still lights up and still runs its clock.

**Fix.** Restore network reachability. The coordinator retries on every tick and
logs `Times Gate at 192.168.1.50 recovered` when a poll succeeds again. You do not
need to reload the integration.

## The device changed IP address

You do not have to do anything. After 3 consecutive failures, and at most once
every 5 minutes, the coordinator re-runs LAN discovery, matches the device on MAC
address first and on DeviceId second, writes the new address into the config
entry, and reloads. The log line is:

```
Times Gate moved from 192.168.1.50 to 192.168.1.77 — updating the config entry and reloading
```

Self-healing needs the cloud discovery call to succeed, so it does not work while
Home Assistant is offline. If it does not recover, open the integration's
three-dot menu and choose **Reconfigure** to set the address by hand. A static
DHCP lease avoids the problem.

If discovery finds a device at the new address whose MAC does not match, the
integration refuses to adopt it and tells you:

```
The device at this IP is a different Times Gate (MAC mismatch). Add it as a new device instead.
```

## You changed the LocalToken in the app

Version 0.2.2 has no reauthentication flow. Delete the config entry and add the
integration again with the new token. Your screen configuration is stored in the
config entry, so write it down first or copy it out of
`.storage/core.config_entries` before deleting.

A reauthentication flow is tracked in
[issue #6, reauthentication flow for a changed LocalToken](https://github.com/averhaegen/hacs-divoom-times-gate-dev/issues/6).
If your version prompts you to re-enter the token, that flow has landed. Follow
the prompt instead.

## A screen is stuck on "Loading"

**Symptom.** One screen shows the device's own `Loading` text and never paints.

**Cause 1, the known bug.** That screen rotates a `dispdata_text` page together
with a `gif` or `visualizer` page. Both of those switch the panel into a native
rendering mode that does not hand the item-list state back. Tracked as
[issue #9, dispdata_text plus gif or visualizer leaves the panel on "Loading"](https://github.com/averhaegen/hacs-divoom-times-gate-dev/issues/9).

**Fix.** Move the `gif` or `visualizer` page to a different screen, or drop it
from that rotation. Rotating `dispdata_text` with `components`, `clock`, or `off`
pages is stable. See
[docs/DISPDATA.md section 6](DISPDATA.md#6-mixing-dispdata_text-with-gif--visualizer-in-the-same-rotation).

**Cause 2.** The device was sent raw RGB pixel data, or a `PicID` larger than it
accepts. This should not happen through the integration, which always sends
base64 JPEG and manages `PicID` itself. If you see it after using the local API by
hand, that is the cause.

**Recovery in both cases.** Press the **Refresh screens** button entity. It clears
every screen's change-tracking signature and forces a full repaint, including a
fresh setup call for any `dispdata_text` page. Reloading the integration has the
same effect.

## A `dispdata_text` page shows a placeholder and never updates

The value on that page is fetched by **the device**, not by Home Assistant. Home
Assistant sends the background and the layout once, then the device polls
`http://<home-assistant-ip>:8123/api/divoom_times_gate/dispdata/<secret>/<entity_id>`
on its own every few seconds. If the device cannot reach that URL, the page
renders but the value never arrives.

Check, in this order:

1. **Direct reachability.** The device must reach the Home Assistant host's port
   8123 on the local network. A Nabu Casa or other external URL does not work,
   because the device is given the local address.
2. **VLAN and firewall.** Allow `<Times Gate IP>` to `<Home Assistant IP>:8123`
   over TCP. This is the most common cause on segmented networks.
3. **Reverse proxy.** If a proxy in front of Home Assistant enforces
   authentication, allowlist the path `/api/divoom_times_gate/dispdata/`. The
   endpoint carries its own secret in the URL and cannot send a bearer token.
4. **HTTPS-only setups.** The device is an embedded HTTP client. A setup that
   redirects or rejects plain HTTP may not work at all.
5. **The entity ID.** Test the URL from a browser on the same network. A working
   endpoint returns `{"DispData": "21.4"}`. A missing entity returns the string
   `unavailable` in the same shape.

The full network notes are in
[docs/DISPDATA.md section 4](DISPDATA.md#4-network-requirements--same-lan-vlans-and-firewalls).

## Text is cut off, or does not scroll

Labels do not scroll on the test device, whatever `dir`, `speed`, or `font` you
set. Long text is truncated. Shorten the label, or move the value to its own
line. See [docs/LIMITATIONS.md, text rendering limits](LIMITATIONS.md#text-rendering-limits).

## A background image does not render

The device accepts a `.jpg` or `.png` background with `error_code 0` and then
shows nothing. Backgrounds for `dispdata_text` pages must be GIF files. Convert
the file and point the page at the `.gif`.

## The preview image does not match the screen

The **Screen N preview** entities show the last frame Home Assistant rendered and
sent. They are not screenshots. The local API offers no way to read pixels back
from the device, so a face you set from the phone app never appears in the
preview. See [docs/LIMITATIONS.md, Home Assistant cannot read back what a screen
shows](LIMITATIONS.md#home-assistant-cannot-read-back-what-a-screen-shows).

## Home Assistant overwrites the face you set in the app

Set the **Display source** select to an `Overall Display: <name>` or
`Independent Display: <name>` option to hand the whole device back to its own
faces, or set the per-screen **Screen N** select to a `Face: <name>` option for
the screens you want left alone. The coordinator pushes pixels only to screens
whose mode is `Custom`.

## The device rejects one command but keeps working

Look for a warning in this form:

```
Times Gate 192.168.1.50 rejected Draw/SendHttpItemList: Request data illegal json
```

The device names the command it refused and its own error string. Match the error
against the table in [docs/API.md section 7, errors and gotchas](API.md#7-errors--gotchas-summary),
which records what each string has meant in testing.

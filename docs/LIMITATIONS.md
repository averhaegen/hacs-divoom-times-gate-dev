# Known limitations

What this integration cannot do, and why. Every item here is a closed
investigation, not a gap waiting for a patch. Where a limitation comes from the
device rather than the integration, this page says so.

Evidence follows the convention in [docs/API.md](API.md): a fact is either
**verified on device**, **documented only** (Divoom's docs claim it, nobody
confirmed it here), or **unverified**.

## Hardware coverage

The maintainer owns one Times Gate, hardware revision **400**, and everything
here was reverse-engineered against that single unit on whatever firmware it was
running at the time. Read "works" as "works on this unit".

`device.py` also routes hardware revision **402** to `http://<ip>:9000/divoom_api`
instead of `http://<ip>/post`, following Divoom's official documentation. Nobody
has run this integration against a revision 402 device. Treat revision 402
support as **unverified**.

## No Divoom cloud account features

The integration never signs in to your Divoom account, so it cannot check or
trigger firmware updates, read your app watchlists, or author faces in the cloud.
This is a hard limit, not a missing feature:

- Divoom's `UserLogin` grants **one valid token per account at a time**. A login
  from Home Assistant immediately invalidates the token your phone app holds. A
  live test kicked the phone app with the message
  `Information mismatch, please login again`.
- There is no refresh-token mechanism to work around it. Fourteen candidate
  endpoint names were probed against `appin.divoom-gz.com` with a valid live
  token. Every one returned the routing-404 body
  `{"ReturnCode":10,"ReturnMessage":"Command is not match","Name":"IndexDefaultMethod"}`,
  which means the routes do not exist.
- Guest login (`User/NewGuest`) also returns that routing-404 body, so that
  endpoint is gone too.

One lead is open and **unverified**: Divoom's buddy / share-code system might let
a throwaway account hold its own token. Nobody has tested it, and the share-code
wording suggests push-only access, which is not the read access this would need.

The cloud calls the integration *does* make are unauthenticated and read-only:
LAN discovery at setup, and face and preset lists when building option lists.

## No sensor entities for device state

The integration exposes controls, not sensors, because the device does not offer
useful readings over the local HTTP API:

- `Device/GetDeviceTemp` returns `Request data illegal json`. Internal
  temperature is a Bluetooth-only command.
- `Device/GetWeatherInfo` works, but returns **cloud weather for the location
  configured in the Divoom app**, not anything the device measures. Your own
  weather integration is a better source, so this is deliberately not exposed.
- `Channel/GetAllConf` returns settings, which are already exposed as light,
  switch, and select entities.

## Home Assistant cannot read back what a screen shows

Nothing in the local API reports the pixels currently on a screen. Two
consequences:

- The **Screen N preview** image entities show what Home Assistant last rendered
  and sent, not a device screenshot. If you change a face from the phone app, the
  preview does not follow.
- The cloud call `Channel/Get5LcdInfoV2` reports faces set **from the app only**.
  It does not see faces the integration set over the local API, so the
  integration treats it as a hint when building option lists, never as truth.

`Device/GetScreenSnapshot` was probed on hardware 400 and is unknown on port 80
`/post`, so there is no screenshot source either.

## Text rendering limits

- **Labels do not scroll.** Type-22 items stay static on the test unit whatever
  you set for `dir`, `speed`, or `font`. Long labels are truncated. Keep
  `dispdata_text` labels short.
- **`Draw/SendHttpText` does not work.** It returns `illegal json` on the Times
  Gate. The integration uses `Draw/SendHttpItemList` instead, which needs
  `LcdIndex`, `NewFlag: 1`, and a `BackgroudGif` background URL. That field name
  is misspelled in the device API; it is not a typo in these docs.
- **A `dispdata_text` `name` must not contain a space.** The device's own
  outbound poll does not reliably handle `%20` in a query string. The integration
  swaps spaces for underscores in the URL and swaps them back for display, so
  this is handled for you, but it is why underscores show up in device logs.
- **Background images must be GIF.** A `.jpg` or `.png` background is accepted
  with `error_code 0` and then fails to render.

## Rendering resolution

`components` pages always render on a 64x64 canvas and are then upscaled to
128x128 with nearest-neighbour. A native 128 mode was removed on purpose
(issue #11, merged in pull request #14) so that a Pixoo page config pasted into a
screen stays pixel-identical, only doubled. If you want fine detail at 128x128,
use `page_type: image` or a `card` page, whose background is rendered at full
resolution.

Animated GIFs on `page_type: image` are capped at **40 frames**, which is the
device limit for `Draw/SendHttpGif` animations. Longer animations are truncated.

## Rotating `dispdata_text` with `gif` or `visualizer` breaks the screen

Confirmed on device and tracked as
[issue #9, dispdata_text plus gif or visualizer leaves the panel on "Loading"](https://github.com/averhaegen/hacs-divoom-times-gate-dev/issues/9).
Both `gif` (`Device/PlayGif`) and `visualizer` (`Channel/SetEqPosition`) switch
the panel into a native rendering mode that does not restore the item-list state
when the rotation comes back around.

Workaround: do not put `dispdata_text` in the same screen's rotation as `gif` or
`visualizer`. Rotating `dispdata_text` with `components`, `clock`, or `off` pages
is stable. See [docs/DISPDATA.md section 6](DISPDATA.md#6-mixing-dispdata_text-with-gif--visualizer-in-the-same-rotation).

## The DispData endpoint is not protected by Home Assistant auth

The device cannot attach a bearer token, so the endpoint the device polls sets
`requires_auth = False` and is gated by a random per-entry secret in the URL
path. There is no per-entity allowlist and no enumeration endpoint, so anyone
holding that URL can read the state of any `entity_id` they can name. Treat the
secret as a read-capability password and do not post the URL publicly.

There is no button to rotate the secret yet. To change it, remove and re-add the
integration. See [docs/DISPDATA.md section 5, rotating and revoking the secret](DISPDATA.md#5-rotating--revoking-the-secret).

## A changed LocalToken needs the integration re-added

As of version 0.2.2 there is no reauthentication flow. If you change the
LocalToken in the Divoom app, delete the config entry and add the integration
again with the new token. A reauthentication flow is tracked in
[issue #6, reauthentication flow for a changed LocalToken](https://github.com/averhaegen/hacs-divoom-times-gate-dev/issues/6).
If your version prompts you to re-enter the token instead, that flow has landed
and you can follow the prompt.

## Shipped but not yet tested on hardware

Two `dispdata_text` features work in code review and have never been confirmed on
a device. Treat them as **unverified**:

- the `items:` key, which replaces `sensors:` with full manual per-item layout,
- the native device kinds under `items:` (clock, date, weather elements) that the
  device renders with no Home Assistant involvement after setup.

## Faces you built in the app cannot be copied into Home Assistant

`Channel/Get5LcdInfoV2` resolves each screen only to a `ClockImagePixelId`, a CDN
path to a pre-rendered face in Divoom's compressed pixel format. The text you
typed in the app cannot be read back. Rebuild the layout as a `card` or
`components` page instead.

# Divoom Times Gate — Local HTTP API Reference

> An unofficial, cleaned-up reference for the **Divoom Times Gate** (5 × 128×128 LCD)
> local HTTP API. Divoom's own docs ([ShowDoc, "TimeGate" section](https://docin.divoom-gz.com/web/#/5))
> mix in generic Pixoo pages, omit device-specific fields (e.g. `LcdArray`), and
> contain contradictions. This document keeps the **same ordering as the official
> docs** but describes each command more clearly and records what we have **verified
> against a real device** vs. what is documented-but-unconfirmed.
>
> **Legend:** ✅ verified on device / in our integration · 📄 documented only · ❓ open question / contradicts docs
>
> Secrets (LocalToken, DeviceId, IP) are shown as placeholders — substitute your own.

---

## 0. General

### 0.1 Transport & command format

Everything is **RPC-over-HTTP**: a single endpoint, `POST` only, with a `Command`
field in the JSON body selecting the operation. There are no REST paths.

| Hardware | Local endpoint |
|----------|----------------|
| HW **400** (our device) ✅ | `POST http://<device-ip>:80/post` |
| HW **402** | `POST http://<device-ip>:9000/divoom_api` |

Body is JSON; response is JSON with `error_code` (`0` = success). Some commands are
**cloud** endpoints on `app.divoom-gz.com` — those return `ReturnCode` instead and
use `DeviceId`, not `LocalToken`.

> ⚠️ **Doc contradiction** ✅: the official "command format" page shows a field named
> `DeviceToken`. On a real Times Gate that name is **rejected** — the local API
> requires **`LocalToken`** (see §0.2).

### 0.2 `LocalToken` — required on every local call ✅

Every request to the **local** API must include an integer `LocalToken` in the body.
Without it, even read-only commands return `{"error_code": "DeviceToken is err"}`.

- Shown in the Divoom phone app (device settings).
- Must be an **integer** in the **body** — not a header, query param, or string, and
  not under the names `DeviceToken` / `Token` / `DeviceId`.

```json
{ "Command": "Channel/GetAllConf", "LocalToken": <LocalToken> }
```

### 0.3 The 5 screens: `LcdArray` vs `LcdIndex` ✅

The Times Gate has **5 independent LCDs**, indexed **0–4**. Two selection styles
appear depending on the command:

- **`LcdArray`** — length-5 mask, e.g. `[1,0,0,0,0]` = screen 0 only (`1`=draw, `0`=skip).
  Used by the *drawing* commands (`SendHttpGif`, `PlayGif`, `SendRemote`); must be
  identical across all frames of one animation.
- **`LcdIndex`** — single integer 0–4. Used by *per-screen* commands (`SendHttpText`,
  per-screen face/visualizer selection, gallery time).

### 0.4 `Device/ReturnSameLANDevice` — discover devices (CLOUD) ✅

Cloud call `POST https://app.divoom-gz.com/Device/ReturnSameLANDevice` (no body params)
returns every Divoom device on the caller's LAN. Used by our integration for
discovery / self-healing the `DeviceId` from an IP.

```json
// → { "ReturnCode": 0, "DeviceList": [
//      { "DeviceName": "...", "DeviceId": <DeviceId>, "DevicePrivateIP": "10.0.0.100", "DeviceMac": "..." } ] }
```

### 0.5 `Draw/UseHTTPCommandSource` / DIY Net Data Clock — self-updating from a URL 📄

Two documented mechanisms let the device **pull** data instead of being pushed to:

- **`Draw/UseHTTPCommandSource`** `{ CommandUrl }` — the device fetches a *command
  array* from your URL and runs it.
- **DIY Net Data Clock** — a face bound to `InputUrlAddress` (a JSON URL) plus
  `DataParsingRules` (a mini path syntax like `object1,object1-2,n:dispNumber;` to
  extract a number/string from the JSON). Renders self-updating data with no pushes.

See also the per-item **type 23** net-text in [§4.10](#410-drawsendhttpitemlist--rich-item-list-with-on-device-data-).

---

## 1. System setting

### 1.1 `Channel/SetBrightness` — LCD brightness ✅

```json
{ "Command": "Channel/SetBrightness", "LocalToken": <LocalToken>, "Brightness": 100 }
```
`Brightness` 0–100.

### 1.2 `Channel/GetAllConf` — read all settings ✅

Read-only dump of device configuration. Requires `LocalToken`. Returned fields include:

| Field | Meaning |
|-------|---------|
| `Brightness` | 0–100 system brightness |
| `RotationFlag` | 1 = auto-rotate between faces and gifs |
| `DateFormat` | date format |
| `Time24Flag` | 24-hour display flag |
| `TemperatureMode` | °C / °F flag |
| `MirrorFlag` | mirror mode |
| `LightSwitch` | screen on/off |

### 1.3 `Sys/LogAndLat` — set weather location 📄

```json
{ "Command": "Sys/LogAndLat", "LocalToken": <LocalToken>, "Longitude": "<lon>", "Latitude": "<lat>" }
```
Sets the coordinates used for on-device weather (feeds the weather text elements).

### 1.4 `Sys/TimeZone` — set time zone 📄

```json
{ "Command": "Sys/TimeZone", "LocalToken": <LocalToken>, "TimeZoneValue": "GMT+1" }
```

### 1.5 `Device/SetUTC` — set system time 📄

```json
{ "Command": "Device/SetUTC", "LocalToken": <LocalToken>, "Utc": <unix-utc-seconds> }
```

### 1.6 `Channel/OnOffScreen` — screen on/off ✅

```json
{ "Command": "Channel/OnOffScreen", "LocalToken": <LocalToken>, "OnOff": 1 }
```
`OnOff` `1`=on, `0`=off.

### 1.7 `Device/GetDeviceTime` — read device time 📄

```json
{ "Command": "Device/GetDeviceTime", "LocalToken": <LocalToken> }
```

### 1.8 `Device/SetDisTempMode` — temperature unit 📄

Sets °C / °F display mode.

### 1.9 `Device/SetMirrorMode` — mirror mode 📄

Toggles horizontal mirroring of the display.

### 1.10 `Device/SetTime24Flag` — 12/24-hour mode 📄

Sets whether the clock elements show 24-hour time.

### 1.11 `Device/GetWeatherInfo` — read on-device weather 📄

Returns the weather the device currently holds (used by the weather text elements).

### 1.12 `Channel/SetSubscribeGalleryTime` — gallery dwell time 📄

```json
{ "Command": "Channel/SetSubscribeGalleryTime", "LocalToken": <LocalToken>,
  "SingleGalleyTime": <seconds>, "LcdIndependence": <independence-id>, "LcdIndex": 0 }
```
How long each item of a subscribed gallery shows, per screen.

### 1.13 `Channel/SetRGBInfo` — ambient RGB lighting ✅

Controls the two ambient light zones (reverse-engineered live).
**Full effect catalog with icons and per-scenario ID tables: see [`docs/RGB_LIGHTS.md`](RGB_LIGHTS.md).**

```json
{ "Command": "Channel/SetRGBInfo", "LocalToken": <LocalToken>,
  "SelectLightIndex": 2, "Brightness": 100, "OnOff": 1,
  "LightList": [ { "SelectEffect": 0 }, { "SelectEffect": 0 }, { "SelectEffect": 5, "Color": "#00FF00", "ColorCycle": 0 } ] }
```

- `SelectLightIndex` — `0` = both / `1` = **Edgelight** (surround strips) / `2` = **Backlight** (behind screens). The two zones are independent.
- `LightList` — array of 3 items; which index controls which zone **shifts depending on `SelectLightIndex`** — see `RGB_LIGHTS.md` §2 for the full mapping.
- `SelectEffect` — effect ID; mapping differs between Edgelight and Backlight (separate ID tables in `RGB_LIGHTS.md`).
- `Color` — `#RRGGBB`; only applied on effects with customizable colour (❌ effects ignore it).
- `ColorCycle` — `1` = auto colour cycle, `0` = fixed colour.
- `OnOff` — `1`=on, `0`=off ✅ (the docs state the opposite — **wrong**).
- `Brightness` — 0–100. `KeyOnOff` — button backlight on/off.

**Backlight "Solid" colour:** `SelectLightIndex: 2`, `LightList[2].SelectEffect: 5`, `ColorCycle: 0`, `Color: "#RRGGBB"`.
**Backlight "Rainbow":** same but `SelectEffect: 4`, `ColorCycle: 1`.

---

## 2. Dial control (faces / channels)

The device shows either **one whole-device face** spanning all 5 screens, or an
**independence group** ("Control preset") of 5 per-screen faces. Custom drawing
(§4) overlays whatever face is active.

**App ↔ API terminology** (important — the app UI and the API use different names):

| App UI term | API concept | Commands | Catalog |
|-------------|-------------|----------|---------|
| **Overall Display** | whole dial — one face across all 5 screens | `Set5LcdWholeClockId` | `Get5LcdClockListForCommon` (§2.3) |
| **Independent Display** | individual dial / visualizer — per-screen faces in a Control preset | `SetClockSelectId`, `SetEqPosition` | `GetDialType` + `GetDialList` (§2.1–2.2) |

Face catalogs are **cloud** reads; selection is **local**. Note the two catalogs are
**disjoint sources**: Overall-Display faces (mostly data widgets — crypto/stock/RSS/
YouTube/city-time) come only from `Get5LcdClockListForCommon`; per-screen faces come
only from `GetDialType`/`GetDialList`. Keep them in **separate catalog documents**.

### 2.1 `Channel/GetDialType` — face categories (CLOUD) 📄

`POST https://app.divoom-gz.com/Channel/GetDialType` → `DialTypeList` (e.g. `Social`,
`normal`, `financial`, `Game`, `HOLIDAYS`, `TOOLS`, `DESIGN-64`). Feeds §2.2.

### 2.2 `Channel/GetDialList` — per-category face list (CLOUD) 📄

```json
{ "DialType": "normal", "DeviceType": "LCD", "Page": 1 }   // 30 per page
```
Returns the individual (per-screen) faces for a category, with their `ClockId`s.

### 2.3 `Channel/Get5LcdClockListForCommon` — whole-device face list (CLOUD) 📄

```json
{ "DeviceId": <DeviceId>, "Page": 1 }   // 30 per page
```
Returns the whole-device spanning faces (~45 named faces).

### 2.4 `Channel/Set5LcdWholeClockId` — select a whole-device face ✅

```json
{ "Command": "Channel/Set5LcdWholeClockId", "LocalToken": <LocalToken>, "ClockId": <face-id> }
```
`ClockId` from §2.3. (Example seen: "Neon" = 1040.) All 5 LCDs switch to the faces channel.

### 2.5 `Channel/Set5LcdChannelType` — whole vs. per-screen ✅

```json
{ "Command": "Channel/Set5LcdChannelType", "LocalToken": <LocalToken>,
  "ChannelType": 1, "LcdIndependence": <independence-id> }
```
- `ChannelType` — `0` whole dial (one spanning face); `1` independence dial (per-screen
  faces from a Control preset).
- `LcdIndependence` — the preset id (from §2.6's `LcdIndependence`); active when `ChannelType=1`.

### 2.6 `Channel/Get5LcdInfoV2` — read channel state (CLOUD) 📄✅

`POST http://app.divoom-gz.com/Channel/Get5LcdInfoV2`

```json
{ "DeviceId": <DeviceId>, "DeviceType": "LCD" }
```
Returns `ChannelType`, whole-face `ClockId`, and `LcdIndependenceList[]` with per-preset
`IndependenceName` / `LcdIndependence` / `LcdList[].LcdClockId` (per-screen face ids).

> ❓ **Critical caveat** ✅: this cloud read reflects **only app-driven** changes,
> **not** local-API writes. A face set via the local API (§2.4/2.7/2.8) does **not**
> update this response. Any "current face" sensor built on it is a soft hint (last app
> state), not ground truth.

### 2.7 `Channel/SetClockSelectId` — set one screen's face ✅

Writes a face into a specific screen of a specific Control preset.

```json
{ "Command": "Channel/SetClockSelectId", "LocalToken": <LocalToken>,
  "ClockId": <face-id>, "LcdIndex": 0, "LcdIndependence": <independence-id> }
```
- `ClockId` from §2.2; `0` blanks that screen.
- `LcdIndex` 0–4. `LcdIndependence` from §2.6.
- Proper sequence: `Set5LcdChannelType {ChannelType:1, LcdIndependence}` first, then one
  `SetClockSelectId` per `LcdIndex`.

### 2.8 `Channel/SetEqPosition` — per-screen visualizer ✅

```json
{ "Command": "Channel/SetEqPosition", "LocalToken": <LocalToken>,
  "EqPosition": 0, "LcdIndex": 0, "LcdIndependence": <independence-id> }
```
`EqPosition` = visualizer index (from 0), for one screen of a preset.

### 2.9 `Channel/GetIndex` — per-screen channel type (LOCAL) ✅

Local read returning a per-screen array, e.g. `SelectIndex: [0,0,1,0,0]` where
`0`=Faces, `1`=Cloud, `2`=Visualizer, `3`=Custom. Our JPEG overlay does **not** change a
screen's channel (confirmed).

---

## 3. Tools

All require `LocalToken`. These drive the built-in tool faces.

| # | Command | Params | Notes |
|---|---------|--------|-------|
| 3.1 | `Tools/SetTimer` 📄 | `Minute`, `Second`, `Status` (1 start / 0 stop) | countdown |
| 3.2 | `Tools/SetStopWatch` 📄 | `Status` (2 reset / 1 start / 0 stop) | stopwatch |
| 3.3 | `Tools/SetScoreBoard` 📄 | `BlueScore`, `RedScore` (0–999) | scoreboard |
| 3.4 | `Tools/SetNoiseStatus` 📄 | `NoiseStatus` (1 start / 0 stop) | noise meter |
| 3.5 | `Device/PlayBuzzer` ✅ | `ActiveTimeInCycle`, `OffTimeInCycle`, `PlayTotalTime` (ms) | buzzer; firmware ≥ 90109 |

```json
{ "Command": "Device/PlayBuzzer", "LocalToken": <LocalToken>,
  "ActiveTimeInCycle": 500, "OffTimeInCycle": 500, "PlayTotalTime": 3000 }
```
> The buzzer doc page omits `LocalToken`, but the local API requires it — include it.

---

## 4. Animation function (custom content)

Everything here draws **custom** content and overlays the active face.

### 4.1 `Channel/GetImgLikeList` — "my like" image list (CLOUD) 📄

The user's liked images from the Divoom gallery (for use with `SendRemote`).

### 4.2 `Channel/GetImgUploadList` — uploaded image list (CLOUD) 📄

The user's uploaded images (`FileId`s for `SendRemote`).

### 4.3 `Draw/SendRemote` — play an uploaded Divoom gif ✅📄

```json
{ "Command": "Draw/SendRemote", "LocalToken": <LocalToken>,
  "FileId": "<FileId>", "LcdArray": [1,0,0,0,0] }
```
Plays a gallery/uploaded gif (by `FileId`) on the selected screens.

### 4.4 `Device/PlayGif` — play a hosted GIF ✅

```json
{ "Command": "Device/PlayGif", "LocalToken": <LocalToken>,
  "LcdArray": [1,0,0,0,0], "FileName": "http://.../64_64.gif" }
```
`FileName` = network file address (max 10 files).

### 4.5 `Device/PlayGifLCDs` — one GIF per screen 📄

```json
{ "Command": "Device/PlayGifLCDs", "LocalToken": <LocalToken>,
  "LCD0GifFile": "http://.../a.gif", "LCD1GifFile": "...", "LCD2GifFile": "...",
  "LCD3GifFile": "...", "LCD4GifFile": "..." }
```
Assigns a separate hosted GIF to each of the 5 screens in one call.

### 4.6 `Draw/SendHttpGif` — push an image/animation ✅ ⭐

Sends a base64 image (or multi-frame animation) as the background of one or more
screens; the device loops it. **This is the core command our integration uses.**

| Field | Type | Notes |
|-------|------|-------|
| `Command` | string | `Draw/SendHttpGif` |
| `LocalToken` | int | required |
| `LcdArray` | int[5] | which screens, e.g. `[1,0,0,0,0]`; same for all frames |
| `PicNum` | int | number of frames, **< 60** |
| `PicWidth` | int | one of `16,32,64,128` — use **128** for Times Gate ✅ |
| `PicOffset` | int | frame index, `0 … PicNum-1` (one packet per frame) |
| `PicID` | int | animation id — **monotonically increasing**, starts at 1 ✅ |
| `PicSpeed` | int | frame duration in ms |
| `PicData` | string | base64 **JPEG** ✅ (see gotcha) |

**Gotcha — JPEG, not raw RGB** ✅: generic Pixoo docs say `PicData` is raw RGB. On
Times Gate that is **wrong** — raw RGB returns `error_code: 0` but leaves the screen
stuck on "loading". `PicData` must be a base64 **JPEG** (quality ~95).

**Gotcha — `PicID` monotonicity** ✅: the id must be strictly greater than the device's
current counter. Reusing/lowering an id → send silently ignored (`error_code 0`, no
change). Oversized ids (e.g. `int(time.time())`) → stuck "loading". Recipe: call
`Draw/ResetHttpGifId` **once** at startup, then a small incrementing counter (1, 2, 3, …)
shared across all screens.

```json
{
  "Command": "Draw/SendHttpGif", "LocalToken": <LocalToken>,
  "LcdArray": [1,0,0,0,0],
  "PicNum": 1, "PicWidth": 128, "PicOffset": 0,
  "PicID": 1, "PicSpeed": 1000, "PicData": "<base64-jpeg>"
}
```

**Related PicID helpers:**
- `Draw/ResetHttpGifId` ✅ — reset the counter so the next send starts at `PicID=1`.
  `{ "Command": "Draw/ResetHttpGifId", "LocalToken": <LocalToken> }`
- `Draw/GetHttpGifId` 📄 — read the next id to use (firmware ≥ 90095).
  Returns `{ "error_code": 0, "PicId": 100 }`.

### 4.7 `Draw/SendHttpText` — simple static text overlay ✅

One line of static text, per-screen. **Verified** path with explicit screen targeting.
Draws **on top of** the current animation and must run **after** a valid `SendHttpGif`
on that screen.

| Field | Type | Notes |
|-------|------|-------|
| `Command` | string | `Draw/SendHttpText` |
| `LocalToken` | int | required |
| `LcdIndex` | int | 0–4; **must equal the first active LCD in the preceding `SendHttpGif`'s `LcdArray`** ✅ |
| `TextId` | int | unique, **< 20**; reusing an id replaces that text |
| `x`, `y` | int | start position |
| `dir` | int | `0` scroll left, `1` scroll right |
| `font` | int | `0–7`, app-animation font |
| `TextWidth` | int | text area width, **> 16 and < 64** — values ≥ 64 return `"Request data illegal json"` ✅ |
| `TextString` | string | utf8, **< 512** chars |
| `speed` | int | scroll step time (ms) |
| `color` | string | `#RRGGBB` |
| `align` | int | `1` left, `3` middle, `5` right (firmware ≥ 90102); text scrolls automatically when longer than `TextWidth` ✅ |

Single line, fixed height 16pt, scrolls if it doesn't fit.

```json
{ "Command": "Draw/SendHttpText", "LocalToken": <LocalToken>,
  "LcdIndex": 0, "TextId": 4, "x": 0, "y": 40, "dir": 0, "font": 4,
  "TextWidth": 56, "speed": 10, "TextString": "hello, Divoom", "color": "#FFFF00", "align": 1 }
```

### 4.8 `Draw/ClearHttpText` — clear text overlays ✅

```json
{ "Command": "Draw/ClearHttpText", "LocalToken": <LocalToken>, "LcdId": 0, "TextId": 0 }
```
`TextId < 0` clears **all** text on that LCD.

### 4.9 `Device/GetTimeDialFontList` — font catalog (CLOUD) 📄

`POST https://app.divoom-gz.com/Device/GetTimeDialFontList` → `FontList[]` of
`{ id, name, width, high, charset, type }`. `type` `0` = scrolls when text overflows,
`1` = no scroll. The `id` is what you pass as `font` in `SendHttpItemList`.

**Verified working font IDs on Times Gate** ✅ (exhaustively tested, all even — odd IDs do not exist):

| Size class | Font IDs |
|------------|----------|
| Small (fits in `Textheight: 16`) | `2, 4, 18, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 80, 96, 108, 120, 124, 128, 140, 150, 158, 160, 162, 164, 174, 178, 180, 182, 184, 186, 188, 190, 194, 196, 198, 200, 246, 248, 250, 252, 254` |
| Large (needs `Textheight: 64`, see note) | `256` *(built-in yellow colour)*, `260` *(built-in white colour)* |

> ⚠️ **Large font gotcha** ✅: fonts 256 and 260 have a built-in colour — the `color`
> field is ignored. They also require more vertical space; use `y: 32, Textheight: 64`
> (full-screen height). Additionally they only render correctly when sent with **`NewFlag: 0`**
> *after* the screen has already been initialised with `NewFlag: 1`. Sending them directly
> with `NewFlag: 1` results in a black screen.
>
> Fonts 262+ were tested and did not render — likely not present on this firmware.

### 4.10 `Draw/SendHttpItemList` — rich item list with on-device data 📄❓

Sends a list of items that can render **device-native elements** (time, date,
temperature, weather, noise) or poll a URL — no per-refresh pushing for those. The
`type` field selects the element. Also runs **after** a `SendHttpGif`.

| Field | Type | Notes |
|-------|------|-------|
| `Command` | string | `Draw/SendHttpItemList` |
| `LocalToken` | int | required |
| `LcdIndex` | int | 0–4, target screen ✅ |
| `NewFlag` | int | `1` = overwrite all items + set new background; `0` = add/update individual items, background unchanged ✅ |
| `BackgroudGif` | string | URL to a `.gif` the device fetches as background — required with `NewFlag: 1`; omit with `NewFlag: 0` ✅. **Must be `.gif`** ✅ — a `.jpg`/`.png` URL returns `error_code 0` (accepted) but the panel gets stuck showing no background/loading; only tested with `.gif` did the background actually render. |
| `ItemList` | array | list of item objects (below) |

**Item object:** `TextId` (< 40), `type` (see table), `x`, `y`, `dir` (`0` scroll left,
`1` scroll right), `font` (id from §4.9; pick a `Type=0` font to allow scrolling),
`TextWidth` (up to **128** for full screen width ✅ — no upper limit like `SendHttpText`),
`Textheight`, `TextString` (< 512; display string **or** request URL; optional), `speed`
(ms per scroll step), `color` (`#RRGGBB`), `update_time` (URL poll interval seconds;
optional), `align` (see table below ✅ — Times Gate values match `SendHttpText`, NOT the Pixoo doc).

**`align` behaviour on Times Gate** ✅ (tested — differs from Pixoo doc values):

| align | Behaviour |
|-------|-----------|
| `1` | **left** within the text block |
| `3` | **centre** within the text block |
| `5` | **right** within the text block |

> ⚠️ The Pixoo doc (page 61) says `1`=left, `2`=middle, `3`=right — these values are
> **wrong** on Times Gate. Use `1`/`3`/`5` (odd numbers: left/centre/right).

**Scrolling** is triggered automatically when `TextString` is longer than `TextWidth`,
regardless of `align`. It is not controlled by `align` or `dir`.

`align` controls alignment **within the text block** (defined by `x` + `TextWidth`),
not across the full screen. To centre text on the full 128px screen: `x: 0`,
`TextWidth: 128`, `align: 3`.

> 💡 **Multi-colour scrolling trick** ✅: place two (or more) adjacent scroll blocks
> (`align: 0`) with the same `speed` and complementary `TextWidth` values that add up
> to 128. Give each block a different `color` and split the sentence across them so
> the text visually runs across the full screen in multiple colours. Because both blocks
> scroll at the same speed they stay in sync, and optically the sentence appears as one
> continuous line with colour changes mid-text. Blocks do not clip each other — they
> scroll through the same pixel area, so text length and timing must be matched.

**`type` values:**

| type | Element | type | Element |
|------|---------|------|---------|
| 1 | second | 13 | weekday 2-letter (SU) |
| 2 | minute | 14 | weekday 3-letter (SUN) |
| 3 | hour | 15 | weekday full (SUNDAY) |
| 4 | am/pm | 16 | month 3-letter (JAN) |
| 5 | hh:mm | 17 | **temperature** |
| 6 | hh:mm:ss | 18 | today max temp |
| 7 | year | 19 | today min temp |
| 8 | day | 20 | **weather word** |
| 9 | month | 21 | noise (dB) |
| 10 | mon-year | **22** | **static text** (set `TextString`) |
| 11 | eng-month.day | **23** | **net text** (see below) |
| 12 | day:month:year | | |

- **Types 1–21** render **on-device** with zero further pushes. The chosen `font` must
  include the needed glyphs (digits for numeric types; letters for weekday/month/weather).
- **Type 22** = a static string you push.
- **Type 23** = **net text**: `TextString` is a URL the device polls every `update_time`
  seconds; the response must be JSON `{"DispData": "value"}`. Example URL
  `http://appin.divoom-gz.com/Device/ReturnCurrentDate?test=0` → `{"DispData": "2022-01-22 13:51:56"}`.

> ✅ **Type 23 confirmed working on Times Gate** — device polls the URL every
> `update_time` seconds and displays the returned `{"DispData": "value"}`. See the
> design note in §0.5 and the `DispData` pull-model architecture discussion in the
> backlog.

**Setup call (NewFlag 1) — send once to set background + all items** ✅:
```json
{
  "Command": "Draw/SendHttpItemList", "LocalToken": <LocalToken>,
  "LcdIndex": 0, "NewFlag": 1,
  "BackgroudGif": "https://dummyimage.com/128x128/1e1e1e/000000.gif",
  "ItemList": [
    { "TextId": 1, "type": 6,  "x": 0, "y": 8,  "dir": 0, "font": 18, "TextWidth": 128, "Textheight": 16, "speed": 100, "align": 2, "color": "#00FFFF" },
    { "TextId": 2, "type": 14, "x": 0, "y": 30, "dir": 0, "font": 18, "TextWidth": 128, "Textheight": 16, "speed": 100, "align": 2, "color": "#FFFFFF" },
    { "TextId": 3, "type": 22, "x": 0, "y": 56, "dir": 0, "font": 4,  "TextWidth": 128, "Textheight": 16, "speed": 50,  "align": 0, "color": "#FFFF00", "TextString": "Hello Times Gate!" },
    { "TextId": 4, "type": 23, "x": 0, "y": 80, "dir": 0, "font": 2,  "TextWidth": 128, "Textheight": 16, "speed": 50,  "align": 2, "color": "#FF8800", "update_time": 10, "TextString": "http://appin.divoom-gz.com/Device/ReturnCurrentDate?test=0" }
  ]
}
```

**Update call (NewFlag 0) — update one item without reloading background** ✅:
```json
{
  "Command": "Draw/SendHttpItemList", "LocalToken": <LocalToken>,
  "LcdIndex": 0, "NewFlag": 0,
  "ItemList": [
    { "TextId": 3, "type": 22, "x": 0, "y": 56, "dir": 0, "font": 4, "TextWidth": 128, "Textheight": 16, "speed": 50, "align": 0, "color": "#00FF00", "TextString": "Updated value!" }
  ]
}
```

> ✅ **Verified working on Times Gate** — but requires two extra fields not in the
> generic Pixoo doc (page 61): **`LcdIndex`** (0–4, target screen) and **`NewFlag`**
> (`1` = overwrite existing items) and **`BackgroudGif`** (URL to a `.gif` file the
> device fetches as background — must be a reachable URL; `NewFlag: 1` makes
> `BackgroudGif` optional). Without `NewFlag` + `BackgroudGif` the device shows a
> brief loading screen and reverts. Tested and confirmed all types: type 6 (hh:mm:ss),
> type 14 (weekday), type 22 (static text), type 23 (URL-poll `DispData`) — all
> rendered correctly on screen 0 with `LcdIndex: 0`. The Times Gate-specific doc
> page (132) correctly documents `LcdIndex` and `NewFlag`/`BackgroudGif`; the generic
> Pixoo page (61) omits them.

---

## 5. Command list (batching)

### 5.1 `Draw/CommandList` — run several commands in one POST ✅

Firmware ≥ 90102. Batches multiple commands into a single HTTP call — confirmed
working on Times Gate. **Always prefer this over sequential calls when updating
multiple screens simultaneously**: it avoids visible per-screen flicker and reduces
round-trips.

```json
{ "Command": "Draw/CommandList", "LocalToken": <LocalToken>,
  "CommandList": [
    { "Command": "Draw/SendHttpItemList", "LcdIndex": 0, "NewFlag": 0, "ItemList": [...] },
    { "Command": "Draw/SendHttpItemList", "LcdIndex": 1, "NewFlag": 0, "ItemList": [...] },
    { "Command": "Draw/SendHttpItemList", "LcdIndex": 2, "NewFlag": 0, "ItemList": [...] }
  ] }
```

> Note: `LocalToken` belongs on the outer wrapper only — omit it from each inner command.

### 5.2 `Draw/UseHTTPCommandSource` — run commands from a URL 📄

```json
{ "Command": "Draw/UseHTTPCommandSource", "LocalToken": <LocalToken>,
  "CommandUrl": "http://<your-host>/commands.json" }
```
The device fetches the command array from `CommandUrl` and runs it (see §0.5).

---

## 6. Device control

### 6.1 `Device/SysReboot` — reboot 📄

```json
{ "Command": "Device/SysReboot", "LocalToken": <LocalToken> }
```

---

## 7. Errors & gotchas summary

| Symptom | Cause | Fix |
|---------|-------|-----|
| `{"error_code":"DeviceToken is err"}` | missing/malformed `LocalToken` (or you used `DeviceToken`) | send int `LocalToken` in body ✅ |
| Screen stuck on **"loading"** | raw-RGB `PicData`, or oversized `PicID` | use base64 **JPEG**; small monotonic `PicID` ✅ |
| Send accepted (`error_code 0`) but no change | reused/lower `PicID` | reset once, then increment ✅ |
| Cloud "current face" wrong | cloud reflects app state only | treat as hint, not truth ✅ |
| Text overlay never appears | no preceding `SendHttpGif` on that screen | draw a gif first, then text ✅ |

---

## Appendix — official ShowDoc source

Divoom's raw docs are JS-rendered; the backend JSON works via curl:

```sh
curl "https://docin.divoom-gz.com/server/index.php?s=/api/page/info&page_id=<N>" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["page_content"])'
```

The full TimeGate menu tree (item_id 5, catalog 22) is at
`s=/api/item/info&item_id=5`. Page-id map by section:

- **system setting** (cat 23): 102 brightness · 103 get all setting · 104 weather area ·
  105 time zone · 106 system time · 107 screen switch · 108 device time · 109 temp mode ·
  110 mirror · 111 hour mode · 112 get weather · 138 gallery time · 353 RGB info
- **dial control** (cat 24): 113 dial type · 114 individual dial list · 115 whole dial list ·
  116 select whole dial · 117 channel type · 118 channel info · 119 individual dial ·
  120 visualizer
- **tool** (cat 25): 121 countdown · 122 stopwatch · 123 scoreboard · 124 noise · 125 buzzer
- **animation function** (cat 26): 126 like list · 127 upload list · 128 send remote ·
  129 play gif · 130 play gif LCDs · 133 send animation · 134 send text · 141 clear text ·
  131 font list · 132 send display list
- **command list** (cat 27): 135 command list · 136 url command file
- **general** (cat 0): 24 command format · 25 find device · 145 DIY net data clock · 140 reboot

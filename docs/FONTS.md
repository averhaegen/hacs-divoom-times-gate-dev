# Device fonts — picking a `font` id

Cards and `dispdata_text` pages render text on the device, so you pick a
**device font id** (not an HA font). This page helps you choose one fast; the
full list of all 308 fonts with exact charsets is in
[FONTS_CATALOG.md](FONTS_CATALOG.md).

Two things matter: **size** (the glyph grid is baked in — you can't scale it)
and **charset** (glyphs a font doesn't have are silently dropped).

## Card-safe fonts (recommended)

The card layouts are sized around the **default `font: 4` (14×14)**. Fonts in
the **12–16 px height** band drop straight into a card without breaking the
row spacing. Pick by what you need to show:

### Values

| Need | Best fits (id · size) | Notes |
|---|---|---|
| **Plain numbers** | `4` · 14×14 · · `24` · 8×14 · · `96` · 7×13 | `4` is the default |
| **Numbers + decimal** | `184` · 12×14 · · `44` · 6×14 · · `370` · 12×12 | for `3.2` |
| **Numbers + `%`** | `248` · 11×11 · · `300` · 13×13 · · `46` · 5×13 | for `67%` |
| **Numbers + `:` (clock)** | `18` · 5×5 · · `22` · 7×11 · · `90` · 8×11 | `18` looks great for clocks |
| **Temperature (`21c`)** | `254` · 11×14 · · `248` · 11×11 | `c`/`f` glyphs |

### Text / units / labels

| Need | Best fits (id · size) | Notes |
|---|---|---|
| **Full text (any case + symbols)** | `4` · 14×14 · · `2` · 16×16 · · `52` · 13×13 | defaults; general bitmap |
| **Unit text (`kWh`, caps)** | `248` · 11×11 · · `568` · 16×14 · · `664` · 11×11 | |

> Tip: the safest single choice for a mixed value is the default **`4`** — it
> renders general text and numbers. Reach for a specialised id only when you
> want a specific look (e.g. `254` for `21c`, `248` for `%`).
>
> Observed on device: **`18`** is a clean small clock/numeric font; **`2`**
> and **`4`** are similar general fonts, with **`4`** rendering a bit larger.

## Bigger / display fonts (outside the card band)

Great for a **1–2 sensor card** where a value can be large, but they will
overflow small rows — use only with few slots:

| Font | Size | Charset | Look |
|---|---|---|---|
| `246` | 18×22 | digits + `.` | Large clean value |
| `260` | 23×20 | digits + `.` | Large value |
| `256` | 29×23 | digits + `:` | Big **dual-colour** clock |
| `170` | 9×10 | near-full ASCII (`$@%.,:;()`…) | Most complete text font |
| `160` | 8×16 | digits + `km.$` | Dollar values |

## Hard facts

- **No font in the whole catalog has `€` or `°`.** Use `$` (160/170), spell
  `EUR`, or put the unit in the label; for temperature use `21c` (254's
  `c`/`f`) or a separate `C` label.
- Glyphs outside a font's charset are dropped silently — check the charset in
  [FONTS_CATALOG.md](FONTS_CATALOG.md) before using symbols.
- Bitmap fonts `2`/`4`/`32` show an empty charset in the catalog but render
  general text (they're the classic full bitmap fonts; the integration
  defaults are `4` for values and `2` for labels).
- **Scrolling:** long text only scrolls in **type-23 (polled value)** items,
  not static labels — see docs/API.md §4.10.
- Device font ids only apply to text the device draws. Labels Home Assistant
  bakes into the artwork use its own fonts: the energy panels use Pixel
  Operator SC Bold (`fonts/PixelOperatorSC-Bold.ttf`, CC0) at 8px steps with
  anti-aliasing off, everything else uses the vendored Pixoo bitmap fonts.
- Regenerate the catalog anytime: `python3 scripts/get_font_list.py <DEVICE_ID>`.

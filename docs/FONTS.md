# Device font test results (SendHttpItemList `font` ids)

Live-tested 2026-07-05 on the Times Gate (HW 400) with sample strings
`Ab3 €%°-:` and `12.5:%-°` per font, two rounds. Glyphs the font doesn't
know are silently dropped (no placeholder box).

## Character fonts (letters supported)

| Font | Case | Digits | Extras seen | Notes |
|---|---|---|---|---|
| 34 | uppercase (small render) | ✅ | `%` | Small; readable but tiny |
| 48 | upper + lower | ✅ | — | Best for unit text (`kWh`, `Wh`) — but no `%` |
| 248 | uppercase only | ✅ | `%` | Good for `W`, `KWH` style units + percentages |

## Number fonts

| Font | Digits | `.` | `:` | `%` | `-` | Notes |
|---|---|---|---|---|---|---|
| 46 | ✅ | ? | ? | ✅ | ? | Small |
| 76 | ✅ | ❌ | ❌ | ❌ | ❌ | Bare digits only |
| 84 | ✅ | ❌ | ❌ | ❌ | ❌ | Bare digits only |
| 184 | ✅ | ✅ | ? | ❌ | ? | |
| 246 | ✅ | ✅ | ? | ❌ | ? | Large, clean — good big-value font |
| 254 | ✅ | ❌ | ? | ❌ | ✅ | |
| 256 | ✅ | ? | ✅ | ❌ | ? | **Dual-color** (yellow/blue) — clock-style |
| 260 | ✅ | ✅ | ? | ❌ | ? | Large |

`?` = not conclusively seen in this round; retest if it matters.

## Key takeaways for cards

- **`€` and `°` exist in NO tested font.** Format currencies/temperatures as
  `EUR` / `C` text (needs a character font) or put the unit in the label and
  keep the value numeric.
- Percentages: fonts 46, 248 (and 34) render `%`.
- Big numeric values: 246 / 260 (with decimal point), 256 for a colored
  clock-ish look (`:` supported).
- Default `font: 4` (used by cards/dispdata) is a general small font;
  labels default to font 2.

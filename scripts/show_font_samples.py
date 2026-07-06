"""Display font samples on the Times Gate for photographing.

The font files on Divoom's CDN are encrypted, so the only way to get true
visual samples is to render them on the device itself. This script walks the
font catalog in batches, showing each font with its id on the 5 screens
(2 fonts per screen = 10 per batch); press Enter to advance to the next
batch, photograph as you go. The sample string per font is derived from its
charset, so you see exactly the glyphs it supports.

Usage:
    python show_font_samples.py DEVICE_IP LOCAL_TOKEN [START_ID] [ONLY_ID...]

Examples:
    python show_font_samples.py 192.168.1.50 417746          # all fonts
    python show_font_samples.py 192.168.1.50 417746 240      # start at id 240
    python show_font_samples.py 192.168.1.50 417746 0 34 48 170   # only these
"""
from __future__ import annotations

import json
import sys
import urllib.request

CATALOG_URL = "https://app.divoom-gz.com/Device/GetTimeDialFontList"
_PREFERRED = "Ab12.5%:-$km"


def sample_text(charset: str) -> str:
    if not charset:
        return "Ab 12.5%"
    picked = [c for c in _PREFERRED if c in charset]
    return "".join(picked) if len(picked) >= 4 else charset[:10]


def post(ip: str, payload: dict) -> dict:
    req = urllib.request.Request(f"http://{ip}/post", json.dumps(payload).encode())
    with urllib.request.urlopen(req, timeout=9) as resp:  # noqa: S310 - user LAN device
        return json.loads(resp.read())


def show_batch(ip: str, token: int, batch: list[dict]) -> None:
    """2 fonts per screen, big rows, id label in font 2."""
    for lcd in range(5):
        pair = batch[lcd * 2 : lcd * 2 + 2]
        items = []
        for r, font in enumerate(pair):
            y = 4 + r * 64
            items.append({"TextId": r * 2 + 1, "type": 22, "x": 0, "y": y, "dir": 0,
                          "font": 2, "TextWidth": 30, "Textheight": 14, "speed": 0,
                          "align": 1, "color": "#888888", "TextString": f"F{font['id']}"})
            items.append({"TextId": r * 2 + 2, "type": 22, "x": 30, "y": y, "dir": 0,
                          "font": int(font["id"]), "TextWidth": 98, "Textheight": 56,
                          "speed": 0, "align": 1, "color": "#FFFFFF",
                          "TextString": sample_text(str(font.get("charset", "")))})
        if not items:
            continue
        resp = post(ip, {"Command": "Draw/SendHttpItemList", "LocalToken": token,
                         "LcdIndex": lcd, "NewFlag": 1,
                         "BackgroudGif": "https://dummyimage.com/128x128/000000/000000.gif",
                         "ItemList": items})
        if resp.get("error_code") != 0:
            print(f"  screen {lcd + 1}: {resp}")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    ip, token = sys.argv[1], int(sys.argv[2])
    start_id = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    only = {int(a) for a in sys.argv[4:]}

    body = json.dumps({"DeviceId": 0, "DeviceType": "LCD"}).encode()
    req = urllib.request.Request(CATALOG_URL, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - fixed Divoom host
        fonts = json.loads(resp.read()).get("FontList", [])
    fonts = [f for f in sorted(fonts, key=lambda f: int(f["id"]))
             if int(f["id"]) >= start_id and (not only or int(f["id"]) in only)]
    if not fonts:
        print("No fonts matched (empty catalog response, or filters too strict).")
        return 1

    print(f"{len(fonts)} fonts, {(len(fonts) + 9) // 10} batches of up to 10.")
    for i in range(0, len(fonts), 10):
        batch = fonts[i : i + 10]
        ids = [f["id"] for f in batch]
        print(f"Batch {i // 10 + 1}: ids {ids}")
        show_batch(ip, token, batch)
        if i + 10 < len(fonts):
            input("  -> photograph, then press Enter for the next batch... ")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

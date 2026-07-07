# Integration icon (home-assistant/brands)

> ⚠️ **ON HOLD — do not submit yet.** The brands registration is keyed on the
> integration **domain** (`divoom_times_gate` from manifest.json), and it's a
> one-shot public registration. We first want to settle the final repo name
> (this is the `-dev` repo) and confirm the domain stays as-is. Submit only
> after that decision.

HA and HACS load integration icons from the central
[home-assistant/brands](https://github.com/home-assistant/brands) repo —
custom integrations can't ship their own. Until the brands PR is merged, HA
shows a generic placeholder for this integration.

Current assets are a **draft** (2D icon based on the device photo — silver
capsule, side rings, 5 neon screens, orange feet), pending final validation:

| File | Size | Notes |
|---|---|---|
| `divoom_times_gate/icon.png` | 256×256 | transparent background |
| `divoom_times_gate/icon@2x.png` | 512×512 | hDPI variant |

## Submitting (when ready)

1. Confirm the final domain in `custom_components/<domain>/manifest.json`.
2. Fork `home-assistant/brands`.
3. Copy this folder to `custom_integrations/<domain>/` in the fork
   (rename if the domain changed).
4. Open a PR titled `Add <domain> (custom integration)` — brands CI
   validates sizes/format automatically.

After the merge, icons appear at
`https://brands.home-assistant.io/<domain>/icon.png` (Cloudflare-cached;
propagation can take a while).

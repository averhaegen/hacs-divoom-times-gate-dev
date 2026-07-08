# Divoom legal documents (reference copies)

Saved 2026-07-08, captured directly from the real Divoom iOS app (`Aurabox/3.8.20`)
via mitmproxy TLS-intercept, from these in-app URLs (served from Divoom's own CDN,
`fin.divoom-gz.com`):

- `divoom_privacy_policy.html` ← `https://fin.divoom-gz.com/DivoomPricyPolicy.html`
  (filename typo — "Pricy" not "Privacy" — is Divoom's, not ours)
- `divoom_user_agreement.html` ← `https://fin.divoom-gz.com/DivoomUserAgreement.html`

## Why these are here

Kept as a reference while we evaluate whether an **optional, opt-in cloud-account
layer** (for reading firmware version / update-availability via `UserLogin` +
`Device/GetListV2`/`Device/GetUpdateInfo` — see `docs/API.md` §6.2/§6.3 and
`BACKLOG.md`) would be consistent with Divoom's own terms, before building
anything that touches a user's real Divoom account credentials. Neither
document has been analyzed yet for anything that would prohibit or restrict
third-party/unofficial API use — that review is a prerequisite for building
the cloud-auth feature, not yet done as of this commit.

These are unofficial mirrors for our own reference only, not redistributed
for any other purpose. Not affiliated with or endorsed by Divoom.

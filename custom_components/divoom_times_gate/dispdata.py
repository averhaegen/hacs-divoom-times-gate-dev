"""HTTP view the Times Gate can poll for one entity's state (type-23 net text).

`Draw/SendHttpItemList` type 23 makes the device itself poll a URL every
`update_time` seconds, expecting JSON `{"DispData": "<value>"}` back — no
per-tick push from HA. This view is that endpoint: one entity's current state,
served without HA auth (the device cannot present a bearer token), gated by a
per-config-entry secret in the URL. See docs/DISPDATA.md.

Registered once globally (not per config entry) since aiohttp only allows one
route per URL pattern; valid secrets for all set-up entries are tracked in
``hass.data[DOMAIN]["dispdata_secrets"]``.
"""
from __future__ import annotations

import logging

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

URL_PATTERN = "/api/divoom_times_gate/dispdata/{secret}/{entity_id}"
_DATA_KEY = "dispdata_secrets"


def register_secret(hass: HomeAssistant, secret: str) -> None:
    """Mark ``secret`` as valid; registers the shared view on first call."""
    secrets: set[str] = hass.data.setdefault(DOMAIN, {}).setdefault(_DATA_KEY, set())
    if not secrets:
        hass.http.register_view(DispDataView(hass))
    secrets.add(secret)


def unregister_secret(hass: HomeAssistant, secret: str) -> None:
    """Drop ``secret`` (e.g. on config entry removal)."""
    secrets: set[str] = hass.data.get(DOMAIN, {}).get(_DATA_KEY, set())
    secrets.discard(secret)


class DispDataView(HomeAssistantView):
    """Serves ``{"DispData": "<state>"}`` for one entity, guarded by a secret."""

    url = URL_PATTERN
    name = "api:divoom_times_gate:dispdata"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request, secret: str, entity_id: str) -> web.Response:
        secrets: set[str] = self._hass.data.get(DOMAIN, {}).get(_DATA_KEY, set())
        if secret not in secrets:
            return web.json_response({"error": "forbidden"}, status=403)

        state = self._hass.states.get(entity_id)
        value = state.state if state is not None else "unavailable"
        unit = state.attributes.get("unit_of_measurement") if state is not None else None
        if unit:
            value = f"{value}{unit}"

        # Optional ?label=<text> prefixes the value as "<label>: <value>", so a
        # dispdata_text page can show a friendly name next to the reading
        # without a separate item/API call. Spaces arrive as underscores (see
        # coordinator._build_dispdata_text) — the device's own poll GET doesn't
        # reliably handle a percent-encoded space in the query string.
        if label := request.query.get("label"):
            value = f"{label.replace('_', ' ')}: {value}"

        return web.json_response({"DispData": value})

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
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.template import Template

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

URL_PATTERN = "/api/divoom_times_gate/dispdata/{secret}/{entity_id}"
CARDBG_URL_PATTERN = "/api/divoom_times_gate/cardbg/{secret}/{digest}"
_DATA_KEY = "dispdata_secrets"
CARDBG_CACHE_KEY = "cardbg_cache"
_CARDBG_CACHE_MAX = 32  # entries; ~5 screens x a few digests in flight


def register_secret(hass: HomeAssistant, secret: str) -> None:
    """Mark ``secret`` as valid; registers the shared views on first call."""
    secrets: set[str] = hass.data.setdefault(DOMAIN, {}).setdefault(_DATA_KEY, set())
    if not secrets:
        hass.http.register_view(DispDataView(hass))
        hass.http.register_view(CardBackgroundView(hass))
        hass.http.register_view(DispDataTemplateView(hass))
    secrets.add(secret)


TPL_URL_PATTERN = "/api/divoom_times_gate/dispdata_tpl/{secret}/{key}"
_TPL_KEY = "dispdata_templates"


_ALLOWED_ENTITIES_KEY = "dispdata_entities"


def register_allowed_entity(hass: HomeAssistant, entity_id: str) -> None:
    """Allow ``entity_id`` on the dispdata view.

    Called wherever a poll URL is built (dispdata_text sensors/items, card
    slots), so the unauthenticated view only ever serves entities the user
    actually put on a screen — not arbitrary ids probed with the secret.
    """
    hass.data.setdefault(DOMAIN, {}).setdefault(_ALLOWED_ENTITIES_KEY, set()).add(
        entity_id
    )


def register_value_template(hass: HomeAssistant, secret: str, key: str, template: str) -> None:
    """Register a Jinja template served at the dispdata_tpl endpoint.

    Cards use this for per-slot ``value_template``: the device polls
    ``/dispdata_tpl/<secret>/<key>`` and the template renders fresh in HA on
    every poll (e.g. turning ``0.001`` kW into ``1 W``). Keyed by a content
    hash under its config entry's ``secret``, so identical templates share an
    entry and re-registration is a no-op. Namespacing under ``secret`` lets
    ``unregister_secret`` drop all of an entry's templates on unload/reload —
    otherwise edited/removed cards would leak old templates in memory forever.
    """
    templates: dict[str, dict[str, str]] = hass.data.setdefault(DOMAIN, {}).setdefault(
        _TPL_KEY, {}
    )
    templates.setdefault(secret, {})[key] = template


def publish_card_background(hass: HomeAssistant, digest: str, gif: bytes) -> None:
    """Make a rendered card background fetchable at its digest URL."""
    cache: dict[str, bytes] = hass.data.setdefault(DOMAIN, {}).setdefault(
        CARDBG_CACHE_KEY, {}
    )
    cache[digest] = gif
    while len(cache) > _CARDBG_CACHE_MAX:
        cache.pop(next(iter(cache)))


def unregister_secret(hass: HomeAssistant, secret: str) -> None:
    """Drop ``secret`` (e.g. on config entry removal/reload), and any
    value-templates registered under it, so they don't accumulate forever."""
    secrets: set[str] = hass.data.get(DOMAIN, {}).get(_DATA_KEY, set())
    secrets.discard(secret)
    templates: dict[str, dict[str, str]] = hass.data.get(DOMAIN, {}).get(_TPL_KEY, {})
    templates.pop(secret, None)


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
        allowed: set[str] = self._hass.data.get(DOMAIN, {}).get(
            _ALLOWED_ENTITIES_KEY, set()
        )
        if entity_id not in allowed:
            # Only entities that a configured screen actually polls are served;
            # anything else is a probe (or a stale config) — deny.
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


class DispDataTemplateView(HomeAssistantView):
    """Serves ``{"DispData": <rendered template>}`` for a registered template."""

    url = TPL_URL_PATTERN
    name = "api:divoom_times_gate:dispdata_tpl"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request, secret: str, key: str) -> web.Response:
        secrets: set[str] = self._hass.data.get(DOMAIN, {}).get(_DATA_KEY, set())
        if secret not in secrets:
            return web.json_response({"error": "forbidden"}, status=403)
        template = self._hass.data.get(DOMAIN, {}).get(_TPL_KEY, {}).get(secret, {}).get(key)
        if template is None:
            return web.json_response({"error": "unknown template"}, status=404)
        try:
            # Render without parsing: the panels format their own decimals, and
            # parsing turns "1.50" back into 1.5 and drops the trailing zero.
            value = str(Template(template, self._hass).async_render(parse_result=False))
        except TemplateError as err:
            _LOGGER.warning("dispdata_tpl %s render failed: %s", key, err)
            value = "err"
        return web.json_response({"DispData": value})


class CardBackgroundView(HomeAssistantView):
    """Serves rendered card backgrounds (GIF) by content digest.

    The digest in the URL doubles as the cache-buster: a changed background
    gets a new digest and therefore a new URL, sidestepping the device's
    cache-by-URL behaviour for ``BackgroudGif``.
    """

    url = CARDBG_URL_PATTERN
    name = "api:divoom_times_gate:cardbg"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request, secret: str, digest: str) -> web.Response:
        secrets: set[str] = self._hass.data.get(DOMAIN, {}).get(_DATA_KEY, set())
        if secret not in secrets:
            return web.json_response({"error": "forbidden"}, status=403)
        cache: dict[str, bytes] = self._hass.data.get(DOMAIN, {}).get(
            CARDBG_CACHE_KEY, {}
        )
        gif = cache.get(digest.removesuffix(".gif"))
        if gif is None:
            return web.Response(status=404)
        return web.Response(body=gif, content_type="image/gif")

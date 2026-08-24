"""Tests for the cloud face catalog reader.

These calls are best-effort by design: they run at setup and when building
option dropdowns, and a Divoom outage must never take setup down with it.

One thing this catalog cannot tell you: ``Channel/GetDialType`` and
``Channel/GetDialList`` take no DeviceId, only ``DeviceType: "LCD"``, so every
LCD device gets the same answer. A face being in here means it still exists,
not that it renders well on a particular hardware revision.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from custom_components.divoom_times_gate.discovery import (
    async_get_per_screen_face_catalog,
    async_get_per_screen_faces,
)

TYPE_URL = "https://app.divoom-gz.com/Channel/GetDialType"
LIST_URL = "https://app.divoom-gz.com/Channel/GetDialList"


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def json(self, content_type: str | None = None) -> dict[str, Any]:
        return self._payload


class FakeSession:
    """A session that answers a queue per URL, so call order is testable."""

    def __init__(self, responses: dict[str, list[Any]]) -> None:
        self._responses = {url: list(items) for url, items in responses.items()}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @asynccontextmanager
    async def post(self, url: str, *, json: dict[str, Any], **kwargs: Any):
        self.calls.append((url, json))
        queue = self._responses.get(url) or []
        answer = queue.pop(0) if queue else {}
        if isinstance(answer, Exception):
            raise answer
        yield FakeResponse(answer)


def dials(start: int, count: int) -> dict[str, Any]:
    return {
        "DialList": [
            {"ClockId": start + i, "Name": f"Face {start + i}"} for i in range(count)
        ]
    }


def session(types: list[str], *pages: Any) -> Any:
    return FakeSession({TYPE_URL: [{"DialTypeList": types}], LIST_URL: list(pages)})


async def test_the_catalog_keeps_its_categories() -> None:
    """The resolver needs the category names, so do not flatten them away."""
    fake = session(["Normal", "Pixel Art"], dials(10, 2), dials(20, 1))

    catalog = await async_get_per_screen_face_catalog(fake)

    assert catalog == {
        "Normal": {10: "Face 10", 11: "Face 11"},
        "Pixel Art": {20: "Face 20"},
    }


async def test_the_catalog_call_asks_for_lcd_faces() -> None:
    """A DeviceId is deliberately absent: this catalog is not device-scoped."""
    fake = session(["Normal"], dials(10, 1))

    await async_get_per_screen_face_catalog(fake)

    assert fake.calls[0] == (TYPE_URL, {"DeviceType": "LCD"})
    assert fake.calls[1] == (
        LIST_URL,
        {"DialType": "Normal", "DeviceType": "LCD", "Page": 1},
    )


async def test_a_full_page_is_followed_by_another_request() -> None:
    """Divoom pages 30 at a time, so a short page is the last page."""
    fake = session(["Normal"], dials(100, 30), dials(200, 1))

    catalog = await async_get_per_screen_face_catalog(fake)

    assert len(catalog["Normal"]) == 31
    assert [call[1].get("Page") for call in fake.calls[1:]] == [1, 2]


async def test_the_page_walk_is_capped() -> None:
    """A catalog that never returns a short page must still terminate."""
    fake = session(["Normal"], *[dials(1 + 30 * n, 30) for n in range(10)])

    await async_get_per_screen_face_catalog(fake, max_pages=3)

    assert len(fake.calls) == 1 + 3


async def test_a_failing_category_call_returns_nothing_rather_than_raising() -> None:
    fake: Any = FakeSession({TYPE_URL: [TimeoutError()]})

    assert await async_get_per_screen_face_catalog(fake) == {}


async def test_a_failing_page_keeps_what_was_already_collected() -> None:
    fake = session(["Normal"], dials(1, 30), TimeoutError())

    catalog = await async_get_per_screen_face_catalog(fake)

    assert len(catalog["Normal"]) == 30


async def test_a_malformed_entry_is_skipped() -> None:
    fake = session(
        ["Normal"], {"DialList": [{"Name": "no id"}, {"ClockId": 7, "Name": "ok"}]}
    )

    catalog = await async_get_per_screen_face_catalog(fake)

    assert catalog == {"Normal": {7: "ok"}}


async def test_an_empty_category_is_left_out() -> None:
    fake = session(["Normal", "Sport"], dials(10, 1), {"DialList": []})

    catalog = await async_get_per_screen_face_catalog(fake)

    assert list(catalog) == ["Normal"]


async def test_the_flat_view_merges_every_category() -> None:
    fake = session(["Normal", "Sci-Fi"], dials(10, 1), dials(20, 1))

    assert await async_get_per_screen_faces(fake) == {10: "Face 10", 20: "Face 20"}

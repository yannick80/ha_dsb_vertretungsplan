"""Tests for the DSB mobile API client against a local fake DSB server."""

from __future__ import annotations

from collections.abc import Callable

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from custom_components.dsb_vertretungsplan.api import (
    DSBAuthError,
    DSBClient,
    DSBConnectionError,
    decode_html,
)

PLAN_HTML = """<html><head><meta charset="iso-8859-1"></head><body>
<div class="mon_title">19.10.2026 Montag</div>
<table class="mon_list">
<tr><th>Art</th><th>Klasse(n)</th><th>Stunde</th><th>Fach</th></tr>
<tr><td>Entfall</td><td>08b</td><td>3</td><td>Ma</td></tr>
</table></body></html>""".encode("iso-8859-1")


class FakeDSB:
    """Minimal stand-in for mobileapi.dsbcontrol.de."""

    def __init__(self) -> None:
        self.password = "pw"
        self.tokens: list[str] = ["token-1", "token-2"]
        self.valid_tokens: set[str] = set()
        self.logins = 0
        self.plan_status = 200
        self.login_status = 200
        self.issue_dead_tokens = False
        self.server: TestServer | None = None

    def url(self, path: str) -> str:
        assert self.server is not None
        return str(self.server.make_url(path))

    def timetables(self) -> list:
        return [
            {
                "Id": "root",
                "Date": "19.10.2026 07:30",
                "Title": "Pläne",
                "Childs": [
                    {
                        "Id": "1",
                        "Date": "19.10.2026 07:30",
                        "Title": "subst_001.htm",
                        "Detail": self.url("/plans/subst_001.htm"),
                        "Childs": [],
                    },
                    {
                        "Id": "2",
                        "Date": "18.10.2026 12:00",
                        "Title": "Mensaplan",
                        "Detail": self.url("/plans/mensa.jpg"),
                        "Childs": [],
                    },
                ],
            }
        ]

    async def authid(self, request: web.Request) -> web.Response:
        self.logins += 1
        if self.login_status != 200:
            return web.Response(status=self.login_status)
        if request.query.get("password") != self.password:
            return web.json_response("")
        token = self.tokens.pop(0)
        if not self.issue_dead_tokens:
            self.valid_tokens.add(token)
        return web.json_response(token)

    def _check(self, request: web.Request) -> web.Response | None:
        if request.query.get("authid") not in self.valid_tokens:
            return web.Response(status=401)
        return None

    async def dsbtimetables(self, request: web.Request) -> web.Response:
        return self._check(request) or web.json_response(self.timetables())

    async def dsbdocuments(self, request: web.Request) -> web.Response:
        return self._check(request) or web.json_response([])

    async def newstab(self, request: web.Request) -> web.Response:
        return self._check(request) or web.json_response(
            [
                {
                    "Id": "n1",
                    "Title": "Elternabend",
                    "Date": "17.10.2026 09:00",
                    "Detail": "",
                }
            ]
        )

    async def plan(self, request: web.Request) -> web.Response:
        if self.plan_status != 200:
            return web.Response(status=self.plan_status)
        return web.Response(body=PLAN_HTML, content_type="text/html")

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/authid", self.authid)
        app.router.add_get("/dsbtimetables", self.dsbtimetables)
        app.router.add_get("/dsbdocuments", self.dsbdocuments)
        app.router.add_get("/newstab", self.newstab)
        app.router.add_get("/plans/subst_001.htm", self.plan)
        return app


@pytest.fixture
async def fake_dsb(socket_enabled) -> FakeDSB:
    fake = FakeDSB()
    async with TestServer(fake.app()) as server:
        fake.server = server
        yield fake


@pytest.fixture
async def make_client(fake_dsb: FakeDSB) -> Callable[[str], DSBClient]:
    async with aiohttp.ClientSession() as session:

        def factory(password: str = "pw") -> DSBClient:
            return DSBClient("user", password, session, base_url=fake_dsb.url("/"))

        yield factory


async def test_login_and_fetch(fake_dsb: FakeDSB, make_client) -> None:
    data = await make_client().async_get_data()

    assert fake_dsb.logins == 1
    assert [p.title for p in data.plans] == ["subst_001.htm", "Mensaplan"]
    assert [p.is_html for p in data.plans] == [True, False]
    assert data.plan_timestamp.isoformat() == "2026-10-19T07:30:00"
    assert len(data.entries) == 1
    assert data.entries[0].classes == "08b"
    assert data.plan_days[0].isoformat() == "2026-10-19"
    assert data.news[0].title == "Elternabend"
    assert data.plan_errors == {}


async def test_invalid_credentials(fake_dsb: FakeDSB, make_client) -> None:
    with pytest.raises(DSBAuthError):
        await make_client("wrong").async_login()


async def test_token_refresh_once(fake_dsb: FakeDSB, make_client) -> None:
    """An expired token triggers exactly one re-login."""
    client = make_client()
    await client.async_get_timetables()
    fake_dsb.valid_tokens.clear()  # token expires server side
    await client.async_get_timetables()
    assert fake_dsb.logins == 2
    assert client._token == "token-2"  # noqa: SLF001


async def test_token_rejected_after_relogin(fake_dsb: FakeDSB, make_client) -> None:
    client = make_client()
    await client.async_get_timetables()
    fake_dsb.valid_tokens.clear()
    fake_dsb.issue_dead_tokens = True
    with pytest.raises(DSBAuthError):
        await client.async_get_timetables()
    assert fake_dsb.logins == 2


async def test_server_error_is_connection_error(fake_dsb: FakeDSB, make_client) -> None:
    fake_dsb.login_status = 503
    with pytest.raises(DSBConnectionError):
        await make_client().async_login()


async def test_all_plans_failing_is_an_error(fake_dsb: FakeDSB, make_client) -> None:
    fake_dsb.plan_status = 500
    with pytest.raises(DSBConnectionError):
        await make_client().async_get_data()


def test_decode_html_charset() -> None:
    raw = '<meta charset="iso-8859-1"><p>Müller</p>'.encode("iso-8859-1")
    assert "Müller" in decode_html(raw)
    raw = '<meta charset="utf-8"><p>Müller</p>'.encode()
    assert "Müller" in decode_html(raw)

"""Async client for the DSBmobile mobile API (mobileapi.dsbcontrol.de).

This is the same API the official DSBmobile apps use. It is token based and
does not require scraping the ASP.NET login form of dsbmobile.de.

The module has no Home Assistant dependencies.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any

import aiohttp

from .parser import DayInfo, ParsedPlan, SubstitutionEntry, parse_plan_html

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://mobileapi.dsbcontrol.de"
AUTH_PARAMS = {
    "bundleid": "de.heinekingmedia.dsbmobile",
    "appversion": "35",
    "osversion": "22",
    "pushid": "",
}
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
USER_AGENT = "Mozilla/5.0 (Linux; Android 12) DSBmobile/35"

_HTML_EXTENSIONS = (".htm", ".html")
_TEXT_ENCODINGS = ("utf-8", "cp1252", "iso-8859-1")


class DSBError(Exception):
    """Base error of the DSB client."""


class DSBAuthError(DSBError):
    """Credentials were rejected."""


class DSBConnectionError(DSBError):
    """DSB could not be reached or returned an unexpected answer."""


@dataclass
class DSBItem:
    """A plan, document or news item as listed by DSB."""

    id: str
    title: str
    date: datetime | None
    date_raw: str
    url: str
    is_html: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON serialisable representation."""
        return {
            "id": self.id,
            "title": self.title,
            "date": self.date.isoformat() if self.date else None,
            "url": self.url,
            "is_html": self.is_html,
        }


@dataclass
class DSBData:
    """Everything fetched in one update cycle."""

    plans: list[DSBItem] = field(default_factory=list)
    documents: list[DSBItem] = field(default_factory=list)
    news: list[DSBItem] = field(default_factory=list)
    entries: list[SubstitutionEntry] = field(default_factory=list)
    infos: list[DayInfo] = field(default_factory=list)
    # Days for which at least one plan page exists.
    plan_days: list = field(default_factory=list)
    # Failures while downloading individual plan files (title -> reason).
    plan_errors: dict[str, str] = field(default_factory=dict)

    @property
    def plan_timestamp(self) -> datetime | None:
        """Return the upload time of the most recent plan."""
        stamps = [p.date for p in self.plans if p.date]
        return max(stamps) if stamps else None


def _parse_dsb_datetime(value: str) -> datetime | None:
    """Parse DSB timestamps such as '19.10.2026 07:30' (naive, local time)."""
    value = (value or "").strip()
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def decode_html(raw: bytes) -> str:
    """Decode an HTML document honouring its declared charset."""
    head = raw[:2048].decode("ascii", errors="ignore").lower()
    declared: str | None = None
    marker = "charset="
    if marker in head:
        candidate = head.split(marker, 1)[1]
        for stop in ('"', "'", ";", ">", " ", "/"):
            candidate = candidate.split(stop, 1)[0]
        declared = candidate.strip() or None
    encodings = (declared, *_TEXT_ENCODINGS) if declared else _TEXT_ENCODINGS
    for encoding in encodings:
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace")


class DSBClient:
    """Client for the DSBmobile mobile API."""

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
        base_url: str = BASE_URL,
    ) -> None:
        self._username = username
        self._password = password
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._token: str | None = None
        self._auth_lock = asyncio.Lock()

    # ------------------------------------------------------------------ auth

    async def async_login(self) -> str:
        """Fetch a fresh auth token. Raises DSBAuthError on bad credentials."""
        params = {**AUTH_PARAMS, "user": self._username, "password": self._password}
        try:
            async with self._session.get(
                f"{self._base_url}/authid",
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                if resp.status in (401, 403):
                    raise DSBAuthError("Credentials rejected by DSB")
                if resp.status != 200:
                    raise DSBConnectionError(f"Login returned HTTP {resp.status}")
                token = await resp.json(content_type=None)
        except asyncio.TimeoutError as err:
            raise DSBConnectionError("Timeout while logging in") from err
        except aiohttp.ClientError as err:
            raise DSBConnectionError(f"Login failed: {err}") from err
        except ValueError as err:
            raise DSBConnectionError("Login returned no JSON") from err

        if not isinstance(token, str) or not token.strip():
            raise DSBAuthError("Credentials rejected by DSB")
        self._token = token.strip()
        _LOGGER.debug("Logged in to DSB as %s", self._username)
        return self._token

    async def _async_token(self) -> str:
        async with self._auth_lock:
            if self._token is None:
                await self.async_login()
            return self._token  # type: ignore[return-value]

    async def _async_get_json(self, endpoint: str) -> Any:
        """GET an authenticated endpoint, re-logging in once if the token expired."""
        for attempt in (1, 2):
            token = await self._async_token()
            try:
                async with self._session.get(
                    f"{self._base_url}/{endpoint}",
                    params={"authid": token},
                    headers={"User-Agent": USER_AGENT},
                    timeout=REQUEST_TIMEOUT,
                ) as resp:
                    if resp.status in (401, 403):
                        if attempt == 1:
                            _LOGGER.debug("Token rejected for %s, re-authenticating", endpoint)
                            self._token = None
                            continue
                        raise DSBAuthError("Token rejected after re-login")
                    if resp.status != 200:
                        raise DSBConnectionError(f"{endpoint} returned HTTP {resp.status}")
                    try:
                        return await resp.json(content_type=None)
                    except ValueError as err:
                        raise DSBConnectionError(f"{endpoint} returned no JSON") from err
            except asyncio.TimeoutError as err:
                raise DSBConnectionError(f"Timeout while fetching {endpoint}") from err
            except aiohttp.ClientError as err:
                raise DSBConnectionError(f"Fetching {endpoint} failed: {err}") from err
        raise DSBConnectionError("Unreachable")  # pragma: no cover

    # ------------------------------------------------------------------ lists

    @staticmethod
    def _flatten_items(payload: Any) -> list[DSBItem]:
        """Flatten the nested DSB list structure into items."""
        items: list[DSBItem] = []
        if not isinstance(payload, list):
            return items

        def visit(node: dict[str, Any], parent_title: str) -> None:
            detail = str(node.get("Detail") or "")
            title = str(node.get("Title") or parent_title or "")
            children = node.get("Childs") or []
            if detail:
                items.append(
                    DSBItem(
                        id=str(node.get("Id") or ""),
                        title=title,
                        date=_parse_dsb_datetime(str(node.get("Date") or "")),
                        date_raw=str(node.get("Date") or ""),
                        url=detail,
                        is_html=detail.lower().split("?", 1)[0].endswith(_HTML_EXTENSIONS),
                    )
                )
            for child in children:
                if isinstance(child, dict):
                    visit(child, title)

        for node in payload:
            if isinstance(node, dict):
                visit(node, "")
        return items

    async def async_get_timetables(self) -> list[DSBItem]:
        """Return the list of published plans."""
        return self._flatten_items(await self._async_get_json("dsbtimetables"))

    async def async_get_documents(self) -> list[DSBItem]:
        """Return the list of published documents."""
        return self._flatten_items(await self._async_get_json("dsbdocuments"))

    async def async_get_news(self) -> list[DSBItem]:
        """Return the list of news items."""
        payload = await self._async_get_json("newstab")
        items: list[DSBItem] = []
        if isinstance(payload, list):
            for node in payload:
                if not isinstance(node, dict):
                    continue
                items.append(
                    DSBItem(
                        id=str(node.get("Id") or ""),
                        title=str(node.get("Title") or ""),
                        date=_parse_dsb_datetime(str(node.get("Date") or "")),
                        date_raw=str(node.get("Date") or ""),
                        url=str(node.get("Detail") or ""),
                    )
                )
        return items

    # ------------------------------------------------------------------ plans

    async def async_fetch_plan(self, item: DSBItem) -> ParsedPlan:
        """Download and parse one HTML plan."""
        try:
            async with self._session.get(
                item.url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status != 200:
                    raise DSBConnectionError(f"Plan '{item.title}' returned HTTP {resp.status}")
                content_type = resp.headers.get("Content-Type", "")
                if "image" in content_type or "pdf" in content_type:
                    raise DSBConnectionError(f"Plan '{item.title}' is not HTML ({content_type})")
                raw = await resp.read()
        except asyncio.TimeoutError as err:
            raise DSBConnectionError(f"Timeout while fetching plan '{item.title}'") from err
        except aiohttp.ClientError as err:
            raise DSBConnectionError(f"Fetching plan '{item.title}' failed: {err}") from err

        return parse_plan_html(decode_html(raw))

    async def async_get_data(self) -> DSBData:
        """Fetch plans, documents, news and parse all HTML plans."""
        data = DSBData()
        data.plans = await self.async_get_timetables()

        # Documents and news are optional; a failure there must not break
        # the substitution plan.
        for attr, fetch in (
            ("documents", self.async_get_documents),
            ("news", self.async_get_news),
        ):
            try:
                setattr(data, attr, await fetch())
            except DSBAuthError:
                raise
            except DSBError as err:
                _LOGGER.debug("Could not fetch %s: %s", attr, err)

        html_plans = [p for p in data.plans if p.is_html]
        results = await asyncio.gather(
            *(self.async_fetch_plan(p) for p in html_plans), return_exceptions=True
        )
        seen_days: set = set()
        for item, result in zip(html_plans, results):
            if isinstance(result, BaseException):
                _LOGGER.warning("Plan '%s' could not be loaded: %s", item.title, result)
                data.plan_errors[item.title] = str(result)
                continue
            data.entries.extend(result.entries)
            data.infos.extend(result.infos)
            for day in result.days:
                if day not in seen_days:
                    seen_days.add(day)
                    data.plan_days.append(day)

        if html_plans and len(data.plan_errors) == len(html_plans):
            raise DSBConnectionError("None of the published plans could be loaded")

        data.plan_days.sort()
        data.entries.sort(key=lambda e: (e.day or datetime.max.date(), _lesson_sort_key(e.lesson)))
        _LOGGER.debug(
            "Fetched %d plans, %d entries, %d days, %d documents, %d news",
            len(data.plans),
            len(data.entries),
            len(data.plan_days),
            len(data.documents),
            len(data.news),
        )
        return data


def _lesson_sort_key(lesson: str) -> int:
    digits = "".join(ch for ch in lesson if ch.isdigit())
    return int(digits[:3]) if digits else 999

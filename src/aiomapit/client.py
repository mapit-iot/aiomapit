"""Async client for the Mapit API (https://api.mapit.me/v1)."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import date, datetime
from types import TracebackType
from typing import Any, Self
from urllib.parse import quote, urlencode

import aiohttp

from ._version import __version__
from .exceptions import (
    MapitAuthError,
    MapitConnectionError,
    MapitError,
    MapitNotFound,
    MapitRateLimited,
    MapitResponseError,
    MapitScopeError,
)
from .models import (
    Account,
    Connection,
    Event,
    Page,
    Response,
    RideStats,
    Route,
    Subscription,
    Summary,
    Vehicle,
    VehicleStatus,
)

DEFAULT_BASE_URL = "https://api.mapit.me/v1"
CACHE_SIZE = 256

TokenProvider = Callable[[], Awaitable[str]]


def _param(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("datetimes need a timezone offset")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _problem(body: bytes) -> tuple[str | None, str | None]:
    try:
        data = json.loads(body)
    except ValueError:
        return None, None
    if not isinstance(data, dict):
        return None, None
    title, detail = data.get("title"), data.get("detail")
    return (title if isinstance(title, str) else None, detail if isinstance(detail, str) else None)


def _retry_after(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None  # an HTTP date: the caller can use its own back-off


def _missing_scope(www_authenticate: str, detail: str | None) -> str | None:
    # The server lists "mapit:read <missing scope>": the missing one is last.
    if (m := re.search(r'scope="([^"]*)"', www_authenticate)) and m.group(1).split():
        return m.group(1).split()[-1]
    if detail and (m := re.search(r"not given (\S+?)\.?$", detail)):
        return m.group(1)
    return None


class MapitClient:
    """Read-only client for one Mapit account.

    ``token`` is a personal key, or an async callable returning a valid access token
    (called before every request, so it may refresh). Pass an ``aiohttp.ClientSession``
    to share one; without it the client creates its own and closes it in :meth:`close`.

    Reads send ``If-None-Match`` for what they fetched before. On 304 the cached object is
    returned with ``Response.not_modified`` set.
    """

    def __init__(
        self,
        token: str | TokenProvider,
        *,
        session: aiohttp.ClientSession | None = None,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._token = token
        self._session = session
        self._owns_session = session is None
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent or f"aiomapit/{__version__}"
        self._timeout_seconds = timeout
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._cache: dict[str, tuple[str, Any]] = {}

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the session if the client created it."""
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    # -- transport ---------------------------------------------------------

    async def _bearer(self) -> str:
        return self._token if isinstance(self._token, str) else await self._token()

    @staticmethod
    def _cache_key(token: str, path: str, query: Mapping[str, str]) -> str:
        # The token is part of the key: a tag is only valid for the identity that got it.
        who = hashlib.sha256(token.encode()).hexdigest()[:16]
        return f"{who}|{path}?{urlencode(sorted(query.items()))}"

    async def _send(
        self, method: str, path: str, params: Mapping[str, str], token: str, etag: str | None
    ) -> tuple[int, Any, str | None]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": self._user_agent,
        }
        if etag:
            headers["If-None-Match"] = etag
        if self._session is None:
            self._session = aiohttp.ClientSession()
        try:
            async with self._session.request(
                method,
                self._base_url + path,
                params=params or None,
                headers=headers,
                timeout=self._timeout,
            ) as resp:
                raw = await resp.read()
                status = resp.status
                response_headers = resp.headers
        except TimeoutError as err:
            raise MapitConnectionError(
                f"The Mapit API did not answer within {self._timeout_seconds:g} s"
            ) from err
        except aiohttp.ClientError as err:
            raise MapitConnectionError(
                f"Cannot reach the Mapit API: {err or type(err).__name__}"
            ) from err
        if status in (204, 304):
            return status, None, None
        if status >= 400:
            raise self._error(status, raw, response_headers)
        try:
            body = json.loads(raw)
        except ValueError as err:  # includes a body that is not valid UTF-8
            raise MapitResponseError(
                "The Mapit API answered with a body that is not valid JSON", status=status
            ) from err
        return status, body, response_headers.get("ETag")

    @staticmethod
    def _error(status: int, body: bytes, headers: Mapping[str, str]) -> MapitError:
        title, detail = _problem(body)
        message = f"{status} {title or 'error'}" + (f": {detail}" if detail else "")
        if status == 401:
            return MapitAuthError(message, status=status, title=title, detail=detail)
        if status == 403 and "insufficient_scope" in headers.get("WWW-Authenticate", ""):
            scope = _missing_scope(headers["WWW-Authenticate"], detail)
            return MapitScopeError(message, scope=scope, status=status, title=title, detail=detail)
        if status == 404:
            return MapitNotFound(message, status=status, title=title, detail=detail)
        if status == 429:
            return MapitRateLimited(
                message,
                retry_after=_retry_after(headers.get("Retry-After")),
                status=status,
                title=title,
                detail=detail,
            )
        if status >= 500:
            return MapitConnectionError(message, status=status, title=title, detail=detail)
        return MapitError(message, status=status, title=title, detail=detail)

    async def _get[T](
        self, path: str, parse: Callable[[Any], T], params: Mapping[str, object] | None = None
    ) -> Response[T]:
        query = {k: _param(v) for k, v in (params or {}).items() if v is not None}
        token = await self._bearer()
        key = self._cache_key(token, path, query)
        cached = self._cache.get(key)
        status, body, etag = await self._send(
            "GET", path, query, token, cached[0] if cached else None
        )
        if status == 304:
            if cached is None:
                raise MapitError("The Mapit API answered 304 for a request without a tag")
            return Response(cached[1], True, cached[0])
        try:
            data = parse(body)
        except (KeyError, TypeError, ValueError, AttributeError) as err:
            raise MapitResponseError(
                f"Unexpected response from the Mapit API: {err!r}", status=status
            ) from err
        self._cache.pop(key, None)
        if etag:
            self._cache[key] = (etag, data)
            if len(self._cache) > CACHE_SIZE:
                del self._cache[next(iter(self._cache))]
        return Response(data, False, etag)

    @staticmethod
    def _id(value: str) -> str:
        return quote(value, safe="")

    # -- account -----------------------------------------------------------

    async def get_me(self) -> Response[Account]:
        return await self._get("/me", Account.from_json)

    async def get_summary(
        self, *, vehicle_cursor: str | None = None, transfer_cursor: str | None = None
    ) -> Response[Summary]:
        return await self._get(
            "/summary",
            Summary.from_json,
            {"vehicleCursor": vehicle_cursor, "transferCursor": transfer_cursor},
        )

    # -- vehicles ----------------------------------------------------------

    async def get_vehicles_page(self, cursor: str | None = None) -> Response[Page[Vehicle]]:
        return await self._get(
            "/vehicles",
            lambda d: Page(tuple(Vehicle.from_json(v) for v in d["vehicles"]), d.get("nextCursor")),
            {"cursor": cursor},
        )

    def iter_vehicles(self) -> AsyncIterator[Vehicle]:
        """Every vehicle, following the cursors."""
        return self._items(self.get_vehicles_page)

    async def get_vehicle(self, vehicle_id: str) -> Response[Vehicle]:
        return await self._get(f"/vehicles/{self._id(vehicle_id)}", Vehicle.from_json)

    async def get_subscription(self, vehicle_id: str) -> Response[Subscription | None]:
        """The stored subscription status, or None when the vehicle has none."""
        return await self._get(
            f"/vehicles/{self._id(vehicle_id)}/subscription",
            lambda d: Subscription.from_json(d["subscription"]) if d.get("subscription") else None,
        )

    # -- status (needs mapit:location:read) --------------------------------

    async def get_statuses_page(self, cursor: str | None = None) -> Response[Page[VehicleStatus]]:
        """Last reported status of every vehicle on the page, in one request."""
        return await self._get(
            "/status",
            lambda d: Page(
                tuple(VehicleStatus.from_json(v) for v in d["vehicles"]),
                d.get("nextCursor"),
                events_cursor=d.get("eventsCursor"),
            ),
            {"cursor": cursor},
        )

    def iter_statuses(self) -> AsyncIterator[VehicleStatus]:
        """Every vehicle's status, following the cursors."""
        return self._items(self.get_statuses_page)

    async def get_vehicle_status(self, vehicle_id: str) -> Response[VehicleStatus]:
        return await self._get(f"/vehicles/{self._id(vehicle_id)}/status", VehicleStatus.from_json)

    # -- events (needs mapit:location:read) --------------------------------

    async def get_events_page(
        self, cursor: str | None = None, limit: int | None = None
    ) -> Response[Page[Event]]:
        """Alerts after ``cursor``, oldest first; without one, the last 24 hours (do not act on
        those). Store ``next_cursor`` for the next call, and call again while ``has_more``.
        Call it when ``events_cursor`` on a status page changes, not on a timer."""
        return await self._get(
            "/events",
            lambda d: Page(
                tuple(Event.from_json(e) for e in d["events"]),
                d["nextCursor"],
                has_more=bool(d.get("hasMore", False)),
            ),
            {"cursor": cursor, "limit": limit},
        )

    async def iter_events(
        self, cursor: str | None = None, limit: int | None = None
    ) -> AsyncIterator[Event]:
        """Every alert after ``cursor``, following ``has_more``. To resume later, use
        :meth:`get_events_page`, whose ``next_cursor`` is what to store."""
        while True:
            page = (await self.get_events_page(cursor, limit)).data
            for event in page.items:
                yield event
            if not page.has_more:
                return
            cursor = page.next_cursor

    # -- routes (needs mapit:routes:read) ----------------------------------

    async def get_routes_page(
        self,
        vehicle_id: str,
        *,
        day: date | str | None = None,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
        timezone: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Response[Page[Route]]:
        """Routes of one local ``day``, or from ``start`` (inclusive) to ``end`` (exclusive,
        at most 93 days, with offsets). Without a filter: the last 30 days, which moves on
        every call and so never answers 304 (``Page.filter`` has the window it used)."""
        return await self._get(
            f"/vehicles/{self._id(vehicle_id)}/routes",
            lambda d: Page(
                tuple(Route.from_json(r) for r in d["routes"]),
                d.get("nextCursor"),
                d.get("filter"),
            ),
            {
                "day": day,
                "from": start,
                "to": end,
                "timezone": timezone,
                "limit": limit,
                "cursor": cursor,
            },
        )

    async def iter_routes(
        self,
        vehicle_id: str,
        *,
        day: date | str | None = None,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
        timezone: str | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[Route]:
        """Every route of the filter, newest first, following the cursors."""
        args: dict[str, Any] = {
            "day": day,
            "start": start,
            "end": end,
            "timezone": timezone,
            "limit": limit,
        }
        cursor = None
        while True:
            page = (await self.get_routes_page(vehicle_id, cursor=cursor, **args)).data
            for route in page.items:
                yield route
            if not page.next_cursor:
                return
            cursor = page.next_cursor
            # Later pages must use the window of the first, or "now" moves under the cursor.
            f = page.filter or {}
            args.update(
                day=f.get("day"), start=f.get("from"), end=f.get("to"), timezone=f.get("timezone")
            )

    async def get_route(
        self, vehicle_id: str, route_id: str, *, geometry: bool = False, simplify: bool = False
    ) -> Response[Route]:
        """One route. ``geometry`` adds GeoJSON (left out when over 40 KB); ``simplify``
        thins it to fit and implies ``geometry``."""
        return await self._get(
            f"/vehicles/{self._id(vehicle_id)}/routes/{self._id(route_id)}",
            lambda d: Route.from_json(d["route"]),
            {"geometry": geometry or None, "simplify": simplify or None},
        )

    async def get_ride_stats(
        self,
        vehicle_id: str,
        start: date | str,
        end: date | str,
        *,
        timezone: str | None = None,
    ) -> Response[RideStats]:
        """Rides per local day from ``start`` to ``end`` inclusive (at most 90 days)."""
        return await self._get(
            f"/vehicles/{self._id(vehicle_id)}/stats",
            RideStats.from_json,
            {"from": start, "to": end, "timezone": timezone},
        )

    # -- connections (a personal key with "Manage connections") ------------

    async def get_connections(self) -> Response[tuple[Connection, ...]]:
        """Every app and personal key connected to the account."""
        return await self._get(
            "/me/connections",
            lambda d: tuple(Connection.from_json(c) for c in d["connections"]),
        )

    async def delete_connection(self, connection_id: str) -> None:
        """Revoke a connection; its tokens stop working at once. Repeating is fine."""
        token = await self._bearer()
        await self._send("DELETE", f"/me/connections/{self._id(connection_id)}", {}, token, None)
        self._cache.pop(self._cache_key(token, "/me/connections", {}), None)

    # -- helpers -----------------------------------------------------------

    @staticmethod
    async def _items[T](
        fetch: Callable[[str | None], Awaitable[Response[Page[T]]]],
    ) -> AsyncIterator[T]:
        cursor = None
        while True:
            page = (await fetch(cursor)).data
            for item in page.items:
                yield item
            if not page.next_cursor:
                return
            cursor = page.next_cursor

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

import aiomapit
from aiomapit import (
    EventType,
    MapitAuthError,
    MapitClient,
    MapitConnectionError,
    MapitError,
    MapitNotFound,
    MapitRateLimited,
    MapitResponseError,
    MapitScopeError,
)

BASE = "https://api.mapit.me/v1"

VEHICLE = {
    "id": "veh_1",
    "name": "Forza",
    "registrationNumber": "1234ABC",
    "model": "Forza 750",
    "km": 1234.5,
    "products": ["Mapit Connect"],
    "cancelled": False,
    "blockedByTransfer": False,
}
STATUS = {
    "vehicleId": "veh_1",
    "state": {
        "status": "parked",
        "batteryPercent": 80,
        "voltage": 0,
        "latitude": 41.38,
        "longitude": 2.17,
        "lastCommunicationAt": "2026-11-17T08:00:00.000Z",
        "lastLocationAt": None,
    },
    "voltageNote": "0 is normal while parked",
    "source": "device",
    "fetchedAt": "2026-11-17T08:01:00.000Z",
}
ROUTE = {
    "id": "rte_1",
    "vehicleId": "veh_1",
    "startedAt": "2026-11-16T10:00:00.000Z",
    "endedAt": "2026-11-16T10:30:00.000Z",
    "distanceMeters": 12000,
    "durationSeconds": 1800,
    "avgSpeedKmh": 40,
    "maxSpeedKmh": 90,
    "startTimezone": "Europe/Madrid",
}
EVENT = {
    "id": "evt_1",
    "type": "geofence_entered",
    "vehicleId": "veh_1",
    "occurredAt": "2026-11-18T08:01:12.000Z",
    "notifiedAt": "2026-11-18T08:01:30.000Z",
    "geofence": {"name": "Home"},
}
CONNECTION = {
    "id": "con_1",
    "kind": "personal_key",
    "name": "script",
    "builtIn": False,
    "api": "rest",
    "scopes": ["mapit:read", "mapit:connections"],
    "createdAt": "2026-11-01T00:00:00.000Z",
    "expiresAt": "2027-11-01T00:00:00.000Z",
    "current": True,
}


def sent(mocked: aioresponses, method: str, url: str) -> Any:
    (call,) = mocked.requests[(method, URL(url))]
    return call


# -- endpoints ---------------------------------------------------------------


async def test_me(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(f"{BASE}/me", payload={"id": "acc_abc", "name": "Ana", "email": "ana@example.com"})
    res = await client.get_me()
    assert (res.data.id, res.data.name, res.data.email, res.not_modified) == (
        "acc_abc",
        "Ana",
        "ana@example.com",
        False,
    )
    call = sent(mocked, "GET", f"{BASE}/me")
    assert call.kwargs["headers"]["Authorization"] == "Bearer mapit_key"
    assert call.kwargs["headers"]["User-Agent"].startswith("aiomapit/")


async def test_me_without_id(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(f"{BASE}/me", payload={"name": "Ana", "email": "ana@example.com"})
    assert (await client.get_me()).data.id is None


async def test_summary(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(
        f"{BASE}/summary?transferCursor=t1&vehicleCursor=v1",
        payload={
            "generatedAt": "2026-11-17T08:00:00.000Z",
            "account": {
                "name": "Ana",
                "email": "ana@example.com",
                "preferences": {"locale": "es", "timezone": "Europe/Madrid"},
                "subscriptionBalanceDays": 12,
            },
            "vehicles": [
                {
                    **VEHICLE,
                    "device": {"model": "M510"},
                    "subscription": {"status": "active", "periodEnd": None, "cancelAtEnd": False},
                }
            ],
            "incomingTransfers": [{"products": ["Honda Plus"], "expired": True}],
            "page": {
                "vehicleCount": 1,
                "incomingTransferCount": 1,
                "nextVehicleCursor": "v2",
                "nextTransferCursor": None,
            },
            "dataCoverage": {"source": "stored_account_records"},
        },
    )
    s = (await client.get_summary(vehicle_cursor="v1", transfer_cursor="t1")).data
    assert (s.name, s.locale, s.timezone, s.subscription_balance_days) == (
        "Ana",
        "es",
        "Europe/Madrid",
        12,
    )
    assert s.vehicles[0].device_model == "M510"
    assert s.vehicles[0].subscription is not None
    assert s.vehicles[0].subscription.status == "active"
    assert s.incoming_transfers[0].expired
    assert (s.next_vehicle_cursor, s.next_transfer_cursor) == ("v2", None)
    assert s.generated_at == datetime(2026, 11, 17, 8, tzinfo=UTC)


async def test_vehicles_and_vehicle(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(f"{BASE}/vehicles", payload={"vehicles": [VEHICLE], "nextCursor": None})
    mocked.get(f"{BASE}/vehicles/veh_1", payload=VEHICLE)
    page = (await client.get_vehicles_page()).data
    v = page.items[0]
    assert page.next_cursor is None
    assert (v.id, v.registration_number, v.km, v.products) == (
        "veh_1",
        "1234ABC",
        1234.5,
        ("Mapit Connect",),
    )
    assert (await client.get_vehicle("veh_1")).data == v


async def test_subscription(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(
        f"{BASE}/vehicles/veh_1/subscription",
        payload={
            "subscription": {
                "status": "active",
                "periodEnd": "2027-01-01T00:00:00.000Z",
                "cancelAtEnd": True,
            }
        },
    )
    mocked.get(f"{BASE}/vehicles/veh_2/subscription", payload={"subscription": None})
    sub = (await client.get_subscription("veh_1")).data
    assert sub is not None
    assert (sub.status, sub.cancel_at_end, sub.period_end) == (
        "active",
        True,
        datetime(2027, 1, 1, tzinfo=UTC),
    )
    assert (await client.get_subscription("veh_2")).data is None


async def test_statuses_and_vehicle_status(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(
        f"{BASE}/status", payload={"vehicles": [STATUS], "nextCursor": "c2", "eventsCursor": "e1"}
    )
    mocked.get(f"{BASE}/vehicles/veh_1/status", payload=STATUS)
    mocked.get(
        f"{BASE}/vehicles/veh_2/status",
        payload={"vehicleId": "veh_2", "state": None, "reason": "no_linked_device"},
    )
    page = (await client.get_statuses_page()).data
    assert (page.next_cursor, page.events_cursor) == ("c2", "e1")
    state = page.items[0].state
    assert state is not None
    assert (state.status, state.battery_percent, state.voltage, state.latitude) == (
        "parked",
        80,
        0,
        41.38,
    )
    assert state.last_location_at is None
    assert state.last_communication_at == datetime(2026, 11, 17, 8, tzinfo=UTC)
    assert page.items[0].voltage_note == "0 is normal while parked"
    assert (await client.get_vehicle_status("veh_1")).data == page.items[0]
    none = (await client.get_vehicle_status("veh_2")).data
    assert (none.state, none.reason, none.fetched_at) == (None, "no_linked_device", None)


async def test_events_page(mocked: aioresponses, client: MapitClient) -> None:
    later = {**EVENT, "id": "evt_2", "type": "tow_detected", "geofence": None}
    mocked.get(
        f"{BASE}/events?cursor=cur_a&limit=2",
        payload={
            "events": [EVENT, later],
            "nextCursor": "cur_b",
            "hasMore": True,
            "fetchedAt": "2026-11-18T08:02:00.000Z",
        },
    )
    page = (await client.get_events_page("cur_a", limit=2)).data
    first, second = page.items
    assert (first.id, first.type, first.vehicle_id, first.geofence_name) == (
        "evt_1",
        EventType.GEOFENCE_ENTERED,
        "veh_1",
        "Home",
    )
    assert first.occurred_at == datetime(2026, 11, 18, 8, 1, 12, tzinfo=UTC)
    assert first.notified_at == datetime(2026, 11, 18, 8, 1, 30, tzinfo=UTC)
    # A type added to the API later is still parsed, as unknown.
    assert (second.type, second.geofence_name) == (EventType.UNKNOWN, None)
    assert (page.next_cursor, page.has_more) == ("cur_b", True)


async def test_events_page_304_keeps_the_cursor(mocked: aioresponses, client: MapitClient) -> None:
    empty = {"events": [], "nextCursor": "cur_a", "fetchedAt": "2026-11-18T08:02:00.000Z"}
    mocked.get(f"{BASE}/events?cursor=cur_a", payload=empty, headers={"ETag": 'W/"e"'})
    mocked.get(f"{BASE}/events?cursor=cur_a", status=304)
    first = await client.get_events_page("cur_a")
    again = await client.get_events_page("cur_a")
    assert (again.not_modified, again.data) == (True, first.data)
    assert again.data.next_cursor == "cur_a"
    assert not again.data.has_more
    second = mocked.requests[("GET", URL(f"{BASE}/events?cursor=cur_a"))][1]
    assert second.kwargs["headers"]["If-None-Match"] == 'W/"e"'


async def test_routes_page_sends_filters(mocked: aioresponses, client: MapitClient) -> None:
    start = datetime(2026, 11, 1, tzinfo=timezone(timedelta(hours=1)))
    url = (
        f"{BASE}/vehicles/veh_1/routes?cursor=c&from={quote(start.isoformat())}"
        "&limit=5&timezone=Europe%2FMadrid&to=2026-11-10T00%3A00%3A00%2B01%3A00"
    )
    mocked.get(
        url,
        payload={"routes": [ROUTE], "nextCursor": None, "filter": {"timezone": "Europe/Madrid"}},
    )
    page = (
        await client.get_routes_page(
            "veh_1",
            start=start,
            end="2026-11-10T00:00:00+01:00",
            timezone="Europe/Madrid",
            limit=5,
            cursor="c",
        )
    ).data
    r = page.items[0]
    assert (r.id, r.distance_meters, r.start_timezone, r.geometry) == (
        "rte_1",
        12000,
        "Europe/Madrid",
        None,
    )
    assert r.started_at == datetime(2026, 11, 16, 10, tzinfo=UTC)
    assert page.filter == {"timezone": "Europe/Madrid"}


async def test_routes_day_filter(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(
        f"{BASE}/vehicles/veh_1/routes?day=2026-11-16",
        payload={"routes": [], "nextCursor": None, "filter": {"day": "2026-11-16"}},
    )
    assert (await client.get_routes_page("veh_1", day=date(2026, 11, 16))).data.items == ()


async def test_naive_datetime_is_refused(client: MapitClient) -> None:
    with pytest.raises(ValueError, match="timezone"):
        await client.get_routes_page("veh_1", start=datetime(2026, 11, 1), end="x")


async def test_route_geometry(mocked: aioresponses, client: MapitClient) -> None:
    geometry = {"type": "LineString", "coordinates": [[2.17, 41.38], [2.18, 41.39]]}
    mocked.get(
        f"{BASE}/vehicles/veh_1/routes/rte_1?geometry=true&simplify=true",
        payload={
            "route": {
                **ROUTE,
                "geometry": geometry,
                "geometryToleranceMeters": 5,
                "maxSpeedDisplay": "+180",
            }
        },
    )
    mocked.get(f"{BASE}/vehicles/veh_1/routes/rte_1", payload={"route": ROUTE})
    r = (await client.get_route("veh_1", "rte_1", simplify=True, geometry=True)).data
    assert (r.geometry, r.geometry_tolerance_meters, r.max_speed_display) == (geometry, 5, "+180")
    plain = (await client.get_route("veh_1", "rte_1")).data
    assert (plain.geometry, plain.geometry_omitted) == (None, False)


async def test_ride_stats(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(
        f"{BASE}/vehicles/veh_1/stats?from=2026-11-01&timezone=Europe%2FMadrid&to=2026-11-02",
        payload={
            "vehicleId": "veh_1",
            "period": {"from": "2026-11-01", "to": "2026-11-02", "timezone": "Europe/Madrid"},
            "totals": {
                "rides": 2,
                "distanceKm": 24.5,
                "ridingHours": 1.0,
                "avgSpeedKmh": 40,
                "maxSpeedKmh": None,
            },
            "days": [
                {
                    "date": "2026-11-01",
                    "rides": 2,
                    "distanceKm": 24.5,
                    "ridingHours": 1.0,
                    "avgSpeedKmh": 40,
                    "maxSpeedKmh": None,
                }
            ],
            "truncated": True,
            "method": "Same rules as the app",
        },
    )
    s = (
        await client.get_ride_stats(
            "veh_1", date(2026, 11, 1), "2026-11-02", timezone="Europe/Madrid"
        )
    ).data
    assert (s.start, s.end, s.totals.rides, s.totals.distance_km, s.truncated) == (
        date(2026, 11, 1),
        date(2026, 11, 2),
        2,
        24.5,
        True,
    )
    assert (s.days[0].day, s.days[0].max_speed_kmh) == (date(2026, 11, 1), None)


async def test_connections(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(f"{BASE}/me/connections", payload={"connections": [CONNECTION]})
    (c,) = (await client.get_connections()).data
    assert (c.id, c.kind, c.api, c.current, c.built_in) == (
        "con_1",
        "personal_key",
        "rest",
        True,
        False,
    )
    assert c.scopes == ("mapit:read", "mapit:connections")
    assert c.expires_at == datetime(2027, 11, 1, tzinfo=UTC)


async def test_delete_connection(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(
        f"{BASE}/me/connections", payload={"connections": [CONNECTION]}, headers={"ETag": 'W/"a"'}
    )
    mocked.delete(f"{BASE}/me/connections/con_1", status=204)
    mocked.get(f"{BASE}/me/connections", payload={"connections": []}, headers={"ETag": 'W/"b"'})
    await client.get_connections()
    await client.delete_connection("con_1")
    # The list is read again from scratch: no stale tag is sent.
    res = await client.get_connections()
    assert res.data == ()
    second = mocked.requests[("GET", URL(f"{BASE}/me/connections"))][1]
    assert "If-None-Match" not in second.kwargs["headers"]


async def test_delete_connection_not_found(mocked: aioresponses, client: MapitClient) -> None:
    mocked.delete(f"{BASE}/me/connections/con_x", status=404)
    with pytest.raises(MapitNotFound):
        await client.delete_connection("con_x")


# -- pagination --------------------------------------------------------------


async def test_iter_vehicles_follows_cursors(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(f"{BASE}/vehicles", payload={"vehicles": [VEHICLE], "nextCursor": "c2"})
    mocked.get(
        f"{BASE}/vehicles?cursor=c2",
        payload={"vehicles": [{**VEHICLE, "id": "veh_2"}], "nextCursor": None},
    )
    assert [v.id async for v in client.iter_vehicles()] == ["veh_1", "veh_2"]


async def test_iter_statuses_follows_cursors(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(f"{BASE}/status", payload={"vehicles": [STATUS], "nextCursor": "c2"})
    mocked.get(
        f"{BASE}/status?cursor=c2",
        payload={"vehicles": [{**STATUS, "vehicleId": "veh_2"}], "nextCursor": None},
    )
    assert [s.vehicle_id async for s in client.iter_statuses()] == ["veh_1", "veh_2"]


async def test_iter_events_follows_has_more(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(
        f"{BASE}/events?limit=1", payload={"events": [EVENT], "nextCursor": "c2", "hasMore": True}
    )
    mocked.get(
        f"{BASE}/events?cursor=c2&limit=1",
        payload={"events": [{**EVENT, "id": "evt_2"}], "nextCursor": "c3", "hasMore": False},
    )
    assert [e.id async for e in client.iter_events(limit=1)] == ["evt_1", "evt_2"]


async def test_iter_routes_reuses_the_first_window(
    mocked: aioresponses, client: MapitClient
) -> None:
    window = {
        "from": "2026-10-18T08:00:00.000Z",
        "to": "2026-11-17T08:00:00.000Z",
        "timezone": "Europe/Madrid",
    }
    mocked.get(
        f"{BASE}/vehicles/veh_1/routes?limit=1",
        payload={"routes": [ROUTE], "nextCursor": "c2", "filter": window},
    )
    mocked.get(
        f"{BASE}/vehicles/veh_1/routes?cursor=c2&from=2026-10-18T08%3A00%3A00.000Z"
        "&limit=1&timezone=Europe%2FMadrid&to=2026-11-17T08%3A00%3A00.000Z",
        payload={"routes": [{**ROUTE, "id": "rte_2"}], "nextCursor": None, "filter": window},
    )
    assert [r.id async for r in client.iter_routes("veh_1", limit=1)] == ["rte_1", "rte_2"]


# -- errors ------------------------------------------------------------------

PROBLEM = {"type": "about:blank", "title": "Unauthorized", "status": 401, "detail": "Token expired"}
JSON = {"Content-Type": "application/problem+json"}


async def test_401(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(f"{BASE}/me", status=401, payload=PROBLEM, headers=JSON)
    with pytest.raises(MapitAuthError) as e:
        await client.get_me()
    assert (e.value.status, e.value.title, e.value.detail) == (401, "Unauthorized", "Token expired")
    assert isinstance(e.value, MapitError)
    assert "Token expired" in str(e.value)


async def test_403_insufficient_scope(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(
        f"{BASE}/status",
        status=403,
        payload={
            "title": "Insufficient scope",
            "status": 403,
            "detail": "This connection was not given mapit:location:read.",
        },
        headers={
            **JSON,
            "WWW-Authenticate": (
                'Bearer error="insufficient_scope", scope="mapit:read mapit:location:read"'
            ),
        },
    )
    with pytest.raises(MapitScopeError) as e:
        await client.get_statuses_page()
    assert e.value.scope == "mapit:location:read"
    assert e.value.status == 403


async def test_403_scope_from_detail_when_header_is_missing(
    mocked: aioresponses, client: MapitClient
) -> None:
    mocked.get(
        f"{BASE}/me/connections",
        status=403,
        payload={
            "title": "Insufficient scope",
            "detail": "This connection was not given mapit:connections.",
        },
        headers={"WWW-Authenticate": 'Bearer error="insufficient_scope"'},
    )
    with pytest.raises(MapitScopeError) as e:
        await client.get_connections()
    assert e.value.scope == "mapit:connections"


async def test_403_without_insufficient_scope_is_a_plain_error(
    mocked: aioresponses, client: MapitClient
) -> None:
    mocked.get(f"{BASE}/me", status=403, body="Forbidden")
    with pytest.raises(MapitError) as e:
        await client.get_me()
    assert type(e.value) is MapitError
    assert e.value.status == 403


async def test_404(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(
        f"{BASE}/vehicles/veh_x",
        status=404,
        payload={"title": "Not found", "status": 404},
        headers=JSON,
    )
    with pytest.raises(MapitNotFound) as e:
        await client.get_vehicle("veh_x")
    assert e.value.title == "Not found"


async def test_429_retry_after(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(
        f"{BASE}/me",
        status=429,
        payload={"title": "Too many requests", "status": 429},
        headers={**JSON, "Retry-After": "17"},
    )
    mocked.get(f"{BASE}/me", status=429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    with pytest.raises(MapitRateLimited) as e:
        await client.get_me()
    assert e.value.retry_after == 17
    with pytest.raises(MapitRateLimited) as e2:
        await client.get_me()
    assert e2.value.retry_after is None


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_5xx(mocked: aioresponses, client: MapitClient, status: int) -> None:
    mocked.get(f"{BASE}/me", status=status, body="<html>bad gateway</html>")
    with pytest.raises(MapitConnectionError) as e:
        await client.get_me()
    assert e.value.status == status


async def test_503_problem_body(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(f"{BASE}/me", status=503, payload={"title": "Temporarily unavailable"}, headers=JSON)
    with pytest.raises(MapitConnectionError, match="Temporarily unavailable"):
        await client.get_me()


async def test_400_is_a_plain_error(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(
        f"{BASE}/vehicles/veh_1/stats?from=a&to=b",
        status=400,
        payload={"title": "Invalid request", "detail": "Use from and to as YYYY-MM-DD"},
        headers=JSON,
    )
    with pytest.raises(MapitError, match="YYYY-MM-DD") as e:
        await client.get_ride_stats("veh_1", "a", "b")
    assert e.value.status == 400


@pytest.mark.parametrize("failure", [aiohttp.ClientConnectionError("down"), TimeoutError()])
async def test_network_failure(
    mocked: aioresponses, client: MapitClient, failure: Exception
) -> None:
    mocked.get(f"{BASE}/me", exception=failure)
    with pytest.raises(MapitConnectionError):
        await client.get_me()


async def test_invalid_json(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(f"{BASE}/me", body="not json")
    with pytest.raises(MapitError, match="not valid JSON"):
        await client.get_me()


async def test_unexpected_shape(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(f"{BASE}/me", payload={"nope": 1})
    with pytest.raises(MapitResponseError, match="Unexpected response"):
        await client.get_me()


# -- ETag --------------------------------------------------------------------


async def test_etag_round_trip(mocked: aioresponses, client: MapitClient) -> None:
    url = f"{BASE}/vehicles/veh_1/status"
    mocked.get(url, payload=STATUS, headers={"ETag": 'W/"abc"'})
    mocked.get(url, status=304)
    mocked.get(url, payload={**STATUS, "state": None}, headers={"ETag": 'W/"def"'})
    mocked.get(url, status=304)
    first = await client.get_vehicle_status("veh_1")
    second = await client.get_vehicle_status("veh_1")
    third = await client.get_vehicle_status("veh_1")
    fourth = await client.get_vehicle_status("veh_1")
    assert (first.not_modified, first.etag) == (False, 'W/"abc"')
    assert second.not_modified
    assert second.data is first.data
    assert second.etag == 'W/"abc"'
    assert (third.not_modified, third.data.state, third.etag) == (False, None, 'W/"def"')
    assert fourth.not_modified
    assert fourth.data is third.data
    calls = mocked.requests[("GET", URL(url))]
    sent_tags = [c.kwargs["headers"].get("If-None-Match") for c in calls]
    assert sent_tags == [None, 'W/"abc"', 'W/"abc"', 'W/"def"']


async def test_etag_is_per_url_and_query(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(
        f"{BASE}/vehicles", payload={"vehicles": [], "nextCursor": "c"}, headers={"ETag": 'W/"p1"'}
    )
    mocked.get(
        f"{BASE}/vehicles?cursor=c",
        payload={"vehicles": [], "nextCursor": None},
        headers={"ETag": 'W/"p2"'},
    )
    await client.get_vehicles_page()
    await client.get_vehicles_page("c")
    (second,) = mocked.requests[("GET", URL(f"{BASE}/vehicles?cursor=c"))]
    assert "If-None-Match" not in second.kwargs["headers"]


async def test_response_without_etag_is_not_cached(
    mocked: aioresponses, client: MapitClient
) -> None:
    mocked.get(f"{BASE}/me", payload={"name": "A", "email": "a@x"}, repeat=True)
    await client.get_me()
    await client.get_me()
    calls = mocked.requests[("GET", URL(f"{BASE}/me"))]
    assert all("If-None-Match" not in c.kwargs["headers"] for c in calls)


async def test_304_without_cache_is_an_error(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(f"{BASE}/me", status=304)
    with pytest.raises(MapitError, match="304"):
        await client.get_me()


async def test_cache_is_bounded(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(
        f"{BASE}/vehicles/veh_1/subscription",
        payload={"subscription": None},
        headers={"ETag": 'W/"x"'},
        repeat=True,
    )
    for i in range(300):
        mocked.get(f"{BASE}/vehicles/v{i}", payload=VEHICLE, headers={"ETag": f'W/"{i}"'})
        await client.get_vehicle(f"v{i}")
    assert len(client._cache) == 256


# -- auth and session --------------------------------------------------------


async def test_token_callback_is_called_for_every_request(mocked: aioresponses) -> None:
    tokens = iter(["one", "two"])

    async def token() -> str:
        return next(tokens)

    mocked.get(f"{BASE}/me", payload={"name": "A", "email": "a@x"}, repeat=True)
    async with aiohttp.ClientSession() as session:
        client = MapitClient(token, session=session)
        await client.get_me()
        await client.get_me()
    calls = mocked.requests[("GET", URL(f"{BASE}/me"))]
    assert [c.kwargs["headers"]["Authorization"] for c in calls] == ["Bearer one", "Bearer two"]


async def test_owned_session_is_created_lazily_and_closed(mocked: aioresponses) -> None:
    mocked.get(f"{BASE}/me", payload={"name": "A", "email": "a@x"})
    async with MapitClient("k", user_agent="HomeAssistant/2026.8", base_url=BASE + "/") as client:
        assert client._session is None
        await client.get_me()
        session = client._session
        assert session is not None
        assert not session.closed
    assert session.closed
    call = sent(mocked, "GET", f"{BASE}/me")
    assert call.kwargs["headers"]["User-Agent"] == "HomeAssistant/2026.8"


async def test_given_session_is_left_open(mocked: aioresponses) -> None:
    async with aiohttp.ClientSession() as session:
        await MapitClient("k", session=session).close()
        assert not session.closed


async def test_ids_are_quoted(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(f"{BASE}/vehicles/a%2Fb", payload=VEHICLE)
    assert (await client.get_vehicle("a/b")).data.id == "veh_1"


async def test_403_scope_unknown(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(
        f"{BASE}/me",
        status=403,
        body="[]",
        headers={"WWW-Authenticate": 'Bearer error="insufficient_scope"'},
    )
    with pytest.raises(MapitScopeError) as e:
        await client.get_me()
    assert e.value.scope is None
    assert e.value.title is None


async def test_undecodable_body_is_a_mapit_error(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(f"{BASE}/me", body=b"\xff\xfe\xfa not utf-8")
    with pytest.raises(MapitResponseError) as e:
        await client.get_me()
    assert isinstance(e.value, MapitError)
    assert e.value.status == 200


async def test_undecodable_error_body_keeps_the_status_mapping(
    mocked: aioresponses, client: MapitClient
) -> None:
    mocked.get(f"{BASE}/me", status=401, body=b"\xff\xfe\xfa")
    with pytest.raises(MapitAuthError) as e:
        await client.get_me()
    assert e.value.title is None


async def test_timeout_has_a_useful_message(mocked: aioresponses) -> None:
    mocked.get(f"{BASE}/me", exception=TimeoutError())
    async with MapitClient("k", timeout=2.5) as client:
        with pytest.raises(MapitConnectionError) as e:
            await client.get_me()
    assert "2.5 s" in str(e.value)
    assert isinstance(e.value.__cause__, TimeoutError)


async def test_client_error_without_text_names_its_type(
    mocked: aioresponses, client: MapitClient
) -> None:
    mocked.get(f"{BASE}/me", exception=aiohttp.ServerDisconnectedError())
    with pytest.raises(MapitConnectionError, match=r"Cannot reach the Mapit API: \w+"):
        await client.get_me()


async def test_two_tokens_never_share_a_cached_object(mocked: aioresponses) -> None:
    current = "token-a"

    async def token() -> str:
        return current

    url = f"{BASE}/me"
    mocked.get(url, payload={"name": "Ana", "email": "a@x"}, headers={"ETag": 'W/"a"'})
    mocked.get(url, payload={"name": "Bea", "email": "b@x"}, headers={"ETag": 'W/"b"'})
    mocked.get(url, status=304)
    mocked.get(url, status=304)
    async with aiohttp.ClientSession() as session:
        client = MapitClient(token, session=session)
        a = await client.get_me()
        current = "token-b"
        b = await client.get_me()
        a_again = await client.get_me()  # token-b still: 304 for b's tag
        current = "token-a"
        a_cached = await client.get_me()
    assert (a.data.name, b.data.name) == ("Ana", "Bea")
    assert not b.not_modified
    assert a_again.not_modified
    assert a_again.data is b.data
    assert a_cached.not_modified
    assert a_cached.data is a.data
    tags = [c.kwargs["headers"].get("If-None-Match") for c in mocked.requests[("GET", URL(url))]]
    # B's first request did not carry A's tag, and A got its own back.
    assert tags == [None, None, 'W/"b"', 'W/"a"']


async def test_untagged_answer_drops_the_old_tag(mocked: aioresponses, client: MapitClient) -> None:
    mocked.get(f"{BASE}/me", payload={"name": "A", "email": "a@x"}, headers={"ETag": 'W/"1"'})
    mocked.get(f"{BASE}/me", payload={"name": "B", "email": "b@x"})
    mocked.get(f"{BASE}/me", payload={"name": "C", "email": "c@x"})
    for _ in range(3):
        await client.get_me()
    tags = [
        c.kwargs["headers"].get("If-None-Match")
        for c in mocked.requests[("GET", URL(f"{BASE}/me"))]
    ]
    assert tags == [None, 'W/"1"', None]


def test_version_is_available_without_a_client() -> None:
    assert aiomapit.__version__ == "0.2.0"

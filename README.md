# aiomapit: the official Python client for the Mapit API

Made and maintained by [Mapit](https://mapit.me). Mapit lists its official and approved apps at <https://developers.mapit.me/approved-apps>. Other projects that use Mapit are not endorsed by Mapit unless they are listed there.

Async Python client for the [Mapit](https://mapit.me) API (`https://api.mapit.me/v1`): the account,
vehicles, last reported position and routes that the Mapit app shows. Read-only, apart from disconnecting
apps and keys (`delete_connection`, which needs the Manage connections permission). Built on `aiohttp`,
fully typed. Used by the Home Assistant integration.

> **Beta, free for now.** The Mapit API it talks to is a beta: it may change or stop, it has no uptime promise, and Mapit does not charge for it today. This library may need updates to follow it. Do not rely on it for emergencies or to recover a stolen bike: use the Mapit app. Use is subject to the [Mapit API Terms of Use](https://developers.mapit.me/terms) and [Privacy Notice](https://developers.mapit.me/privacy), for personal, non-commercial use.

```
pip install aiomapit
```

Python 3.12 or newer.

## A personal key (your own scripts)

You need a Mapit account. Create a key at <https://login.mapit.me/connections> and pass it as the token.
Location, route history and managing connections each need their own permission, ticked when the key
is created (see [personal keys](https://developers.mapit.me/keys)).

```python
import asyncio

from aiomapit import MapitClient


async def main() -> None:
    async with MapitClient("mapit_...") as client:
        async for status in client.iter_statuses():
            if status.state:
                print(status.vehicle_id, status.state.latitude, status.state.longitude)


asyncio.run(main())
```

## A token callback (apps that do OAuth themselves)

This is for apps that Mapit has approved (see [Approved apps](https://developers.mapit.me/approved-apps)); anything built for other Mapit customers needs Mapit's written approval. The
OAuth flow itself is described at <https://developers.mapit.me/oauth>. The library has no OAuth logic. Give it an async callable that returns a valid access token; it is
called before every request, so it may refresh. Share your own `aiohttp.ClientSession`:

```python
async def token() -> str:
    await oauth_session.async_ensure_token_valid()
    return oauth_session.token["access_token"]


client = MapitClient(token, session=session, user_agent="my-app/1.0")
vehicles = [v async for v in client.iter_vehicles()]
```

Without `session`, the client creates one and closes it in `close()` (or when leaving `async with`).
With one, the session stays yours.

## What it covers

| Method | Endpoint |
| --- | --- |
| `get_me()` (an `Account` with `id`, `name`, `email`; `id` is stable across email changes) | `GET /me` |
| `get_summary(vehicle_cursor=, transfer_cursor=)` | `GET /summary` |
| `get_vehicles_page(cursor)`, `iter_vehicles()` | `GET /vehicles` |
| `get_vehicle(id)`, `get_subscription(id)` | `GET /vehicles/{id}`, `.../subscription` |
| `get_statuses_page(cursor)`, `iter_statuses()`, `get_vehicle_status(id)` (Location permission) | `GET /status`, `/vehicles/{id}/status` |
| `get_routes_page(id, day=, start=, end=, ...)`, `iter_routes(id, ...)` (Route history permission) | `GET /vehicles/{id}/routes` |
| `get_route(id, route_id, geometry=, simplify=)` (Route history) | `GET /vehicles/{id}/routes/{route_id}` |
| `get_ride_stats(id, start, end, timezone=)` (Route history) | `GET /vehicles/{id}/stats` |
| `get_connections()`, `delete_connection(id)` | `GET`, `DELETE /me/connections` (a personal key with "Manage connections") |

Ids and cursors are opaque: pass them back as you got them. `iter_*` follow the cursors for you.
The API allows 30 requests a minute per key or token, and positions are what the device last
reported, so poll `iter_statuses()` once a minute at most.

Every `get_*` returns a `Response` with `data` (a frozen dataclass, snake_case fields),
`not_modified` and `etag`.

## ETag and 304

The client remembers the `ETag` of what it fetched (in memory, per URL and query) and sends it as
`If-None-Match`. On `304` you get the earlier object back with `not_modified=True`:

```python
res = await client.get_vehicle_status(vehicle_id)
if not res.not_modified:
    update(res.data)
```

The cache key includes the token, so two tokens never share an object; a refreshed OAuth token starts
with a fresh cache. A 304 saves bandwidth and parsing, not quota: it still counts towards the 30 requests a minute.
The routes list without a `day` or `start`/`end` is "the last 30 days to now" and never answers 304.

## Errors

All derive from `MapitError`, which has `status`, `title` and `detail` from the
`application/problem+json` body.

| Raised | When |
| --- | --- |
| `MapitAuthError` | 401: missing, expired or revoked token |
| `MapitScopeError` | 403 `insufficient_scope`; `.scope` is the missing scope |
| `MapitNotFound` | 404: also for a foreign or unknown id |
| `MapitRateLimited` | 429; `.retry_after` in seconds, or `None` |
| `MapitConnectionError` | 5xx, timeout, network failure |
| `MapitResponseError` | a 2xx answer that is not valid JSON or lacks the expected fields |

Other statuses (such as 400 for a bad filter) raise `MapitError` itself. The client never retries:
back off on `MapitRateLimited` and `MapitConnectionError` yourself.

## Development

```
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

## Help

Docs and API reference: <https://developers.mapit.me>. Questions: atencioncliente@mapit.me.

MIT licence.

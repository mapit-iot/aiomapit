# Changelog

## 0.2.0 - 2026-11-18

- Alerts the Mapit app pushed (`GET /v1/events`, Location permission): `get_events_page(cursor, limit)`
  and `iter_events()` return `Event` (`id`, `type`, `vehicle_id`, `occurred_at`, `notified_at`,
  `geofence_name`). `EventType` lists the types; ones added to the API later parse as `UNKNOWN`.
  `Page.has_more` says to fetch the next events page now.
- `Page.events_cursor` on status pages: it changes when there are new alerts.

## 0.1.1 - 2026-11-17

- README and project metadata: official Mapit client, Mapit API terms.

## 0.1.0 - 2026-11-17

First release: every `/v1` endpoint (account, summary, vehicles, subscription, status, routes,
route geometry, ride stats, connections), cursor pagination as async iterators, ETag and
`If-None-Match` with a cached object on 304, typed errors from `application/problem+json`.
`Account.id`: the stable account id from `/v1/me` (None from servers that predate it).

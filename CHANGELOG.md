# Changelog

## 0.1.0 - 2026-11-17

First release: every `/v1` endpoint (account, summary, vehicles, subscription, status, routes,
route geometry, ride stats, connections), cursor pagination as async iterators, ETag and
`If-None-Match` with a cached object on 304, typed errors from `application/problem+json`.
`Account.id`: the stable account id from `/v1/me` (None from servers that predate it).

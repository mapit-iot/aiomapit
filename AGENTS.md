# aiomapit

Async Python client for the Mapit API. The API is documented at https://developers.mapit.me
(reference and OpenAPI at https://api.mapit.me/v1/openapi.json). Library only: no OAuth, no global
session. Home Assistant depends on it, so keep it small, typed and dependency-free beyond aiohttp.

Checks (use a uv virtualenv): `uv sync`, then `uv run ruff check .`, `uv run ruff format --check .`,
`uv run mypy`, `uv run pytest` (coverage must stay at 100%). Tests mock HTTP with
aioresponses; `aiohttp<3.14` is pinned in the dev group because aioresponses does not support 3.14 yet.
Never merge your own PR.

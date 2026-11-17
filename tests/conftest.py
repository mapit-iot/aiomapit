from collections.abc import AsyncIterator, Iterator

import aiohttp
import pytest
from aioresponses import aioresponses

from aiomapit import MapitClient


@pytest.fixture
def mocked() -> Iterator[aioresponses]:
    with aioresponses() as m:
        yield m


@pytest.fixture
async def client() -> AsyncIterator[MapitClient]:
    async with aiohttp.ClientSession() as session:
        yield MapitClient("mapit_key", session=session)

"""Async Python client for the Mapit API."""

from ._version import __version__
from .client import DEFAULT_BASE_URL, MapitClient, TokenProvider
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
    DeviceState,
    IncomingTransfer,
    Page,
    Response,
    RideDay,
    RideStats,
    RideTotals,
    Route,
    Subscription,
    Summary,
    Vehicle,
    VehicleStatus,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "Account",
    "Connection",
    "DeviceState",
    "IncomingTransfer",
    "MapitAuthError",
    "MapitClient",
    "MapitConnectionError",
    "MapitError",
    "MapitNotFound",
    "MapitRateLimited",
    "MapitResponseError",
    "MapitScopeError",
    "Page",
    "Response",
    "RideDay",
    "RideStats",
    "RideTotals",
    "Route",
    "Subscription",
    "Summary",
    "TokenProvider",
    "Vehicle",
    "VehicleStatus",
    "__version__",
]

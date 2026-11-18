"""Frozen dataclasses for what the API returns, with snake_case field names."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

type Json = Mapping[str, Any]


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _req_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass(frozen=True, slots=True)
class Account:
    """``id`` is opaque and stable for the customer, also across email changes. It is None
    from servers that predate it."""

    name: str
    email: str
    id: str | None = None

    @classmethod
    def from_json(cls, d: Json) -> Account:
        return cls(name=d["name"], email=d["email"], id=d.get("id"))


@dataclass(frozen=True, slots=True)
class Subscription:
    status: str
    period_end: datetime | None
    cancel_at_end: bool

    @classmethod
    def from_json(cls, d: Json) -> Subscription:
        return cls(
            status=d["status"],
            period_end=_dt(d.get("periodEnd")),
            cancel_at_end=bool(d.get("cancelAtEnd", False)),
        )


@dataclass(frozen=True, slots=True)
class Vehicle:
    """``device_model`` and ``subscription`` are only filled by the summary."""

    id: str
    name: str | None
    registration_number: str | None
    model: str | None
    km: float | None
    products: tuple[str, ...]
    cancelled: bool
    blocked_by_transfer: bool
    device_model: str | None = None
    subscription: Subscription | None = None

    @classmethod
    def from_json(cls, d: Json) -> Vehicle:
        sub = d.get("subscription")
        device = d.get("device")
        return cls(
            id=d["id"],
            name=d.get("name"),
            registration_number=d.get("registrationNumber"),
            model=d.get("model"),
            km=d.get("km"),
            products=tuple(d.get("products") or ()),
            cancelled=bool(d.get("cancelled", False)),
            blocked_by_transfer=bool(d.get("blockedByTransfer", False)),
            device_model=device.get("model") if device else None,
            subscription=Subscription.from_json(sub) if sub else None,
        )


@dataclass(frozen=True, slots=True)
class DeviceState:
    """What the tracker last reported. ``voltage`` 0 or None is normal while parked."""

    status: str | None
    battery_percent: float | None
    voltage: float | None
    latitude: float | None
    longitude: float | None
    last_communication_at: datetime | None
    last_location_at: datetime | None

    @classmethod
    def from_json(cls, d: Json) -> DeviceState:
        return cls(
            status=d.get("status"),
            battery_percent=d.get("batteryPercent"),
            voltage=d.get("voltage"),
            latitude=d.get("latitude"),
            longitude=d.get("longitude"),
            last_communication_at=_dt(d.get("lastCommunicationAt")),
            last_location_at=_dt(d.get("lastLocationAt")),
        )


@dataclass(frozen=True, slots=True)
class VehicleStatus:
    """``state`` is None when there is no device data; ``reason`` then says why
    (``blocked_by_transfer``, ``subscription_cancelled`` or ``no_linked_device``)."""

    vehicle_id: str
    state: DeviceState | None
    reason: str | None
    voltage_note: str | None
    source: str | None
    fetched_at: datetime | None

    @classmethod
    def from_json(cls, d: Json) -> VehicleStatus:
        state = d.get("state")
        return cls(
            vehicle_id=d["vehicleId"],
            state=DeviceState.from_json(state) if state else None,
            reason=d.get("reason"),
            voltage_note=d.get("voltageNote"),
            source=d.get("source"),
            fetched_at=_dt(d.get("fetchedAt")),
        )


@dataclass(frozen=True, slots=True)
class Route:
    """``geometry`` is GeoJSON, only when asked for and small enough
    (``geometry_omitted`` says it was too large)."""

    id: str
    vehicle_id: str
    started_at: datetime
    ended_at: datetime | None
    distance_meters: float | None
    duration_seconds: float | None
    avg_speed_kmh: float | None
    max_speed_kmh: float | None
    start_timezone: str | None
    max_speed_display: str | None = None
    geometry: Json | None = None
    geometry_omitted: bool = False
    geometry_tolerance_meters: float | None = None

    @classmethod
    def from_json(cls, d: Json) -> Route:
        return cls(
            id=d["id"],
            vehicle_id=d["vehicleId"],
            started_at=_req_dt(d["startedAt"]),
            ended_at=_dt(d.get("endedAt")),
            distance_meters=d.get("distanceMeters"),
            duration_seconds=d.get("durationSeconds"),
            avg_speed_kmh=d.get("avgSpeedKmh"),
            max_speed_kmh=d.get("maxSpeedKmh"),
            start_timezone=d.get("startTimezone"),
            max_speed_display=d.get("maxSpeedDisplay"),
            geometry=d.get("geometry"),
            geometry_omitted=bool(d.get("geometryOmitted", False)),
            geometry_tolerance_meters=d.get("geometryToleranceMeters"),
        )


@dataclass(frozen=True, slots=True)
class RideTotals:
    rides: int
    distance_km: float
    riding_hours: float
    avg_speed_kmh: float | None
    max_speed_kmh: float | None

    @classmethod
    def from_json(cls, d: Json) -> RideTotals:
        return cls(
            rides=d["rides"],
            distance_km=d["distanceKm"],
            riding_hours=d["ridingHours"],
            avg_speed_kmh=d.get("avgSpeedKmh"),
            max_speed_kmh=d.get("maxSpeedKmh"),
        )


@dataclass(frozen=True, slots=True)
class RideDay(RideTotals):
    day: date

    @classmethod
    def from_json(cls, d: Json) -> RideDay:
        t = RideTotals.from_json(d)
        return cls(
            rides=t.rides,
            distance_km=t.distance_km,
            riding_hours=t.riding_hours,
            avg_speed_kmh=t.avg_speed_kmh,
            max_speed_kmh=t.max_speed_kmh,
            day=date.fromisoformat(d["date"]),
        )


@dataclass(frozen=True, slots=True)
class RideStats:
    """Per local day, with the Mapit app's own rules (see ``method``).
    Days without rides are left out. ``truncated`` is set when too many routes were read."""

    vehicle_id: str
    start: date
    end: date
    timezone: str
    totals: RideTotals
    days: tuple[RideDay, ...]
    truncated: bool
    method: str | None

    @classmethod
    def from_json(cls, d: Json) -> RideStats:
        period = d["period"]
        return cls(
            vehicle_id=d["vehicleId"],
            start=date.fromisoformat(period["from"]),
            end=date.fromisoformat(period["to"]),
            timezone=period["timezone"],
            totals=RideTotals.from_json(d["totals"]),
            days=tuple(RideDay.from_json(x) for x in d["days"]),
            truncated=bool(d.get("truncated", False)),
            method=d.get("method"),
        )


@dataclass(frozen=True, slots=True)
class IncomingTransfer:
    products: tuple[str, ...]
    expired: bool

    @classmethod
    def from_json(cls, d: Json) -> IncomingTransfer:
        return cls(products=tuple(d.get("products") or ()), expired=bool(d.get("expired", False)))


@dataclass(frozen=True, slots=True)
class Summary:
    """Account, vehicles with device and subscription, and incoming transfers.
    Page with ``next_vehicle_cursor`` and ``next_transfer_cursor``."""

    generated_at: datetime | None
    name: str
    email: str
    locale: str | None
    timezone: str | None
    subscription_balance_days: float | None
    vehicles: tuple[Vehicle, ...]
    incoming_transfers: tuple[IncomingTransfer, ...]
    next_vehicle_cursor: str | None
    next_transfer_cursor: str | None

    @classmethod
    def from_json(cls, d: Json) -> Summary:
        account = d["account"]
        prefs = account.get("preferences") or {}
        page = d.get("page") or {}
        return cls(
            generated_at=_dt(d.get("generatedAt")),
            name=account["name"],
            email=account["email"],
            locale=prefs.get("locale"),
            timezone=prefs.get("timezone"),
            subscription_balance_days=account.get("subscriptionBalanceDays"),
            vehicles=tuple(Vehicle.from_json(v) for v in d["vehicles"]),
            incoming_transfers=tuple(
                IncomingTransfer.from_json(t) for t in d.get("incomingTransfers", ())
            ),
            next_vehicle_cursor=page.get("nextVehicleCursor"),
            next_transfer_cursor=page.get("nextTransferCursor"),
        )


@dataclass(frozen=True, slots=True)
class Connection:
    """An app or personal key connected to the account."""

    id: str
    kind: str  # "app" or "personal_key"
    name: str  # as the app registered it: unverified unless ``built_in``
    built_in: bool
    api: str  # "rest" or "mcp"
    scopes: tuple[str, ...]
    created_at: datetime
    expires_at: datetime
    current: bool  # the key making this request

    @classmethod
    def from_json(cls, d: Json) -> Connection:
        return cls(
            id=d["id"],
            kind=d["kind"],
            name=d["name"],
            built_in=bool(d.get("builtIn", False)),
            api=d["api"],
            scopes=tuple(d.get("scopes") or ()),
            created_at=_req_dt(d["createdAt"]),
            expires_at=_req_dt(d["expiresAt"]),
            current=bool(d.get("current", False)),
        )


class EventType(StrEnum):
    """What an alert is about. ``UNKNOWN`` stands for types added to the API after this
    release: ignore them."""

    MOVEMENT_DETECTED = "movement_detected"  # also when a ride starts after a stop
    GEOFENCE_ENTERED = "geofence_entered"
    GEOFENCE_EXITED = "geofence_exited"
    IGNITION_ON_DETECTED = "ignition_on_detected"  # parked with the ignition on
    FALL_DETECTED = "fall_detected"
    ACCIDENT_DETECTED = "accident_detected"
    ACCIDENT_CONTACTS_NOTIFIED = "accident_contacts_notified"
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value: object) -> EventType:
        return cls.UNKNOWN


@dataclass(frozen=True, slots=True)
class Event:
    """An alert the Mapit app pushed. ``id`` is stable: skip one you have seen.
    ``occurred_at`` is never after ``notified_at``; ``geofence_name`` only on geofence events."""

    id: str
    type: EventType
    vehicle_id: str
    occurred_at: datetime
    notified_at: datetime
    geofence_name: str | None = None

    @classmethod
    def from_json(cls, d: Json) -> Event:
        geofence = d.get("geofence")
        return cls(
            id=d["id"],
            type=EventType(d["type"]),
            vehicle_id=d["vehicleId"],
            occurred_at=_req_dt(d["occurredAt"]),
            notified_at=_req_dt(d["notifiedAt"]),
            geofence_name=geofence.get("name") if geofence else None,
        )


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of ``items``. ``filter`` is what the server applied to a routes list;
    send it back unchanged (with ``next_cursor``) to get the next page.

    On a status page, ``events_cursor`` changes when there are new events (None when the
    account had no alert today or yesterday, UTC). On an events page, ``next_cursor`` is
    always set: store it for the next call; ``has_more`` says to call again now."""

    items: tuple[T, ...]
    next_cursor: str | None
    filter: Json | None = None
    events_cursor: str | None = None
    has_more: bool = False


@dataclass(frozen=True, slots=True)
class Response[T]:
    """``data`` is the parsed answer. ``not_modified`` is True when the server answered
    304 and ``data`` is the object cached from the earlier 200."""

    data: T
    not_modified: bool
    etag: str | None

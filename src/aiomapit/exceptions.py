"""Errors raised by the client. Every one derives from :class:`MapitError`."""

from __future__ import annotations


class MapitError(Exception):
    """Base class. ``status``, ``title`` and ``detail`` come from the problem+json body."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        title: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.title = title
        self.detail = detail


class MapitAuthError(MapitError):
    """401: the token or key is missing, expired or revoked."""


class MapitScopeError(MapitError):
    """403 insufficient_scope: the connection was not given ``scope``."""

    def __init__(
        self,
        message: str,
        *,
        scope: str | None = None,
        status: int | None = None,
        title: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, status=status, title=title, detail=detail)
        self.scope = scope


class MapitNotFound(MapitError):
    """404: not available for this account. A foreign or unknown id answers the same."""


class MapitRateLimited(MapitError):
    """429: over 30 requests a minute. ``retry_after`` is in seconds when the server said."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        status: int | None = None,
        title: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, status=status, title=title, detail=detail)
        self.retry_after = retry_after


class MapitConnectionError(MapitError):
    """5xx, timeout or network failure: worth retrying later."""


class MapitResponseError(MapitError):
    """A 2xx answer that is not valid JSON (or UTF-8) or lacks the expected fields."""

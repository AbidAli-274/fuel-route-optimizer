class RoutingError(Exception):
    """Base exception for routing failures."""


class RoutingConfigurationError(RoutingError):
    """Raised when routing credentials or configuration are invalid."""


class RoutingRateLimited(RoutingError):
    """Raised when the routing provider rejects requests due to quota limits."""

    def __init__(self, message: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class RoutingUnavailable(RoutingError):
    """Raised when transient provider failures exhaust the retry budget."""


class InvalidRoutingResponse(RoutingError):
    """Raised when the provider returns malformed or incomplete data."""


class LocationNotFound(RoutingError):
    """Raised when a location cannot be resolved in the United States."""


class RoutingProviderError(RoutingError):
    """Raised when the provider rejects an otherwise valid request."""

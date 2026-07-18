from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ResolvedLocation:
    input_text: str
    normalized_query: str
    resolved_name: str
    latitude: float
    longitude: float
    provider: str
    cache_hit: bool
    cached_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ProviderRoute:
    geometry: dict
    distance_meters: float
    duration_seconds: float


@dataclass(frozen=True)
class RouteResult:
    start: ResolvedLocation
    finish: ResolvedLocation
    geometry: dict
    distance_meters: float
    duration_seconds: float
    provider: str
    profile: str
    cache_hit: bool
    cached_at: datetime
    expires_at: datetime

    @property
    def distance_miles(self) -> float:
        return self.distance_meters / 1609.344

    @property
    def duration_minutes(self) -> float:
        return self.duration_seconds / 60

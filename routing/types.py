from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


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
    geometry: dict[str, object]
    distance_meters: float
    duration_seconds: float


@dataclass(frozen=True)
class RouteResult:
    start: ResolvedLocation
    finish: ResolvedLocation
    geometry: dict[str, object]
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


@dataclass(frozen=True)
class StationCandidate:
    station_id: int
    name: str
    address: str
    city: str
    state: str
    latitude: float
    longitude: float
    coordinate_accuracy: str
    price_per_gallon: Decimal
    route_mile: Decimal
    distance_from_route_miles: Decimal


@dataclass(frozen=True)
class FuelStop:
    station: StationCandidate
    arrival_fuel_gallons: Decimal
    gallons_purchased: Decimal
    departure_fuel_gallons: Decimal
    purchase_cost: Decimal


@dataclass(frozen=True)
class FuelPlan:
    stops: tuple[FuelStop, ...]
    estimated_fuel_consumed_gallons: Decimal
    en_route_gallons_purchased: Decimal
    en_route_fuel_cost: Decimal
    final_fuel_gallons: Decimal
    initial_fill_included: bool
    initial_fill_price_per_gallon: Decimal | None
    initial_fill_cost: Decimal

    @property
    def total_fuel_cost(self) -> Decimal:
        return self.en_route_fuel_cost + self.initial_fill_cost


@dataclass(frozen=True)
class RoutePlan:
    route: RouteResult
    fuel: FuelPlan

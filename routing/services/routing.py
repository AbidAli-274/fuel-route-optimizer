import re
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.utils import timezone

from routing.exceptions import RoutingConfigurationError
from routing.models import GeocodeCache, RouteCache
from routing.services.openrouteservice import OpenRouteServiceClient
from routing.types import ResolvedLocation, RouteResult

COORDINATE_QUANTUM = Decimal("0.000001")
WHITESPACE_RE = re.compile(r"\s+")
CACHE_FORMAT_VERSION = "v1"


class RoutingService:
    def __init__(self, *, client: OpenRouteServiceClient | None = None) -> None:
        self.client = client or OpenRouteServiceClient()

    def get_route(self, start: str, finish: str) -> RouteResult:
        resolved_start = self.resolve_location(start)
        resolved_finish = self.resolve_location(finish)
        route_key = self.route_cache_key(resolved_start, resolved_finish)
        now = timezone.now()
        cached = RouteCache.objects.filter(
            cache_key=route_key,
            expires_at__gt=now,
        ).first()
        if cached is not None:
            return self._route_result(
                cached,
                start=resolved_start,
                finish=resolved_finish,
                cache_hit=True,
            )

        provider_route = self.client.directions(
            start_latitude=resolved_start.latitude,
            start_longitude=resolved_start.longitude,
            finish_latitude=resolved_finish.latitude,
            finish_longitude=resolved_finish.longitude,
        )
        cached_at = timezone.now()
        expires_at = cached_at + timedelta(seconds=self._route_ttl())
        cached, _ = RouteCache.objects.update_or_create(
            cache_key=route_key,
            defaults={
                "provider": self.client.provider_name,
                "profile": self.client.profile,
                "start_latitude": self._coordinate(resolved_start.latitude),
                "start_longitude": self._coordinate(resolved_start.longitude),
                "finish_latitude": self._coordinate(resolved_finish.latitude),
                "finish_longitude": self._coordinate(resolved_finish.longitude),
                "geometry": provider_route.geometry,
                "distance_meters": provider_route.distance_meters,
                "duration_seconds": provider_route.duration_seconds,
                "cached_at": cached_at,
                "expires_at": expires_at,
            },
        )
        return self._route_result(
            cached,
            start=resolved_start,
            finish=resolved_finish,
            cache_hit=False,
        )

    def resolve_location(self, input_text: str) -> ResolvedLocation:
        normalized_query = self.normalize_location(input_text)
        geocode_key = self.geocode_cache_key(normalized_query)
        now = timezone.now()
        cached = GeocodeCache.objects.filter(
            cache_key=geocode_key,
            expires_at__gt=now,
        ).first()
        if cached is not None:
            return self._resolved_location(
                cached,
                input_text=input_text,
                cache_hit=True,
            )

        resolved_name, latitude, longitude = self.client.geocode(normalized_query)
        cached_at = timezone.now()
        expires_at = cached_at + timedelta(seconds=self._geocode_ttl())
        cached, _ = GeocodeCache.objects.update_or_create(
            cache_key=geocode_key,
            defaults={
                "provider": self.client.provider_name,
                "normalized_query": normalized_query,
                "resolved_name": resolved_name,
                "latitude": self._coordinate(latitude),
                "longitude": self._coordinate(longitude),
                "cached_at": cached_at,
                "expires_at": expires_at,
            },
        )
        return self._resolved_location(
            cached,
            input_text=input_text,
            cache_hit=False,
        )

    def geocode_cache_key(self, normalized_query: str) -> str:
        return f"{self.client.provider_name}|geocode|us|{CACHE_FORMAT_VERSION}|{normalized_query}"

    def route_cache_key(
        self,
        start: ResolvedLocation,
        finish: ResolvedLocation,
    ) -> str:
        start_coordinates = f"{start.longitude:.6f},{start.latitude:.6f}"
        finish_coordinates = f"{finish.longitude:.6f},{finish.latitude:.6f}"
        return (
            f"{self.client.provider_name}|route|{self.client.profile}|"
            f"{CACHE_FORMAT_VERSION}|{start_coordinates}->{finish_coordinates}"
        )

    @staticmethod
    def normalize_location(value: str) -> str:
        normalized = WHITESPACE_RE.sub(" ", value).strip().casefold()
        if not normalized:
            raise ValueError("Location must not be blank.")
        if len(normalized) > 500:
            raise ValueError("Location must not exceed 500 characters.")
        return normalized

    @staticmethod
    def _coordinate(value: float) -> Decimal:
        return Decimal(str(value)).quantize(
            COORDINATE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )

    @staticmethod
    def _resolved_location(
        cached: GeocodeCache,
        *,
        input_text: str,
        cache_hit: bool,
    ) -> ResolvedLocation:
        return ResolvedLocation(
            input_text=input_text,
            normalized_query=cached.normalized_query,
            resolved_name=cached.resolved_name,
            latitude=float(cached.latitude),
            longitude=float(cached.longitude),
            provider=cached.provider,
            cache_hit=cache_hit,
            cached_at=cached.cached_at,
            expires_at=cached.expires_at,
        )

    @staticmethod
    def _route_result(
        cached: RouteCache,
        *,
        start: ResolvedLocation,
        finish: ResolvedLocation,
        cache_hit: bool,
    ) -> RouteResult:
        return RouteResult(
            start=start,
            finish=finish,
            geometry=cached.geometry,
            distance_meters=cached.distance_meters,
            duration_seconds=cached.duration_seconds,
            provider=cached.provider,
            profile=cached.profile,
            cache_hit=cache_hit,
            cached_at=cached.cached_at,
            expires_at=cached.expires_at,
        )

    @staticmethod
    def _geocode_ttl() -> int:
        return RoutingService._positive_ttl(
            settings.GEOCODE_CACHE_TTL_SECONDS,
            "GEOCODE_CACHE_TTL_SECONDS",
        )

    @staticmethod
    def _route_ttl() -> int:
        return RoutingService._positive_ttl(
            settings.ROUTE_CACHE_TTL_SECONDS,
            "ROUTE_CACHE_TTL_SECONDS",
        )

    @staticmethod
    def _positive_ttl(value: int, setting_name: str) -> int:
        if value <= 0:
            raise RoutingConfigurationError(f"{setting_name} must be positive.")
        return value

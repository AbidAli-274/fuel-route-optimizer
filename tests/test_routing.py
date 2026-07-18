from datetime import timedelta

import httpx
import pytest
from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from routing.exceptions import (
    InvalidRoutingResponse,
    LocationNotFound,
    RoutingConfigurationError,
    RoutingRateLimited,
)
from routing.models import GeocodeCache, RouteCache
from routing.services.openrouteservice import OpenRouteServiceClient
from routing.services.routing import RoutingService

GEOCODE_RESULTS = {
    "dallas, tx": (
        "Dallas, Dallas County, Texas, United States",
        32.7767,
        -96.797,
    ),
    "albuquerque, nm": (
        "Albuquerque, Bernalillo County, New Mexico, United States",
        35.0844,
        -106.6504,
    ),
}
ROUTE_GEOMETRY = {
    "type": "LineString",
    "coordinates": [
        [-96.797, 32.7767],
        [-101.8313, 35.222],
        [-106.6504, 35.0844],
    ],
}


def geocode_response(query: str) -> httpx.Response:
    label, latitude, longitude = GEOCODE_RESULTS[query]
    return httpx.Response(
        200,
        json={
            "features": [
                {
                    "properties": {
                        "label": label,
                        "country_a": "USA",
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [longitude, latitude],
                    },
                }
            ]
        },
    )


def route_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": ROUTE_GEOMETRY,
                    "properties": {
                        "summary": {
                            "distance": 1_040_000.0,
                            "duration": 35_400.0,
                        }
                    },
                }
            ],
        },
    )


def routing_client(
    handler,
    *,
    sleep=lambda _seconds: None,
) -> OpenRouteServiceClient:
    return OpenRouteServiceClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleep,
    )


@pytest.mark.django_db
@override_settings(
    ORS_API_KEY="test-key",
    GEOCODE_CACHE_TTL_SECONDS=60,
    ROUTE_CACHE_TTL_SECONDS=120,
)
def test_cold_route_uses_three_calls_and_cached_route_uses_zero() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return geocode_response(request.url.params["text"])
        return route_response()

    service = RoutingService(client=routing_client(handler))
    first = service.get_route("  Dallas,   TX ", "Albuquerque, NM")
    second = service.get_route("dallas, tx", "albuquerque, nm")

    assert len(requests) == 3
    assert [request.method for request in requests] == ["GET", "GET", "POST"]
    assert first.cache_hit is False
    assert first.start.cache_hit is False
    assert first.finish.cache_hit is False
    assert second.cache_hit is True
    assert second.start.cache_hit is True
    assert second.finish.cache_hit is True
    assert first.geometry == ROUTE_GEOMETRY
    assert first.distance_meters == 1_040_000.0
    assert first.duration_seconds == 35_400.0
    assert first.distance_miles == pytest.approx(646.226, rel=0.001)
    assert first.duration_minutes == 590.0
    assert GeocodeCache.objects.count() == 2
    assert RouteCache.objects.count() == 1

    route_cache = RouteCache.objects.get()
    assert route_cache.provider == "openrouteservice"
    assert route_cache.profile == "driving-car"
    assert route_cache.expires_at - route_cache.cached_at == timedelta(seconds=120)
    assert route_cache.cache_key == (
        "openrouteservice|route|driving-car|v1|-96.797000,32.776700->-106.650400,35.084400"
    )
    geocode_cache = GeocodeCache.objects.get(normalized_query="dallas, tx")
    assert geocode_cache.cache_key == ("openrouteservice|geocode|us|v1|dallas, tx")
    assert geocode_cache.expires_at - geocode_cache.cached_at == timedelta(seconds=60)


@pytest.mark.django_db
@override_settings(ORS_API_KEY="test-key")
def test_expired_route_refreshes_with_one_call_when_geocodes_are_fresh() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return geocode_response(request.url.params["text"])
        return route_response()

    service = RoutingService(client=routing_client(handler))
    service.get_route("Dallas, TX", "Albuquerque, NM")
    RouteCache.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    requests.clear()

    refreshed = service.get_route("Dallas, TX", "Albuquerque, NM")

    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert refreshed.cache_hit is False
    assert refreshed.start.cache_hit is True
    assert refreshed.finish.cache_hit is True


@override_settings(ORS_API_KEY="test-key")
def test_transient_failure_is_retried_once() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return geocode_response("dallas, tx")

    client = routing_client(handler, sleep=sleeps.append)

    resolved = client.geocode("dallas, tx")

    assert resolved[0].startswith("Dallas")
    assert attempts == 2
    assert sleeps == [0.25]


@override_settings(ORS_API_KEY="test-key")
def test_rate_limit_is_not_retried() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "45"})

    client = routing_client(handler)

    with pytest.raises(RoutingRateLimited) as error:
        client.geocode("dallas, tx")

    assert attempts == 1
    assert error.value.retry_after_seconds == 45


@override_settings(ORS_API_KEY="test-key")
def test_empty_geocode_result_is_not_cached() -> None:
    client = routing_client(lambda _request: httpx.Response(200, json={"features": []}))

    with pytest.raises(LocationNotFound):
        client.geocode("not a real place")


@override_settings(ORS_API_KEY="test-key")
def test_invalid_route_response_is_rejected() -> None:
    client = routing_client(
        lambda _request: httpx.Response(
            200,
            json={"features": [{"geometry": {"type": "Point"}}]},
        )
    )

    with pytest.raises(InvalidRoutingResponse):
        client.directions(
            start_latitude=32.7767,
            start_longitude=-96.797,
            finish_latitude=35.0844,
            finish_longitude=-106.6504,
        )


@override_settings(ORS_API_KEY="")
def test_missing_api_key_fails_without_an_http_call() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500)

    client = routing_client(handler)

    with pytest.raises(RoutingConfigurationError, match="ORS_API_KEY"):
        client.geocode("dallas, tx")

    assert attempts == 0


def test_default_cache_ttls_match_routing_policy() -> None:
    assert settings.GEOCODE_CACHE_TTL_SECONDS == 30 * 24 * 60 * 60
    assert settings.ROUTE_CACHE_TTL_SECONDS == 7 * 24 * 60 * 60

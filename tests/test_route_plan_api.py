from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from fuel.models import FuelStation
from routing.exceptions import (
    InvalidRoutingResponse,
    RoutingConfigurationError,
    RoutingRateLimited,
)
from routing.models import GeocodeCache, RouteCache
from routing.views import RoutePlanView

ROUTE_URL = "/api/v1/route-plans/"


def seed_cached_route(*, distance_miles: float) -> None:
    now = timezone.now()
    expires_at = now + timedelta(days=7)
    locations = [
        (
            "openrouteservice|geocode|us|v1|dallas, tx",
            "dallas, tx",
            "Dallas, Texas, United States",
            Decimal("35.000000"),
            Decimal("-100.000000"),
        ),
        (
            "openrouteservice|geocode|us|v1|albuquerque, nm",
            "albuquerque, nm",
            "Albuquerque, New Mexico, United States",
            Decimal("35.000000"),
            Decimal("-90.000000"),
        ),
    ]
    for cache_key, query, name, latitude, longitude in locations:
        GeocodeCache.objects.create(
            cache_key=cache_key,
            provider="openrouteservice",
            normalized_query=query,
            resolved_name=name,
            latitude=latitude,
            longitude=longitude,
            cached_at=now,
            expires_at=expires_at,
        )
    RouteCache.objects.create(
        cache_key=(
            "openrouteservice|route|driving-car|v1|-100.000000,35.000000->-90.000000,35.000000"
        ),
        provider="openrouteservice",
        profile="driving-car",
        start_latitude=Decimal("35.000000"),
        start_longitude=Decimal("-100.000000"),
        finish_latitude=Decimal("35.000000"),
        finish_longitude=Decimal("-90.000000"),
        geometry={
            "type": "LineString",
            "coordinates": [[-100.0, 35.0], [-90.0, 35.0]],
        },
        distance_meters=distance_miles * 1609.344,
        duration_seconds=35_400,
        cached_at=now,
        expires_at=expires_at,
    )


def create_station(*, route_fraction: float = 0.5643) -> FuelStation:
    return FuelStation.objects.create(
        opis_truckstop_id=12345,
        name="Example Travel Center",
        address="I-40, Exit 75",
        city="Amarillo",
        state="TX",
        rack_id=500,
        retail_price=Decimal("3.15900000"),
        source_row_count=1,
        latitude=Decimal("35.000000"),
        longitude=Decimal(str(-100 + 10 * route_fraction)),
        coordinate_accuracy=FuelStation.CoordinateAccuracy.CITY_CENTROID,
    )


@pytest.mark.django_db
def test_route_plan_success_uses_cached_route_and_returns_documented_shape() -> None:
    seed_cached_route(distance_miles=646.8)
    create_station()
    client = APIClient()

    response = client.post(
        ROUTE_URL,
        {
            "start": "Dallas, TX",
            "finish": "Albuquerque, NM",
            "include_initial_fill": False,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["route"]["geometry"]["type"] == "LineString"
    assert body["route"]["distance_miles"] == 646.8
    assert len(body["fuel_stops"]) == 1
    assert body["fuel_stops"][0]["station_id"] == 12345
    assert body["fuel_stops"][0]["purchase_cost"] == "46.37"
    assert body["cost_summary"] == {
        "currency": "USD",
        "estimated_fuel_consumed_gallons": 64.68,
        "en_route_gallons_purchased": 14.68,
        "en_route_fuel_cost": "46.37",
        "initial_fill_included": False,
        "initial_fill_gallons": 0.0,
        "initial_fill_price_per_gallon": None,
        "initial_fill_cost": "0.00",
        "total_fuel_cost": "46.37",
        "final_fuel_gallons": 0.0,
    }
    assert body["metadata"]["route_cache_hit"] is True
    assert body["assumptions"]["maximum_range_miles"] == 500.0
    assert len(body["warnings"]) == 2


@pytest.mark.django_db
def test_route_plan_validates_initial_fill_fields() -> None:
    response = APIClient().post(
        ROUTE_URL,
        {
            "start": "Dallas, TX",
            "finish": "Albuquerque, NM",
            "include_initial_fill": True,
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "initial_fuel_price_per_gallon" in response.json()["error"]["details"]


@pytest.mark.django_db
def test_malformed_json_uses_documented_error_envelope() -> None:
    response = APIClient().generic(
        "POST",
        ROUTE_URL,
        data=b'{"start":',
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
def test_route_plan_returns_422_for_infeasible_station_gap() -> None:
    seed_cached_route(distance_miles=1100)

    response = APIClient().post(
        ROUTE_URL,
        {
            "start": "Dallas, TX",
            "finish": "Albuquerque, NM",
        },
        format="json",
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "NO_FEASIBLE_FUEL_PLAN"
    assert error["details"] == {
        "gap_start_mile": 0.0,
        "gap_end_mile": 1100.0,
        "gap_miles": 1100.0,
    }


@pytest.mark.django_db
def test_route_plan_preserves_provider_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RateLimitedService:
        def create_plan(self, **_kwargs):
            raise RoutingRateLimited(
                "Provider quota reached.",
                retry_after_seconds=45,
            )

    monkeypatch.setattr(
        RoutePlanView,
        "get_planning_service",
        staticmethod(RateLimitedService),
    )

    response = APIClient().post(
        ROUTE_URL,
        {"start": "Dallas, TX", "finish": "Albuquerque, NM"},
        format="json",
    )

    assert response.status_code == 429
    assert response["Retry-After"] == "45"
    assert response.json()["error"]["code"] == "ROUTING_RATE_LIMITED"


@pytest.mark.django_db
def test_route_plan_maps_invalid_provider_data_to_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidProviderService:
        def create_plan(self, **_kwargs):
            raise InvalidRoutingResponse("Provider response was invalid.")

    monkeypatch.setattr(
        RoutePlanView,
        "get_planning_service",
        staticmethod(InvalidProviderService),
    )

    response = APIClient().post(
        ROUTE_URL,
        {"start": "Dallas, TX", "finish": "Albuquerque, NM"},
        format="json",
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "ROUTING_UNAVAILABLE"


@pytest.mark.django_db
def test_route_plan_hides_internal_configuration_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MisconfiguredService:
        def create_plan(self, **_kwargs):
            raise RoutingConfigurationError("OPENROUTESERVICE_API_KEY contains a secret.")

    monkeypatch.setattr(
        RoutePlanView,
        "get_planning_service",
        staticmethod(MisconfiguredService),
    )

    response = APIClient().post(
        ROUTE_URL,
        {"start": "Dallas, TX", "finish": "Albuquerque, NM"},
        format="json",
    )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "ROUTING_NOT_CONFIGURED",
        "message": (
            "OPENROUTESERVICE_API_KEY is not configured. "
            "Copy .env.example to .env and add a valid key."
        ),
    }


@pytest.mark.django_db
def test_openapi_swagger_and_redoc_are_available() -> None:
    client = APIClient()

    schema_response = client.get(
        "/api/schema/",
        HTTP_ACCEPT="application/json",
    )
    swagger_response = client.get("/api/docs/")
    redoc_response = client.get("/api/redoc/")

    assert schema_response.status_code == 200
    schema = schema_response.json()
    operation = schema["paths"][ROUTE_URL]["post"]
    assert operation["requestBody"]["required"] is True
    assert set(operation["responses"]) >= {"200", "400", "422", "429", "502"}
    assert swagger_response.status_code == 200
    assert b"swagger-ui" in swagger_response.content
    assert redoc_response.status_code == 200
    assert b"redoc" in redoc_response.content.lower()

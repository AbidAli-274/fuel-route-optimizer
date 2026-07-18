from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from fuel.models import FuelStation
from fuel.services.stations import select_nearby_stations
from routing.exceptions import NoFeasibleFuelPlan
from routing.services.optimizer import optimize_fuel_stops
from routing.types import ResolvedLocation, RouteResult, StationCandidate


def candidate(
    *,
    station_id: int,
    route_mile: str,
    price: str,
) -> StationCandidate:
    return StationCandidate(
        station_id=station_id,
        name=f"Station {station_id}",
        address="Highway exit",
        city="Example",
        state="TX",
        latitude=35.0,
        longitude=-100.0,
        coordinate_accuracy=FuelStation.CoordinateAccuracy.CITY_CENTROID,
        price_per_gallon=Decimal(price),
        route_mile=Decimal(route_mile),
        distance_from_route_miles=Decimal("1"),
    )


def route_result(*, distance_miles: float) -> RouteResult:
    now = timezone.now()
    start = ResolvedLocation(
        input_text="Start",
        normalized_query="start",
        resolved_name="Start, United States",
        latitude=35.0,
        longitude=-100.0,
        provider="openrouteservice",
        cache_hit=True,
        cached_at=now,
        expires_at=now + timedelta(days=1),
    )
    finish = ResolvedLocation(
        input_text="Finish",
        normalized_query="finish",
        resolved_name="Finish, United States",
        latitude=35.0,
        longitude=-90.0,
        provider="openrouteservice",
        cache_hit=True,
        cached_at=now,
        expires_at=now + timedelta(days=1),
    )
    return RouteResult(
        start=start,
        finish=finish,
        geometry={
            "type": "LineString",
            "coordinates": [[-100.0, 35.0], [-90.0, 35.0]],
        },
        distance_meters=distance_miles * 1609.344,
        duration_seconds=36_000,
        provider="openrouteservice",
        profile="driving-car",
        cache_hit=True,
        cached_at=now,
        expires_at=now + timedelta(days=1),
    )


def optimize(
    distance_miles: float,
    candidates: tuple[StationCandidate, ...] = (),
    *,
    include_initial_fill: bool = False,
    initial_price: Decimal | None = None,
):
    return optimize_fuel_stops(
        route_distance_miles=distance_miles,
        candidates=candidates,
        include_initial_fill=include_initial_fill,
        initial_fuel_price_per_gallon=initial_price,
    )


def test_route_within_initial_range_requires_no_purchase() -> None:
    plan = optimize(400)

    assert plan.stops == ()
    assert plan.estimated_fuel_consumed_gallons == Decimal("40")
    assert plan.en_route_fuel_cost == Decimal("0")
    assert plan.final_fuel_gallons == Decimal("10")


def test_one_stop_buys_only_fuel_needed_to_finish() -> None:
    plan = optimize(
        646.8,
        (candidate(station_id=1, route_mile="365", price="3.15900000"),),
    )

    assert len(plan.stops) == 1
    assert plan.stops[0].arrival_fuel_gallons == Decimal("13.5")
    assert plan.stops[0].gallons_purchased == Decimal("14.68")
    assert plan.stops[0].purchase_cost == Decimal("46.3741200000")
    assert plan.final_fuel_gallons == Decimal("0.00")


def test_greedy_optimizer_waits_for_cheaper_reachable_station() -> None:
    plan = optimize(
        1200,
        (
            candidate(station_id=1, route_mile="300", price="4"),
            candidate(station_id=2, route_mile="450", price="3"),
            candidate(station_id=3, route_mile="800", price="5"),
            candidate(station_id=4, route_mile="900", price="2"),
        ),
    )

    assert [stop.station.station_id for stop in plan.stops] == [2, 4]
    assert [stop.gallons_purchased for stop in plan.stops] == [
        Decimal("40"),
        Decimal("30"),
    ]
    assert plan.en_route_fuel_cost == Decimal("180")


def test_initial_fill_is_optional_and_does_not_change_stop_selection() -> None:
    station = candidate(station_id=1, route_mile="365", price="3")
    excluded = optimize(650, (station,))
    included = optimize(
        650,
        (station,),
        include_initial_fill=True,
        initial_price=Decimal("3.25"),
    )

    assert excluded.stops == included.stops
    assert excluded.initial_fill_cost == Decimal("0")
    assert included.initial_fill_cost == Decimal("162.50")
    assert included.total_fuel_cost == included.en_route_fuel_cost + Decimal("162.50")


def test_infeasible_gap_is_reported() -> None:
    with pytest.raises(NoFeasibleFuelPlan) as error:
        optimize(
            1100,
            (candidate(station_id=1, route_mile="400", price="3"),),
        )

    assert error.value.gap_start_mile == 400.0
    assert error.value.gap_end_mile == 1100.0
    assert error.value.gap_miles == 700.0


@pytest.mark.django_db
def test_station_selector_projects_and_filters_city_centroids() -> None:
    FuelStation.objects.create(
        opis_truckstop_id=1,
        name="Near Route",
        address="Exit 1",
        city="Example",
        state="TX",
        rack_id=1,
        retail_price=Decimal("3.00000000"),
        source_row_count=1,
        latitude=Decimal("35.050000"),
        longitude=Decimal("-95.000000"),
        coordinate_accuracy=FuelStation.CoordinateAccuracy.CITY_CENTROID,
    )
    FuelStation.objects.create(
        opis_truckstop_id=2,
        name="Outside Corridor",
        address="Exit 2",
        city="Example",
        state="TX",
        rack_id=2,
        retail_price=Decimal("2.00000000"),
        source_row_count=1,
        latitude=Decimal("35.300000"),
        longitude=Decimal("-95.000000"),
        coordinate_accuracy=FuelStation.CoordinateAccuracy.CITY_CENTROID,
    )

    selected = select_nearby_stations(
        route_result(distance_miles=600),
        corridor_miles=10,
    )

    assert len(selected) == 1
    assert selected[0].station_id == 1
    assert float(selected[0].route_mile) == pytest.approx(300, rel=0.01)
    assert selected[0].distance_from_route_miles < Decimal("4")


def test_station_selector_rejects_explicit_zero_corridor() -> None:
    with pytest.raises(ValueError, match="corridor must be positive"):
        select_nearby_stations(
            route_result(distance_miles=600),
            corridor_miles=0,
        )

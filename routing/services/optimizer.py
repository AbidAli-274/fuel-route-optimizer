from decimal import Decimal

from routing.exceptions import NoFeasibleFuelPlan
from routing.types import FuelPlan, FuelStop, StationCandidate

FUEL_EFFICIENCY_MPG = Decimal("10")
TANK_CAPACITY_GALLONS = Decimal("50")
MAXIMUM_RANGE_MILES = FUEL_EFFICIENCY_MPG * TANK_CAPACITY_GALLONS
ZERO = Decimal("0")


def optimize_fuel_stops(
    *,
    route_distance_miles: float,
    candidates: tuple[StationCandidate, ...],
    include_initial_fill: bool,
    initial_fuel_price_per_gallon: Decimal | None,
) -> FuelPlan:
    """Choose range-safe purchases using the next-cheaper-station policy."""
    route_distance = Decimal(str(route_distance_miles))
    usable_candidates = tuple(
        candidate for candidate in candidates if ZERO < candidate.route_mile < route_distance
    )
    current_fuel = TANK_CAPACITY_GALLONS
    previous_mile = ZERO
    last_refuel_mile = ZERO
    stops: list[FuelStop] = []

    for index, candidate in enumerate(usable_candidates):
        leg_miles = candidate.route_mile - previous_mile
        current_fuel -= leg_miles / FUEL_EFFICIENCY_MPG
        if current_fuel < ZERO:
            raise _infeasible(last_refuel_mile, candidate.route_mile)

        target_mile = _first_cheaper_target(
            candidate=candidate,
            later_candidates=usable_candidates[index + 1 :],
            route_distance=route_distance,
        )
        desired_departure_fuel = (
            (target_mile - candidate.route_mile) / FUEL_EFFICIENCY_MPG
            if target_mile is not None
            else TANK_CAPACITY_GALLONS
        )
        desired_departure_fuel = min(
            TANK_CAPACITY_GALLONS,
            desired_departure_fuel,
        )
        gallons_purchased = max(ZERO, desired_departure_fuel - current_fuel)
        arrival_fuel = current_fuel
        if gallons_purchased > ZERO:
            current_fuel += gallons_purchased
            last_refuel_mile = candidate.route_mile
            stops.append(
                FuelStop(
                    station=candidate,
                    arrival_fuel_gallons=arrival_fuel,
                    gallons_purchased=gallons_purchased,
                    departure_fuel_gallons=current_fuel,
                    purchase_cost=gallons_purchased * candidate.price_per_gallon,
                )
            )
        previous_mile = candidate.route_mile

    current_fuel -= (route_distance - previous_mile) / FUEL_EFFICIENCY_MPG
    if current_fuel < ZERO:
        raise _infeasible(last_refuel_mile, route_distance)

    consumed = route_distance / FUEL_EFFICIENCY_MPG
    purchased = sum(
        (stop.gallons_purchased for stop in stops),
        start=ZERO,
    )
    en_route_cost = sum(
        (stop.purchase_cost for stop in stops),
        start=ZERO,
    )
    initial_fill_cost = (
        TANK_CAPACITY_GALLONS * initial_fuel_price_per_gallon
        if include_initial_fill and initial_fuel_price_per_gallon is not None
        else ZERO
    )
    return FuelPlan(
        stops=tuple(stops),
        estimated_fuel_consumed_gallons=consumed,
        en_route_gallons_purchased=purchased,
        en_route_fuel_cost=en_route_cost,
        final_fuel_gallons=max(ZERO, current_fuel),
        initial_fill_included=include_initial_fill,
        initial_fill_price_per_gallon=initial_fuel_price_per_gallon,
        initial_fill_cost=initial_fill_cost,
    )


def _first_cheaper_target(
    *,
    candidate: StationCandidate,
    later_candidates: tuple[StationCandidate, ...],
    route_distance: Decimal,
) -> Decimal | None:
    for later in later_candidates:
        distance = later.route_mile - candidate.route_mile
        if distance > MAXIMUM_RANGE_MILES:
            break
        if later.price_per_gallon < candidate.price_per_gallon:
            return later.route_mile

    destination_distance = route_distance - candidate.route_mile
    if destination_distance <= MAXIMUM_RANGE_MILES:
        return route_distance
    return None


def _infeasible(start_mile: Decimal, end_mile: Decimal) -> NoFeasibleFuelPlan:
    return NoFeasibleFuelPlan(
        "No fuel-stop sequence can satisfy the 500-mile vehicle range.",
        gap_start_mile=float(start_mile),
        gap_end_mile=float(end_mile),
    )

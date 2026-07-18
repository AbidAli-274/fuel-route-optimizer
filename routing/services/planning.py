from decimal import Decimal

from fuel.services.stations import select_nearby_stations
from routing.services.optimizer import optimize_fuel_stops
from routing.services.routing import RoutingService
from routing.types import RoutePlan


class RoutePlanningService:
    def __init__(self, *, routing_service: RoutingService | None = None) -> None:
        self.routing_service = routing_service or RoutingService()

    def create_plan(
        self,
        *,
        start: str,
        finish: str,
        include_initial_fill: bool,
        initial_fuel_price_per_gallon: Decimal | None = None,
    ) -> RoutePlan:
        route = self.routing_service.get_route(start, finish)
        candidates = select_nearby_stations(route)
        fuel_plan = optimize_fuel_stops(
            route_distance_miles=route.distance_miles,
            candidates=candidates,
            include_initial_fill=include_initial_fill,
            initial_fuel_price_per_gallon=initial_fuel_price_per_gallon,
        )
        return RoutePlan(route=route, fuel=fuel_plan)

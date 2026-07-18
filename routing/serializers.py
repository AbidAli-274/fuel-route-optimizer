import re
from decimal import ROUND_HALF_UP, Decimal

from rest_framework import serializers

from routing.types import RoutePlan

MONEY_QUANTUM = Decimal("0.01")
DISPLAY_QUANTUM = Decimal("0.01")
WHITESPACE_RE = re.compile(r"\s+")


class RoutePlanRequestSerializer(serializers.Serializer):
    start = serializers.CharField(
        max_length=500,
        help_text="Starting location within the contiguous United States.",
    )
    finish = serializers.CharField(
        max_length=500,
        help_text="Destination within the contiguous United States.",
    )
    include_initial_fill = serializers.BooleanField(
        default=False,
        help_text="Include the cost of purchasing the full starting tank.",
    )
    initial_fuel_price_per_gallon = serializers.DecimalField(
        max_digits=10,
        decimal_places=8,
        min_value=Decimal("0.00000001"),
        required=False,
        allow_null=True,
        help_text=(
            "Starting fuel price in USD per gallon. Required only when "
            "include_initial_fill is true."
        ),
    )

    def validate(self, attrs: dict) -> dict:
        include_initial_fill = attrs["include_initial_fill"]
        initial_price = attrs.get("initial_fuel_price_per_gallon")
        if include_initial_fill and initial_price is None:
            raise serializers.ValidationError(
                {
                    "initial_fuel_price_per_gallon": (
                        "This field is required when include_initial_fill is true."
                    )
                }
            )
        if not include_initial_fill and initial_price is not None:
            raise serializers.ValidationError(
                {
                    "initial_fuel_price_per_gallon": (
                        "This field is only accepted when include_initial_fill is true."
                    )
                }
            )
        start = WHITESPACE_RE.sub(" ", attrs["start"]).strip().casefold()
        finish = WHITESPACE_RE.sub(" ", attrs["finish"]).strip().casefold()
        if start == finish:
            raise serializers.ValidationError(
                {"finish": "Start and finish must be different locations."}
            )
        return attrs


class ResolvedLocationSerializer(serializers.Serializer):
    input = serializers.CharField()
    resolved_name = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()


class RouteSummarySerializer(serializers.Serializer):
    distance_miles = serializers.FloatField()
    duration_minutes = serializers.FloatField()
    geometry = serializers.JSONField()


class StopLocationSerializer(serializers.Serializer):
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    accuracy = serializers.CharField()


class FuelStopSerializer(serializers.Serializer):
    sequence = serializers.IntegerField()
    station_id = serializers.IntegerField()
    name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    location = StopLocationSerializer()
    route_mile = serializers.FloatField()
    distance_from_route_miles = serializers.FloatField()
    price_per_gallon = serializers.CharField()
    arrival_fuel_gallons = serializers.FloatField()
    gallons_purchased = serializers.FloatField()
    departure_fuel_gallons = serializers.FloatField()
    purchase_cost = serializers.CharField()


class CostSummarySerializer(serializers.Serializer):
    currency = serializers.CharField()
    estimated_fuel_consumed_gallons = serializers.FloatField()
    en_route_gallons_purchased = serializers.FloatField()
    en_route_fuel_cost = serializers.CharField()
    initial_fill_included = serializers.BooleanField()
    initial_fill_gallons = serializers.FloatField()
    initial_fill_price_per_gallon = serializers.CharField(allow_null=True)
    initial_fill_cost = serializers.CharField()
    total_fuel_cost = serializers.CharField()
    final_fuel_gallons = serializers.FloatField()


class AssumptionsSerializer(serializers.Serializer):
    fuel_efficiency_mpg = serializers.FloatField()
    tank_capacity_gallons = serializers.FloatField()
    maximum_range_miles = serializers.FloatField()
    starting_tank = serializers.CharField()
    destination_reserve_gallons = serializers.FloatField()
    station_detours_included = serializers.BooleanField()


class MetadataSerializer(serializers.Serializer):
    routing_provider = serializers.CharField()
    routing_profile = serializers.CharField()
    route_cache_hit = serializers.BooleanField()
    fuel_price_source = serializers.CharField()
    station_coordinate_source = serializers.CharField()
    price_duplicate_policy = serializers.CharField()
    attribution = serializers.ListField(child=serializers.CharField())


class RoutePlanResponseSerializer(serializers.Serializer):
    start = ResolvedLocationSerializer()
    finish = ResolvedLocationSerializer()
    route = RouteSummarySerializer()
    fuel_stops = FuelStopSerializer(many=True)
    cost_summary = CostSummarySerializer()
    assumptions = AssumptionsSerializer()
    metadata = MetadataSerializer()
    warnings = serializers.ListField(child=serializers.CharField())


class ErrorBodySerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.JSONField(required=False)


class ErrorResponseSerializer(serializers.Serializer):
    error = ErrorBodySerializer()


def route_plan_response(plan: RoutePlan) -> dict[str, object]:
    route = plan.route
    fuel = plan.fuel
    stops = [
        {
            "sequence": sequence,
            "station_id": stop.station.station_id,
            "name": stop.station.name,
            "address": stop.station.address,
            "city": stop.station.city,
            "state": stop.station.state,
            "location": {
                "latitude": stop.station.latitude,
                "longitude": stop.station.longitude,
                "accuracy": stop.station.coordinate_accuracy,
            },
            "route_mile": _display_float(stop.station.route_mile),
            "distance_from_route_miles": _display_float(stop.station.distance_from_route_miles),
            "price_per_gallon": f"{stop.station.price_per_gallon:.8f}",
            "arrival_fuel_gallons": _display_float(stop.arrival_fuel_gallons),
            "gallons_purchased": _display_float(stop.gallons_purchased),
            "departure_fuel_gallons": _display_float(stop.departure_fuel_gallons),
            "purchase_cost": _money(stop.purchase_cost),
        }
        for sequence, stop in enumerate(fuel.stops, start=1)
    ]
    initial_price = fuel.initial_fill_price_per_gallon
    return {
        "start": {
            "input": route.start.input_text,
            "resolved_name": route.start.resolved_name,
            "latitude": route.start.latitude,
            "longitude": route.start.longitude,
        },
        "finish": {
            "input": route.finish.input_text,
            "resolved_name": route.finish.resolved_name,
            "latitude": route.finish.latitude,
            "longitude": route.finish.longitude,
        },
        "route": {
            "distance_miles": round(route.distance_miles, 2),
            "duration_minutes": round(route.duration_minutes, 2),
            "geometry": route.geometry,
        },
        "fuel_stops": stops,
        "cost_summary": {
            "currency": "USD",
            "estimated_fuel_consumed_gallons": _display_float(fuel.estimated_fuel_consumed_gallons),
            "en_route_gallons_purchased": _display_float(fuel.en_route_gallons_purchased),
            "en_route_fuel_cost": _money(fuel.en_route_fuel_cost),
            "initial_fill_included": fuel.initial_fill_included,
            "initial_fill_gallons": 50.0 if fuel.initial_fill_included else 0.0,
            "initial_fill_price_per_gallon": (
                f"{initial_price:.8f}" if initial_price is not None else None
            ),
            "initial_fill_cost": _money(fuel.initial_fill_cost),
            "total_fuel_cost": _money(fuel.total_fuel_cost),
            "final_fuel_gallons": _display_float(fuel.final_fuel_gallons),
        },
        "assumptions": {
            "fuel_efficiency_mpg": 10.0,
            "tank_capacity_gallons": 50.0,
            "maximum_range_miles": 500.0,
            "starting_tank": "full",
            "destination_reserve_gallons": 0.0,
            "station_detours_included": False,
        },
        "metadata": {
            "routing_provider": route.provider,
            "routing_profile": route.profile,
            "route_cache_hit": route.cache_hit,
            "fuel_price_source": "fuel-prices-for-be-assessment.csv",
            "station_coordinate_source": "GeoNames",
            "price_duplicate_policy": "median",
            "attribution": [
                "Routing and geocoding: openrouteservice.org by HeiGIT",
                "Map data: OpenStreetMap contributors",
                "Station coordinates: GeoNames, CC BY 4.0",
            ],
        },
        "warnings": [
            (
                "Fuel-station coordinates are city centroids and may not "
                "represent exact driveway locations."
            ),
            ("Station access detours are excluded from route distance and fuel calculations."),
        ],
    }


def error_response(
    *,
    code: str,
    message: str,
    details: object | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return {"error": body}


def _money(value: Decimal) -> str:
    return str(value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP))


def _display_float(value: Decimal) -> float:
    return float(value.quantize(DISPLAY_QUANTUM, rounding=ROUND_HALF_UP))

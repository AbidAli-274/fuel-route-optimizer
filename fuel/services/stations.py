import math
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

from django.conf import settings

from fuel.models import FuelStation
from routing.exceptions import InvalidRoutingResponse
from routing.types import RouteResult, StationCandidate

MILES_PER_LATITUDE_DEGREE = 69.0
MILES_PER_LONGITUDE_DEGREE = 69.172


@dataclass(frozen=True)
class ProjectedSegment:
    start_longitude: float
    start_latitude: float
    delta_x: float
    delta_y: float
    longitude_scale: float
    length_miles: float
    cumulative_miles: float


def select_nearby_stations(
    route: RouteResult,
    *,
    corridor_miles: float | None = None,
) -> tuple[StationCandidate, ...]:
    """Project coordinate-matched stations onto a route and filter its corridor."""
    corridor = settings.STATION_CORRIDOR_MILES if corridor_miles is None else corridor_miles
    if corridor <= 0:
        raise ValueError("Station corridor must be positive.")

    coordinates = _downsample_coordinates(_route_coordinates(route))
    segments, geometry_length = _segments(coordinates)
    if geometry_length <= 0:
        raise InvalidRoutingResponse("Route geometry has no measurable length.")

    latitudes = [latitude for _, latitude in coordinates]
    longitudes = [longitude for longitude, _ in coordinates]
    latitude_padding = corridor / MILES_PER_LATITUDE_DEGREE
    minimum_longitude_scale = min(
        MILES_PER_LONGITUDE_DEGREE * max(math.cos(math.radians(abs(latitude))), 0.1)
        for latitude in latitudes
    )
    longitude_padding = corridor / minimum_longitude_scale
    stations = FuelStation.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False,
        latitude__gte=min(latitudes) - latitude_padding,
        latitude__lte=max(latitudes) + latitude_padding,
        longitude__gte=min(longitudes) - longitude_padding,
        longitude__lte=max(longitudes) + longitude_padding,
    ).only(
        "opis_truckstop_id",
        "name",
        "address",
        "city",
        "state",
        "latitude",
        "longitude",
        "coordinate_accuracy",
        "retail_price",
    )

    candidates: list[StationCandidate] = []
    for station in stations.iterator():
        distance, projected_geometry_mile = _nearest_projection(
            float(station.longitude),
            float(station.latitude),
            segments,
        )
        if distance > corridor:
            continue
        route_mile = (
            Decimal(str(projected_geometry_mile))
            / Decimal(str(geometry_length))
            * Decimal(str(route.distance_miles))
        )
        candidates.append(
            StationCandidate(
                station_id=station.opis_truckstop_id,
                name=station.name,
                address=station.address,
                city=station.city,
                state=station.state,
                latitude=float(station.latitude),
                longitude=float(station.longitude),
                coordinate_accuracy=station.coordinate_accuracy,
                price_per_gallon=station.retail_price,
                route_mile=route_mile,
                distance_from_route_miles=Decimal(str(distance)),
            )
        )

    candidates.sort(
        key=lambda candidate: (
            candidate.route_mile,
            candidate.price_per_gallon,
            candidate.station_id,
        )
    )
    return tuple(candidates)


def _route_coordinates(route: RouteResult) -> list[tuple[float, float]]:
    raw_coordinates = route.geometry.get("coordinates")
    if not isinstance(raw_coordinates, list) or len(raw_coordinates) < 2:
        raise InvalidRoutingResponse("Route geometry coordinates are unavailable.")
    coordinates: list[tuple[float, float]] = []
    for coordinate in raw_coordinates:
        if (
            not isinstance(coordinate, list)
            or len(coordinate) < 2
            or not all(isinstance(value, int | float) for value in coordinate[:2])
        ):
            raise InvalidRoutingResponse("Route geometry coordinates are invalid.")
        coordinates.append((float(coordinate[0]), float(coordinate[1])))
    return coordinates


def _downsample_coordinates(
    coordinates: list[tuple[float, float]],
    *,
    maximum_points: int = 1000,
) -> list[tuple[float, float]]:
    if len(coordinates) <= maximum_points:
        return coordinates
    step = math.ceil((len(coordinates) - 1) / (maximum_points - 1))
    sampled = coordinates[::step]
    if sampled[-1] != coordinates[-1]:
        sampled.append(coordinates[-1])
    return sampled


def _segments(
    coordinates: list[tuple[float, float]],
) -> tuple[list[ProjectedSegment], float]:
    segments: list[ProjectedSegment] = []
    cumulative = 0.0
    for start, finish in pairwise(coordinates):
        midpoint_latitude = (start[1] + finish[1]) / 2
        longitude_scale = MILES_PER_LONGITUDE_DEGREE * math.cos(math.radians(midpoint_latitude))
        delta_x = (finish[0] - start[0]) * longitude_scale
        delta_y = (finish[1] - start[1]) * MILES_PER_LATITUDE_DEGREE
        length = math.hypot(delta_x, delta_y)
        if length == 0:
            continue
        segments.append(
            ProjectedSegment(
                start_longitude=start[0],
                start_latitude=start[1],
                delta_x=delta_x,
                delta_y=delta_y,
                longitude_scale=longitude_scale,
                length_miles=length,
                cumulative_miles=cumulative,
            )
        )
        cumulative += length
    return segments, cumulative


def _nearest_projection(
    station_longitude: float,
    station_latitude: float,
    segments: list[ProjectedSegment],
) -> tuple[float, float]:
    nearest_distance = math.inf
    nearest_route_mile = 0.0
    for segment in segments:
        station_x = (station_longitude - segment.start_longitude) * segment.longitude_scale
        station_y = (station_latitude - segment.start_latitude) * MILES_PER_LATITUDE_DEGREE
        projection = (station_x * segment.delta_x + station_y * segment.delta_y) / (
            segment.length_miles**2
        )
        projection = min(1.0, max(0.0, projection))
        projected_x = projection * segment.delta_x
        projected_y = projection * segment.delta_y
        distance = math.hypot(
            station_x - projected_x,
            station_y - projected_y,
        )
        if distance < nearest_distance:
            nearest_distance = distance
            nearest_route_mile = segment.cumulative_miles + projection * segment.length_miles
    return nearest_distance, nearest_route_mile

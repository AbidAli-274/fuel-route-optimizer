import time
from collections.abc import Callable
from typing import Any

import httpx
from django.conf import settings

from routing.configuration import has_valid_api_key
from routing.exceptions import (
    InvalidRoutingResponse,
    LocationNotFound,
    RoutingConfigurationError,
    RoutingProviderError,
    RoutingRateLimited,
    RoutingUnavailable,
)
from routing.types import ProviderRoute


class OpenRouteServiceClient:
    provider_name = "openrouteservice"
    profile = "driving-car"
    transient_statuses = frozenset({502, 503, 504})

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = settings.ORS_API_KEY
        self.base_url = settings.ORS_BASE_URL.rstrip("/")
        self.sleep = sleep
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(
                connect=settings.ROUTING_CONNECT_TIMEOUT_SECONDS,
                read=settings.ROUTING_READ_TIMEOUT_SECONDS,
                write=settings.ROUTING_READ_TIMEOUT_SECONDS,
                pool=settings.ROUTING_CONNECT_TIMEOUT_SECONDS,
            )
        )

    def geocode(self, query: str) -> tuple[str, float, float]:
        self._require_api_key()
        response = self._request(
            "GET",
            "/geocode/search",
            params={
                "api_key": self.api_key,
                "text": query,
                "boundary.country": "US",
                "size": 5,
            },
        )
        payload = self._json_object(response)
        features = payload.get("features")
        if not isinstance(features, list):
            raise InvalidRoutingResponse("Geocoding response has no feature list.")

        for feature in features:
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties")
            geometry = feature.get("geometry")
            if not isinstance(properties, dict) or not isinstance(geometry, dict):
                continue
            country_code = str(properties.get("country_a", "")).upper()
            if country_code and country_code not in {"US", "USA"}:
                continue
            coordinates = geometry.get("coordinates")
            if not self._valid_coordinate_pair(coordinates):
                continue
            longitude = float(coordinates[0])
            latitude = float(coordinates[1])
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                continue
            label = properties.get("label") or properties.get("name")
            if not isinstance(label, str) or not label.strip():
                continue
            return label.strip(), latitude, longitude

        raise LocationNotFound(f"No U.S. location was found for {query!r}.")

    def directions(
        self,
        *,
        start_latitude: float,
        start_longitude: float,
        finish_latitude: float,
        finish_longitude: float,
    ) -> ProviderRoute:
        self._require_api_key()
        response = self._request(
            "POST",
            f"/v2/directions/{self.profile}/geojson",
            headers={"Authorization": self.api_key},
            json={
                "coordinates": [
                    [start_longitude, start_latitude],
                    [finish_longitude, finish_latitude],
                ]
            },
        )
        payload = self._json_object(response)
        features = payload.get("features")
        if not isinstance(features, list) or not features:
            raise InvalidRoutingResponse("Directions response has no route feature.")

        feature = features[0]
        if not isinstance(feature, dict):
            raise InvalidRoutingResponse("Directions route feature is invalid.")
        geometry = feature.get("geometry")
        properties = feature.get("properties")
        if not isinstance(geometry, dict) or not isinstance(properties, dict):
            raise InvalidRoutingResponse("Directions route data is incomplete.")
        if geometry.get("type") != "LineString":
            raise InvalidRoutingResponse("Directions geometry is not a LineString.")
        coordinates = geometry.get("coordinates")
        if (
            not isinstance(coordinates, list)
            or len(coordinates) < 2
            or not all(self._valid_coordinate_pair(item) for item in coordinates)
        ):
            raise InvalidRoutingResponse("Directions geometry coordinates are invalid.")

        summary = properties.get("summary")
        if not isinstance(summary, dict):
            raise InvalidRoutingResponse("Directions response has no route summary.")
        distance = summary.get("distance")
        duration = summary.get("duration")
        if not self._positive_number(distance) or not self._positive_number(duration):
            raise InvalidRoutingResponse("Directions distance or duration is invalid.")

        return ProviderRoute(
            geometry={"type": "LineString", "coordinates": coordinates},
            distance_meters=float(distance),
            duration_seconds=float(duration),
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(2):
            try:
                response = self.client.request(
                    method,
                    f"{self.base_url}{path}",
                    **kwargs,
                )
            except httpx.TransportError as exc:
                if attempt == 0:
                    self.sleep(0.25)
                    continue
                raise RoutingUnavailable("The routing provider could not be reached.") from exc

            if response.status_code in self.transient_statuses:
                if attempt == 0:
                    self.sleep(0.25)
                    continue
                raise RoutingUnavailable(
                    f"The routing provider returned HTTP {response.status_code}."
                )
            self._raise_for_provider_error(response)
            return response

        raise RoutingUnavailable("The routing provider could not be reached.")

    def _raise_for_provider_error(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        response_text = response.text.casefold()
        is_quota_error = (
            response.status_code == 429
            or response.headers.get("x-ratelimit-remaining") == "0"
            or any(term in response_text for term in ("rate limit", "quota", "too many"))
        )
        if is_quota_error:
            raise RoutingRateLimited(
                "The routing provider rate limit was reached.",
                retry_after_seconds=self._retry_after(response),
            )
        if response.status_code in {401, 403}:
            raise RoutingConfigurationError("The routing provider rejected the configured API key.")
        raise RoutingProviderError(
            f"The routing provider rejected the request with HTTP {response.status_code}."
        )

    def _require_api_key(self) -> None:
        if not has_valid_api_key(self.api_key):
            raise RoutingConfigurationError("OPENROUTESERVICE_API_KEY is not configured.")

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise InvalidRoutingResponse("The routing provider returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise InvalidRoutingResponse("The routing provider returned an invalid JSON object.")
        return payload

    @staticmethod
    def _retry_after(response: httpx.Response) -> int | None:
        value = response.headers.get("retry-after")
        if value is None:
            return None
        try:
            return max(0, int(value))
        except ValueError:
            return None

    @staticmethod
    def _positive_number(value: object) -> bool:
        return isinstance(value, int | float) and not isinstance(value, bool) and value > 0

    @staticmethod
    def _valid_coordinate_pair(value: object) -> bool:
        return (
            isinstance(value, list)
            and len(value) >= 2
            and all(
                isinstance(coordinate, int | float) and not isinstance(coordinate, bool)
                for coordinate in value[:2]
            )
        )

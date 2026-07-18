from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from routing.exceptions import (
    InvalidRoutingResponse,
    LocationNotFound,
    NoFeasibleFuelPlan,
    RoutingConfigurationError,
    RoutingProviderError,
    RoutingRateLimited,
    RoutingUnavailable,
)
from routing.serializers import (
    ErrorResponseSerializer,
    RoutePlanRequestSerializer,
    RoutePlanResponseSerializer,
    error_response,
    route_plan_response,
)
from routing.services import RoutePlanningService


class RoutePlanView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="create_route_plan",
        summary="Calculate a route and cost-effective fuel stops",
        description=(
            "Resolves two U.S. locations, retrieves a driving route, and returns "
            "fuel purchases for a vehicle that gets 10 MPG and has a 500-mile range. "
            "Starting fuel is treated as existing fuel unless initial-fill cost is enabled."
        ),
        request=RoutePlanRequestSerializer,
        responses={
            200: RoutePlanResponseSerializer,
            400: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Invalid input or unresolved location.",
            ),
            422: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="No station sequence can satisfy the vehicle range.",
            ),
            429: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="OpenRouteService rate limit or quota exceeded.",
            ),
            502: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="OpenRouteService unavailable or returned invalid data.",
            ),
            503: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="The OpenRouteService API key is not configured.",
            ),
        },
        examples=[
            OpenApiExample(
                "Dallas to Albuquerque",
                value={
                    "start": "Dallas, TX",
                    "finish": "Albuquerque, NM",
                    "include_initial_fill": False,
                },
                request_only=True,
            ),
            OpenApiExample(
                "Validation error",
                value=error_response(
                    code="VALIDATION_ERROR",
                    message="The request is invalid.",
                    details={
                        "initial_fuel_price_per_gallon": [
                            ("This field is required when include_initial_fill is true.")
                        ]
                    },
                ),
                response_only=True,
                status_codes=["400"],
            ),
            OpenApiExample(
                "No feasible fuel plan",
                value=error_response(
                    code="NO_FEASIBLE_FUEL_PLAN",
                    message=("No fuel-stop sequence can satisfy the 500-mile vehicle range."),
                    details={
                        "gap_start_mile": 412.6,
                        "gap_end_mile": 928.4,
                        "gap_miles": 515.8,
                    },
                ),
                response_only=True,
                status_codes=["422"],
            ),
        ],
        tags=["Route planning"],
    )
    def post(self, request: Request) -> Response:
        serializer = RoutePlanRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                error_response(
                    code="VALIDATION_ERROR",
                    message="The request is invalid.",
                    details=serializer.errors,
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            plan = self.get_planning_service().create_plan(**serializer.validated_data)
        except LocationNotFound as exc:
            return Response(
                error_response(
                    code="LOCATION_NOT_FOUND",
                    message=str(exc),
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )
        except NoFeasibleFuelPlan as exc:
            return Response(
                error_response(
                    code="NO_FEASIBLE_FUEL_PLAN",
                    message=str(exc),
                    details={
                        "gap_start_mile": round(exc.gap_start_mile, 2),
                        "gap_end_mile": round(exc.gap_end_mile, 2),
                        "gap_miles": round(exc.gap_miles, 2),
                    },
                ),
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except RoutingRateLimited as exc:
            response = Response(
                error_response(
                    code="ROUTING_RATE_LIMITED",
                    message=str(exc),
                ),
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            if exc.retry_after_seconds is not None:
                response["Retry-After"] = str(exc.retry_after_seconds)
            return response
        except RoutingConfigurationError:
            return Response(
                error_response(
                    code="ROUTING_NOT_CONFIGURED",
                    message=(
                        "OPENROUTESERVICE_API_KEY is not configured. "
                        "Copy .env.example to .env and add a valid key."
                    ),
                ),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except (
            InvalidRoutingResponse,
            RoutingProviderError,
            RoutingUnavailable,
        ) as exc:
            return Response(
                error_response(
                    code="ROUTING_UNAVAILABLE",
                    message=str(exc),
                ),
                status=status.HTTP_502_BAD_GATEWAY,
            )

        response_serializer = RoutePlanResponseSerializer(data=route_plan_response(plan))
        response_serializer.is_valid(raise_exception=True)
        return Response(response_serializer.validated_data)

    @staticmethod
    def get_planning_service() -> RoutePlanningService:
        return RoutePlanningService()

"""Project-level HTTP views."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response


@require_GET
def route_planner_demo(request: HttpRequest) -> HttpResponse:
    """Render the lightweight map-based route-planning demo."""
    return render(request, "config/route_planner_demo.html")


@extend_schema(
    summary="Check application health",
    responses={
        200: inline_serializer(
            name="HealthResponse",
            fields={"status": serializers.CharField()},
        )
    },
    tags=["System"],
)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def health(_request) -> Response:
    """Return process health without requiring a database connection."""
    return Response({"status": "ok"})

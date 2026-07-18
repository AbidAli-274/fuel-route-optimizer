"""Project-level HTTP views."""

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def health(_request) -> Response:
    """Return process health without requiring a database connection."""
    return Response({"status": "ok"})

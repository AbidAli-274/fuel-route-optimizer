from rest_framework.exceptions import ParseError
from rest_framework.response import Response
from rest_framework.views import exception_handler

from routing.serializers import error_response


def api_exception_handler(exc: Exception, context: dict) -> Response | None:
    response = exception_handler(exc, context)
    if response is not None and isinstance(exc, ParseError):
        response.data = error_response(
            code="VALIDATION_ERROR",
            message="The request body contains invalid JSON.",
            details={"body": [str(exc.detail)]},
        )
    return response

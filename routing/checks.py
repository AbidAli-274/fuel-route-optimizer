from django.conf import settings
from django.core.checks import Error, register

from routing.configuration import has_valid_api_key


@register()
def check_openrouteservice_api_key(**_kwargs) -> list[Error]:
    if has_valid_api_key(settings.ORS_API_KEY):
        return []
    return [
        Error(
            "OPENROUTESERVICE_API_KEY is not configured.",
            hint=(
                "Copy .env.example to .env, then add a valid key from "
                "https://openrouteservice.org/dev/#/signup."
            ),
            id="routing.E001",
        )
    ]

PLACEHOLDER_API_KEYS = frozenset(
    {
        "",
        "replace-with-openrouteservice-key",
        "replace-with-your-openrouteservice-key",
        "your-openrouteservice-api-key",
    }
)


def has_valid_api_key(value: str) -> bool:
    return value.strip().casefold() not in PLACEHOLDER_API_KEYS

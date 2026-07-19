"""Read-only Django admin views for routing caches."""

from django.contrib import admin
from django.utils import timezone

from routing.models import GeocodeCache, RouteCache


class ReadOnlyCacheAdmin(admin.ModelAdmin):
    """Allow cache inspection and deletion without manual cache mutation."""

    actions = None
    list_per_page = 50

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    @admin.display(boolean=True, description="Fresh")
    def is_fresh(self, obj) -> bool:
        return obj.expires_at > timezone.now()


@admin.register(GeocodeCache)
class GeocodeCacheAdmin(ReadOnlyCacheAdmin):
    list_display = (
        "normalized_query",
        "resolved_name",
        "provider",
        "cached_at",
        "expires_at",
        "is_fresh",
    )
    search_fields = ("normalized_query", "resolved_name", "cache_key")
    list_filter = ("provider",)
    ordering = ("-cached_at",)


@admin.register(RouteCache)
class RouteCacheAdmin(ReadOnlyCacheAdmin):
    list_display = (
        "cache_key",
        "provider",
        "profile",
        "distance_meters",
        "cached_at",
        "expires_at",
        "is_fresh",
    )
    search_fields = ("cache_key",)
    list_filter = ("provider", "profile")
    ordering = ("-cached_at",)

"""Django admin configuration for fuel data."""

from django.contrib import admin

from fuel.models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = (
        "opis_truckstop_id",
        "name",
        "city",
        "state",
        "retail_price",
        "coordinate_accuracy",
        "updated_at",
    )
    list_filter = ("state", "coordinate_accuracy")
    search_fields = (
        "=opis_truckstop_id",
        "name",
        "address",
        "city",
    )
    ordering = ("opis_truckstop_id",)
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 50

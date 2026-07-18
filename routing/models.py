from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class GeocodeCache(models.Model):
    cache_key = models.CharField(max_length=600, primary_key=True)
    provider = models.CharField(max_length=40)
    normalized_query = models.CharField(max_length=500)
    resolved_name = models.CharField(max_length=500)
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=[
            MinValueValidator(Decimal("-90")),
            MaxValueValidator(Decimal("90")),
        ],
    )
    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        validators=[
            MinValueValidator(Decimal("-180")),
            MaxValueValidator(Decimal("180")),
        ],
    )
    cached_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["cache_key"]

    def __str__(self) -> str:
        return self.cache_key


class RouteCache(models.Model):
    cache_key = models.CharField(max_length=300, primary_key=True)
    provider = models.CharField(max_length=40)
    profile = models.CharField(max_length=40)
    start_latitude = models.DecimalField(max_digits=9, decimal_places=6)
    start_longitude = models.DecimalField(max_digits=10, decimal_places=6)
    finish_latitude = models.DecimalField(max_digits=9, decimal_places=6)
    finish_longitude = models.DecimalField(max_digits=10, decimal_places=6)
    geometry = models.JSONField()
    distance_meters = models.FloatField(validators=[MinValueValidator(0.000001)])
    duration_seconds = models.FloatField(validators=[MinValueValidator(0.000001)])
    cached_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["cache_key"]

    def __str__(self) -> str:
        return self.cache_key

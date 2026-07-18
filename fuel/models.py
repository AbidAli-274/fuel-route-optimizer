from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class FuelStation(models.Model):
    class CoordinateAccuracy(models.TextChoices):
        CITY_CENTROID = "city_centroid", "City centroid"
        UNMATCHED = "unmatched", "Unmatched"

    opis_truckstop_id = models.PositiveBigIntegerField(unique=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=2)
    rack_id = models.PositiveIntegerField()
    retail_price = models.DecimalField(
        max_digits=10,
        decimal_places=8,
        validators=[MinValueValidator(Decimal("0.00000001"))],
    )
    source_row_count = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("-90")),
            MaxValueValidator(Decimal("90")),
        ],
    )
    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("-180")),
            MaxValueValidator(Decimal("180")),
        ],
    )
    coordinate_accuracy = models.CharField(
        max_length=20,
        choices=CoordinateAccuracy,
        default=CoordinateAccuracy.UNMATCHED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["opis_truckstop_id"]
        indexes = [models.Index(fields=["state", "city"], name="fuel_state_city_idx")]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(latitude__isnull=True, longitude__isnull=True)
                    | Q(latitude__isnull=False, longitude__isnull=False)
                ),
                name="fuel_coordinates_both_or_neither",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state})"

    def clean(self) -> None:
        super().clean()
        has_latitude = self.latitude is not None
        has_longitude = self.longitude is not None

        if has_latitude != has_longitude:
            raise ValidationError("Latitude and longitude must either both be set or both be null.")

        has_coordinates = has_latitude and has_longitude
        if has_coordinates and self.coordinate_accuracy == self.CoordinateAccuracy.UNMATCHED:
            raise ValidationError(
                {"coordinate_accuracy": "Matched coordinates require a matched accuracy."}
            )
        if not has_coordinates and self.coordinate_accuracy != self.CoordinateAccuracy.UNMATCHED:
            raise ValidationError(
                {"coordinate_accuracy": "Unmatched coordinates must use unmatched accuracy."}
            )

import csv
import io
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command

from fuel.models import FuelStation

CSV_FIELDNAMES = [
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
]


def write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_geonames_zip(
    path: Path,
    places: list[tuple[str, str, str, str]],
) -> Path:
    lines = []
    for index, (city, state, latitude, longitude) in enumerate(places):
        fields = [
            "US",
            f"79{index:03}",
            city,
            "Texas",
            state,
            "County",
            "001",
            "",
            "",
            latitude,
            longitude,
            "6",
        ]
        lines.append("\t".join(fields))

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("readme.txt", "GeoNames test fixture")
        archive.writestr("US.txt", "\n".join(lines))
    return path


def station_row(**overrides: str) -> dict[str, str]:
    row = {
        "OPIS Truckstop ID": "101",
        "Truckstop Name": "Example Stop",
        "Address": "I-40, Exit 75",
        "City": "Amarillo",
        "State": "TX",
        "Rack ID": "500",
        "Retail Price": "3.00000000",
    }
    row.update(overrides)
    return row


@pytest.fixture
def geonames_zip(tmp_path: Path) -> Path:
    return write_geonames_zip(
        tmp_path / "US.zip",
        [
            ("Amarillo", "TX", "35.2000", "-101.8500"),
            ("Amarillo", "TX", "35.2400", "-101.8100"),
        ],
    )


@pytest.mark.django_db
def test_import_normalizes_aggregates_filters_and_matches_coordinates(
    tmp_path: Path,
    geonames_zip: Path,
) -> None:
    csv_path = write_csv(
        tmp_path / "prices.csv",
        [
            station_row(
                **{
                    "Truckstop Name": " Example Stop ",
                    "Address": " I-40,   Exit 75 ",
                    "City": " Amarillo ",
                    "State": "tx",
                    "Retail Price": "3.00000000",
                }
            ),
            station_row(
                **{
                    "Truckstop Name": "Example Travel Center",
                    "Retail Price": "4.00000000",
                }
            ),
            station_row(
                **{
                    "OPIS Truckstop ID": "202",
                    "City": "Toronto",
                    "State": "ON",
                }
            ),
        ],
    )
    output = io.StringIO()

    call_command(
        "import_fuel_prices",
        csv=csv_path,
        geonames_zip=geonames_zip,
        stdout=output,
    )

    station = FuelStation.objects.get()
    assert station.opis_truckstop_id == 101
    assert station.name == "Example Travel Center"
    assert station.address == "I-40, Exit 75"
    assert station.city == "Amarillo"
    assert station.state == "TX"
    assert station.rack_id == 500
    assert station.retail_price == Decimal("3.50000000")
    assert station.source_row_count == 2
    assert station.latitude == Decimal("35.220000")
    assert station.longitude == Decimal("-101.830000")
    assert station.coordinate_accuracy == FuelStation.CoordinateAccuracy.CITY_CENTROID
    assert "Non-U.S. rows filtered: 1" in output.getvalue()
    assert "Duplicate observations aggregated: 1" in output.getvalue()
    assert "Stations coordinate-matched: 1" in output.getvalue()


@pytest.mark.django_db
def test_import_is_idempotent(tmp_path: Path, geonames_zip: Path) -> None:
    csv_path = write_csv(tmp_path / "prices.csv", [station_row()])
    call_command(
        "import_fuel_prices",
        csv=csv_path,
        geonames_zip=geonames_zip,
        stdout=io.StringIO(),
    )
    original_updated_at = FuelStation.objects.get().updated_at
    output = io.StringIO()

    call_command(
        "import_fuel_prices",
        csv=csv_path,
        geonames_zip=geonames_zip,
        stdout=output,
    )

    assert FuelStation.objects.count() == 1
    assert FuelStation.objects.get().updated_at == original_updated_at
    assert "Stations created: 0" in output.getvalue()
    assert "Stations updated: 0" in output.getvalue()
    assert "Stations unchanged: 1" in output.getvalue()


@pytest.mark.django_db
def test_partial_import_does_not_delete_existing_stations_by_default(
    tmp_path: Path,
    geonames_zip: Path,
) -> None:
    first_csv = write_csv(tmp_path / "first.csv", [station_row()])
    second_csv = write_csv(
        tmp_path / "second.csv",
        [station_row(**{"OPIS Truckstop ID": "202"})],
    )
    call_command(
        "import_fuel_prices",
        csv=first_csv,
        geonames_zip=geonames_zip,
        stdout=io.StringIO(),
    )

    call_command(
        "import_fuel_prices",
        csv=second_csv,
        geonames_zip=geonames_zip,
        stdout=io.StringIO(),
    )

    assert set(FuelStation.objects.values_list("opis_truckstop_id", flat=True)) == {
        101,
        202,
    }


@pytest.mark.django_db
def test_replace_import_deletes_stations_absent_from_csv(
    tmp_path: Path,
    geonames_zip: Path,
) -> None:
    first_csv = write_csv(tmp_path / "first.csv", [station_row()])
    second_csv = write_csv(
        tmp_path / "second.csv",
        [station_row(**{"OPIS Truckstop ID": "202"})],
    )
    call_command(
        "import_fuel_prices",
        csv=first_csv,
        geonames_zip=geonames_zip,
        stdout=io.StringIO(),
    )

    call_command(
        "import_fuel_prices",
        csv=second_csv,
        geonames_zip=geonames_zip,
        replace=True,
        stdout=io.StringIO(),
    )

    assert list(FuelStation.objects.values_list("opis_truckstop_id", flat=True)) == [202]


@pytest.mark.django_db
def test_import_reports_truncated_csv_rows(
    tmp_path: Path,
    geonames_zip: Path,
) -> None:
    csv_path = tmp_path / "truncated.csv"
    csv_path.write_text(
        ",".join(CSV_FIELDNAMES) + "\n101,Example Stop\n",
        encoding="utf-8",
    )

    with pytest.raises(CommandError, match="Row 2: missing values"):
        call_command(
            "import_fuel_prices",
            csv=csv_path,
            geonames_zip=geonames_zip,
        )


@pytest.mark.django_db
def test_import_retains_unmatched_station_without_coordinates(
    tmp_path: Path,
    geonames_zip: Path,
) -> None:
    csv_path = write_csv(
        tmp_path / "prices.csv",
        [station_row(**{"City": "Unknown Place"})],
    )

    call_command(
        "import_fuel_prices",
        csv=csv_path,
        geonames_zip=geonames_zip,
        stdout=io.StringIO(),
    )

    station = FuelStation.objects.get()
    assert station.latitude is None
    assert station.longitude is None
    assert station.coordinate_accuracy == FuelStation.CoordinateAccuracy.UNMATCHED


@pytest.mark.django_db
def test_import_rejects_conflicting_physical_station_ids(
    tmp_path: Path,
    geonames_zip: Path,
) -> None:
    csv_path = write_csv(
        tmp_path / "prices.csv",
        [
            station_row(),
            station_row(**{"Address": "Different address"}),
        ],
    )

    with pytest.raises(
        CommandError,
        match="refers to conflicting physical stations",
    ):
        call_command(
            "import_fuel_prices",
            csv=csv_path,
            geonames_zip=geonames_zip,
        )

    assert not FuelStation.objects.exists()


def test_model_requires_a_complete_coordinate_pair() -> None:
    station = FuelStation(
        opis_truckstop_id=101,
        name="Example Stop",
        address="I-40, Exit 75",
        city="Amarillo",
        state="TX",
        rack_id=500,
        retail_price=Decimal("3.00000000"),
        source_row_count=1,
        latitude=Decimal("35.200000"),
        coordinate_accuracy=FuelStation.CoordinateAccuracy.CITY_CENTROID,
    )

    with pytest.raises(ValidationError, match="both be set or both be null"):
        station.full_clean(validate_unique=False, validate_constraints=False)


def test_model_rejects_free_text_coordinate_accuracy() -> None:
    station = FuelStation(
        opis_truckstop_id=101,
        name="Example Stop",
        address="I-40, Exit 75",
        city="Amarillo",
        state="TX",
        rack_id=500,
        retail_price=Decimal("3.00000000"),
        source_row_count=1,
        coordinate_accuracy="approximately_correct",
    )

    with pytest.raises(ValidationError):
        station.full_clean(validate_unique=False, validate_constraints=False)

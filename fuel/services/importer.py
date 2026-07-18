import csv
import re
import statistics
import tempfile
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from fuel.models import FuelStation

CSV_FIELDS = {
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
}
PRICE_QUANTUM = Decimal("0.00000001")
COORDINATE_QUANTUM = Decimal("0.000001")
GEONAMES_DOWNLOAD_URL = "https://download.geonames.org/export/zip/US.zip"
US_STATE_CODES = frozenset(
    """
    AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS
    MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV
    WI WY DC
    """.split()
)
WHITESPACE_RE = re.compile(r"\s+")


class ImportDataError(ValueError):
    """Raised when source data cannot be imported safely."""


@dataclass(frozen=True)
class StationRecord:
    opis_truckstop_id: int
    name: str
    address: str
    city: str
    state: str
    rack_id: int
    retail_price: Decimal
    source_row_count: int
    latitude: Decimal | None
    longitude: Decimal | None
    coordinate_accuracy: str


@dataclass(frozen=True)
class ImportSummary:
    source_rows: int
    us_rows: int
    non_us_rows: int
    duplicate_rows: int
    matched_stations: int
    unmatched_stations: int
    created: int
    updated: int
    unchanged: int
    deleted: int


def normalize_whitespace(value: str | None) -> str:
    if value is None:
        return ""
    return WHITESPACE_RE.sub(" ", value).strip()


def normalize_key(value: str) -> str:
    return normalize_whitespace(value).casefold()


def parse_positive_integer(value: str, *, field: str, row_number: int) -> int:
    try:
        parsed = int(normalize_whitespace(value))
    except (TypeError, ValueError) as exc:
        raise ImportDataError(f"Row {row_number}: {field} must be an integer.") from exc
    if parsed <= 0:
        raise ImportDataError(f"Row {row_number}: {field} must be positive.")
    return parsed


def parse_price(value: str, *, row_number: int) -> Decimal:
    try:
        parsed = Decimal(normalize_whitespace(value))
    except (InvalidOperation, TypeError) as exc:
        raise ImportDataError(f"Row {row_number}: Retail Price must be a decimal.") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ImportDataError(f"Row {row_number}: Retail Price must be positive.")
    return parsed


def canonical_text(values: list[str]) -> str:
    normalized_values = {normalize_whitespace(value) for value in values}
    return sorted(
        normalized_values,
        key=lambda value: (-len(value), value.casefold(), value),
    )[0]


def load_city_coordinates(
    geonames_zip_path: Path,
) -> dict[tuple[str, str], tuple[Decimal, Decimal]]:
    coordinate_groups: dict[tuple[str, str], list[tuple[Decimal, Decimal]]] = defaultdict(list)

    try:
        archive = zipfile.ZipFile(geonames_zip_path)
    except (FileNotFoundError, zipfile.BadZipFile) as exc:
        raise ImportDataError(
            f"GeoNames archive is unavailable or invalid: {geonames_zip_path}"
        ) from exc

    with archive:
        text_files = [name for name in archive.namelist() if name.lower().endswith(".txt")]
        if not text_files:
            raise ImportDataError("GeoNames archive does not contain a text dataset.")
        dataset_name = next(
            (name for name in text_files if Path(name).name.casefold() == "us.txt"),
            text_files[0],
        )

        with archive.open(dataset_name) as source:
            for raw_line in source:
                fields = raw_line.decode("utf-8").rstrip("\n").split("\t")
                if len(fields) < 11 or fields[0] != "US":
                    continue
                city = normalize_key(fields[2])
                state = normalize_whitespace(fields[4]).upper()
                try:
                    latitude = Decimal(fields[9])
                    longitude = Decimal(fields[10])
                except InvalidOperation:
                    continue
                if city and state:
                    coordinate_groups[(city, state)].append((latitude, longitude))

    coordinates: dict[tuple[str, str], tuple[Decimal, Decimal]] = {}
    for key, values in coordinate_groups.items():
        latitude = statistics.median(value[0] for value in values).quantize(
            COORDINATE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        longitude = statistics.median(value[1] for value in values).quantize(
            COORDINATE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        coordinates[key] = (latitude, longitude)
    return coordinates


def build_station_records(
    csv_path: Path,
    coordinates: dict[tuple[str, str], tuple[Decimal, Decimal]],
) -> tuple[list[StationRecord], dict[str, int]]:
    """Normalize CSV rows into one validated record per OPIS station."""
    grouped_rows: dict[int, list[dict[str, object]]] = defaultdict(list)
    source_rows = 0
    us_rows = 0
    non_us_rows = 0

    try:
        source = csv_path.open(encoding="utf-8-sig", newline="")
    except FileNotFoundError as exc:
        raise ImportDataError(f"CSV file does not exist: {csv_path}") from exc

    with source:
        reader = csv.DictReader(source)
        missing_fields = CSV_FIELDS - set(reader.fieldnames or ())
        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise ImportDataError(f"CSV is missing required columns: {missing}.")

        for row_number, row in enumerate(reader, start=2):
            source_rows += 1
            missing_values = [field for field in CSV_FIELDS if row.get(field) is None]
            if missing_values:
                missing = ", ".join(sorted(missing_values))
                raise ImportDataError(f"Row {row_number}: missing values for {missing}.")
            state = normalize_whitespace(row["State"]).upper()
            if state not in US_STATE_CODES:
                non_us_rows += 1
                continue

            values = {
                "opis_truckstop_id": parse_positive_integer(
                    row["OPIS Truckstop ID"],
                    field="OPIS Truckstop ID",
                    row_number=row_number,
                ),
                "name": normalize_whitespace(row["Truckstop Name"]),
                "address": normalize_whitespace(row["Address"]),
                "city": normalize_whitespace(row["City"]),
                "state": state,
                "rack_id": parse_positive_integer(
                    row["Rack ID"],
                    field="Rack ID",
                    row_number=row_number,
                ),
                "retail_price": parse_price(
                    row["Retail Price"],
                    row_number=row_number,
                ),
            }
            for field in ("name", "address", "city"):
                if not values[field]:
                    raise ImportDataError(f"Row {row_number}: {field} is required.")

            grouped_rows[values["opis_truckstop_id"]].append(values)
            us_rows += 1

    if not grouped_rows:
        raise ImportDataError("CSV does not contain any U.S. fuel stations.")

    records: list[StationRecord] = []
    for opis_id, observations in grouped_rows.items():
        physical_locations = {
            (
                normalize_key(str(observation["address"])),
                normalize_key(str(observation["city"])),
                observation["state"],
                observation["rack_id"],
            )
            for observation in observations
        }
        if len(physical_locations) != 1:
            raise ImportDataError(
                f"OPIS Truckstop ID {opis_id} refers to conflicting physical stations."
            )

        city = canonical_text([str(item["city"]) for item in observations])
        state = str(observations[0]["state"])
        coordinate = coordinates.get((normalize_key(city), state))
        latitude, longitude = coordinate or (None, None)
        accuracy = (
            FuelStation.CoordinateAccuracy.CITY_CENTROID
            if coordinate
            else FuelStation.CoordinateAccuracy.UNMATCHED
        )
        median_price = statistics.median(item["retail_price"] for item in observations).quantize(
            PRICE_QUANTUM, rounding=ROUND_HALF_UP
        )

        records.append(
            StationRecord(
                opis_truckstop_id=opis_id,
                name=canonical_text([str(item["name"]) for item in observations]),
                address=canonical_text([str(item["address"]) for item in observations]),
                city=city,
                state=state,
                rack_id=int(observations[0]["rack_id"]),
                retail_price=median_price,
                source_row_count=len(observations),
                latitude=latitude,
                longitude=longitude,
                coordinate_accuracy=accuracy,
            )
        )

    records.sort(key=lambda record: record.opis_truckstop_id)
    return records, {
        "source_rows": source_rows,
        "us_rows": us_rows,
        "non_us_rows": non_us_rows,
        "duplicate_rows": us_rows - len(records),
    }


def download_geonames_archive(url: str, destination: Path) -> Path:
    """Download the GeoNames archive once and return its local path."""
    if destination.exists():
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (
            urllib.request.urlopen(url, timeout=30) as response,
            tempfile.NamedTemporaryFile(
                dir=destination.parent,
                delete=False,
            ) as temporary_file,
        ):
            temporary_path = Path(temporary_file.name)
            temporary_file.write(response.read())
        temporary_path.replace(destination)
    except OSError as exc:
        raise ImportDataError(f"Unable to download GeoNames data from {url}.") from exc
    return destination


@transaction.atomic
def synchronize_stations(
    records: list[StationRecord],
    source_counts: dict[str, int],
    *,
    replace_existing: bool = False,
) -> ImportSummary:
    """Upsert station records and optionally remove rows absent from the source."""
    existing = FuelStation.objects.in_bulk(field_name="opis_truckstop_id")
    now = timezone.now()
    to_create: list[FuelStation] = []
    to_update: list[FuelStation] = []
    unchanged = 0
    incoming_ids = {record.opis_truckstop_id for record in records}
    synchronized_fields = tuple(StationRecord.__dataclass_fields__)

    for record in records:
        values = record.__dict__
        station = existing.get(record.opis_truckstop_id)
        if station is None:
            station = FuelStation(**values, created_at=now, updated_at=now)
            _validate_station(station)
            to_create.append(station)
            continue

        if all(getattr(station, field) == values[field] for field in synchronized_fields):
            unchanged += 1
            continue

        for field in synchronized_fields:
            setattr(station, field, values[field])
        station.updated_at = now
        _validate_station(station)
        to_update.append(station)

    if to_create:
        FuelStation.objects.bulk_create(to_create, batch_size=500)
    if to_update:
        FuelStation.objects.bulk_update(
            to_update,
            [*synchronized_fields, "updated_at"],
            batch_size=500,
        )

    stale_primary_keys = (
        [station.pk for opis_id, station in existing.items() if opis_id not in incoming_ids]
        if replace_existing
        else []
    )
    deleted = 0
    for offset in range(0, len(stale_primary_keys), 500):
        batch = stale_primary_keys[offset : offset + 500]
        batch_deleted, _ = FuelStation.objects.filter(pk__in=batch).delete()
        deleted += batch_deleted

    matched = sum(record.latitude is not None for record in records)
    return ImportSummary(
        **source_counts,
        matched_stations=matched,
        unmatched_stations=len(records) - matched,
        created=len(to_create),
        updated=len(to_update),
        unchanged=unchanged,
        deleted=deleted,
    )


def _validate_station(station: FuelStation) -> None:
    try:
        station.full_clean(validate_unique=False)
    except ValidationError as exc:
        raise ImportDataError(
            f"Station {station.opis_truckstop_id} failed validation: {exc}"
        ) from exc

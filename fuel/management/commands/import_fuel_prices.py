from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from fuel.services.importer import (
    GEONAMES_DOWNLOAD_URL,
    ImportDataError,
    build_station_records,
    download_geonames_archive,
    load_city_coordinates,
    synchronize_stations,
)


class Command(BaseCommand):
    help = "Import and normalize the assessment fuel-price CSV."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--csv",
            type=Path,
            default=settings.BASE_DIR / "fuel-prices-for-be-assessment.csv",
            help="Path to the assessment fuel-price CSV.",
        )
        parser.add_argument(
            "--geonames-zip",
            type=Path,
            help="Path to a local GeoNames US postal-code ZIP.",
        )
        parser.add_argument(
            "--geonames-url",
            default=GEONAMES_DOWNLOAD_URL,
            help="GeoNames archive URL used when --geonames-zip is omitted.",
        )

    def handle(self, *args, **options) -> None:
        csv_path: Path = options["csv"]
        geonames_path: Path | None = options["geonames_zip"]

        try:
            if geonames_path is None:
                geonames_path = download_geonames_archive(
                    options["geonames_url"],
                    settings.BASE_DIR / ".cache" / "geonames" / "US.zip",
                )
            coordinates = load_city_coordinates(geonames_path)
            records, source_counts = build_station_records(csv_path, coordinates)
            summary = synchronize_stations(records, source_counts)
        except ImportDataError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Fuel-price import completed."))
        self.stdout.write(f"Source rows: {summary.source_rows}")
        self.stdout.write(f"U.S. rows: {summary.us_rows}")
        self.stdout.write(f"Non-U.S. rows filtered: {summary.non_us_rows}")
        self.stdout.write(f"Duplicate observations aggregated: {summary.duplicate_rows}")
        self.stdout.write(f"Stations created: {summary.created}")
        self.stdout.write(f"Stations updated: {summary.updated}")
        self.stdout.write(f"Stations unchanged: {summary.unchanged}")
        self.stdout.write(f"Stale stations deleted: {summary.deleted}")
        self.stdout.write(f"Stations coordinate-matched: {summary.matched_stations}")
        self.stdout.write(f"Stations unmatched: {summary.unmatched_stations}")

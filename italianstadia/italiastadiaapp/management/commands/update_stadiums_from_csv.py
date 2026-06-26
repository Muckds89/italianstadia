# italiastadiaapp/management/commands/update_stadiums_from_csv.py

import csv
from pathlib import Path
from datetime import datetime

from django.core.management.base import BaseCommand
from italiastadiaapp.models import Stadium


class Command(BaseCommand):
    help = "Update Stadium missing fields from CSV. Dry-run by default and writes backup CSV."

    OWNERSHIP_MAP = {
        "public": "PUBLIC",
        "private": "PRIVATE",
        "mixed": "MIXED",
        "unknown": "UNKNOWN",
    }

    STADIUM_TYPE_MAP = {
        "open": "OPEN",
        "closed": "CLOSED",
        "retractable": "RETRACTABLE",
        "retractable roof": "RETRACTABLE",
        "indoor": "INDOOR",
    }

    SURFACE_MAP = {
        "grass": "GRASS",
        "natural grass": "GRASS",
        "natural turf": "GRASS",
        "artificial": "ARTIFICIAL",
        "artificial turf": "ARTIFICIAL",
        "synthetic": "ARTIFICIAL",
        "synthetic turf": "ARTIFICIAL",
        "hybrid": "HYBRID",
        "hybrid grass": "HYBRID",
    }

    def add_arguments(self, parser):
        parser.add_argument("--csv", default="italiastadiaapp/data/stadium_missing_data_import.csv")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--backup-csv", default=None)

    def clean_text(self, value):
        return str(value or "").strip()

    def clean_int(self, value):
        value = str(value or "").strip().replace(",", "")
        return int(value) if value else None

    def normalize_choice(self, field, value):
        value = self.clean_text(value)

        if not value:
            return ""

        key = value.lower()

        maps = {
            "ownership": self.OWNERSHIP_MAP,
            "stadium_type": self.STADIUM_TYPE_MAP,
            "surface": self.SURFACE_MAP,
        }

        valid = maps[field]

        if key not in valid:
            raise ValueError(
                f"Invalid {field} value '{value}'. "
                f"Expected one of: {sorted(valid.keys())}"
            )

        return valid[key]

    def handle(self, *args, **options):
        input_csv = Path(options["csv"])
        commit = options["commit"]

        backup_csv = Path(
            options["backup_csv"]
            or f"stadium_backup_{datetime.now():%Y%m%d_%H%M%S}.csv"
        )

        fields = [
            "capacity",
            "address",
            "year_of_construction",
            "owner_raw",
            "ownership",
            "stadium_type",
            "surface",
            "architect",
            "wikipedia_url",
            "transfermarkt_url",
            "image_url",
            "image_credit",
        ]

        int_fields = {"capacity", "year_of_construction"}
        choice_fields = {"ownership", "stadium_type", "surface"}

        backup_rows = []

        with input_csv.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            for row in reader:
                stadium_id = row["stadium_id"].strip()

                try:
                    stadium = Stadium.objects.get(id=stadium_id)
                except Stadium.DoesNotExist:
                    self.stderr.write(self.style.ERROR(f"[MISSING] Stadium ID {stadium_id} not found"))
                    continue

                changes = {}

                for field in fields:
                    if field not in row:
                        continue

                    raw_value = row.get(field)

                    try:
                        if field in int_fields:
                            new_value = self.clean_int(raw_value)
                        elif field in choice_fields:
                            new_value = self.normalize_choice(field, raw_value)
                        else:
                            new_value = self.clean_text(raw_value)
                    except ValueError as e:
                        self.stderr.write(self.style.ERROR(f"[SKIP] Stadium {stadium_id}: {e}"))
                        continue

                    # Do not overwrite existing values with blanks
                    if new_value in [None, ""]:
                        continue

                    old_value = getattr(stadium, field, None)

                    if old_value != new_value:
                        changes[field] = (old_value, new_value)

                if not changes:
                    self.stdout.write(f"[NO CHANGE] {stadium.id} {stadium.name}")
                    continue

                self.stdout.write(f"\n{'[UPDATE]' if commit else '[DRY RUN]'} {stadium.id} {stadium.name}")

                for field, (old, new) in changes.items():
                    self.stdout.write(f"  {field}: {old} -> {new}")

                    backup_rows.append({
                        "stadium_id": stadium.id,
                        "stadium_name": stadium.name,
                        "field_name": field,
                        "old_value": "" if old is None else old,
                        "new_value": "" if new is None else new,
                    })

                if commit:
                    for field, (_, new) in changes.items():
                        setattr(stadium, field, new)

                    stadium.save()

        with backup_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["stadium_id", "stadium_name", "field_name", "old_value", "new_value"],
            )
            writer.writeheader()
            writer.writerows(backup_rows)

        self.stdout.write(self.style.SUCCESS(f"\nBackup CSV written to: {backup_csv}"))

        if not commit:
            self.stdout.write(self.style.WARNING("Dry run only: database was not changed."))
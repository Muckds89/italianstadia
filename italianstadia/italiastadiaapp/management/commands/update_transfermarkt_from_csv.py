import csv
from pathlib import Path
from datetime import datetime

from django.core.management.base import BaseCommand
from italiastadiaapp.models import Team


class Command(BaseCommand):
    help = "Update Team Transfermarkt fields from CSV. Dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument("--csv", default="italiastadiaapp/data/missing_transfermarkt_data_with_attendance.csv")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--backup-csv", default=None)

    def clean_int(self, value):
        value = str(value or "").strip().replace(",", "")
        return int(value) if value else None

    def clean_text(self, value):
        return str(value or "").strip()

    def handle(self, *args, **options):
        input_csv = Path(options["csv"])
        commit = options["commit"]

        backup_csv = Path(
            options["backup_csv"]
            or f"team_transfermarkt_backup_{datetime.now():%Y%m%d_%H%M%S}.csv"
        )

        backup_rows = []

        with input_csv.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            for row in reader:
                team = Team.objects.get(id=row["team_id"].strip())

                updates = {
                    "transfermarkt_id": self.clean_int(row.get("transfermarkt_id")),
                    "transfermarkt_url": self.clean_text(row.get("transfermarkt_url")),
                    "image_url": self.clean_text(row.get("image_url")),
                    "average_attendance": self.clean_int(row.get("average_attendance")),
                }

                changes = {}

                for field, new_value in updates.items():
                    old_value = getattr(team, field, None)

                    if old_value != new_value:
                        changes[field] = (old_value, new_value)

                if not changes:
                    self.stdout.write(f"[NO CHANGE] {team.id} {team.name}")
                    continue

                self.stdout.write(f"\n{'[UPDATE]' if commit else '[DRY RUN]'} {team.id} {team.name}")

                for field, (old, new) in changes.items():
                    self.stdout.write(f"  {field}: {old} -> {new}")

                    backup_rows.append({
                        "team_id": team.id,
                        "team_name": team.name,
                        "field_name": field,
                        "old_value": "" if old is None else old,
                        "new_value": "" if new is None else new,
                    })

                if commit:
                    for field, (_, new) in changes.items():
                        setattr(team, field, new)

                    team.save()

        with backup_csv.open("w", encoding="utf-8", newline="") as f:
            fieldnames = ["team_id", "team_name", "field_name", "old_value", "new_value"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(backup_rows)

        self.stdout.write(self.style.SUCCESS(f"\nBackup CSV written to: {backup_csv}"))

        if not commit:
            self.stdout.write(self.style.WARNING("Dry run only: database was not changed."))
# management/commands/update_stadium_surfaces_from_csv.py
import csv
from django.core.management.base import BaseCommand
from django.db import transaction
from italiastadiaapp.models import Stadium

VALID_SURFACES = {"GRASS", "ARTIFICIAL", "HYBRID"}

class Command(BaseCommand):
    help = "Update Stadium.surface from CSV after creating a backup CSV."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--backup", default="stadium_surface_backup.csv")

    def handle(self, *args, **opts):
        csv_path = opts["csv_path"]
        commit = opts["commit"]
        backup_path = opts["backup"]

        updates = []
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sid = row.get("stadium_id") or row.get("id")
                surface = (row.get("surface") or "").strip().upper()
                if not sid or not surface:
                    continue
                if surface not in VALID_SURFACES:
                    self.stdout.write(self.style.WARNING(f"Skipping {sid}: invalid surface {surface}"))
                    continue
                updates.append((int(sid), surface))

        stadiums = Stadium.objects.in_bulk([sid for sid, _ in updates])

        with open(backup_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["stadium_id", "stadium_name", "field_name", "old_value", "new_value"])
            for sid, new_surface in updates:
                s = stadiums.get(sid)
                if not s:
                    self.stdout.write(self.style.WARNING(f"Missing stadium id {sid}"))
                    continue
                writer.writerow([s.id, s.name, "surface", s.surface or "", new_surface])

        self.stdout.write(f"Backup written: {backup_path}")

        if not commit:
            self.stdout.write(self.style.WARNING("Dry run only. Re-run with --commit to update DB."))
            for sid, new_surface in updates[:20]:
                s = stadiums.get(sid)
                if s:
                    self.stdout.write(f"{s.id} | {s.name}: {s.surface or ''} -> {new_surface}")
            self.stdout.write(f"Rows ready: {len(updates)}")
            return

        with transaction.atomic():
            count = 0
            for sid, new_surface in updates:
                s = stadiums.get(sid)
                if not s:
                    continue
                s.surface = new_surface
                s.save(update_fields=["surface"])
                count += 1

        self.stdout.write(self.style.SUCCESS(f"Updated {count} stadium surfaces."))

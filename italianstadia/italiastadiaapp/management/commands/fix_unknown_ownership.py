"""
Re-classify UNKNOWN ownership stadiums where owner_raw has a value.

Usage:
    python manage.py fix_unknown_ownership --dry-run   # preview changes
    python manage.py fix_unknown_ownership             # apply
"""
from django.core.management.base import BaseCommand
from italiastadiaapp.models import Stadium
from italiastadiaapp.ownership import classify_ownership


class Command(BaseCommand):
    help = "Re-classify UNKNOWN ownership stadiums where owner_raw has a value"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show what would change without writing to the database",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        unknown_qs = Stadium.objects.filter(ownership="UNKNOWN").exclude(
            owner_raw__isnull=True
        ).exclude(owner_raw="")

        self.stdout.write(f"Found {unknown_qs.count()} UNKNOWN stadiums with owner_raw set")
        changed = 0

        for s in unknown_qs:
            new_ownership = classify_ownership(s.owner_raw)
            if new_ownership == "UNKNOWN":
                new_ownership = "PRIVATE"

            action = "[dry-run]" if dry_run else "→"
            self.stdout.write(f"  {s.name}: '{s.owner_raw}' {action} {new_ownership}")

            if not dry_run:
                s.ownership = new_ownership
                s.save(update_fields=["ownership"])
                changed += 1

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"\nDry run complete — {unknown_qs.count()} stadiums would be updated. "
                f"Run without --dry-run to apply."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nUpdated {changed} stadiums."))

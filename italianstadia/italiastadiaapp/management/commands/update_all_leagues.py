"""
update_all_leagues
==================
Orchestrator that runs scrape_season for every urls_*.json file found in
scripts/data/, then refreshes UEFA country rankings and club coefficients.

Usage examples
--------------
# Preview all leagues (no DB writes, no network calls):
    python manage.py update_all_leagues --dry-run

# Full refresh of every configured league:
    python manage.py update_all_leagues

# Refresh only two specific leagues:
    python manage.py update_all_leagues --leagues serie-a bundesliga

# Scrape all leagues but skip the UEFA meta-update at the end:
    python manage.py update_all_leagues --skip-meta
"""

import glob
import os

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


def _all_league_slugs():
    """
    Return hyphenated slugs for every urls_*.json file in scripts/data/,
    sorted alphabetically.  Example: urls_serie_a.json → "serie-a".
    """
    data_dir = os.path.join(settings.BASE_DIR, "scripts", "data")
    paths = glob.glob(os.path.join(data_dir, "urls_*.json"))
    slugs = []
    for p in sorted(paths):
        basename = os.path.basename(p)                    # urls_serie_a.json
        slug = basename[len("urls_"):-len(".json")]       # serie_a
        slugs.append(slug.replace("_", "-"))              # serie-a
    return slugs


class Command(BaseCommand):
    help = (
        "Scrape all configured leagues from Transfermarkt, "
        "then refresh UEFA country rankings and club coefficients."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--leagues",
            nargs="+",
            metavar="SLUG",
            help=(
                "Run only these league slugs "
                "(e.g. --leagues serie-a bundesliga). "
                "Defaults to every urls_*.json file in scripts/data/."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Pass --dry-run to each scrape_season call; no DB writes.",
        )
        parser.add_argument(
            "--skip-meta",
            action="store_true",
            help="Skip update_uefa_ranking and update_club_coefficients at the end.",
        )

    def handle(self, *args, **options):
        slugs     = options["leagues"] or _all_league_slugs()
        dry_run   = options["dry_run"]
        skip_meta = options["skip_meta"]

        self.stdout.write(self.style.HTTP_INFO(
            f"\nupdate_all_leagues — {len(slugs)} league(s) | "
            f"{'DRY RUN' if dry_run else 'FULL SCRAPE'}\n"
        ))

        ok = failed = 0

        for slug in slugs:
            self.stdout.write(f"\n{'-' * 60}")
            self.stdout.write(self.style.HTTP_INFO(f"  [{ok + failed + 1}/{len(slugs)}] {slug}"))
            try:
                kwargs = {"league": slug}
                if dry_run:
                    kwargs["dry_run"] = True
                call_command("scrape_season", **kwargs)
                ok += 1
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  FAILED: {exc}"))
                failed += 1
                # Continue to the next league — don't abort the whole run

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(self.style.SUCCESS(f"  Leagues OK:     {ok}"))
        if failed:
            self.stdout.write(self.style.ERROR(f"  Leagues FAILED: {failed}"))

        if not dry_run and not skip_meta:
            self.stdout.write(self.style.HTTP_INFO("\nUpdating UEFA country rankings…"))
            try:
                call_command("update_uefa_ranking")
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  update_uefa_ranking failed: {exc}"))

            self.stdout.write(self.style.HTTP_INFO("Updating UEFA club coefficients…"))
            try:
                call_command("update_club_coefficients")
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  update_club_coefficients failed: {exc}"))

        self.stdout.write(self.style.SUCCESS("\nDone.\n"))

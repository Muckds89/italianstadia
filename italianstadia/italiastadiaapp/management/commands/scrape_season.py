import importlib.util
import json
import os
import sys

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


def _load_scraper():
    """Import the standalone scraper module without polluting sys.modules."""
    scripts_path = os.path.join(settings.BASE_DIR, "scripts")
    spec = importlib.util.spec_from_file_location(
        "_transfermrkt_scraper",
        os.path.join(scripts_path, "populate_data_from_transfermrkt.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _season_from_year(year: int) -> str:
    return f"{str(year - 1)[2:]}/{str(year)[2:]}"


class Command(BaseCommand):
    help = "Scrape Transfermarkt data for a league season"

    def add_arguments(self, parser):
        parser.add_argument(
            "--league",
            required=True,
            help="League slug matching scripts/data/urls_<slug>.json  (e.g. serie-a, bundesliga)",
        )
        parser.add_argument(
            "--year",
            type=int,
            help="Season end year (e.g. 2025 → season string '24/25'). "
                 "Defaults to the season field in the JSON config.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate config and show CREATE/UPDATE per team; no network calls, no DB writes.",
        )

    def handle(self, *args, **options):
        league_slug = options["league"]
        year = options.get("year")
        dry_run = options["dry_run"]

        data_file = os.path.join(
            settings.BASE_DIR,
            "scripts",
            "data",
            f"urls_{league_slug.replace('-', '_')}.json",
        )
        if not os.path.exists(data_file):
            raise CommandError(f"Config file not found: {data_file}")

        with open(data_file, encoding="utf-8") as f:
            data = json.load(f)

        league_config = data["league"]
        season = _season_from_year(year) if year else league_config["season"]

        self.stdout.write(self.style.HTTP_INFO(
            f"\nLeague : {league_config['name']} ({league_config['country']})"
        ))
        self.stdout.write(f"Season : {season}")
        self.stdout.write(f"Teams  : {len(data['teams'])}")
        self.stdout.write(f"Mode   : {'DRY RUN' if dry_run else 'FULL SCRAPE'}\n")

        if dry_run:
            self._dry_run(data, league_config, season)
        else:
            self._full_scrape(league_slug, season)

    # ------------------------------------------------------------------
    # Dry-run: DB state check, no network
    # ------------------------------------------------------------------

    def _dry_run(self, data, league_config, season):
        from italiastadiaapp.models import Country, League, Stadium, Team

        self.stdout.write("-" * 50)

        country_exists = Country.objects.filter(name=league_config["country"]).exists()
        self.stdout.write(
            f"Country '{league_config['country']}': "
            + (self.style.SUCCESS("EXISTS") if country_exists else self.style.WARNING("WILL CREATE"))
        )

        league_exists = League.objects.filter(
            name=league_config["name"],
            country__name=league_config["country"],
        ).exists()
        self.stdout.write(
            f"League  '{league_config['name']}': "
            + (self.style.SUCCESS("EXISTS") if league_exists else self.style.WARNING("WILL CREATE"))
        )

        self.stdout.write("\nTeams:")
        creates = updates = 0
        for team_data in data["teams"]:
            name = team_data["name"]
            stadium_name = team_data.get("stadium", {}).get("name", "?")
            team_exists = Team.objects.filter(name=name).exists()
            action = "UPDATE" if team_exists else "CREATE"
            color = self.style.SUCCESS if team_exists else self.style.WARNING
            self.stdout.write(f"  [{color(action)}] {name:<35} stadium: {stadium_name}")
            if team_exists:
                updates += 1
            else:
                creates += 1

        self.stdout.write("-" * 50)
        self.stdout.write(
            f"\nSummary: {self.style.WARNING(str(creates))} to create, "
            f"{self.style.SUCCESS(str(updates))} to update  —  no changes made."
        )

    # ------------------------------------------------------------------
    # Full scrape: delegate to the standalone scraper module
    # ------------------------------------------------------------------

    def _full_scrape(self, league_slug, season_override):
        self.stdout.write("Loading scraper module…")
        scraper = _load_scraper()

        self.stdout.write(f"Starting scrape for '{league_slug}' (season override: {season_override or 'none'})…")
        scraper.run(league_slug, season_override=season_override)
        self.stdout.write(self.style.SUCCESS("\nScrape complete. Check scraping_transfermarkt.log for details."))

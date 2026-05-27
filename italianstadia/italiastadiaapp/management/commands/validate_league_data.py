import importlib.util
import os

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


def _load_scraper():
    scripts_path = os.path.join(settings.BASE_DIR, "scripts")
    spec = importlib.util.spec_from_file_location(
        "_transfermrkt_scraper",
        os.path.join(scripts_path, "populate_data_from_transfermrkt.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Command(BaseCommand):
    help = "Run data quality checks on a scraped league without re-scraping"

    def add_arguments(self, parser):
        parser.add_argument(
            "--league",
            required=True,
            help="League slug matching scripts/data/urls_<slug>.json (e.g. ligue-1, bundesliga)",
        )

    def handle(self, *args, **options):
        from italiastadiaapp.models import League

        league_slug = options["league"]

        try:
            league = League.objects.select_related("country").get(
                name__iexact=league_slug.replace("-", " ")
            )
        except League.DoesNotExist:
            # Try matching by country / common name variants via the JSON file
            data_file = os.path.join(
                settings.BASE_DIR,
                "scripts",
                "data",
                f"urls_{league_slug.replace('-', '_')}.json",
            )
            if not os.path.exists(data_file):
                raise CommandError(
                    f"No league found for slug '{league_slug}' and config file not found: {data_file}"
                )
            import json
            with open(data_file, encoding="utf-8") as f:
                league_config = json.load(f)["league"]
            try:
                league = League.objects.select_related("country").get(
                    name=league_config["name"],
                    country__name=league_config["country"],
                )
            except League.DoesNotExist:
                raise CommandError(
                    f"League '{league_config['name']}' not found in DB. "
                    f"Run scrape_season first."
                )

        self.stdout.write(self.style.HTTP_INFO(
            f"\nValidating: {league.name} ({league.country.name})\n"
        ))
        scraper = _load_scraper()
        scraper._validate_league(league)

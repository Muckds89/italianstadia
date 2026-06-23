import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from italiastadiaapp.models import City

# Bumped by the August bulk update when the new season's data is loaded.
DEFAULT_SEASON = "2025/2026"

_TIER_LABEL = {1: "1st tier", 2: "2nd tier", 3: "3rd tier"}


class Command(BaseCommand):
    help = (
        "Pre-generate italiastadiaapp/static/data/city_clubs.json (cities with 2+ "
        "football clubs, with logos, tiers and coordinates). Cheap, query-only pass; "
        "run after every scrape / data load and before collectstatic. Wired into "
        "build.sh after loaddata so prod refreshes on every deploy."
    )

    def add_arguments(self, parser):
        parser.add_argument("--season", default=DEFAULT_SEASON,
                            help="Season label written into the payload (default %(default)s).")

    def handle(self, *args, **options):
        season = options["season"]
        cities = (City.objects.prefetch_related("teams__league__country", "teams__stadium")
                  .order_by("-population", "name"))
        out_cities = []
        for c in cities:
            clubs = [t for t in c.teams.all() if not getattr(t, "is_national", False)]
            if len(clubs) < 2:               # single-club cities are out of scope
                continue
            country = next((t.league.country.name for t in clubs
                            if t.league and t.league.country), c.country or "")
            club_rows = []
            for t in sorted(clubs, key=lambda x: (_div(x), x.name)):
                st = t.stadium
                club_rows.append({
                    "name": t.name,
                    "slug": t.slug,
                    "logo": t.image_url or "",
                    "tier": _div(t),
                    "tier_label": _TIER_LABEL.get(_div(t), ""),
                    "lat": float(st.latitude) if st and st.latitude is not None else None,
                    "lng": float(st.longitude) if st and st.longitude is not None else None,
                })
            out_cities.append({
                "city": c.name,
                "country": country,
                "image_url": c.image_url or "",
                "count": len(club_rows),
                "clubs": club_rows,
            })
        out_cities.sort(key=lambda r: (-r["count"], r["city"]))

        payload = json.dumps({"season": season, "cities": out_cities},
                             ensure_ascii=False, separators=(",", ":"))
        out_path = (Path(settings.BASE_DIR) / "italiastadiaapp" / "static"
                    / "data" / "city_clubs.json")
        out_path.write_text(payload, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(
            f"Written {len(out_cities)} multi-club cities ({len(payload)/1024:.0f} KB, "
            f"season {season}) -> {out_path.relative_to(settings.BASE_DIR)}"))


def _div(team):
    return team.league.division_level if (team.league and team.league.division_level) else None

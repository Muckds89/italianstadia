from datetime import date, datetime, timezone
from pathlib import Path

from django.contrib.sitemaps import Sitemap
from django.utils.text import slugify
from django.urls import reverse

from .models import Country, Stadium, StadiumDevelopment, Team


def _data_lastmod():
    """Single sitewide 'content changed' date = the data fixture's mtime. It is rewritten
    by `dumpdata` on every data change, so re-crawling is signalled without a per-row
    updated_at column. Falls back to None if the file is missing."""
    f = Path(__file__).parent / "fixtures" / "initial_data.json"
    try:
        return datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).date()
    except OSError:
        return None


_LASTMOD = _data_lastmod()


class _DataLastmodMixin:
    """Stamp every URL in the sitemap with the dataset's last-changed date."""
    def lastmod(self, obj):
        return _LASTMOD


class StadiumSitemap(_DataLastmodMixin, Sitemap):
    changefreq = "monthly"

    def items(self):
        return (Stadium.objects.filter(latitude__isnull=False).exclude(slug="")
                .prefetch_related("teams__league").order_by("id"))

    def priority(self, obj):
        # Focus crawl budget: grounds with a top-division or national tenant rank
        # highest; lower-tier grounds get a lower priority so Google indexes the
        # high-value pages first while the site's authority is still building.
        levels = [t.league.division_level for t in obj.teams.all()
                  if t.league and t.league.division_level]
        if any(getattr(t, "is_national", False) for t in obj.teams.all()):
            return 0.9
        if levels and min(levels) == 1:
            return 0.8
        if levels and min(levels) == 2:
            return 0.6
        return 0.4

    def location(self, obj):
        return reverse("italiastadiaapp:stadium_detail", args=[obj.slug])


class TeamSitemap(_DataLastmodMixin, Sitemap):
    changefreq = "monthly"

    def items(self):
        return Team.objects.select_related("league").exclude(slug="").order_by("id")

    def priority(self, obj):
        # Same tiering as stadiums — top-flight clubs first.
        if getattr(obj, "is_national", False):
            return 0.8
        lvl = obj.league.division_level if obj.league else None
        return {1: 0.7, 2: 0.5}.get(lvl, 0.3)

    def location(self, obj):
        return reverse("italiastadiaapp:team_detail", args=[obj.slug])


class DevelopmentSitemap(_DataLastmodMixin, Sitemap):
    changefreq = "weekly"  # dev projects change status often
    priority = 0.7
    cache_timeout = 86400  # 24 h — avoid full table scan on every sitemap request

    def items(self):
        return StadiumDevelopment.objects.exclude(slug="").order_by("id")

    def location(self, obj):
        return reverse("italiastadiaapp:stadium_development_detail", args=[obj.slug])


class TournamentSitemap(_DataLastmodMixin, Sitemap):
    changefreq = "monthly"
    priority = 0.9
    cache_timeout = 86400  # 24 h — tournament venues change rarely

    def items(self):
        """Return unique tournament slugs derived from Stadium and StadiumDevelopment JSONFields."""
        seen = set()
        slugs = []
        for stadium in Stadium.objects.exclude(tournaments=[]):
            for entry in (stadium.tournaments or []):
                name = entry.get("tournament", "")
                if name:
                    s = slugify(name)
                    if s not in seen:
                        seen.add(s)
                        slugs.append(s)
        for dev in StadiumDevelopment.objects.exclude(tournaments=[]):
            for entry in (dev.tournaments or []):
                name = entry.get("tournament", "")
                if name:
                    s = slugify(name)
                    if s not in seen:
                        seen.add(s)
                        slugs.append(s)
        return slugs

    def location(self, slug):
        return reverse("italiastadiaapp:tournament_detail", args=[slug])


class CountryHubSitemap(_DataLastmodMixin, Sitemap):
    changefreq = "weekly"
    priority = 0.6

    def items(self):
        # Countries that actually have at least one stadium (by league country).
        return list(
            Country.objects.filter(leagues__isnull=False)
            .distinct().order_by("name").values_list("name", flat=True)
        )

    def location(self, name):
        return reverse("italiastadiaapp:country_stats", args=[name])


class StaticViewSitemap(_DataLastmodMixin, Sitemap):
    changefreq = "weekly"
    priority = 1.0

    def items(self):
        return ["home", "map_page", "stadium_list", "team_list", "city_list", "stadium_development_list",
                "insights_index", "insight_national", "insight_surface", "insight_density",
                "insight_biggest", "insight_league_capacity", "insight_city_clubs",
                "insight_retractable_roofs", "about", "contact", "privacy"]

    def location(self, item):
        return reverse(f"italiastadiaapp:{item}")

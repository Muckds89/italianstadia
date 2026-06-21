from datetime import date, datetime, timezone
from pathlib import Path

from django.contrib.sitemaps import Sitemap
from django.utils.text import slugify
from django.urls import reverse

from .models import City, Stadium, StadiumDevelopment, Team


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
    priority = 0.8

    def items(self):
        return Stadium.objects.filter(latitude__isnull=False).exclude(slug="").order_by("id")

    def location(self, obj):
        return reverse("italiastadiaapp:stadium_detail", args=[obj.slug])


class TeamSitemap(_DataLastmodMixin, Sitemap):
    changefreq = "monthly"
    priority = 0.7

    def items(self):
        return Team.objects.select_related("league").exclude(slug="").order_by("id")

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


class CitySitemap(_DataLastmodMixin, Sitemap):
    changefreq = "yearly"
    priority = 0.4

    def items(self):
        return City.objects.order_by("id")

    def location(self, obj):
        return reverse("italiastadiaapp:city_list") + f"?country={obj.country}"


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


class StaticViewSitemap(_DataLastmodMixin, Sitemap):
    changefreq = "weekly"
    priority = 1.0

    def items(self):
        return ["home", "stadium_list", "team_list", "city_list", "stadium_development_list",
                "insights_index", "insight_national", "insight_surface", "insight_density",
                "insight_biggest"]

    def location(self, item):
        return reverse(f"italiastadiaapp:{item}")

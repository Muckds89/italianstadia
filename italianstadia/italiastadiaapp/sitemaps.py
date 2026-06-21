from django.contrib.sitemaps import Sitemap
from django.utils.text import slugify
from django.urls import reverse

from .models import City, Stadium, StadiumDevelopment, Team


class StadiumSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.8

    def items(self):
        return Stadium.objects.filter(latitude__isnull=False).exclude(slug="").order_by("id")

    def location(self, obj):
        return reverse("italiastadiaapp:stadium_detail", args=[obj.slug])


class TeamSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.7

    def items(self):
        return Team.objects.select_related("league").exclude(slug="").order_by("id")

    def location(self, obj):
        return reverse("italiastadiaapp:team_detail", args=[obj.slug])


class DevelopmentSitemap(Sitemap):
    changefreq = "weekly"  # dev projects change status often
    priority = 0.7
    cache_timeout = 86400  # 24 h — avoid full table scan on every sitemap request

    def items(self):
        return StadiumDevelopment.objects.exclude(slug="").order_by("id")

    def location(self, obj):
        return reverse("italiastadiaapp:stadium_development_detail", args=[obj.slug])


class CitySitemap(Sitemap):
    changefreq = "yearly"
    priority = 0.4

    def items(self):
        return City.objects.order_by("id")

    def location(self, obj):
        return reverse("italiastadiaapp:city_list") + f"?country={obj.country}"


class TournamentSitemap(Sitemap):
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


class StaticViewSitemap(Sitemap):
    changefreq = "weekly"
    priority = 1.0

    def items(self):
        return ["home", "stadium_list", "team_list", "city_list", "stadium_development_list",
                "insights_index", "insight_national", "insight_surface", "insight_density",
                "insight_biggest"]

    def location(self, item):
        return reverse(f"italiastadiaapp:{item}")

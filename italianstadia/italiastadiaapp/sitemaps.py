from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import City, Stadium, Team


class StadiumSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.8

    def items(self):
        # Only stadiums with coordinates are meaningfully indexable
        return Stadium.objects.filter(latitude__isnull=False).order_by("id")

    def location(self, obj):
        return reverse("italiastadiaapp:stadium_detail", args=[obj.id])


class TeamSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.7

    def items(self):
        return Team.objects.select_related("league").order_by("id")

    def location(self, obj):
        return reverse("italiastadiaapp:team_detail", args=[obj.pk])


class CitySitemap(Sitemap):
    changefreq = "yearly"
    priority = 0.4

    def items(self):
        return City.objects.order_by("id")

    def location(self, obj):
        # City list filtered to this city's country — best proxy until individual city pages exist
        return reverse("italiastadiaapp:city_list") + f"?country={obj.country}"


class StaticViewSitemap(Sitemap):
    changefreq = "weekly"
    priority = 1.0

    def items(self):
        return ["home", "stadium_list", "team_list", "city_list"]

    def location(self, item):
        return reverse(f"italiastadiaapp:{item}")

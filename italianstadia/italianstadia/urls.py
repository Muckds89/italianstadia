from django.conf import settings
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponse
from django.urls import path, include

from italiastadiaapp.sitemaps import (
    CountryHubSitemap,
    DevelopmentSitemap,
    StadiumSitemap,
    StaticViewSitemap,
    TeamSitemap,
    TournamentSitemap,
)

# NB: no CitySitemap — it emitted /cities/?country=X once per CITY (hundreds of
# query-string URLs, duplicated within each country, with no canonical), which GSC
# filed under "Duplicate without user-selected canonical". Country coverage is the
# CountryHubSitemap's job; /cities/ itself is in the static sitemap.
sitemaps = {
    "stadiums":     StadiumSitemap,
    "developments": DevelopmentSitemap,
    "teams":        TeamSitemap,
    "countries":    CountryHubSitemap,
    "tournaments":  TournamentSitemap,
    "static":       StaticViewSitemap,
}


# Fallback publisher ID so ads.txt is NEVER served empty (an empty file makes
# AdSense report "Not found", even though the file 200s). The env var still wins
# when set; this guarantees the seller line survives an unset/cleared env var.
_DEFAULT_ADSENSE_CLIENT = "ca-pub-9969866762001544"


def ads_txt(request):
    client = settings.GOOGLE_ADSENSE_CLIENT or _DEFAULT_ADSENSE_CLIENT
    pub_id = client.replace("ca-", "", 1)   # ads.txt uses pub-XXX, not ca-pub-XXX
    return HttpResponse(
        f"google.com, {pub_id}, DIRECT, f08c47fec0942fa0\n",
        content_type="text/plain",
    )


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        # Machine-readable data, not pages — GSC showed Google crawling these and
        # filing them under "Crawled - currently not indexed" (wasted crawl budget).
        "Disallow: /api/",
        "Disallow: /static/data/",
        # Internal back-navigation params on detail links; the pages self-canonicalise
        # to the clean URL, but blocking the variants stops Google recrawling them.
        "Disallow: /*?from_list",
        "Disallow: /*?from_team_list",
        "Disallow: /*?*&from_list",
        "Disallow: /*?*&from_team_list",
        "",
        f"Sitemap: {request.build_absolute_uri('/sitemap.xml')}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


urlpatterns = [
    path("admin/",      admin.site.urls),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps},
         name="django.contrib.sitemaps.views.sitemap"),
    path("ads.txt",     ads_txt,    name="ads_txt"),
    path("robots.txt",  robots_txt, name="robots_txt"),
    path("",            include("italiastadiaapp.urls")),
]

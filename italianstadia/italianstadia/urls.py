from django.conf import settings
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponse
from django.urls import path, include

from italiastadiaapp.sitemaps import (
    CitySitemap,
    StadiumSitemap,
    StaticViewSitemap,
    TeamSitemap,
    TournamentSitemap,
)

sitemaps = {
    "stadiums":    StadiumSitemap,
    "teams":       TeamSitemap,
    "cities":      CitySitemap,
    "tournaments": TournamentSitemap,
    "static":      StaticViewSitemap,
}


def ads_txt(request):
    client = settings.GOOGLE_ADSENSE_CLIENT  # e.g. ca-pub-9969866762001544
    if not client:
        return HttpResponse("", content_type="text/plain")
    pub_id = client.replace("ca-", "", 1)   # ads.txt uses pub-XXX, not ca-pub-XXX
    return HttpResponse(
        f"google.com, {pub_id}, DIRECT, f08c47fec0942fa0\n",
        content_type="text/plain",
    )


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
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

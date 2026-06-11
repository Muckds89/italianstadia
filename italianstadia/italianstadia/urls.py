from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponse
from django.urls import path, include

from italiastadiaapp.sitemaps import (
    CitySitemap,
    StadiumSitemap,
    StaticViewSitemap,
    TeamSitemap,
)

sitemaps = {
    "stadiums": StadiumSitemap,
    "teams":    TeamSitemap,
    "cities":   CitySitemap,
    "static":   StaticViewSitemap,
}


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
    path("robots.txt",  robots_txt, name="robots_txt"),
    path("",            include("italiastadiaapp.urls")),
]

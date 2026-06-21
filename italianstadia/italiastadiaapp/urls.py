from django.urls import path
from django.views.generic.base import RedirectView
from . import views
from .views import (
    api_status, city_list, country_stats, export_stadiums,
    stadium_developments_geojson, stadium_development_list, stadium_list, team_list,
    stadium_detail, stadium_detail_redirect, stadiums_geojson,
    stadium_development_detail, stadium_development_detail_redirect,
    team_detail, team_detail_redirect,
    tournament_list, tournament_detail, map_export,
    export_page, export_checkout, export_webhook, export_success, export_download, export_options,
    insights_index, insight_national, insight_surface, insight_density,
)

app_name = "italiastadiaapp"
urlpatterns = [
    # Serve the pin favicon at the well-known path so browsers and Google's
    # fallback get it site-wide (shows the pin next to search results).
    path("favicon.ico", RedirectView.as_view(url="/static/icons/favicon.ico", permanent=True)),
    path('', views.index, name='home'),
    path('cities/', city_list, name='city_list'),
    path('stadiums/', stadium_list, name='stadium_list'),
    path('under-development/', stadium_development_list, name='stadium_development_list'),
    path('teams/', team_list, name='team_list'),
    path("team/<int:pk>/", views.team_detail_redirect, name="team_detail_by_id"),
    path("team/<slug:slug>/", team_detail, name="team_detail"),
    path("stadium/<int:id>/", stadium_detail_redirect, name="stadium_detail_by_id"),
    path("stadium/<slug:slug>/", stadium_detail, name="stadium_detail"),
    path("country/<str:country_name>/", country_stats, name="country_stats"),
    path("tournaments/", tournament_list, name="tournament_list"),
    path("tournaments/<slug:slug>/", tournament_detail, name="tournament_detail"),
    path("insights/", insights_index, name="insights_index"),
    path("insights/national-stadiums/", insight_national, name="insight_national"),
    path("insights/stadium-surfaces/", insight_surface, name="insight_surface"),
    path("insights/stadium-density/", insight_density, name="insight_density"),
    path("api/stadiums/", stadiums_geojson, name="stadiums_geojson"),
    path("api/stadium-developments/", stadium_developments_geojson, name="stadium_developments_geojson"),
    path("api/export/stadiums/", export_stadiums, name="export_stadiums"),
    path("api/export/map/", map_export, name="map_export"),
    path("api/status/", api_status, name="api_status"),
    path("stadium-development/<int:pk>/", stadium_development_detail_redirect, name="stadium_development_detail_by_id"),
    path("stadium-development/<slug:slug>/", stadium_development_detail, name="stadium_development_detail"),
    path("privacy/", views.privacy, name="privacy"),
    # Paid export
    path("export/", export_page, name="export_page"),
    path("export/checkout/", export_checkout, name="export_checkout"),
    path("export/webhook/", export_webhook, name="export_webhook"),
    path("export/success/", export_success, name="export_success"),
    path("export/download/<uuid:token>/", export_download, name="export_download"),
    path("api/export/options/", export_options, name="export_options"),
]

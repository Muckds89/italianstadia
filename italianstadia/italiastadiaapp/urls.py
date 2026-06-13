from django.urls import path
from . import views
from .views import (
    api_status, city_list, country_stats, export_stadiums,
    stadium_developments_geojson, stadium_development_list, stadium_list, team_list,
    stadium_detail, stadium_detail_redirect, stadiums_geojson,
    stadium_development_detail, team_detail,
)

app_name = "italiastadiaapp"
urlpatterns = [
    path('', views.index, name='home'),
    path('cities/', city_list, name='city_list'),
    path('stadiums/', stadium_list, name='stadium_list'),
    path('under-development/', stadium_development_list, name='stadium_development_list'),
    path('teams/', team_list, name='team_list'),
    path("team/<int:pk>/", team_detail, name="team_detail"),
    path("stadium/<int:id>/", stadium_detail_redirect, name="stadium_detail_by_id"),
    path("stadium/<slug:slug>/", stadium_detail, name="stadium_detail"),
    path("country/<str:country_name>/", country_stats, name="country_stats"),
    path("api/stadiums/", stadiums_geojson, name="stadiums_geojson"),
    path("api/stadium-developments/", stadium_developments_geojson, name="stadium_developments_geojson"),
    path("api/export/stadiums/", export_stadiums, name="export_stadiums"),
    path("api/status/", api_status, name="api_status"),
    path("stadium-development/<int:pk>/", stadium_development_detail, name="stadium_development_detail"),
    path("privacy/", views.privacy, name="privacy"),
]

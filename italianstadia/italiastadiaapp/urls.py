from django.urls import path
from . import views
from .views import (
    city_list, stadium_developments_geojson, stadium_list, team_list,
    stadium_detail, stadiums_geojson, stadium_development_detail, team_detail,
)

app_name = "italiastadiaapp"
urlpatterns = [
    path('', views.index, name='home'),
    path('cities/', city_list, name='city_list'),
    path('stadiums/', stadium_list, name='stadium_list'),
    path('teams/', team_list, name='team_list'),
    path("team/<int:pk>/", team_detail, name="team_detail"),
    path("stadium/<int:id>/", stadium_detail, name="stadium_detail"),
    path("api/stadiums/", stadiums_geojson, name="stadiums_geojson"),
    path("api/stadium-developments/", stadium_developments_geojson, name="stadium_developments_geojson"),
    path("stadium-development/<int:pk>/", stadium_development_detail, name="stadium_development_detail"),
]

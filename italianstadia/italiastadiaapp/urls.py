from django.urls import path
from . import views
from .views import city_list,stadium_list,team_list,stadium_detail,stadiums_geojson

appname = "italiastadiaapp"
urlpatterns = [
    path('',views.index,name='index'),
    path('cities/', city_list, name='city_list'),
    path('stadia/', stadium_list, name='stadium_list'),
    path('teams/', team_list, name='team_list'),
    path("stadium/<int:id>/", stadium_detail, name="stadium_detail"),
    path("api/stadiums/", stadiums_geojson, name="stadiums_geojson"),

]

from django.contrib import admin
from .models import City, Stadium, Team


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "population", "wikipedia_url")
    search_fields = ("name", "country")


@admin.register(Stadium)
class StadiumAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "city",
        "capacity",
        "year_of_construction",
        "latitude",
        "longitude",
        "wikipedia_url",
        "transfermarkt_url",
    )
    search_fields = ("name", "city__name")
    list_filter = ("city",)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "city",
        "stadium",
        "tier",
        "manager",
        "num_of_titles",
        "wikipedia_url",
        "transfermarkt_url",
    )
    search_fields = ("name", "city__name", "stadium__name")
    list_filter = ("tier", "city")
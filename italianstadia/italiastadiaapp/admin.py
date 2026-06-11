from django.contrib import admin
from .models import City, Country, League, Stadium, Team


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("name", "code")
    search_fields = ("name", "code")


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "division_level")
    list_filter = ("country",)
    ordering = ("country", "division_level")


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name",
                    "country",
                    "population",
                    "wikipedia_url",
                    "image_url",
        )
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
        "image_url",
        "ownership",
        "owner_raw",
    )

    list_filter = ("ownership", "city")
    search_fields = ("name", "city__name", "owner_raw")


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "city",
        "stadium",
        "league",
        "tier",
        "girone",
        "founded",
        "manager",
        "num_of_titles",
        "wikipedia_url",
        "transfermarkt_url",
        "image_url",
    )
    search_fields = ("name", "city__name", "stadium__name")
    list_filter = ("league", "tier", "city")

from .models import StadiumDevelopment, LastRefresh

@admin.register(StadiumDevelopment)
class StadiumDevelopmentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "project_type",
        "status",
        "future_capacity",
        "estimated_opening",
        "architect",
        "developer",
        "latitude",
        "longitude",
        "source_url",
        "image_url",
        "image_credit",
        "notes",
    )
    list_filter = ("project_type", "status")
    search_fields = ("name", "notes", "architect", "developer")


@admin.register(LastRefresh)
class LastRefreshAdmin(admin.ModelAdmin):
    list_display = ("status", "ran_at", "detail")
    readonly_fields = ("status", "ran_at", "detail")
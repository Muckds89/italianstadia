from django.contrib import admin
from .models import City, Stadium, Team


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
    list_filter = ("tier", "city")

from .models import StadiumDevelopment

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
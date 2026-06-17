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
        "stadium_type",
        "surface",
        "architect",
        "ownership",
        "locked",
        "slug",
        "latitude",
        "longitude",
    )
    list_editable = ("locked",)   # tick to protect a corrected stadium from the scraper

    list_filter = ("locked", "ownership", "stadium_type", "surface", "city")
    search_fields = ("name", "city__name", "owner_raw", "architect", "slug")
    actions = ["lock_stadiums", "unlock_stadiums"]

    @admin.action(description="🔒 Lock — protect from the scraper")
    def lock_stadiums(self, request, queryset):
        n = queryset.update(locked=True)
        self.message_user(request, f"Locked {n} stadium(s) — the scraper will skip them.")

    @admin.action(description="🔓 Unlock — allow the scraper to update")
    def unlock_stadiums(self, request, queryset):
        n = queryset.update(locked=False)
        self.message_user(request, f"Unlocked {n} stadium(s).")
    prepopulated_fields = {"slug": ("name",)}
    fieldsets = (
        (None, {
            "fields": ("name", "slug", "city", "address"),
        }),
        ("Capacity & Construction", {
            "fields": ("capacity", "year_of_construction", "stadium_type", "surface", "architect"),
        }),
        ("Ownership", {
            "fields": ("ownership", "owner_raw"),
        }),
        ("Location", {
            "fields": ("latitude", "longitude"),
        }),
        ("Tournaments", {
            "fields": ("tournaments",),
            "description": 'JSON list: [{"tournament": "UEFA Euro 2028", "year": 2028, "status": "CONFIRMED", "matches": 5}]',
        }),
        ("Media & Links", {
            "fields": ("image_url", "image_credit", "extra_images", "wikipedia_url", "transfermarkt_url", "description"),
        }),
    )


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
        "country",
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
    list_filter = ("project_type", "status", "country")
    search_fields = ("name", "country", "notes", "architect", "developer")


@admin.register(LastRefresh)
class LastRefreshAdmin(admin.ModelAdmin):
    list_display = ("status", "ran_at", "detail")
    readonly_fields = ("status", "ran_at", "detail")
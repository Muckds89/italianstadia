from django.contrib import admin
from .models import City, Stadium, Team

@admin.register(Stadium)
class StadiumAdmin(admin.ModelAdmin):
    list_display = ('name', 'capacity', 'address', 'year_of_construction', 'city',"latitude", "longitude")
    list_editable  = (
        "capacity",
        "address",
        "year_of_construction",
        "city",
        "latitude",
        "longitude",
    )
    search_fields = ("name", "city", "team")
    list_filter = ("city",)

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'founded', 'tier', 'stadium', 'manager', 'num_of_titles', 'average_attendance')  # Updated to include new fields

class StadiaInLine(admin.StackedInline):
    model = Stadium
    extra = 3

@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    inlines = [StadiaInLine]
    list_display = ('name', 'population', 'country')
    search_fields = ['name']
    list_filter = ['country']

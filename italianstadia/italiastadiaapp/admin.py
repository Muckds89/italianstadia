from django.contrib import admin
from .models import City,Stadium,Team

# Register your models here.
@admin.register(Stadium)
class StadiumAdmin(admin.ModelAdmin):
    list_display = ('name','capacity','address','year_of_construction','average_attendance','city')

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name','founded','tier','stadium')

class StadiaInLine(admin.StackedInline):
    model = Stadium
    extra = 3

@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    inlines = [StadiaInLine]
    list_display = ('name','population','country')
    search_fields = ['name']
    list_filter = ['country']

# admin.site.register(City)
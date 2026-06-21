"""
Cleanup:
1. Remove the duplicate Iceland "Valur Reykjavík" team (the URL file names the club
   "Valur" — id with the TM link; "Valur Reykjavík" was a stray dup, leaving Besta
   deild with 14 teams across 13 stadiums).
2. Delete teamless "clutter" stadiums (scrape orphans / bad rows in the map's "Other"
   group) EXCEPT those tagged in a tournament (e.g. the Euro 2032/2036 venues).
"""
from django.db import migrations


def forwards(apps, schema_editor):
    Team = apps.get_model("italiastadiaapp", "Team")
    Stadium = apps.get_model("italiastadiaapp", "Stadium")

    # 1. duplicate Valur (keep the canonical "Valur" from the scrape)
    Team.objects.filter(name="Valur Reykjavík").delete()

    # 2. teamless, non-tournament stadiums
    for s in Stadium.objects.filter(teams__isnull=True).distinct():
        if not (s.tournaments or []):
            s.delete()


def backwards(apps, schema_editor):
    # Destructive cleanup — nothing to restore.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0064_poland_bid_add_venues"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

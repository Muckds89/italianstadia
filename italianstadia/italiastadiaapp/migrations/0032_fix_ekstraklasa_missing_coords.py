"""
Patch coordinates for two Ekstraklasa stadiums whose Wikipedia pages
did not expose geo metadata during the initial scrape.

Sources:
  Motor Lublin Arena  — Wikidata Q9341160 / Wikivoyage Lublin
  Stadion GOSiR       — Wikipedia "Stadion Miejski (Gdynia)"
"""

from django.db import migrations
from decimal import Decimal

COORDS = [
    # (wikipedia_url fragment, lat, lng)
    ("PKO_BP_Motor_Lublin_Arena", Decimal("51.232400"), Decimal("22.557400")),
    ("GOSiR_Stadium,_Gdynia",     Decimal("54.493060"), Decimal("18.531110")),
]


def patch_coords(apps, schema_editor):
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    for url_fragment, lat, lng in COORDS:
        updated = Stadium.objects.filter(
            wikipedia_url__icontains=url_fragment,
            latitude__isnull=True,
        ).update(latitude=lat, longitude=lng)
        # Also update if already set to wrong value (idempotent on re-run)
        if not updated:
            Stadium.objects.filter(
                wikipedia_url__icontains=url_fragment
            ).update(latitude=lat, longitude=lng)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0031_remove_relegated_2425_clubs"),
    ]

    operations = [
        migrations.RunPython(patch_coords, reverse_code=noop),
    ]

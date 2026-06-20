"""
Enrich the 4 Polish Euro 2036 bid stadiums that were created as stubs (no image,
no capacity) so their cards render properly. Images are CC BY-SA from Wikimedia
Commons (credited); capacities from Wikidata P1083. Kraków also gets accurate coords
and the Henryk Reyman article. (Full Polish 2nd-tier scrape is a separate step.)
"""
from django.db import migrations

ENRICH = {
    "PGE Narodowy": {
        "capacity": 58274,
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/f/f8/National_Stadium_Warsaw_aerial_view_2.jpg",
        "image_credit": "Arne Müseler / Wikimedia Commons / CC BY-SA 3.0 de",
    },
    "Stadion Śląski": {
        "capacity": 54378,
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/c/c4/Widok_bramka.jpg",
        "image_credit": "DzejKej86 / Wikimedia Commons / CC BY-SA 4.0",
    },
    "Tarczyński Arena": {
        "capacity": 42771,
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/5/56/Wroclaw_Munincipal_Stadium_2019_%28cropped%29.jpg",
        "image_credit": "Arne Müseler / Wikimedia Commons / CC BY-SA 3.0 de",
    },
    "Stadion Miejski (Kraków)": {
        "capacity": 33130,
        "latitude": 50.063611,
        "longitude": 19.911944,
        "wikipedia_url": "https://en.wikipedia.org/wiki/Henryk_Reyman_Municipal_Stadium",
    },
}


def forwards(apps, schema_editor):
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    for name, fields in ENRICH.items():
        for s in Stadium.objects.filter(name=name):
            for k, v in fields.items():
                setattr(s, k, v)
            s.save(update_fields=list(fields.keys()))


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0062_euro2036_bids"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

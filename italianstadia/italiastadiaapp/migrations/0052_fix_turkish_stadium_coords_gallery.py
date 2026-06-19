"""
Fix coordinates for the three Turkish Euro 2032 stadiums (the seed values were off)
using Wikipedia/Wikidata geo, and add the one additional freely-licensed Commons
photo that exists (Timsah Arena). The new Eskişehir and Ankara grounds have no further
CC-licensed photos on Commons yet (new / under-construction), so they keep just the hero.
"""
from django.db import migrations


COORDS = {
    "Timsah Arena": (40.210833, 29.009444),
    "Yeni Eskişehir Stadyumu": (39.762222, 30.467778),
    "Yeni Ankara Stadyumu": (39.940278, 32.845833),
}

EXTRA_IMAGES = {
    "Timsah Arena": [
        {
            "url": "https://upload.wikimedia.org/wikipedia/commons/0/03/Y%C3%BCz%C3%BCnc%C3%BC_Y%C4%B1l_Atat%C3%BCrk_Stadyumu.jpg",
            "credit": "Kızıldeniz / Wikimedia Commons / CC BY-SA 4.0",
        },
    ],
}


def forwards(apps, schema_editor):
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    for name, (lat, lon) in COORDS.items():
        for s in Stadium.objects.filter(name=name):
            s.latitude = lat
            s.longitude = lon
            if name in EXTRA_IMAGES:
                s.extra_images = EXTRA_IMAGES[name]
            s.save()


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0051_enrich_turkish_euro2032_stadiums"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
